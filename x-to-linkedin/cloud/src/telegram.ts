import { createHash, timingSafeEqual } from "node:crypto";
import { db } from "./db.js";
import { requiredEnv, switches } from "./env.js";
import { recordEvent } from "./events.js";
import { normalizeUrl } from "./external-url.js";
import { redact } from "./redaction.js";

type TelegramUser = {
  id: number;
};

type TelegramChat = {
  id: number;
};

type TelegramMessage = {
  message_id: number;
  text?: string;
  caption?: string;
  chat: TelegramChat;
  from?: TelegramUser;
  reply_to_message?: Pick<TelegramMessage, "message_id" | "text" | "caption">;
};

type TelegramCallback = {
  id: string;
  data?: string;
  from: TelegramUser;
  message?: TelegramMessage;
};

export type TelegramUpdate = {
  update_id: number;
  message?: TelegramMessage;
  callback_query?: TelegramCallback;
};

type TelegramResponse<T = Record<string, unknown>> = {
  ok: boolean;
  result?: T;
  description?: string;
};

type PostSummary = {
  id: number;
  status: string;
  linkedin_text: string;
  tweet_url: string;
  tweet_author: string;
  publish_at: string | null;
  scheduled_at: string | null;
  source: string;
  media_type: string;
  version: number;
};

const TELEGRAM_TEXT_LIMIT = 4096;
const POST_CARD_TEXT_LIMIT = 3100;

function hash(value: unknown): string {
  return createHash("sha256").update(JSON.stringify(value)).digest("hex");
}

export function validTelegramSecret(actual: string | null): boolean {
  if (!actual) return false;
  const expected = requiredEnv("TELEGRAM_WEBHOOK_SECRET");
  const left = Buffer.from(actual);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

function allowedTelegramUser(): number {
  const value = Number(requiredEnv("TELEGRAM_USER_ID"));
  if (!Number.isSafeInteger(value)) throw new Error("Invalid TELEGRAM_USER_ID");
  return value;
}

function compactText(value: string, max = TELEGRAM_TEXT_LIMIT): string {
  const normalized = value.replace(/\r\n/g, "\n").trim();
  return normalized.length <= max ? normalized : `${normalized.slice(0, max - 1)}…`;
}

async function telegramApi<T = Record<string, unknown>>(
  method: string,
  payload: Record<string, unknown>,
  idempotencyKey: string
): Promise<T | null> {
  const sql = db();
  const fingerprint = hash({ method, payload });
  const effectRows = await sql<
    Array<{
      id: number;
      status: string;
      response_payload: T | null;
    }>
  >`
    insert into app.external_effects (
      effect_type, idempotency_key, entity_type, entity_id,
      request_fingerprint, request_payload
    ) values (
      'telegram_message',
      ${idempotencyKey},
      'telegram',
      ${method},
      ${fingerprint},
      ${sql.json({ method, payload } as never)}
    )
    on conflict (idempotency_key) do update set updated_at = now()
    returning id, status, response_payload
  `;
  const effect = effectRows[0]!;
  if (effect.status === "succeeded") return effect.response_payload;

  if (!switches.telegramSendEnabled()) {
    await sql`
      update app.external_effects
      set status = 'cancelled',
          response_payload = ${sql.json({ shadow: true, method, payload } as never)},
          completed_at = now()
      where id = ${effect.id} and status <> 'succeeded'
    `;
    await recordEvent({
      subsystem: "telegram",
      eventType: "shadow_send_captured",
      entityType: "telegram_effect",
      entityId: effect.id,
      metadata: { method, idempotency_key: idempotencyKey },
      dedupeKey: `shadow:${idempotencyKey}`
    });
    return null;
  }

  const claim = await sql<[{ id: number }]>`
    update app.external_effects
    set status = 'executing',
        attempts = attempts + 1,
        leased_until = now() + interval '1 minute'
    where id = ${effect.id}
      and (
        status in ('pending', 'failed', 'cancelled')
        or (status = 'executing' and leased_until < now())
      )
    returning id
  `;
  if (!claim[0]) return null;

  try {
    const response = await fetch(
      `https://api.telegram.org/bot${requiredEnv("TELEGRAM_BOT_TOKEN")}/${method}`,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
        signal: AbortSignal.timeout(8_000)
      }
    );
    const data = (await response.json()) as TelegramResponse<T>;
    if (!response.ok || !data.ok) {
      throw new Error(`Telegram ${method} failed (${response.status}): ${data.description ?? ""}`);
    }
    const result = data.result ?? ({} as T);
    await sql`
      update app.external_effects
      set status = 'succeeded',
          response_payload = ${sql.json(result as never)},
          completed_at = now(),
          leased_until = null
      where id = ${effect.id}
    `;
    return result;
  } catch (error) {
    await sql`
      update app.external_effects
      set status = 'ambiguous',
          last_error = ${redact(error)},
          leased_until = null
      where id = ${effect.id}
    `;
    throw error;
  }
}

export async function sendTelegramMessage(input: {
  chatId?: number;
  text: string;
  idempotencyKey: string;
  replyMarkup?: Record<string, unknown>;
  replyToMessageId?: number;
  postId?: number;
  commentId?: number;
  messageType?: string;
}): Promise<number | null> {
  const chatId = input.chatId ?? allowedTelegramUser();
  const result = await telegramApi<{ message_id?: number }>(
    "sendMessage",
    {
      chat_id: chatId,
      text: compactText(input.text),
      disable_web_page_preview: true,
      ...(input.replyMarkup ? { reply_markup: input.replyMarkup } : {}),
      ...(input.replyToMessageId
        ? { reply_parameters: { message_id: input.replyToMessageId } }
        : {})
    },
    input.idempotencyKey
  );
  const messageId = result?.message_id;
  if (messageId) {
    const sql = db();
    await sql`
      insert into app.telegram_messages (
        chat_id, message_id, post_id, comment_id, message_type, payload
      ) values (
        ${chatId}, ${messageId}, ${input.postId ?? null}, ${input.commentId ?? null},
        ${input.messageType ?? "message"},
        ${sql.json({ idempotency_key: input.idempotencyKey } as never)}
      )
      on conflict (chat_id, message_id) do update
      set post_id = coalesce(excluded.post_id, app.telegram_messages.post_id),
          comment_id = coalesce(excluded.comment_id, app.telegram_messages.comment_id),
          message_type = excluded.message_type
    `;
  }
  return messageId ?? null;
}

async function answerCallback(
  callbackId: string,
  text: string,
  updateId: number
): Promise<void> {
  await telegramApi(
    "answerCallbackQuery",
    {
      callback_query_id: callbackId,
      text: compactText(text, 180),
      show_alert: false
    },
    `telegram_callback_answer:${updateId}`
  );
}

async function clearCallbackButtons(
  callback: TelegramCallback,
  updateId: number
): Promise<void> {
  if (!callback.message) return;
  await telegramApi(
    "editMessageReplyMarkup",
    {
      chat_id: callback.message.chat.id,
      message_id: callback.message.message_id,
      reply_markup: { inline_keyboard: [] }
    },
    `telegram_clear_buttons:${updateId}`
  );
}

export function approvalKeyboard(postId: number): Record<string, unknown> {
  return {
    inline_keyboard: [
      [
        { text: "Aprobar", callback_data: `approve:${postId}` },
        { text: "Pedir cambios", callback_data: `revise:${postId}` }
      ],
      [
        { text: "Otra fuente", callback_data: `another:${postId}` },
        { text: "Cancelar", callback_data: `cancel:${postId}` }
      ]
    ]
  };
}

function approvalCardText(post: PostSummary, reason = ""): string {
  const source = post.tweet_author || new URL(post.tweet_url).hostname;
  const body = compactText(post.linkedin_text, POST_CARD_TEXT_LIMIT);
  return compactText(
    [
      `Post #${post.id}`,
      "",
      body,
      "",
      `Fuente: ${source}`,
      post.tweet_url,
      reason ? `Criterio editorial: ${reason}` : "",
      "",
      "La aprobación queda abierta hasta que decidas. Al aprobar, se programa 30 minutos después."
    ]
      .filter((line, index, lines) => line || lines[index - 1] !== "")
      .join("\n")
  );
}

export async function sendApprovalCard(
  postId: number,
  reason = "",
  version?: number
): Promise<number | null> {
  const rows = await db()<PostSummary[]>`
    select id, status, linkedin_text, tweet_url, tweet_author, publish_at,
           scheduled_at, source, media_type, version
    from app.posts where id = ${postId}
  `;
  const post = rows[0];
  if (!post) throw new Error("Post not found");
  if (post.status !== "approval_pending") return null;
  return sendTelegramMessage({
    text: approvalCardText(post, reason),
    replyMarkup: approvalKeyboard(post.id),
    idempotencyKey: `approval_card:${post.id}:${version ?? post.version}`,
    postId: post.id,
    messageType: "approval"
  });
}

async function locateReplyEntity(
  chatId: number,
  reply: TelegramMessage["reply_to_message"]
): Promise<{ postId: number | null; commentId: number | null }> {
  if (!reply) return { postId: null, commentId: null };
  const mapped = await db()<Array<{ post_id: number | null; comment_id: number | null }>>`
    select post_id, comment_id
    from app.telegram_messages
    where chat_id = ${chatId} and message_id = ${reply.message_id}
  `;
  if (mapped[0]) {
    return { postId: mapped[0].post_id, commentId: mapped[0].comment_id };
  }
  const text = reply.text ?? reply.caption ?? "";
  const postMatch = text.match(/Post\s+#(\d+)/i);
  return {
    postId: postMatch ? Number(postMatch[1]) : null,
    commentId: null
  };
}

async function sessionFor(userId: number): Promise<{
  mode: string;
  post_id: number | null;
  comment_id: number | null;
} | null> {
  const rows = await db()<
    Array<{ mode: string; post_id: number | null; comment_id: number | null }>
  >`
    select mode, post_id, comment_id
    from app.telegram_sessions where user_id = ${userId}
  `;
  return rows[0] ?? null;
}

async function setSession(input: {
  userId: number;
  chatId: number;
  mode: string;
  postId?: number;
  commentId?: number;
}): Promise<void> {
  await db()`
    insert into app.telegram_sessions (user_id, chat_id, mode, post_id, comment_id)
    values (
      ${input.userId}, ${input.chatId}, ${input.mode},
      ${input.postId ?? null}, ${input.commentId ?? null}
    )
    on conflict (user_id) do update
    set chat_id = excluded.chat_id,
        mode = excluded.mode,
        post_id = excluded.post_id,
        comment_id = excluded.comment_id,
        expires_at = null,
        updated_at = now()
  `;
}

async function clearSession(userId: number): Promise<void> {
  await db()`delete from app.telegram_sessions where user_id = ${userId}`;
}

async function approvePost(postId: number): Promise<{
  status: string;
  publish_at: string | null;
  already_processed: boolean;
}> {
  const rows = await db()<
    Array<{ status: string; publish_at: string | null; already_processed: boolean }>
  >`
    select status, publish_at, already_processed
    from app.approve_post(${postId}, 'telegram')
  `;
  return rows[0]!;
}

async function cancelPost(postId: number): Promise<string> {
  const rows = await db()<[{ status: string }]>`
    select app.cancel_post(${postId}, 'telegram') as status
  `;
  return rows[0]?.status ?? "unknown";
}

async function requestAnotherSource(postId: number): Promise<number> {
  const sql = db();
  return sql.begin(async (transaction) => {
    const posts = await transaction<Array<{ status: string; version: number }>>`
      select status, version from app.posts where id = ${postId} for update
    `;
    const post = posts[0];
    if (!post) throw new Error("Post not found");
    if (post.status !== "approval_pending") return post.version;
    await transaction`
      update app.radar_candidates
      set excluded = true,
          exclusion_reason = coalesce(exclusion_reason, 'rejected from Telegram'),
          selected = false
      where post_id = ${postId} and selected
    `;
    const nextVersion = post.version + 1;
    await transaction`
      update app.posts
      set status = 'radar_slot',
          linkedin_text = '',
          image_urls = '[]'::jsonb,
          media_type = 'none',
          pdf_url = null,
          generated_image_path = null,
          version = ${nextVersion}
      where id = ${postId}
    `;
    await transaction`
      select app.enqueue_job(
        'radar_prepare',
        now(),
        jsonb_build_object('post_id', ${postId}),
        ${`radar_prepare:${postId}:${nextVersion}`},
        4,
        30,
        null
      )
    `;
    return nextVersion;
  }) as Promise<number>;
}

function formatLocalDate(value: string | null): string {
  if (!value) return "sin horario";
  return new Intl.DateTimeFormat("es-MX", {
    timeZone: "America/Mexico_City",
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

async function commandToday(chatId: number, idempotencyPrefix: string): Promise<void> {
  const posts = await db()<PostSummary[]>`
    select id, status, linkedin_text, tweet_url, tweet_author, publish_at,
           scheduled_at, source, media_type, version
    from app.posts
    where coalesce(publish_at, scheduled_at, created_at) >=
          (date_trunc('day', now() at time zone 'America/Mexico_City')
            at time zone 'America/Mexico_City')
      and coalesce(publish_at, scheduled_at, created_at) <
          ((date_trunc('day', now() at time zone 'America/Mexico_City') + interval '1 day')
            at time zone 'America/Mexico_City')
    order by coalesce(publish_at, scheduled_at, created_at), id
    limit 20
  `;
  const text = posts.length
    ? [
        "Publicaciones de hoy",
        "",
        ...posts.map(
          (post) =>
            `Post #${post.id}: ${post.status}, ${formatLocalDate(
              post.publish_at ?? post.scheduled_at
            )}\n${compactText(post.linkedin_text || "Radar pendiente", 180)}`
        )
      ].join("\n\n")
    : "No hay publicaciones para hoy.";
  await sendTelegramMessage({
    chatId,
    text,
    idempotencyKey: `${idempotencyPrefix}:today`
  });
}

async function commandPending(chatId: number, idempotencyPrefix: string): Promise<void> {
  const posts = await db()<PostSummary[]>`
    select id, status, linkedin_text, tweet_url, tweet_author, publish_at,
           scheduled_at, source, media_type, version
    from app.posts
    where status in ('approval_pending', 'radar_slot', 'scheduled', 'failed')
    order by
      case status when 'approval_pending' then 0 when 'scheduled' then 1 else 2 end,
      coalesce(publish_at, scheduled_at, created_at),
      id
    limit 20
  `;
  if (!posts.length) {
    await sendTelegramMessage({
      chatId,
      text: "No hay publicaciones pendientes.",
      idempotencyKey: `${idempotencyPrefix}:empty`
    });
    return;
  }
  for (const post of posts) {
    await sendTelegramMessage({
      chatId,
      text: compactText(
        `Post #${post.id}\nEstado: ${post.status}\nFecha: ${formatLocalDate(
          post.publish_at ?? post.scheduled_at
        )}\n\n${post.linkedin_text || "Radar pendiente"}`
      ),
      ...(post.status === "approval_pending"
        ? { replyMarkup: approvalKeyboard(post.id) }
        : {}),
      idempotencyKey: `${idempotencyPrefix}:post:${post.id}:${post.version}`,
      postId: post.id,
      messageType: "pending_list"
    });
  }
}

async function commandStatus(chatId: number, idempotencyPrefix: string): Promise<void> {
  const queue = await db()<
    Array<{ status: string; count: number }>
  >`
    select status, count(*)::integer as count
    from app.job_queue
    group by status
  `;
  const health = await db()<
    Array<{
      subsystem: string;
      last_success_at: string | null;
      last_error_at: string | null;
    }>
  >`
    select subsystem, last_success_at, last_error_at
    from app.system_health order by subsystem
  `;
  const backups = await db()<
    Array<{ status: string; completed_at: string | null }>
  >`
    select status, completed_at
    from app.backup_runs
    order by started_at desc
    limit 1
  `;
  const queueSummary =
    queue.map((item) => `${item.status}: ${item.count}`).join(", ") || "vacía";
  const healthSummary = health
    .map(
      (item) =>
        `${item.subsystem}: ${
          item.last_error_at &&
          (!item.last_success_at ||
            new Date(item.last_error_at) > new Date(item.last_success_at))
            ? "con error"
            : "bien"
        }`
    )
    .join("\n");
  const backup = backups[0]
    ? `${backups[0].status}, ${formatLocalDate(backups[0].completed_at)}`
    : "sin ejecución registrada";
  await sendTelegramMessage({
    chatId,
    text: `Estado del sistema\n\nCola: ${queueSummary}\n\n${healthSummary}\n\nÚltimo backup: ${backup}`,
    idempotencyKey: `${idempotencyPrefix}:status`
  });
}

async function commandArticles(chatId: number, idempotencyPrefix: string): Promise<void> {
  const candidates = await db()<
    Array<{ title: string; source_url: string; source_kind: string; score: string }>
  >`
    select title, source_url, source_kind, score::text
    from app.radar_candidates
    where excluded = false
      and source_kind in ('article', 'news', 'paper', 'tool', 'practice')
    order by discovered_at desc, score desc
    limit 10
  `;
  const text = candidates.length
    ? [
        "Fuentes recientes del radar",
        "",
        ...candidates.map(
          (item) => `${item.title}\nTipo: ${item.source_kind}\n${item.source_url}`
        )
      ].join("\n\n")
    : "El radar todavía no tiene fuentes recientes para mostrar.";
  await sendTelegramMessage({
    chatId,
    text,
    idempotencyKey: `${idempotencyPrefix}:articles`
  });
}

async function commandDay(
  chatId: number,
  argument: string,
  idempotencyPrefix: string
): Promise<void> {
  const match = argument.trim().match(/^(\d{1,2})[/-](\d{1,2})(?:[/-](\d{4}))?$/);
  if (!match) {
    await sendTelegramMessage({
      chatId,
      text: "Usa /dia DD/MM o /dia DD/MM/AAAA.",
      idempotencyKey: `${idempotencyPrefix}:invalid`
    });
    return;
  }
  const year = Number(match[3] ?? new Date().getFullYear());
  const month = Number(match[2]);
  const day = Number(match[1]);
  const date = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  const posts = await db()<PostSummary[]>`
    select id, status, linkedin_text, tweet_url, tweet_author, publish_at,
           scheduled_at, source, media_type, version
    from app.posts
    where coalesce(publish_at, scheduled_at, created_at) >=
          (${date}::date::timestamp at time zone 'America/Mexico_City')
      and coalesce(publish_at, scheduled_at, created_at) <
          ((${date}::date + 1)::timestamp at time zone 'America/Mexico_City')
    order by coalesce(publish_at, scheduled_at, created_at), id
    limit 20
  `;
  await sendTelegramMessage({
    chatId,
    text: posts.length
      ? [
          `Publicaciones del ${date}`,
          "",
          ...posts.map(
            (post) =>
              `Post #${post.id}: ${post.status}, ${formatLocalDate(
                post.publish_at ?? post.scheduled_at
              )}\n${compactText(post.linkedin_text || "Radar pendiente", 180)}`
          )
        ].join("\n\n")
      : `No hay publicaciones el ${date}.`,
    idempotencyKey: `${idempotencyPrefix}:day:${date}`
  });
}

async function processCommand(message: TelegramMessage, updateId: number): Promise<boolean> {
  const text = (message.text ?? "").trim();
  if (!text.startsWith("/")) return false;
  const [rawCommand = "", ...parts] = text.split(/\s+/);
  const command = rawCommand.split("@")[0]!.toLowerCase();
  const prefix = `telegram_command:${updateId}`;
  if (command === "/hoy") await commandToday(message.chat.id, prefix);
  else if (command === "/pendientes") await commandPending(message.chat.id, prefix);
  else if (command === "/status") await commandStatus(message.chat.id, prefix);
  else if (command === "/articulos") await commandArticles(message.chat.id, prefix);
  else if (command === "/dia") await commandDay(message.chat.id, parts.join(" "), prefix);
  else {
    await sendTelegramMessage({
      chatId: message.chat.id,
      text:
        "Comandos disponibles: /hoy, /pendientes, /status, /dia DD/MM y /articulos.",
      idempotencyKey: `${prefix}:help`
    });
  }
  return true;
}

async function processTextMessage(message: TelegramMessage, updateId: number): Promise<void> {
  const text = compactText(message.text ?? "", 5000);
  if (!text) return;
  if (await processCommand(message, updateId)) return;
  const userId = message.from!.id;
  const reply = await locateReplyEntity(message.chat.id, message.reply_to_message);
  const session = await sessionFor(userId);
  const postId = reply.postId ?? session?.post_id ?? null;
  const commentId = reply.commentId ?? session?.comment_id ?? null;

  if (postId && (!session || session.mode === "revise_post" || reply.postId)) {
    const rows = await db()<[{ append_revision_and_enqueue: number }]>`
      select app.append_revision_and_enqueue(${postId}, ${text}, 'telegram')
    `;
    await clearSession(userId);
    await sendTelegramMessage({
      chatId: message.chat.id,
      text: `Recibí los cambios para el post #${postId}. Prepararé una nueva versión y la aprobación seguirá abierta.`,
      replyToMessageId: message.message_id,
      idempotencyKey: `revision_received:${updateId}:${rows[0]!.append_revision_and_enqueue}`,
      postId,
      messageType: "revision_ack"
    });
    return;
  }

  if (commentId && session?.mode === "edit_comment") {
    await db()`
      update app.linkedin_comments
      set suggested_reply = ${text}, reply_status = 'pending', updated_at = now()
      where id = ${commentId}
    `;
    await clearSession(userId);
    await sendTelegramMessage({
      chatId: message.chat.id,
      text: `Actualicé la respuesta sugerida del comentario #${commentId}.`,
      idempotencyKey: `comment_edit_ack:${updateId}`,
      commentId
    });
    return;
  }

  const url = text.match(/https?:\/\/[^\s]+/i)?.[0];
  if (url) {
    const normalized = normalizeUrl(url);
    const sql = db();
    const posts = await sql<Array<{ id: number; version: number }>>`
      insert into app.posts (
        tweet_url, tweet_text, linkedin_text, status, source, media_type,
        source_metadata
      ) values (
        ${normalized}, '', '', 'pending', 'telegram', 'none',
        ${sql.json({ submitted_via: "telegram", update_id: updateId } as never)}
      )
      returning id, version
    `;
    const post = posts[0]!;
    await sql`
      select app.enqueue_job(
        'prepare_url',
        now(),
        jsonb_build_object('post_id', ${post.id}),
        ${`prepare_url:${post.id}:${post.version}`},
        4,
        30,
        null
      )
    `;
    await sendTelegramMessage({
      chatId: message.chat.id,
      text: `Recibí la fuente para el post #${post.id}. Decidiré el mejor tratamiento editorial y te enviaré el borrador.`,
      idempotencyKey: `url_received:${updateId}`,
      postId: post.id
    });
    return;
  }

  await sendTelegramMessage({
    chatId: message.chat.id,
    text:
      "No pude relacionar ese mensaje con una publicación. Responde directamente a la tarjeta que quieres cambiar o envía un enlace.",
    idempotencyKey: `telegram_unmatched:${updateId}`
  });
}

async function processCallback(callback: TelegramCallback, updateId: number): Promise<void> {
  const data = callback.data ?? "";
  const match = data.match(/^([a-z_]+):(\d+)$/);
  if (!match) {
    await answerCallback(callback.id, "Ese botón ya no es válido.", updateId);
    return;
  }
  const action = match[1]!;
  const entityId = Number(match[2]);
  const chatId = callback.message?.chat.id ?? callback.from.id;

  if (action === "approve") {
    const current = await db()<Array<{ status: string }>>`
      select status from app.posts where id = ${entityId}
    `;
    if (
      !current[0] ||
      !["approval_pending", "scheduled", "publishing", "published"].includes(
        current[0].status
      )
    ) {
      await answerCallback(
        callback.id,
        `Estado actual: ${current[0]?.status ?? "ausente"}.`,
        updateId
      );
      return;
    }
    const result = await approvePost(entityId);
    await answerCallback(
      callback.id,
      result.already_processed ? "La decisión ya estaba registrada." : "Aprobado.",
      updateId
    );
    await clearCallbackButtons(callback, updateId);
    await sendTelegramMessage({
      chatId,
      text: `Post #${entityId} programado para ${formatLocalDate(result.publish_at)}. Son 30 minutos desde la aprobación.`,
      idempotencyKey: `approval_confirmation:${entityId}`,
      postId: entityId,
      messageType: "approval_confirmation"
    });
    return;
  }

  if (action === "revise") {
    const posts = await db()<Array<{ status: string }>>`
      select status from app.posts where id = ${entityId}
    `;
    if (posts[0]?.status !== "approval_pending") {
      await answerCallback(callback.id, `El post ahora está ${posts[0]?.status ?? "ausente"}.`, updateId);
      return;
    }
    await setSession({
      userId: callback.from.id,
      chatId,
      mode: "revise_post",
      postId: entityId
    });
    await answerCallback(callback.id, "Listo para recibir tus cambios.", updateId);
    await sendTelegramMessage({
      chatId,
      text: `Responde a esta tarjeta con los cambios para el post #${entityId}. Puedes escribirlos con lenguaje natural.`,
      idempotencyKey: `revision_prompt:${updateId}`,
      postId: entityId,
      messageType: "revision_prompt"
    });
    return;
  }

  if (action === "another") {
    const current = await db()<Array<{ status: string }>>`
      select status from app.posts where id = ${entityId}
    `;
    if (current[0]?.status !== "approval_pending") {
      await answerCallback(
        callback.id,
        `Estado actual: ${current[0]?.status ?? "ausente"}.`,
        updateId
      );
      return;
    }
    await requestAnotherSource(entityId);
    await answerCallback(callback.id, "Buscaré otra fuente.", updateId);
    await clearCallbackButtons(callback, updateId);
    await sendTelegramMessage({
      chatId,
      text: `Descarté la fuente anterior del post #${entityId}. El radar volverá a decidir sin repetirla.`,
      idempotencyKey: `another_source_ack:${updateId}`,
      postId: entityId
    });
    return;
  }

  if (action === "cancel") {
    const status = await cancelPost(entityId);
    await answerCallback(callback.id, `Estado actual: ${status}.`, updateId);
    if (status === "cancelled") await clearCallbackButtons(callback, updateId);
    return;
  }

  if (action === "comment_publish") {
    const comments = await db()<Array<{ reply_status: string }>>`
      select reply_status from app.linkedin_comments where id = ${entityId}
    `;
    if (!comments[0] || !["pending", "failed"].includes(comments[0].reply_status)) {
      await answerCallback(
        callback.id,
        `Estado actual: ${comments[0]?.reply_status ?? "ausente"}.`,
        updateId
      );
      return;
    }
    await db()`
      update app.linkedin_comments
      set reply_status = 'approved', updated_at = now()
      where id = ${entityId}
    `;
    await db()`
      select app.enqueue_job(
        'publish_comment',
        now(),
        jsonb_build_object('comment_id', ${entityId}),
        ${`publish_comment:${entityId}`},
        5,
        20,
        null
      )
    `;
    await answerCallback(callback.id, "Respuesta aprobada.", updateId);
    await clearCallbackButtons(callback, updateId);
    return;
  }

  if (action === "comment_edit") {
    await setSession({
      userId: callback.from.id,
      chatId,
      mode: "edit_comment",
      commentId: entityId
    });
    await answerCallback(callback.id, "Escribe la nueva respuesta.", updateId);
    return;
  }

  if (action === "comment_dismiss") {
    await db()`
      update app.linkedin_comments
      set reply_status = 'dismissed', updated_at = now()
      where id = ${entityId} and reply_status in ('pending', 'approved', 'failed')
    `;
    await answerCallback(callback.id, "Respuesta descartada.", updateId);
    await clearCallbackButtons(callback, updateId);
    return;
  }

  await answerCallback(callback.id, "Ese botón ya no es válido.", updateId);
}

export async function processTelegramUpdate(update: TelegramUpdate): Promise<{
  duplicate: boolean;
  accepted: boolean;
}> {
  if (!Number.isSafeInteger(update.update_id)) throw new Error("Invalid Telegram update_id");
  const callback = update.callback_query;
  const message = update.message;
  const userId = callback?.from.id ?? message?.from?.id ?? null;
  const chatId = callback?.message?.chat.id ?? message?.chat.id ?? null;
  const updateType = callback ? "callback_query" : message ? "message" : "unsupported";
  const inserted = await db()<[{ update_id: number }]>`
    insert into app.telegram_updates (
      update_id, chat_id, user_id, update_type, payload_hash
    ) values (
      ${update.update_id}, ${chatId}, ${userId}, ${updateType}, ${hash(update)}
    )
    on conflict (update_id) do nothing
    returning update_id
  `;
  if (!inserted[0]) return { duplicate: true, accepted: true };

  if (userId !== allowedTelegramUser()) {
    await db()`
      update app.telegram_updates
      set status = 'rejected', processed_at = now()
      where update_id = ${update.update_id}
    `;
    return { duplicate: false, accepted: false };
  }

  try {
    if (callback) await processCallback(callback, update.update_id);
    else if (message) await processTextMessage(message, update.update_id);
    await db()`
      update app.telegram_updates
      set status = 'processed', processed_at = now()
      where update_id = ${update.update_id}
    `;
    return { duplicate: false, accepted: true };
  } catch (error) {
    await db()`
      update app.telegram_updates
      set status = 'failed', error_message = ${redact(error)}, processed_at = now()
      where update_id = ${update.update_id}
    `;
    await recordEvent({
      subsystem: "telegram",
      eventType: "webhook_failed",
      severity: "error",
      entityType: "telegram_update",
      entityId: update.update_id,
      message: redact(error),
      dedupeKey: `telegram_update_failed:${update.update_id}`
    });
    throw error;
  }
}

export function commentKeyboard(commentId: number): Record<string, unknown> {
  return {
    inline_keyboard: [
      [{ text: "Publicar respuesta", callback_data: `comment_publish:${commentId}` }],
      [
        { text: "Editar", callback_data: `comment_edit:${commentId}` },
        { text: "Descartar", callback_data: `comment_dismiss:${commentId}` }
      ]
    ]
  };
}

export async function notifyDeadJob(jobId: number, jobType: string): Promise<void> {
  await sendTelegramMessage({
    text: `El job #${jobId} (${jobType}) agotó sus intentos. Sigue visible en la cola para revisión manual.`,
    idempotencyKey: `dead_job:${jobId}`,
    messageType: "alert"
  });
}

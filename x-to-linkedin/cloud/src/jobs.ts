import { db } from "./db.js";
import { currentCostState, currentStorageState } from "./cost.js";
import { switches } from "./env.js";
import { recordEvent } from "./events.js";
import {
  createComment,
  publishPost,
  reconcileAmbiguousPublication
} from "./linkedin.js";
import {
  prepareProvidedUrl,
  refreshMetricsBatch,
  revisePost,
  syncCommentsBatch,
  verifyPostSource
} from "./operations.js";
import {
  maintainRadarSchedule,
  prepareRadarPost
} from "./radar.js";
import { enqueueJob, type JobRow } from "./queue.js";
import {
  commentKeyboard,
  notifyDeadJob,
  sendApprovalCard,
  sendTelegramMessage
} from "./telegram.js";

export class DeferredJobError extends Error {
  constructor(
    message: string,
    readonly delaySeconds: number
  ) {
    super(message);
  }
}

function payloadId(job: JobRow, name: string): number {
  const value = Number(job.payload[name]);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`Job ${job.id} has invalid ${name}`);
  }
  return value;
}

async function setHealth(
  subsystem: string,
  error: unknown = null,
  metadata: Record<string, unknown> = {}
): Promise<void> {
  const sql = db();
  if (error) {
    await sql`
      update app.system_health
      set last_error_at = now(),
          last_error = ${error instanceof Error ? error.message.slice(0, 1000) : String(error).slice(0, 1000)},
          metadata = ${sql.json(metadata as never)},
          updated_at = now()
      where subsystem = ${subsystem}
    `;
  } else {
    await sql`
      update app.system_health
      set last_success_at = now(),
          last_error = null,
          metadata = ${sql.json(metadata as never)},
          updated_at = now()
      where subsystem = ${subsystem}
    `;
  }
}

async function notifyApproval(job: JobRow): Promise<Record<string, unknown>> {
  const postId = payloadId(job, "post_id");
  const rows = await db()<
    Array<{ version: number; source_metadata: { reason?: string } }>
  >`
    select version, source_metadata from app.posts where id = ${postId}
  `;
  const post = rows[0];
  if (!post) throw new Error("Post not found");
  const messageId = await sendApprovalCard(
    postId,
    post.source_metadata.reason ?? "",
    post.version
  );
  if (!switches.telegramSendEnabled()) {
    throw new DeferredJobError("Telegram send is disabled", 3600);
  }
  return { post_id: postId, message_id: messageId };
}

async function notifyComment(job: JobRow): Promise<Record<string, unknown>> {
  const commentId = payloadId(job, "comment_id");
  const comments = await db()<
    Array<{
      id: number;
      commenter_name: string;
      comment_text: string;
      suggested_reply: string | null;
    }>
  >`
    select id, commenter_name, comment_text, suggested_reply
    from app.linkedin_comments where id = ${commentId}
  `;
  const comment = comments[0];
  if (!comment) throw new Error("Comment not found");
  const messageId = await sendTelegramMessage({
    text: [
      `Comentario #${comment.id}`,
      `De: ${comment.commenter_name || "Persona en LinkedIn"}`,
      "",
      comment.comment_text,
      "",
      "Respuesta propuesta:",
      comment.suggested_reply || "Sin propuesta todavía."
    ].join("\n"),
    replyMarkup: commentKeyboard(comment.id),
    idempotencyKey: `comment_card:${comment.id}`,
    commentId: comment.id,
    messageType: "comment"
  });
  if (!switches.telegramSendEnabled()) {
    throw new DeferredJobError("Telegram send is disabled", 3600);
  }
  if (messageId) {
    await db()`
      update app.linkedin_comments
      set telegram_message_id = ${messageId}, last_notified_at = now()
      where id = ${commentId}
    `;
  }
  return { comment_id: commentId, message_id: messageId };
}

async function publishComment(job: JobRow): Promise<Record<string, unknown>> {
  if (!switches.publishingEnabled()) {
    throw new DeferredJobError("Publishing is disabled", 900);
  }
  const commentId = payloadId(job, "comment_id");
  const comments = await db()<
    Array<{
      linkedin_comment_urn: string;
      parent_comment_urn: string | null;
      linkedin_object_urn: string;
      suggested_reply: string | null;
      reply_status: string;
      published_reply_urn: string | null;
    }>
  >`
    select linkedin_comment_urn, parent_comment_urn, linkedin_object_urn,
           suggested_reply, reply_status, published_reply_urn
    from app.linkedin_comments where id = ${commentId}
  `;
  const comment = comments[0];
  if (!comment) throw new Error("Comment not found");
  if (comment.reply_status === "published" && comment.published_reply_urn) {
    return { comment_id: commentId, external_id: comment.published_reply_urn };
  }
  if (comment.reply_status !== "approved" || !comment.suggested_reply) {
    throw new Error("Comment reply is not approved");
  }
  const externalId = await createComment({
    targetUrn: comment.linkedin_comment_urn,
    objectUrn: comment.linkedin_object_urn,
    text: comment.suggested_reply,
    ...(comment.parent_comment_urn ? { parentCommentUrn: comment.parent_comment_urn } : {}),
    idempotencyKey: `linkedin_comment:${commentId}`
  });
  if (!externalId) throw new Error("LinkedIn returned no comment ID");
  await db()`
    update app.linkedin_comments
    set reply_status = 'published',
        owner_replied = true,
        owner_reply_text = suggested_reply,
        published_reply_text = suggested_reply,
        published_reply_urn = ${externalId},
        error_message = null,
        updated_at = now()
    where id = ${commentId}
  `;
  return { comment_id: commentId, external_id: externalId };
}

async function runNoncritical(
  action: () => Promise<Record<string, unknown>>,
  delaySeconds: number
): Promise<Record<string, unknown>> {
  const cost = await currentCostState();
  if (!cost.noncriticalAllowed) {
    throw new DeferredJobError(`Noncritical jobs paused at ${cost.percentage.toFixed(1)}%`, delaySeconds);
  }
  return action();
}

async function monitorCostAndStorage(): Promise<Record<string, unknown>> {
  const cost = await currentCostState();
  const storage = await currentStorageState();
  const month = new Date().toISOString().slice(0, 7);
  const costThreshold =
    cost.percentage >= 90
      ? 90
      : cost.percentage >= 85
        ? 85
        : cost.percentage >= 70
          ? 70
          : cost.percentage >= 50
            ? 50
            : null;
  const storageThreshold =
    storage.databaseMegabytes >= 425
      ? 425
      : storage.databaseMegabytes >= 350
        ? 350
        : null;

  if (costThreshold) {
    const text = [
      `Alerta de costo: ${cost.percentage.toFixed(1)}% de los créditos Netlify estimados.`,
      `Nivel operativo: ${cost.level}.`,
      cost.hardLimitReached
        ? "El límite duro está alcanzado. No se habilitará cobro."
        : `Quedan aproximadamente ${cost.remainingCredits.toFixed(1)} créditos.`
    ].join("\n");
    await sendTelegramMessage({
      text,
      idempotencyKey: `cost_alert:${month}:${costThreshold}`,
      messageType: "alert"
    });
    await recordEvent({
      subsystem: "cost",
      eventType: "netlify_threshold",
      severity: costThreshold >= 90 ? "critical" : "warning",
      message: text,
      metadata: { threshold: costThreshold, ...cost },
      dedupeKey: `cost_alert:${month}:${costThreshold}`
    });
  }

  if (storageThreshold) {
    const text =
      `Alerta de almacenamiento: la base usa ${storage.databaseMegabytes.toFixed(1)} MB. ` +
      `Umbral ${storageThreshold} MB.`;
    await sendTelegramMessage({
      text,
      idempotencyKey: `storage_alert:${month}:${storageThreshold}`,
      messageType: "alert"
    });
    await recordEvent({
      subsystem: "cost",
      eventType: "database_storage_threshold",
      severity: storageThreshold >= 425 ? "critical" : "warning",
      message: text,
      metadata: { threshold_mb: storageThreshold, ...storage },
      dedupeKey: `storage_alert:${month}:${storageThreshold}`
    });
  }

  const result = { cost, storage };
  await setHealth("cost", null, result);
  return result;
}

export async function runJob(job: JobRow): Promise<Record<string, unknown>> {
  const correlationId = job.correlation_id ?? crypto.randomUUID();
  switch (job.job_type) {
    case "radar_maintenance": {
      if (!switches.radarEnabled()) {
        throw new DeferredJobError("Radar is disabled", 21_600);
      }
      const result = await maintainRadarSchedule();
      await setHealth("radar", null, result);
      return result;
    }
    case "radar_prepare": {
      if (!switches.radarEnabled()) {
        throw new DeferredJobError("Radar is disabled", 21_600);
      }
      const postId = payloadId(job, "post_id");
      const decision = await prepareRadarPost(postId);
      await setHealth("radar", null, { post_id: postId, intent: decision.intent });
      return { post_id: postId, intent: decision.intent, reason: decision.reason };
    }
    case "prepare_url": {
      const postId = payloadId(job, "post_id");
      const result = await prepareProvidedUrl(postId);
      const version = Number(result.version ?? 1);
      await enqueueJob({
        type: "notify_approval",
        payload: { post_id: postId },
        dedupeKey: `notify_approval:${postId}:${version}`,
        priority: 20,
        correlationId
      });
      return result;
    }
    case "revise_post": {
      const postId = payloadId(job, "post_id");
      const result = await revisePost(postId);
      const version = Number(result.version ?? 1);
      await enqueueJob({
        type: "notify_approval",
        payload: { post_id: postId },
        dedupeKey: `notify_approval:${postId}:${version}`,
        priority: 20,
        correlationId
      });
      return result;
    }
    case "notify_approval":
      return notifyApproval(job);
    case "publish_post": {
      if (!switches.publishingEnabled()) {
        throw new DeferredJobError("Publishing is disabled", 900);
      }
      const postId = payloadId(job, "post_id");
      await verifyPostSource(postId);
      const externalId = await publishPost(postId, correlationId);
      await setHealth("linkedin", null, { last_post_id: postId });
      return { post_id: postId, external_id: externalId };
    }
    case "reconcile_publish": {
      const postId = payloadId(job, "post_id");
      const result = await reconcileAmbiguousPublication(postId);
      if (!result.reconciled) {
        throw new Error("Ambiguous publication was not found in recent LinkedIn posts");
      }
      return result;
    }
    case "verify_post": {
      const postId = payloadId(job, "post_id");
      return verifyPostSource(postId);
    }
    case "metrics_refresh":
      return runNoncritical(() => refreshMetricsBatch(), 86_400);
    case "comments_sync":
      return runNoncritical(() => syncCommentsBatch(), 3_600);
    case "notify_comment":
      return notifyComment(job);
    case "notify_alert": {
      const text = String(job.payload.text ?? "").trim().slice(0, 3500);
      const alertKey = String(job.payload.alert_key ?? job.id).slice(0, 300);
      if (!text) throw new Error("Alert job has no text");
      const messageId = await sendTelegramMessage({
        text,
        idempotencyKey: `operational_alert:${alertKey}`,
        messageType: "alert"
      });
      if (!switches.telegramSendEnabled()) {
        throw new DeferredJobError("Telegram send is disabled", 3600);
      }
      return { message_id: messageId, alert_key: alertKey };
    }
    case "publish_comment":
      return publishComment(job);
    case "editorial_profile":
      return runNoncritical(async () => {
        const { loadOrBuildEditorialProfile } = await import("./editorial.js");
        const profile = await loadOrBuildEditorialProfile(true);
        return { profile_length: profile.length };
      }, 86_400);
    case "cost_monitor":
      return monitorCostAndStorage();
    default:
      throw new Error(`Unsupported job type: ${job.job_type}`);
  }
}

export async function handleDeadJob(job: JobRow, error: unknown): Promise<void> {
  await setHealth("queue", error, { job_id: job.id, job_type: job.job_type });
  await recordEvent({
    subsystem: "queue",
    eventType: "job_dead",
    severity: "critical",
    ...(job.correlation_id ? { correlationId: job.correlation_id } : {}),
    entityType: "job",
    entityId: job.id,
    message: error instanceof Error ? error.message : String(error),
    metadata: { job_type: job.job_type, attempts: job.attempts },
    dedupeKey: `job_dead:${job.id}`
  });
  await notifyDeadJob(job.id, job.job_type);
}

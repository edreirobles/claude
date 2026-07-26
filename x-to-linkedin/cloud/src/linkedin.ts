import { createHash, randomBytes, randomUUID } from "node:crypto";
import { db } from "./db.js";
import {
  decryptSecret,
  encryptSecret,
  type EncryptedValue
} from "./crypto.js";
import { env, envBoolean, requiredEnv } from "./env.js";
import { recordEvent } from "./events.js";
import { safeFetch } from "./external-url.js";
import { enqueueJob } from "./queue.js";
import { redact } from "./redaction.js";

const API_BASE = "https://api.linkedin.com/v2";
const REST_BASE = "https://api.linkedin.com/rest";
const AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization";
const TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken";

type TokenRow = {
  id: number;
  access_token_cipher: EncryptedValue;
  refresh_token_cipher: EncryptedValue | null;
  person_urn: string;
  person_name: string;
  person_picture: string;
  expires_at: Date | null;
  refresh_token_expires_at: Date | null;
};

type PostRow = {
  id: number;
  linkedin_text: string;
  image_urls: string[];
  use_first_image: boolean;
  media_type: string;
  pdf_url: string | null;
  document_title: string;
  status: string;
  publish_at: Date | null;
  linkedin_post_id: string | null;
};

export class LinkedInReconnectError extends Error {}

class LinkedInApiError extends Error {
  constructor(
    message: string,
    readonly status: number | null,
    readonly ambiguous: boolean
  ) {
    super(message);
  }
}

function authHeaders(accessToken: string): HeadersInit {
  return {
    authorization: `Bearer ${accessToken}`,
    "content-type": "application/json",
    "x-restli-protocol-version": "2.0.0",
    "linkedin-version": env("LINKEDIN_API_VERSION", "202605")
  };
}

function asPersonUrn(value: string): string {
  return value.startsWith("urn:li:person:") ? value : `urn:li:person:${value}`;
}

async function fetchLinkedIn(
  url: string,
  init: RequestInit,
  ambiguousOnNetwork = false
): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25_000);
  try {
    const response = await fetch(url, { ...init, signal: controller.signal });
    if (!response.ok) {
      const text = (await response.text()).slice(0, 800);
      throw new LinkedInApiError(
        `LinkedIn returned ${response.status}: ${text}`,
        response.status,
        false
      );
    }
    return response;
  } catch (error) {
    if (error instanceof LinkedInApiError) throw error;
    throw new LinkedInApiError(
      error instanceof Error ? error.message : "LinkedIn network error",
      null,
      ambiguousOnNetwork
    );
  } finally {
    clearTimeout(timeout);
  }
}

async function loadToken(): Promise<TokenRow> {
  const rows = await db()<TokenRow[]>`
    select * from app.linkedin_tokens order by id limit 1
  `;
  if (!rows[0]) throw new LinkedInReconnectError("LinkedIn is not connected");
  return rows[0];
}

async function persistRefreshedToken(
  token: TokenRow,
  payload: Record<string, unknown>
): Promise<TokenRow> {
  const accessToken = String(payload.access_token ?? "");
  if (!accessToken) throw new LinkedInReconnectError("LinkedIn refresh returned no token");
  const refreshToken = String(payload.refresh_token ?? "");
  const expiresIn = Number(payload.expires_in ?? 0);
  const refreshExpiresIn = Number(payload.refresh_token_expires_in ?? 0);
  const rows = await db()<TokenRow[]>`
    update app.linkedin_tokens
    set access_token_cipher = ${db().json(encryptSecret(accessToken))},
        refresh_token_cipher = case
          when ${refreshToken} = '' then refresh_token_cipher
          else ${db().json(refreshToken ? encryptSecret(refreshToken) : null)}
        end,
        expires_at = case
          when ${expiresIn} > 0 then now() + make_interval(secs => ${expiresIn})
          else null
        end,
        refresh_token_expires_at = case
          when ${refreshExpiresIn} > 0 then now() + make_interval(secs => ${refreshExpiresIn})
          else refresh_token_expires_at
        end
    where id = ${token.id}
    returning *
  `;
  return rows[0]!;
}

export async function validAccessToken(): Promise<{
  accessToken: string;
  personUrn: string;
  token: TokenRow;
}> {
  let token = await loadToken();
  const stillValid =
    !token.expires_at ||
    new Date(token.expires_at).valueOf() > Date.now() + 5 * 60 * 1000;
  if (!stillValid) {
    if (
      !token.refresh_token_cipher ||
      (token.refresh_token_expires_at &&
        new Date(token.refresh_token_expires_at).valueOf() <= Date.now())
    ) {
      throw new LinkedInReconnectError("LinkedIn requires reconnection");
    }
    const body = new URLSearchParams({
      grant_type: "refresh_token",
      refresh_token: decryptSecret(token.refresh_token_cipher),
      client_id: requiredEnv("LINKEDIN_CLIENT_ID"),
      client_secret: requiredEnv("LINKEDIN_CLIENT_SECRET")
    });
    const response = await fetchLinkedIn(TOKEN_URL, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body
    });
    token = await persistRefreshedToken(
      token,
      (await response.json()) as Record<string, unknown>
    );
  }
  return {
    accessToken: decryptSecret(token.access_token_cipher),
    personUrn: token.person_urn,
    token
  };
}

function stateHash(state: string): Buffer {
  return createHash("sha256").update(state).digest();
}

export async function createLinkedInOAuthUrl(): Promise<string> {
  const state = randomBytes(32).toString("base64url");
  await db()`
    insert into app.oauth_states (state_hash, provider, expires_at)
    values (${stateHash(state)}, 'linkedin', now() + interval '10 minutes')
  `;
  const scopes = ["openid", "profile", "email", "w_member_social"];
  if (envBoolean("LINKEDIN_READ_SCOPE_ENABLED", false)) {
    scopes.push("r_member_social");
  }
  const params = new URLSearchParams({
    response_type: "code",
    client_id: requiredEnv("LINKEDIN_CLIENT_ID"),
    redirect_uri: requiredEnv("LINKEDIN_REDIRECT_URI"),
    state,
    scope: scopes.join(" ")
  });
  return `${AUTH_URL}?${params.toString()}`;
}

export async function finishLinkedInOAuth(
  code: string,
  state: string
): Promise<void> {
  const consumed = await db()<[{ provider: string }]>`
    update app.oauth_states
    set used_at = now()
    where state_hash = ${stateHash(state)}
      and provider = 'linkedin'
      and used_at is null
      and expires_at > now()
    returning provider
  `;
  if (!consumed[0]) throw new Error("Invalid or expired OAuth state");

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: requiredEnv("LINKEDIN_REDIRECT_URI"),
    client_id: requiredEnv("LINKEDIN_CLIENT_ID"),
    client_secret: requiredEnv("LINKEDIN_CLIENT_SECRET")
  });
  const tokenResponse = await fetchLinkedIn(TOKEN_URL, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body
  });
  const tokenPayload = (await tokenResponse.json()) as Record<string, unknown>;
  const accessToken = String(tokenPayload.access_token ?? "");
  if (!accessToken) throw new Error("LinkedIn returned no access token");
  const profileResponse = await fetchLinkedIn(`${API_BASE}/userinfo`, {
    headers: authHeaders(accessToken)
  });
  const profile = (await profileResponse.json()) as Record<string, unknown>;
  const refreshToken = String(tokenPayload.refresh_token ?? "");
  const expiresIn = Number(tokenPayload.expires_in ?? 0);
  const refreshExpiresIn = Number(tokenPayload.refresh_token_expires_in ?? 0);
  const sql = db();
  await sql.begin(async (transaction) => {
    await transaction`delete from app.linkedin_tokens`;
    await transaction`
      insert into app.linkedin_tokens (
        access_token_cipher, refresh_token_cipher, person_urn, person_name,
        person_picture, expires_at, refresh_token_expires_at
      ) values (
        ${transaction.json(encryptSecret(accessToken))},
        ${refreshToken ? transaction.json(encryptSecret(refreshToken)) : null},
        ${String(profile.sub ?? "")},
        ${String(profile.name ?? "")},
        ${String(profile.picture ?? "")},
        ${expiresIn > 0 ? new Date(Date.now() + expiresIn * 1000).toISOString() : null},
        ${refreshExpiresIn > 0
          ? new Date(Date.now() + refreshExpiresIn * 1000).toISOString()
          : null}
      )
    `;
  });
  await recordEvent({
    subsystem: "linkedin",
    eventType: "oauth_connected",
    entityType: "linkedin_account",
    entityId: String(profile.sub ?? ""),
    dedupeKey: `linkedin_oauth:${String(profile.sub ?? "")}:${new Date().toISOString().slice(0, 10)}`
  });
}

export async function linkedinStatus(): Promise<Record<string, unknown>> {
  try {
    const valid = await validAccessToken();
    return {
      connected: true,
      person_name: valid.token.person_name,
      person_picture: valid.token.person_picture,
      person_urn: valid.token.person_urn,
      expires_at: valid.token.expires_at,
      can_refresh: Boolean(valid.token.refresh_token_cipher),
      needs_reconnect: false,
      message: ""
    };
  } catch (error) {
    const rows = await db()<TokenRow[]>`
      select * from app.linkedin_tokens order by id limit 1
    `;
    const token = rows[0];
    return {
      connected: false,
      person_name: token?.person_name ?? "",
      person_picture: token?.person_picture ?? "",
      person_urn: token?.person_urn ?? "",
      expires_at: token?.expires_at ?? null,
      can_refresh: Boolean(token?.refresh_token_cipher),
      needs_reconnect: Boolean(token),
      message: error instanceof LinkedInReconnectError ? error.message : "LinkedIn unavailable"
    };
  }
}

async function initializeUpload(
  accessToken: string,
  personUrn: string,
  type: "image" | "document"
): Promise<{ uploadUrl: string; mediaUrn: string }> {
  const resource = type === "image" ? "images" : "documents";
  const response = await fetchLinkedIn(`${REST_BASE}/${resource}?action=initializeUpload`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify({
      initializeUploadRequest: {
        owner: asPersonUrn(personUrn)
      }
    })
  });
  const payload = (await response.json()) as any;
  const value = payload.value ?? {};
  const mediaUrn = String(type === "image" ? value.image ?? "" : value.document ?? "");
  const uploadUrl = String(value.uploadUrl ?? "");
  if (!uploadUrl || !mediaUrn) {
    throw new Error(`LinkedIn ${type} upload initialization was incomplete`);
  }
  return {
    uploadUrl,
    mediaUrn
  };
}

async function uploadSourceAsset(input: {
  accessToken: string;
  personUrn: string;
  url: string;
  type: "image" | "document";
}): Promise<string> {
  const source = await safeFetch(input.url, {}, 25 * 1024 * 1024);
  if (!source.ok) throw new Error(`Media source returned ${source.status}`);
  const bytes = Buffer.from(await source.arrayBuffer());
  if (bytes.length > 25 * 1024 * 1024) throw new Error("Media source is too large");
  const upload = await initializeUpload(input.accessToken, input.personUrn, input.type);
  await fetchLinkedIn(upload.uploadUrl, {
    method: "PUT",
    headers: {
      authorization: `Bearer ${input.accessToken}`,
      "content-type": input.type === "document" ? "application/pdf" : "application/octet-stream"
    },
    body: bytes
  });
  return upload.mediaUrn;
}

export function buildPostPayload(input: {
  personUrn: string;
  text: string;
  assetUrn?: string;
  documentTitle?: string;
}): Record<string, unknown> {
  return {
    author: asPersonUrn(input.personUrn),
    commentary: input.text,
    visibility: "PUBLIC",
    distribution: {
      feedDistribution: "MAIN_FEED",
      targetEntities: [],
      thirdPartyDistributionChannels: []
    },
    ...(input.assetUrn
      ? {
          content: {
            media: {
              id: input.assetUrn,
              ...(input.documentTitle ? { title: input.documentTitle } : {})
            }
          }
        }
      : {}),
    lifecycleState: "PUBLISHED",
    isReshareDisabledByAuthor: false
  };
}

async function createPost(input: {
  accessToken: string;
  personUrn: string;
  text: string;
  mediaType: "none" | "image" | "document";
  assetUrn?: string;
  documentTitle?: string;
}): Promise<string> {
  const response = await fetchLinkedIn(
    `${REST_BASE}/posts`,
    {
      method: "POST",
      headers: authHeaders(input.accessToken),
      body: JSON.stringify(
        buildPostPayload({
          personUrn: input.personUrn,
          text: input.text,
          ...(input.assetUrn ? { assetUrn: input.assetUrn } : {}),
          ...(input.mediaType === "document"
            ? { documentTitle: input.documentTitle ?? "Documento" }
            : {})
        })
      )
    },
    true
  );
  return response.headers.get("x-restli-id") ?? "";
}

async function publicationEffect(
  post: PostRow,
  fingerprint: string
): Promise<{ id: number; status: string; external_id: string | null }> {
  const rows = await db()<Array<{ id: number; status: string; external_id: string | null }>>`
    insert into app.external_effects (
      effect_type, idempotency_key, entity_type, entity_id,
      request_fingerprint, request_payload
    ) values (
      'linkedin_post',
      ${`linkedin_post:${post.id}`},
      'post',
      ${String(post.id)},
      ${fingerprint},
      ${db().json({ post_id: post.id })}
    )
    on conflict (idempotency_key) do update set updated_at = now()
    returning id, status, external_id
  `;
  return rows[0]!;
}

export async function publishPost(postId: number, correlationId: string): Promise<string> {
  const rows = await db()<PostRow[]>`select * from app.posts where id = ${postId}`;
  const post = rows[0];
  if (!post) throw new Error("Post not found");
  if (post.status === "published" && post.linkedin_post_id) return post.linkedin_post_id;

  const fingerprint = createHash("sha256")
    .update(
      JSON.stringify({
        text: post.linkedin_text,
        images: post.image_urls,
        media_type: post.media_type,
        pdf_url: post.pdf_url
      })
    )
    .digest("hex");
  const claimedRows = await db()<[{ claim_post_for_publication: boolean }]>`
    select app.claim_post_for_publication(${postId}, ${fingerprint}) as claim_post_for_publication
  `;
  const effect = await publicationEffect(post, fingerprint);
  if (effect.status === "succeeded" && effect.external_id) return effect.external_id;
  if (!claimedRows[0]?.claim_post_for_publication) {
    throw new Error("Post is not claimable for publication");
  }
  if (effect.status === "ambiguous") {
    throw new Error("Publication is awaiting ambiguous-timeout reconciliation");
  }

  const leaseToken = randomUUID();
  const effectClaim = await db()<[{ id: number }]>`
    update app.external_effects
    set status = 'executing',
        lease_token = ${leaseToken}::uuid,
        leased_until = now() + interval '10 minutes',
        attempts = attempts + 1
    where id = ${effect.id}
      and status in ('pending', 'failed')
    returning id
  `;
  if (!effectClaim[0]) throw new Error("Publication effect is already executing");

  try {
    const auth = await validAccessToken();
    let mediaType: "none" | "image" | "document" = "none";
    let assetUrn: string | undefined;
    if (post.media_type === "image" && post.use_first_image && post.image_urls[0]) {
      try {
        assetUrn = await uploadSourceAsset({
          accessToken: auth.accessToken,
          personUrn: auth.personUrn,
          url: post.image_urls[0],
          type: "image"
        });
        mediaType = "image";
      } catch {
        mediaType = "none";
      }
    } else if (post.media_type === "document" && post.pdf_url) {
      try {
        assetUrn = await uploadSourceAsset({
          accessToken: auth.accessToken,
          personUrn: auth.personUrn,
          url: post.pdf_url,
          type: "document"
        });
        mediaType = "document";
      } catch {
        mediaType = "none";
      }
    }
    const linkedinPostId = await createPost({
      accessToken: auth.accessToken,
      personUrn: auth.personUrn,
      text: post.linkedin_text,
      mediaType,
      ...(assetUrn ? { assetUrn } : {}),
      documentTitle: post.document_title
    });
    if (!linkedinPostId) {
      throw new LinkedInApiError(
        "LinkedIn accepted the post but returned no publication ID",
        null,
        true
      );
    }
    await db().begin(async (transaction) => {
      await transaction`
        update app.external_effects
        set status = 'succeeded',
            external_id = ${linkedinPostId},
            completed_at = now(),
            leased_until = null
        where id = ${effect.id} and lease_token = ${leaseToken}::uuid
      `;
      await transaction`
        select app.mark_post_published(${postId}, ${linkedinPostId})
      `;
      await transaction`
        insert into app.publication_attempts (
          post_id, effect_id, attempt_number, request_fingerprint, status,
          linkedin_post_id, completed_at
        )
        select ${postId}, ${effect.id}, attempts, ${fingerprint}, 'succeeded',
               ${linkedinPostId}, now()
        from app.external_effects where id = ${effect.id}
      `;
    });
    await recordEvent({
      subsystem: "linkedin",
      eventType: "post_published",
      correlationId,
      entityType: "post",
      entityId: postId,
      metadata: { media_type: mediaType },
      dedupeKey: `post_published:${postId}`
    });
    return linkedinPostId;
  } catch (error) {
    const ambiguous = error instanceof LinkedInApiError && error.ambiguous;
    await db()`
      update app.external_effects
      set status = ${ambiguous ? "ambiguous" : "failed"},
          last_error = ${redact(error)},
          leased_until = null
      where id = ${effect.id} and lease_token = ${leaseToken}::uuid
    `;
    await db()`
      update app.posts
      set status = ${ambiguous ? "failed" : "scheduled"},
          error_message = ${redact(error)}
      where id = ${postId} and status = 'publishing'
    `;
    if (ambiguous) {
      await enqueueJob({
        type: "reconcile_publish",
        runAt: new Date(Date.now() + 15 * 60 * 1000),
        payload: { post_id: postId, effect_id: effect.id },
        dedupeKey: `reconcile_publish:${postId}`,
        priority: 5,
        correlationId
      });
    }
    throw error;
  }
}

export async function getPostMetrics(postId: string): Promise<Record<string, number | null>> {
  const auth = await validAccessToken();
  const urns = postId.startsWith("urn:li:")
    ? [postId]
    : [`urn:li:ugcPost:${postId}`, `urn:li:share:${postId}`];
  for (const urn of urns) {
    const encoded = encodeURIComponent(urn);
    const response = await fetch(`${API_BASE}/socialActions/${encoded}`, {
      headers: authHeaders(auth.accessToken)
    });
    if (!response.ok) continue;
    const payload = (await response.json()) as any;
    return {
      likes: payload.likesSummary?.totalLikes ?? null,
      comments: payload.commentsSummary?.totalFirstLevelComments ?? null,
      impressions: null,
      clicks: null,
      shares: null
    };
  }
  return { likes: null, comments: null, impressions: null, clicks: null, shares: null };
}

export async function createComment(input: {
  targetUrn: string;
  objectUrn: string;
  text: string;
  parentCommentUrn?: string;
  idempotencyKey: string;
}): Promise<string> {
  const sql = db();
  const existing = await sql<{ id: number; status: string; external_id: string | null }[]>`
    insert into app.external_effects (
      effect_type, idempotency_key, entity_type, entity_id,
      request_fingerprint, request_payload
    ) values (
      'linkedin_comment', ${input.idempotencyKey}, 'comment', ${input.targetUrn},
      ${createHash("sha256").update(input.text).digest("hex")},
      ${sql.json({ target_urn: input.targetUrn })}
    )
    on conflict (idempotency_key) do update set updated_at = now()
    returning id, status, external_id
  `;
  if (existing[0]?.status === "succeeded") return existing[0].external_id ?? "";
  const auth = await validAccessToken();
  const target = encodeURIComponent(input.parentCommentUrn ?? input.targetUrn);
  const response = await fetchLinkedIn(`${REST_BASE}/socialActions/${target}/comments`, {
    method: "POST",
    headers: authHeaders(auth.accessToken),
    body: JSON.stringify({
      actor: asPersonUrn(auth.personUrn),
      object: input.objectUrn || input.targetUrn,
      message: { text: input.text },
      ...(input.parentCommentUrn ? { parentComment: input.parentCommentUrn } : {})
    })
  }, true);
  const externalId = response.headers.get("x-restli-id") ?? "";
  if (!externalId) {
    await sql`
      update app.external_effects
      set status = 'ambiguous',
          last_error = 'LinkedIn accepted a comment without returning an ID'
      where id = ${existing[0]!.id}
    `;
    throw new LinkedInApiError(
      "LinkedIn accepted the comment but returned no comment ID",
      null,
      true
    );
  }
  await sql`
    update app.external_effects
    set status = 'succeeded', external_id = ${externalId}, completed_at = now()
    where id = ${existing[0]!.id}
  `;
  return externalId;
}

export type LinkedInCommentData = {
  urn: string;
  parentUrn: string | null;
  actorUrn: string;
  actorName: string;
  text: string;
  createdAt: string;
  raw: Record<string, unknown>;
};

export async function fetchPostComments(postUrn: string): Promise<LinkedInCommentData[]> {
  const auth = await validAccessToken();
  const response = await fetchLinkedIn(
    `${REST_BASE}/socialActions/${encodeURIComponent(postUrn)}/comments?q=comments&count=50`,
    { headers: authHeaders(auth.accessToken) }
  );
  const payload = (await response.json()) as {
    elements?: Array<Record<string, any>>;
  };
  return (payload.elements ?? []).flatMap((item): LinkedInCommentData[] => {
    const urn = String(item.id ?? item["$URN"] ?? item.commentUrn ?? "");
    const message = String(item.message?.text ?? item.commentary?.text ?? "").trim();
    if (!urn || !message) return [];
    const actorUrn = String(item.actor ?? item.commenter?.urn ?? "");
    const actorName = String(
      item.actorName ??
        item.commenter?.name ??
        [item.commenter?.firstName, item.commenter?.lastName].filter(Boolean).join(" ") ??
        ""
    );
    const created = Number(item.created?.time ?? item.createdAt ?? Date.now());
    return [
      {
        urn,
        parentUrn: item.parentComment ? String(item.parentComment) : null,
        actorUrn,
        actorName,
        text: message,
        createdAt: new Date(created).toISOString(),
        raw: item
      }
    ];
  });
}

export async function reconcileAmbiguousPublication(
  postId: number
): Promise<{ reconciled: boolean; linkedinPostId?: string }> {
  const sql = db();
  const posts = await sql<PostRow[]>`select * from app.posts where id = ${postId}`;
  const post = posts[0];
  if (!post) throw new Error("Post not found");
  if (post.linkedin_post_id) {
    return { reconciled: true, linkedinPostId: post.linkedin_post_id };
  }
  if (!envBoolean("LINKEDIN_READ_SCOPE_ENABLED", false)) {
    return { reconciled: false };
  }
  const auth = await validAccessToken();
  const author = encodeURIComponent(asPersonUrn(auth.personUrn));
  const response = await fetchLinkedIn(
    `${REST_BASE}/posts?author=${author}&q=author&viewContext=AUTHOR&sortBy=LAST_MODIFIED&count=20`,
    { headers: authHeaders(auth.accessToken) }
  );
  const payload = (await response.json()) as { elements?: Array<Record<string, any>> };
  const matched = (payload.elements ?? []).find((item) => {
    const text = String(item.commentary ?? "");
    return text === post.linkedin_text;
  });
  const externalId = String(matched?.id ?? matched?.["$URN"] ?? "");
  if (!externalId) return { reconciled: false };
  await sql.begin(async (transaction) => {
    await transaction`
      update app.external_effects
      set status = 'succeeded', external_id = ${externalId}, completed_at = now()
      where idempotency_key = ${`linkedin_post:${postId}`}
        and status = 'ambiguous'
    `;
    await transaction`
      update app.posts
      set status = 'published',
          linkedin_post_id = ${externalId},
          published_at = coalesce(published_at, now()),
          error_message = null
      where id = ${postId} and status in ('publishing', 'failed')
    `;
  });
  return { reconciled: true, linkedinPostId: externalId };
}

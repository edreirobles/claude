import { createHash } from "node:crypto";
import { db } from "./db.js";
import {
  decideEditorialTreatment,
  generateLinkedInCopy,
  loadOrBuildEditorialProfile
} from "./editorial.js";
import { recordEvent } from "./events.js";
import { enqueueJob } from "./queue.js";
import { generateText } from "./text-provider.js";
import { fetchPostComments, getPostMetrics } from "./linkedin.js";
import { scrapeSource } from "./source.js";

type EditablePost = {
  id: number;
  status: string;
  tweet_url: string;
  editorial_revision_notes: string | null;
  source_metadata: {
    intent?: string;
    angle?: string;
    reason?: string;
  };
  version: number;
};

export async function prepareProvidedUrl(postId: number): Promise<Record<string, unknown>> {
  const sql = db();
  const rows = await sql<EditablePost[]>`
    select id, status, tweet_url, editorial_revision_notes, source_metadata, version
    from app.posts where id = ${postId}
  `;
  const post = rows[0];
  if (!post) throw new Error("Post not found");
  if (!["pending", "failed"].includes(post.status)) {
    return { post_id: postId, status: post.status, unchanged: true };
  }
  const source = await scrapeSource(post.tweet_url);
  if (source.text.length < 40) throw new Error("Source has insufficient readable content");
  const profile = await loadOrBuildEditorialProfile();
  const treatment = await decideEditorialTreatment(source, profile);
  const settings = await sql<Array<{ custom_prompt: string | null }>>`
    select custom_prompt from app.settings where id = 1
  `;
  const copy = await generateLinkedInCopy({
    source,
    ...treatment,
    profile,
    customPrompt: settings[0]?.custom_prompt ?? null,
    revisionNotes: post.editorial_revision_notes
  });
  const mediaType = source.images.length ? "image" : source.pdfUrl ? "document" : "none";
  const updated = await sql<Array<{ version: number }>>`
    update app.posts
    set tweet_url = ${source.url},
        tweet_text = ${source.text.slice(0, 20_000)},
        tweet_author = ${source.author},
        linkedin_text = ${copy},
        image_urls = ${sql.json((mediaType === "image" ? source.images : []) as never)},
        use_first_image = ${mediaType === "image"},
        media_type = ${mediaType},
        pdf_url = ${source.pdfUrl ?? null},
        document_title = ${source.title.slice(0, 500) || "Documento"},
        generated_image_path = null,
        status = 'approval_pending',
        source_metadata = ${sql.json({
          title: source.title,
          intent: treatment.intent,
          angle: treatment.angle,
          reason: treatment.reason,
          source_hash: createHash("sha256").update(source.url).digest("hex")
        } as never)},
        error_message = null,
        version = version + 1
    where id = ${postId} and status in ('pending', 'failed')
    returning version
  `;
  if (!updated[0]) throw new Error("Post changed while source was being prepared");
  await recordEvent({
    subsystem: "editorial",
    eventType: "provided_url_prepared",
    entityType: "post",
    entityId: postId,
    metadata: { intent: treatment.intent, media_type: mediaType },
    dedupeKey: `provided_url_prepared:${postId}:${updated[0].version}`
  });
  return {
    post_id: postId,
    status: "approval_pending",
    version: updated[0].version,
    reason: treatment.reason
  };
}

export async function revisePost(postId: number): Promise<Record<string, unknown>> {
  const sql = db();
  const rows = await sql<EditablePost[]>`
    select id, status, tweet_url, editorial_revision_notes, source_metadata, version
    from app.posts where id = ${postId}
  `;
  const post = rows[0];
  if (!post) throw new Error("Post not found");
  if (post.status !== "approval_pending") {
    return { post_id: postId, status: post.status, unchanged: true };
  }
  const source = await scrapeSource(post.tweet_url);
  const profile = await loadOrBuildEditorialProfile();
  const settings = await sql<Array<{ custom_prompt: string | null }>>`
    select custom_prompt from app.settings where id = 1
  `;
  const existingIntent = post.source_metadata.intent;
  const treatment =
    existingIntent &&
    ["presentar", "describir", "invitar", "explicar", "advertir", "analizar", "reflexionar"].includes(
      existingIntent
    )
      ? {
          intent: existingIntent as
            | "presentar"
            | "describir"
            | "invitar"
            | "explicar"
            | "advertir"
            | "analizar"
            | "reflexionar",
          angle: post.source_metadata.angle ?? "",
          reason: post.source_metadata.reason ?? ""
        }
      : await decideEditorialTreatment(source, profile);
  const copy = await generateLinkedInCopy({
    source,
    ...treatment,
    profile,
    customPrompt: settings[0]?.custom_prompt ?? null,
    revisionNotes: post.editorial_revision_notes
  });
  const updated = await sql<Array<{ version: number }>>`
    update app.posts
    set linkedin_text = ${copy},
        generated_image_path = null,
        manual_edited_at = now(),
        manual_edited_via = 'telegram_revision',
        error_message = null,
        version = version + 1
    where id = ${postId}
      and status = 'approval_pending'
      and version = ${post.version}
    returning version
  `;
  if (!updated[0]) throw new Error("Post changed while revision was generated");
  return {
    post_id: postId,
    status: "approval_pending",
    version: updated[0].version,
    reason: treatment.reason
  };
}

export async function refreshMetricsBatch(limit = 15): Promise<Record<string, unknown>> {
  const posts = await db()<
    Array<{ id: number; linkedin_post_id: string; metrics_updated_at: string | null }>
  >`
    select id, linkedin_post_id, metrics_updated_at
    from app.posts
    where status = 'published'
      and linkedin_post_id is not null
      and (
        metrics_updated_at is null
        or metrics_updated_at < now() - interval '23 hours'
      )
    order by metrics_updated_at asc nulls first, published_at desc
    limit ${Math.max(1, Math.min(limit, 30))}
  `;
  let updated = 0;
  for (const post of posts) {
    try {
      const metrics = await getPostMetrics(post.linkedin_post_id);
      await db()`
        update app.posts
        set li_likes = coalesce(${metrics.likes ?? null}, li_likes),
            li_comments = coalesce(${metrics.comments ?? null}, li_comments),
            li_impressions = coalesce(${metrics.impressions ?? null}, li_impressions),
            li_clicks = coalesce(${metrics.clicks ?? null}, li_clicks),
            li_shares = coalesce(${metrics.shares ?? null}, li_shares),
            metrics_updated_at = now()
        where id = ${post.id}
      `;
      updated += 1;
    } catch {
      continue;
    }
  }
  if (updated) await loadOrBuildEditorialProfile();
  return { scanned: posts.length, updated };
}

export async function verifyPostSource(postId: number): Promise<Record<string, unknown>> {
  const sql = db();
  const posts = await sql<
    Array<{
      id: number;
      status: string;
      tweet_url: string;
      manual_edited_at: string | null;
      version: number;
    }>
  >`
    select id, status, tweet_url, manual_edited_at, version
    from app.posts where id = ${postId}
  `;
  const post = posts[0];
  if (!post) throw new Error("Post not found");
  if (!["scheduled", "publishing"].includes(post.status)) {
    return { post_id: postId, status: post.status, skipped: true };
  }
  const source = await scrapeSource(post.tweet_url);
  if (source.text.length < 40) throw new Error("Source no longer has enough readable content");
  const verification = {
    checked_at: new Date().toISOString(),
    source_url: source.url,
    content_hash: createHash("sha256").update(source.text).digest("hex"),
    valid: true,
    manual_copy_preserved: Boolean(post.manual_edited_at)
  };
  await sql`
    update app.posts
    set verification_metadata = ${sql.json(verification as never)}
    where id = ${postId} and version = ${post.version}
  `;
  await recordEvent({
    subsystem: "linkedin",
    eventType: "prepublish_verified",
    entityType: "post",
    entityId: postId,
    metadata: verification,
    dedupeKey: `prepublish_verified:${postId}:${post.version}`
  });
  return verification;
}

function publicPostUrn(value: string): string {
  if (value.startsWith("urn:li:")) return value;
  return `urn:li:ugcPost:${value}`;
}

export async function syncCommentsBatch(limit = 5): Promise<Record<string, unknown>> {
  const posts = await db()<
    Array<{ id: number; linkedin_post_id: string }>
  >`
    select id, linkedin_post_id
    from app.posts
    where status = 'published'
      and linkedin_post_id is not null
      and published_at >= now() - interval '30 days'
    order by published_at desc
    limit ${Math.max(1, Math.min(limit, 10))}
  `;
  let inserted = 0;
  for (const post of posts) {
    let comments;
    try {
      comments = await fetchPostComments(publicPostUrn(post.linkedin_post_id));
    } catch {
      continue;
    }
    for (const comment of comments) {
      const existing = await db()<Array<{ id: number }>>`
        select id from app.linkedin_comments
        where linkedin_comment_urn = ${comment.urn}
      `;
      if (existing[0]) continue;
      let suggestion = "";
      try {
        suggestion = (
          await generateText({
            system: [
              "Escribe una respuesta breve, humana y especifica para un comentario en LinkedIn.",
              "No uses markdown, asteriscos, guiones ni cierres genericos.",
              "No inventes informacion y no publiques: solo propone el borrador."
            ].join("\n"),
            user: comment.text,
            maxTokens: 350
          })
        ).trim();
      } catch {
        suggestion = "Gracias por sumar este punto. Vale la pena incorporarlo a la conversación.";
      }
      const sql = db();
      const rows = await sql<Array<{ id: number }>>`
        insert into app.linkedin_comments (
          scheduled_post_id, linkedin_post_urn, linkedin_object_urn,
          linkedin_comment_urn, parent_comment_urn, commenter_name,
          comment_text, suggested_reply, reply_status, raw_payload, created_at
        ) values (
          ${post.id}, ${publicPostUrn(post.linkedin_post_id)},
          ${publicPostUrn(post.linkedin_post_id)}, ${comment.urn},
          ${comment.parentUrn}, ${comment.actorName}, ${comment.text},
          ${suggestion.slice(0, 3000)}, 'pending',
          ${sql.json(comment.raw as never)}, ${comment.createdAt}::timestamptz
        )
        on conflict (linkedin_comment_urn) do nothing
        returning id
      `;
      if (!rows[0]) continue;
      inserted += 1;
      await enqueueJob({
        type: "notify_comment",
        payload: { comment_id: rows[0].id },
        dedupeKey: `notify_comment:${rows[0].id}`,
        priority: 25
      });
    }
  }
  return { posts_scanned: posts.length, comments_inserted: inserted };
}

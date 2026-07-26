import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { db } from "../../cloud/src/db.js";

type Manifest = {
  format_version: number;
  source_database_snapshot_sha256: string;
  files: Record<string, { rows: number; sha256: string; canonical_sha256: string }>;
};

type JsonRow = Record<string, any>;

function sha256(value: Buffer | string): string {
  return createHash("sha256").update(value).digest("hex");
}

async function readJsonLines(
  directory: string,
  filename: string,
  manifest: Manifest
): Promise<JsonRow[]> {
  const content = await readFile(resolve(directory, filename));
  const expected = manifest.files[filename];
  if (!expected || sha256(content) !== expected.sha256) {
    throw new Error(`Snapshot checksum mismatch: ${filename}`);
  }
  const rows = content
    .toString("utf8")
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => JSON.parse(line) as JsonRow);
  if (rows.length !== expected.rows) {
    throw new Error(`Snapshot row count mismatch: ${filename}`);
  }
  return rows;
}

async function importSnapshot(directory: string): Promise<void> {
  const manifestBytes = await readFile(resolve(directory, "manifest.json"));
  const manifest = JSON.parse(manifestBytes.toString("utf8")) as Manifest;
  if (manifest.format_version !== 1) throw new Error("Unsupported snapshot format");
  const manifestHash = sha256(manifestBytes);
  const sql = db();
  const existing = await sql<Array<{ status: string }>>`
    select status from app.import_runs where manifest_hash = ${manifestHash}
  `;
  if (existing[0]?.status === "succeeded") {
    process.stdout.write(JSON.stringify({ imported: false, already_succeeded: true }) + "\n");
    return;
  }

  const settings = await readJsonLines(directory, "settings.jsonl", manifest);
  const tokens = await readJsonLines(directory, "linkedin_tokens.jsonl", manifest);
  const posts = await readJsonLines(directory, "posts.jsonl", manifest);
  const likes = await readJsonLines(directory, "x_liked_tweets.jsonl", manifest);
  const comments = await readJsonLines(directory, "linkedin_comments.jsonl", manifest);
  const counts = {
    settings: settings.length,
    linkedin_tokens: tokens.length,
    posts: posts.length,
    x_liked_tweets: likes.length,
    linkedin_comments: comments.length
  };

  await sql`
    insert into app.import_runs (
      manifest_hash, source_database_hash, status, counts
    ) values (
      ${manifestHash}, ${manifest.source_database_snapshot_sha256}, 'started',
      ${sql.json(counts as never)}
    )
    on conflict (manifest_hash) do update
    set status = 'started', counts = excluded.counts, error_message = null,
        started_at = now(), completed_at = null
  `;

  try {
    await sql.begin(async (transaction) => {
      for (const row of settings) {
        await transaction`
          insert into app.settings (id, custom_prompt, created_at, updated_at)
          values (
            ${row.id}, ${row.custom_prompt}, coalesce(${row.updated_at}::timestamptz, now()),
            coalesce(${row.updated_at}::timestamptz, now())
          )
          on conflict (id) do update
          set custom_prompt = excluded.custom_prompt,
              updated_at = excluded.updated_at,
              version = app.settings.version + 1
        `;
      }
      for (const row of tokens) {
        await transaction`
          insert into app.linkedin_tokens (
            id, access_token_cipher, refresh_token_cipher, cipher_version,
            person_urn, person_name, person_picture, expires_at,
            refresh_token_expires_at, created_at
          ) values (
            ${row.id}, ${transaction.json(row.access_token_cipher)},
            ${row.refresh_token_cipher
              ? transaction.json(row.refresh_token_cipher)
              : null},
            ${row.cipher_version}, ${row.person_urn}, ${row.person_name},
            ${row.person_picture}, ${row.expires_at}::timestamptz,
            ${row.refresh_token_expires_at}::timestamptz,
            coalesce(${row.created_at}::timestamptz, now())
          )
          on conflict (id) do update
          set access_token_cipher = excluded.access_token_cipher,
              refresh_token_cipher = excluded.refresh_token_cipher,
              person_urn = excluded.person_urn,
              person_name = excluded.person_name,
              person_picture = excluded.person_picture,
              expires_at = excluded.expires_at,
              refresh_token_expires_at = excluded.refresh_token_expires_at
        `;
      }
      for (const row of posts) {
        await transaction`
          insert into app.posts (
            id, tweet_url, tweet_text, tweet_author, linkedin_text, image_urls,
            scheduled_at, approved_at, publish_at, publishing_at, published_at,
            status, linkedin_post_id, error_message, created_at, use_first_image,
            media_type, pdf_url, document_title, source, manual_edited_at,
            manual_edited_via, editorial_revision_notes, generated_image_path,
            li_likes, li_comments, li_impressions, li_clicks, li_shares,
            metrics_updated_at, source_metadata, verification_metadata, version
          ) values (
            ${row.id}, ${row.tweet_url}, ${row.tweet_text}, ${row.tweet_author},
            ${row.linkedin_text}, ${transaction.json(row.image_urls)},
            ${row.scheduled_at}::timestamptz, ${row.approved_at}::timestamptz,
            ${row.publish_at}::timestamptz, ${row.publishing_at}::timestamptz,
            ${row.published_at}::timestamptz, ${row.status},
            ${row.linkedin_post_id}, ${row.error_message},
            coalesce(${row.created_at}::timestamptz, now()),
            ${row.use_first_image}, ${row.media_type}, ${row.pdf_url},
            ${row.document_title}, ${row.source}, ${row.manual_edited_at}::timestamptz,
            ${row.manual_edited_via}, ${row.editorial_revision_notes}, null,
            ${row.li_likes}, ${row.li_comments}, ${row.li_impressions},
            ${row.li_clicks}, ${row.li_shares}, ${row.metrics_updated_at}::timestamptz,
            ${transaction.json(row.source_metadata ?? {})},
            ${transaction.json(row.verification_metadata ?? {})}, ${row.version ?? 1}
          )
          on conflict (id) do update
          set tweet_url = excluded.tweet_url,
              tweet_text = excluded.tweet_text,
              tweet_author = excluded.tweet_author,
              linkedin_text = excluded.linkedin_text,
              image_urls = excluded.image_urls,
              scheduled_at = excluded.scheduled_at,
              approved_at = excluded.approved_at,
              publish_at = excluded.publish_at,
              publishing_at = excluded.publishing_at,
              published_at = excluded.published_at,
              status = excluded.status,
              linkedin_post_id = excluded.linkedin_post_id,
              error_message = excluded.error_message,
              use_first_image = excluded.use_first_image,
              media_type = excluded.media_type,
              pdf_url = excluded.pdf_url,
              document_title = excluded.document_title,
              source = excluded.source,
              manual_edited_at = excluded.manual_edited_at,
              manual_edited_via = excluded.manual_edited_via,
              editorial_revision_notes = excluded.editorial_revision_notes,
              generated_image_path = null,
              li_likes = excluded.li_likes,
              li_comments = excluded.li_comments,
              li_impressions = excluded.li_impressions,
              li_clicks = excluded.li_clicks,
              li_shares = excluded.li_shares,
              metrics_updated_at = excluded.metrics_updated_at,
              source_metadata = excluded.source_metadata,
              verification_metadata = excluded.verification_metadata
        `;
      }
      for (const row of likes) {
        await transaction`
          insert into app.x_liked_tweets (
            id, tweet_id, tweet_url, tweet_author, processed_at, post_id,
            status, error_message, created_at, updated_at
          ) values (
            ${row.id}, ${row.tweet_id}, ${row.tweet_url}, ${row.tweet_author},
            coalesce(${row.processed_at}::timestamptz, now()), ${row.post_id},
            ${row.status}, ${row.error_message},
            coalesce(${row.processed_at}::timestamptz, now()),
            coalesce(${row.processed_at}::timestamptz, now())
          )
          on conflict (id) do update
          set tweet_id = excluded.tweet_id,
              tweet_url = excluded.tweet_url,
              tweet_author = excluded.tweet_author,
              processed_at = excluded.processed_at,
              post_id = excluded.post_id,
              status = excluded.status,
              error_message = excluded.error_message
        `;
      }
      for (const row of comments) {
        await transaction`
          insert into app.linkedin_comments (
            id, scheduled_post_id, linkedin_post_urn, linkedin_object_urn,
            linkedin_comment_urn, parent_comment_urn, commenter_name,
            commenter_profile_url, commenter_headline, comment_text,
            comment_age_label, post_public_url, suggested_reply, reply_status,
            telegram_message_id, last_notified_at, owner_replied, owner_reply_text,
            published_reply_urn, published_reply_text, error_message, raw_payload,
            created_at, updated_at
          ) values (
            ${row.id}, ${row.scheduled_post_id}, ${row.linkedin_post_urn},
            ${row.linkedin_object_urn}, ${row.linkedin_comment_urn},
            ${row.parent_comment_urn}, ${row.commenter_name},
            ${row.commenter_profile_url}, ${row.commenter_headline},
            ${row.comment_text}, ${row.comment_age_label}, ${row.post_public_url},
            ${row.suggested_reply}, ${row.reply_status}, ${row.telegram_message_id},
            ${row.last_notified_at}::timestamptz, ${row.owner_replied},
            ${row.owner_reply_text}, ${row.published_reply_urn},
            ${row.published_reply_text}, ${row.error_message},
            ${row.raw_payload ? transaction.json(row.raw_payload) : null},
            coalesce(${row.created_at}::timestamptz, now()),
            coalesce(${row.created_at}::timestamptz, now())
          )
          on conflict (id) do update
          set scheduled_post_id = excluded.scheduled_post_id,
              linkedin_post_urn = excluded.linkedin_post_urn,
              linkedin_object_urn = excluded.linkedin_object_urn,
              linkedin_comment_urn = excluded.linkedin_comment_urn,
              parent_comment_urn = excluded.parent_comment_urn,
              commenter_name = excluded.commenter_name,
              commenter_profile_url = excluded.commenter_profile_url,
              commenter_headline = excluded.commenter_headline,
              comment_text = excluded.comment_text,
              comment_age_label = excluded.comment_age_label,
              post_public_url = excluded.post_public_url,
              suggested_reply = excluded.suggested_reply,
              reply_status = excluded.reply_status,
              telegram_message_id = excluded.telegram_message_id,
              last_notified_at = excluded.last_notified_at,
              owner_replied = excluded.owner_replied,
              owner_reply_text = excluded.owner_reply_text,
              published_reply_urn = excluded.published_reply_urn,
              published_reply_text = excluded.published_reply_text,
              error_message = excluded.error_message,
              raw_payload = excluded.raw_payload
        `;
      }

      for (const table of [
        "linkedin_tokens",
        "posts",
        "x_liked_tweets",
        "linkedin_comments"
      ]) {
        await transaction.unsafe(
          `select setval(pg_get_serial_sequence('app.${table}', 'id'), greatest(coalesce((select max(id) from app.${table}), 1), 1), true)`
        );
      }
      for (const post of posts.filter((row) => row.status === "scheduled")) {
        await transaction`
          select app.enqueue_job(
            'publish_post',
            coalesce(${post.publish_at}::timestamptz, ${post.scheduled_at}::timestamptz, now()),
            jsonb_build_object('post_id', ${post.id}),
            ${`publish_post:${post.id}`},
            5,
            10,
            null
          )
        `;
      }
      await transaction`
        update app.import_runs
        set status = 'succeeded', completed_at = now()
        where manifest_hash = ${manifestHash}
      `;
    });
  } catch (error) {
    await sql`
      update app.import_runs
      set status = 'failed',
          error_message = ${error instanceof Error ? error.message.slice(0, 1500) : String(error)},
          completed_at = now()
      where manifest_hash = ${manifestHash}
    `;
    throw error;
  }
  process.stdout.write(JSON.stringify({ imported: true, counts }) + "\n");
}

const directory = resolve(process.argv[2] ?? process.env.MIGRATION_ARTIFACT_DIR ?? "");
if (!process.argv[2] && !process.env.MIGRATION_ARTIFACT_DIR) {
  throw new Error("Pass the snapshot directory or set MIGRATION_ARTIFACT_DIR");
}
await importSnapshot(directory);

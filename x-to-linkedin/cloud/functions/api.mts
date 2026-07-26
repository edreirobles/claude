import type { Config } from "@netlify/functions";
import { z } from "zod";
import { requireMutationGuard, requireUser } from "../src/auth.js";
import { currentCostState, currentStorageState } from "../src/cost.js";
import { db } from "../src/db.js";
import {
  DEFAULT_EDITORIAL_PROMPT,
  decideEditorialTreatment,
  generateLinkedInCopy,
  loadOrBuildEditorialProfile,
  sanitizeLinkedInCopy
} from "../src/editorial.js";
import { switches } from "../src/env.js";
import { recordEvent } from "../src/events.js";
import {
  AppError,
  json,
  methodNotAllowed,
  parseJson,
  requestId,
  toErrorResponse
} from "../src/http.js";
import {
  createLinkedInOAuthUrl,
  getPostMetrics,
  linkedinStatus
} from "../src/linkedin.js";
import { enqueueJob } from "../src/queue.js";
import { scrapeSource } from "../src/source.js";

const postInput = z.object({
  tweet_url: z.string().url().max(3000),
  tweet_text: z.string().max(20_000).default(""),
  tweet_author: z.string().max(500).default(""),
  linkedin_text: z.string().min(1).max(3000),
  image_urls: z.array(z.string().url().max(3000)).max(8).default([]),
  use_first_image: z.boolean().default(false),
  media_type: z
    .enum(["none", "image", "video", "document", "paper_image", "auto"])
    .default("none"),
  pdf_url: z.string().url().max(3000).nullable().optional(),
  document_title: z.string().max(500).default("Documento")
});

const editInput = z.object({
  linkedin_text: z.string().min(1).max(3000),
  media_type: z.enum(["none", "image", "video", "document", "paper_image", "auto"]),
  use_first_image: z.boolean(),
  pdf_url: z.string().url().max(3000).nullable().optional(),
  document_title: z.string().max(500),
  scheduled_at: z.string().datetime().optional(),
  version: z.number().int().positive().optional()
});

async function consumeRateLimit(userId: string, request: Request): Promise<void> {
  const mutation = !["GET", "HEAD"].includes(request.method);
  const rows = await db()<[{ allowed: boolean }]>`
    select app.consume_rate_limit(
      ${`dashboard:${userId}:${mutation ? "write" : "read"}`},
      ${mutation ? 30 : 120},
      60
    ) as allowed
  `;
  if (!rows[0]?.allowed) throw new AppError("Too many requests", 429, "rate_limited");
}

function postIdFromPath(pathname: string): number | null {
  const match = pathname.match(/^\/api\/posts\/(\d+)(?:\/|$)/);
  return match ? Number(match[1]) : null;
}

function retryJobIdFromPath(pathname: string): number | null {
  const match = pathname.match(/^\/api\/operations\/jobs\/(\d+)\/retry$/);
  return match ? Number(match[1]) : null;
}

async function generateFromUrl(request: Request, id: string): Promise<Response> {
  const body = z
    .object({ url: z.string().url().max(3000), language: z.string().max(20).optional() })
    .parse(await parseJson(request));
  const source = await scrapeSource(body.url);
  if (source.text.length < 40) {
    throw new AppError("La fuente no tiene suficiente contenido legible", 422, "source_too_short");
  }
  const profile = await loadOrBuildEditorialProfile();
  const treatment = await decideEditorialTreatment(source, profile);
  const settings = await db()<Array<{ custom_prompt: string | null }>>`
    select custom_prompt from app.settings where id = 1
  `;
  const copy = await generateLinkedInCopy({
    source,
    ...treatment,
    profile,
    customPrompt: settings[0]?.custom_prompt ?? null
  });
  const mediaType = source.images.length ? "image" : source.pdfUrl ? "document" : "none";
  return json(
    {
      tweet: {
        tweet_url: source.url,
        text: source.text,
        author_name: source.author,
        author_handle: "",
        images: source.images,
        is_article: source.kind !== "x_post",
        pdf_url: source.pdfUrl ?? null,
        ...(source.kind === "paper"
          ? {
              paper_info: {
                title: source.title,
                authors: source.author ? [source.author] : [],
                abstract: source.text.slice(0, 500)
              }
            }
          : {})
      },
      linkedin_text: copy,
      suggested_images: source.images,
      media_type: mediaType,
      editorial_decision: treatment,
      request_id: id
    },
    { requestId: id }
  );
}

async function insertManualPost(
  request: Request,
  mode: "now" | "schedule"
): Promise<{ id: number; scheduled_at: string }> {
  const input = postInput.parse(await parseJson(request));
  const sql = db();
  const rows = await sql<Array<{ id: number; scheduled_at: string }>>`
    insert into app.posts (
      tweet_url, tweet_text, tweet_author, linkedin_text, image_urls,
      scheduled_at, approved_at, publish_at, status, use_first_image,
      media_type, pdf_url, document_title, source, manual_edited_at,
      manual_edited_via, generated_image_path
    ) values (
      ${input.tweet_url}, ${input.tweet_text}, ${input.tweet_author},
      ${sanitizeLinkedInCopy(input.linkedin_text)},
      ${sql.json(input.image_urls as never)},
      ${mode === "now" ? sql`now()` : sql`now() + interval '30 minutes'`},
      now(),
      ${mode === "now" ? sql`now()` : sql`now() + interval '30 minutes'`},
      'scheduled',
      ${input.use_first_image && input.image_urls.length > 0},
      ${input.media_type === "auto" ? "none" : input.media_type},
      ${input.pdf_url ?? null},
      ${input.document_title},
      'manual',
      now(),
      'dashboard',
      null
    )
    returning id, scheduled_at
  `;
  const post = rows[0]!;
  await enqueueJob({
    type: "publish_post",
    runAt: new Date(post.scheduled_at),
    payload: { post_id: post.id },
    dedupeKey: `publish_post:${post.id}`,
    priority: 10
  });
  return post;
}

async function listPosts(url: URL, id: string): Promise<Response> {
  const limit = Math.max(1, Math.min(Number(url.searchParams.get("limit") ?? 200), 200));
  const offset = Math.max(0, Number(url.searchParams.get("offset") ?? 0));
  const statuses = url.searchParams
    .getAll("status")
    .filter((value) =>
      [
        "pending",
        "radar_slot",
        "approval_pending",
        "scheduled",
        "publishing",
        "published",
        "failed",
        "cancelled",
        "paused"
      ].includes(value)
    );
  const rows = await db()`
    select *
    from app.posts
    where ${statuses.length ? db()`status = any(${statuses})` : db()`true`}
    order by coalesce(publish_at, scheduled_at, created_at) desc, id desc
    limit ${limit} offset ${offset}
  `;
  return json(rows, { requestId: id });
}

async function updatePost(request: Request, postId: number, id: string): Promise<Response> {
  const input = editInput.parse(await parseJson(request));
  const sql = db();
  const rows = await sql<Array<{ id: number; status: string; version: number }>>`
    update app.posts
    set linkedin_text = ${sanitizeLinkedInCopy(input.linkedin_text)},
        media_type = ${input.media_type === "auto" ? "none" : input.media_type},
        use_first_image = ${input.use_first_image},
        pdf_url = ${input.pdf_url ?? null},
        document_title = ${input.document_title},
        scheduled_at = coalesce(${input.scheduled_at ?? null}::timestamptz, scheduled_at),
        publish_at = case
          when status = 'scheduled'
            then coalesce(${input.scheduled_at ?? null}::timestamptz, publish_at)
          else publish_at
        end,
        manual_edited_at = now(),
        manual_edited_via = 'dashboard',
        generated_image_path = null,
        version = version + 1
    where id = ${postId}
      and status in ('pending', 'approval_pending', 'scheduled', 'failed')
      ${input.version ? sql`and version = ${input.version}` : sql``}
    returning id, status, version
  `;
  const post = rows[0];
  if (!post) throw new AppError("El post cambió o ya no se puede editar", 409, "post_conflict");
  if (post.status === "scheduled" && input.scheduled_at) {
    await sql`
      update app.job_queue
      set run_at = ${input.scheduled_at}::timestamptz,
          status = 'pending',
          attempts = 0,
          leased_until = null,
          lease_owner = null,
          lease_token = null
      where dedupe_key = ${`publish_post:${postId}`}
        and status in ('pending', 'retry_wait', 'claimed')
    `;
  }
  return json(post, { requestId: id });
}

async function exportPosts(url: URL, id: string): Promise<Response> {
  const from = url.searchParams.get("from_date");
  const to = url.searchParams.get("to_date");
  const rows = await db()<
    Array<Record<string, string | number | null>>
  >`
    select id, status, source, tweet_url, tweet_author, linkedin_text,
           scheduled_at::text, approved_at::text, publish_at::text,
           published_at::text, linkedin_post_id, li_likes, li_comments,
           li_impressions, li_clicks, li_shares
    from app.posts
    where (${from}::date is null or created_at >= ${from}::date)
      and (${to}::date is null or created_at < ${to}::date + 1)
    order by id
  `;
  const headers = [
    "id",
    "status",
    "source",
    "tweet_url",
    "tweet_author",
    "linkedin_text",
    "scheduled_at",
    "approved_at",
    "publish_at",
    "published_at",
    "linkedin_post_id",
    "li_likes",
    "li_comments",
    "li_impressions",
    "li_clicks",
    "li_shares"
  ];
  const csvCell = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const csv = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvCell(row[header])).join(","))
  ].join("\r\n");
  return new Response(`\uFEFF${csv}`, {
    headers: {
      "content-type": "text/csv; charset=utf-8",
      "content-disposition": 'attachment; filename="linkedin-posts.csv"',
      "cache-control": "no-store",
      "x-request-id": id
    }
  });
}

async function analytics(id: string): Promise<Response> {
  const summary = await db()<
    Array<{
      total_published: number;
      posts_with_metrics: number;
      total_impressions: number;
      total_likes: number;
      total_comments: number;
      total_clicks: number;
      total_shares: number;
    }>
  >`
    select
      count(*) filter (where status = 'published')::integer as total_published,
      count(*) filter (
        where status = 'published' and metrics_updated_at is not null
      )::integer as posts_with_metrics,
      coalesce(sum(li_impressions), 0)::integer as total_impressions,
      coalesce(sum(li_likes), 0)::integer as total_likes,
      coalesce(sum(li_comments), 0)::integer as total_comments,
      coalesce(sum(li_clicks), 0)::integer as total_clicks,
      coalesce(sum(li_shares), 0)::integer as total_shares
    from app.posts
  `;
  const byDay = await db()`
    select (published_at at time zone 'America/Mexico_City')::date::text as date,
           count(*)::integer as count
    from app.posts
    where status = 'published' and published_at >= now() - interval '90 days'
    group by 1 order by 1
  `;
  const hours = await db()`
    with values as (select generate_series(0, 23) as hour)
    select values.hour,
           count(app.posts.id)::integer as count
    from values
    left join app.posts
      on extract(hour from app.posts.published_at at time zone 'America/Mexico_City') = values.hour
     and app.posts.status = 'published'
    group by values.hour order by values.hour
  `;
  const statuses = await db()<Array<{ status: string; count: number }>>`
    select status, count(*)::integer as count from app.posts group by status
  `;
  const media = await db()<Array<{ media_type: string; count: number }>>`
    select media_type, count(*)::integer as count from app.posts group by media_type
  `;
  const top = await db()`
    select id, left(linkedin_text, 120) as text,
           coalesce(li_likes, 0) as likes,
           coalesce(li_comments, 0) as comments,
           coalesce(li_impressions, 0) as impressions,
           coalesce(li_clicks, 0) as clicks,
           coalesce(li_shares, 0) as shares,
           coalesce(li_likes, 0) + coalesce(li_comments, 0) * 2 +
             coalesce(li_shares, 0) * 3 as total,
           case when coalesce(li_impressions, 0) > 0
             then round(
               ((coalesce(li_likes, 0) + coalesce(li_comments, 0) +
                 coalesce(li_clicks, 0) + coalesce(li_shares, 0))::numeric /
                 li_impressions) * 100,
               2
             )
             else 0
           end as engagement_rate
    from app.posts
    where status = 'published' and metrics_updated_at is not null
    order by total desc, published_at desc
    limit 10
  `;
  const data = summary[0]!;
  const coverage = data.total_published
    ? Math.round((data.posts_with_metrics / data.total_published) * 100)
    : 0;
  const average = (value: number) =>
    data.posts_with_metrics ? Math.round(value / data.posts_with_metrics) : 0;
  return json(
    {
      ...data,
      posts_missing_metrics: data.total_published - data.posts_with_metrics,
      metrics_coverage_pct: coverage,
      avg_impressions: average(data.total_impressions),
      avg_likes: average(data.total_likes),
      engagement_rate: data.total_impressions
        ? Number(
            (
              ((data.total_likes + data.total_comments + data.total_clicks + data.total_shares) /
                data.total_impressions) *
              100
            ).toFixed(2)
          )
        : 0,
      posts_by_day: byDay,
      posts_by_hour: hours,
      status_breakdown: Object.fromEntries(statuses.map((row) => [row.status, row.count])),
      media_type_breakdown: Object.fromEntries(
        media.map((row) => [row.media_type, row.count])
      ),
      top_posts: top
    },
    { requestId: id }
  );
}

async function operationsStatus(id: string): Promise<Response> {
  const jobs = await db()`
    select status, count(*)::integer as count
    from app.job_queue group by status
  `;
  const health = await db()`
    select subsystem, last_success_at, last_error_at, last_error, metadata
    from app.system_health order by subsystem
  `;
  const backup = await db()`
    select status, artifact_name, size_bytes, checksum, completed_at
    from app.backup_runs order by started_at desc limit 1
  `;
  return json(
    {
      jobs,
      health,
      backup: backup[0] ?? null,
      cost: await currentCostState(),
      storage: await currentStorageState(),
      switches: {
        publishing: switches.publishingEnabled(),
        telegram: switches.telegramSendEnabled(),
        radar: switches.radarEnabled(),
        noncritical: switches.noncriticalJobsEnabled(),
        migration_freeze: switches.migrationFreeze()
      }
    },
    { requestId: id }
  );
}

export default async function handler(request: Request): Promise<Response> {
  const id = requestId(request);
  const url = new URL(request.url);
  try {
    const user = await requireUser(request);
    requireMutationGuard(request);
    await consumeRateLimit(user.id, request);
    if (
      switches.migrationFreeze() &&
      !["GET", "HEAD"].includes(request.method) &&
      url.pathname !== "/api/auth/linkedin/start"
    ) {
      throw new AppError("Migration freeze is active", 503, "migration_freeze");
    }

    if (url.pathname === "/auth/status") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      return json(await linkedinStatus(), { requestId: id });
    }
    if (url.pathname === "/auth/linkedin") {
      if (request.method !== "DELETE") return methodNotAllowed(request, ["DELETE"], id);
      await db()`delete from app.linkedin_tokens`;
      return json({ disconnected: true }, { requestId: id });
    }
    if (url.pathname === "/api/auth/linkedin/start") {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      return json({ url: await createLinkedInOAuthUrl() }, { requestId: id });
    }
    if (url.pathname === "/api/generate") {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      return generateFromUrl(request, id);
    }
    if (url.pathname === "/api/publish") {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      const post = await insertManualPost(request, "now");
      return json({ accepted: true, ...post }, { status: 202, requestId: id });
    }
    if (url.pathname === "/api/schedule") {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      const post = await insertManualPost(request, "schedule");
      return json(post, { status: 201, requestId: id });
    }
    if (url.pathname === "/api/posts") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      return listPosts(url, id);
    }
    if (url.pathname === "/api/posts/export") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      return exportPosts(url, id);
    }
    if (url.pathname === "/api/settings") {
      if (request.method === "GET") {
        const settings = await db()`
          select custom_prompt, version, updated_at from app.settings where id = 1
        `;
        return json(
          { ...settings[0], default_prompt: DEFAULT_EDITORIAL_PROMPT },
          { requestId: id }
        );
      }
      if (request.method === "PUT") {
        const input = z
          .object({
            custom_prompt: z.string().max(10_000).nullable(),
            version: z.number().int().positive().optional()
          })
          .parse(await parseJson(request));
        const rows = await db()`
          update app.settings
          set custom_prompt = ${input.custom_prompt},
              version = version + 1,
              profile_invalidated_at = now()
          where id = 1
            ${input.version ? db()`and version = ${input.version}` : db()``}
          returning custom_prompt, version, updated_at
        `;
        if (!rows[0]) throw new AppError("Settings changed", 409, "settings_conflict");
        await enqueueJob({
          type: "editorial_profile",
          payload: {},
          dedupeKey: `editorial_profile:settings:${rows[0].version}`,
          priority: 80
        });
        return json(rows[0], { requestId: id });
      }
      return methodNotAllowed(request, ["GET", "PUT"], id);
    }
    if (url.pathname === "/api/analytics") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      return analytics(id);
    }
    if (url.pathname === "/api/linkedin-scraper/status") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      const status = await linkedinStatus();
      return json(
        {
          configured: status.connected,
          has_jsessionid: false,
          transport: "linkedin_http_api"
        },
        { requestId: id }
      );
    }
    if (url.pathname === "/api/posts/refresh-all-metrics") {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      const jobId = await enqueueJob({
        type: "metrics_refresh",
        payload: {},
        dedupeKey: `metrics_refresh:manual:${Date.now()}`,
        priority: 60
      });
      return json(
        { running: true, job_id: jobId, message: "Actualización encolada." },
        { status: 202, requestId: id }
      );
    }
    if (url.pathname === "/api/posts/refresh-all-metrics/status") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      const jobs = await db()`
        select status, result, last_error, created_at, completed_at
        from app.job_queue
        where job_type = 'metrics_refresh'
        order by id desc limit 1
      `;
      const job = jobs[0];
      return json(
        {
          running: ["pending", "claimed", "running", "retry_wait"].includes(
            String(job?.status ?? "")
          ),
          finished_at: job?.completed_at ?? null,
          message: job?.last_error ?? "",
          ...(typeof job?.result === "object" ? job.result : {})
        },
        { requestId: id }
      );
    }
    if (url.pathname === "/api/posts/verify-scheduled") {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      const posts = await db()<Array<{ id: number; version: number }>>`
        select id, version from app.posts
        where status = 'scheduled'
        order by publish_at
        limit 50
      `;
      for (const post of posts) {
        await enqueueJob({
          type: "verify_post",
          payload: { post_id: post.id },
          dedupeKey: `verify_post:${post.id}:${post.version}`,
          priority: 15
        });
      }
      return json({ running: Boolean(posts.length), queued: posts.length }, { requestId: id });
    }
    if (url.pathname === "/api/posts/verify-scheduled/status") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      const rows = await db()`
        select count(*) filter (
          where status in ('pending', 'claimed', 'running', 'retry_wait')
        )::integer as pending,
        max(completed_at) as finished_at
        from app.job_queue where job_type = 'verify_post'
      `;
      return json(
        {
          running: Number(rows[0]?.pending ?? 0) > 0,
          finished_at: rows[0]?.finished_at ?? null
        },
        { requestId: id }
      );
    }
    if (url.pathname === "/api/operations/status") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      return operationsStatus(id);
    }
    if (url.pathname === "/api/operations/jobs") {
      if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
      const jobs = await db()`
        select id, job_type, status, run_at, attempts, max_attempts,
               last_error, created_at, started_at, completed_at, correlation_id
        from app.job_queue
        order by
          case status
            when 'dead' then 0
            when 'retry_wait' then 1
            when 'running' then 2
            when 'claimed' then 3
            when 'pending' then 4
            else 5
          end,
          id desc
        limit 100
      `;
      return json(jobs, { requestId: id });
    }
    const retryJobId = retryJobIdFromPath(url.pathname);
    if (retryJobId) {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      const sql = db();
      const retried = await sql<Array<{ id: number }>>`
        with source as (
          select job_type, payload, max_attempts, priority, correlation_id
          from app.job_queue
          where id = ${retryJobId} and status = 'dead'
          for update
        ),
        inserted as (
          insert into app.job_queue (
            job_type, run_at, payload, dedupe_key, max_attempts,
            priority, correlation_id
          )
          select job_type, now(), payload,
                 ${`manual_retry:${retryJobId}:${crypto.randomUUID()}`},
                 max_attempts, priority, correlation_id
          from source
          returning id
        ),
        retired as (
          update app.job_queue original
          set status = 'cancelled',
              result = jsonb_build_object(
                'manual_retry_job_id',
                (select id from inserted)
              ),
              completed_at = coalesce(completed_at, now()),
              updated_at = now()
          where original.id = ${retryJobId}
            and exists (select 1 from inserted)
          returning original.id
        )
        select id from inserted
      `;
      const newJobId = retried[0]?.id;
      if (!newJobId) {
        throw new AppError("El job no está en dead", 409, "job_not_retryable");
      }
      await recordEvent({
        subsystem: "queue",
        eventType: "job_manual_retry",
        entityType: "job",
        entityId: newJobId,
        metadata: { original_job_id: retryJobId },
        dedupeKey: `job_manual_retry:${newJobId}`
      });
      return json(
        { accepted: true, original_job_id: retryJobId, job_id: newJobId },
        { status: 202, requestId: id }
      );
    }

    const postId = postIdFromPath(url.pathname);
    if (postId && url.pathname.endsWith("/refresh-metrics")) {
      if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
      const posts = await db()<
        Array<{ linkedin_post_id: string | null }>
      >`select linkedin_post_id from app.posts where id = ${postId}`;
      if (!posts[0]?.linkedin_post_id) {
        throw new AppError("El post no tiene ID de LinkedIn", 409, "metrics_unavailable");
      }
      const metrics = await getPostMetrics(posts[0].linkedin_post_id);
      await db()`
        update app.posts
        set li_likes = coalesce(${metrics.likes ?? null}, li_likes),
            li_comments = coalesce(${metrics.comments ?? null}, li_comments),
            li_impressions = coalesce(${metrics.impressions ?? null}, li_impressions),
            li_clicks = coalesce(${metrics.clicks ?? null}, li_clicks),
            li_shares = coalesce(${metrics.shares ?? null}, li_shares),
            metrics_updated_at = now()
        where id = ${postId}
      `;
      return json(
        {
          li_likes: metrics.likes ?? null,
          li_comments: metrics.comments ?? null,
          li_impressions: metrics.impressions ?? null,
          li_clicks: metrics.clicks ?? null,
          li_shares: metrics.shares ?? null
        },
        { requestId: id }
      );
    }
    if (postId && url.pathname === `/api/posts/${postId}`) {
      if (request.method === "PUT") return updatePost(request, postId, id);
      if (request.method === "DELETE") {
        const rows = await db()<[{ status: string }]>`
          select app.cancel_post(${postId}, 'dashboard') as status
        `;
        return json({ id: postId, status: rows[0]?.status }, { requestId: id });
      }
      return methodNotAllowed(request, ["PUT", "DELETE"], id);
    }
    throw new AppError("Not found", 404, "not_found");
  } catch (error) {
    return toErrorResponse(error, id);
  }
}

export const config: Config = {
  path: [
    "/auth/status",
    "/auth/linkedin",
    "/api/auth/linkedin/start",
    "/api/generate",
    "/api/publish",
    "/api/schedule",
    "/api/posts",
    "/api/posts/*",
    "/api/settings",
    "/api/analytics",
    "/api/linkedin-scraper/status",
    "/api/operations/*"
  ]
};

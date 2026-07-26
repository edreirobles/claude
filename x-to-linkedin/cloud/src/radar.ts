import { createHash } from "node:crypto";
import { XMLParser } from "fast-xml-parser";
import { db } from "./db.js";
import {
  generateLinkedInCopy,
  loadOrBuildEditorialProfile,
  type EditorialIntent
} from "./editorial.js";
import { recordEvent } from "./events.js";
import { normalizeUrl, safeFetch } from "./external-url.js";
import { enqueueJob } from "./queue.js";
import { scrapeSource } from "./source.js";
import { extractJsonObject, generateText } from "./text-provider.js";

export type RadarCandidate = {
  url: string;
  title: string;
  summary: string;
  sourceName: string;
  sourceDomain: string;
  kind: "news" | "paper" | "tool" | "practice";
  publishedAt: Date | null;
  sourceWeight: number;
  score: number;
};

type RadarDecision = {
  candidate: RadarCandidate;
  reason: string;
  intent: EditorialIntent;
  angle: string;
};

const FEEDS = [
  ["Anthropic Engineering", "https://www.anthropic.com/engineering/rss.xml", "practice", 5],
  ["Google Research", "https://blog.research.google/feeds/posts/default?alt=rss", "paper", 4],
  ["Hugging Face", "https://huggingface.co/blog/feed.xml", "tool", 4],
  ["MIT AI", "https://news.mit.edu/topic/mitartificial-intelligence2-rss.xml", "news", 4],
  ["Stanford HAI", "https://hai.stanford.edu/news/rss.xml", "news", 4],
  ["DeepLearning.AI", "https://www.deeplearning.ai/the-batch/feed/", "practice", 3],
  [
    "Google News AI Education",
    "https://news.google.com/rss/search?q=%22artificial+intelligence%22+education+tool+OR+research&hl=en-US&gl=US&ceid=US:en",
    "news",
    3
  ],
  [
    "Google News AI Practice",
    "https://news.google.com/rss/search?q=AI+workflow+best+practice+education&hl=en-US&gl=US&ceid=US:en",
    "practice",
    3
  ]
] as const;

const SIGNALS = [
  "education", "educacion", "learning", "teacher", "student", "classroom",
  "assessment", "agent", "workflow", "evaluation", "safety", "privacy",
  "governance", "open source", "multimodal", "research", "paper", "tool",
  "productivity", "best practice", "prompt"
];
const GENERAL_LLM = ["chatgpt", "gpt-", "claude", "gemini", "grok", "llama", "mistral"];
const LAUNCH = ["launch", "release", "announc", "introduc", "presenta", "lanza", "modelo", "model"];
const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: "" });

function toDate(value: unknown): Date | null {
  const date = new Date(String(value ?? ""));
  return Number.isNaN(date.valueOf()) ? null : date;
}

function scoreCandidate(candidate: Omit<RadarCandidate, "score">): number {
  const ageHours = candidate.publishedAt
    ? Math.max(0, (Date.now() - candidate.publishedAt.valueOf()) / 3_600_000)
    : 168;
  const recency = Math.max(0, 8 - ageHours / 24);
  const haystack = `${candidate.title} ${candidate.summary}`.toLowerCase();
  const relevance = SIGNALS.filter((signal) => haystack.includes(signal)).length;
  return candidate.sourceWeight * 10 + recency + relevance * 3;
}

function isGeneralLlmLaunch(candidate: RadarCandidate): boolean {
  const text = `${candidate.title} ${candidate.summary}`.toLowerCase();
  return GENERAL_LLM.some((marker) => text.includes(marker)) &&
    LAUNCH.some((marker) => text.includes(marker)) &&
    !/(education|teacher|student|classroom|assessment|safety|evaluation)/.test(text);
}

function arrayify<T>(value: T | T[] | undefined): T[] {
  return value === undefined ? [] : Array.isArray(value) ? value : [value];
}

async function readFeed(
  name: string,
  url: string,
  kind: RadarCandidate["kind"],
  weight: number
): Promise<RadarCandidate[]> {
  const response = await safeFetch(url, {}, 4 * 1024 * 1024);
  if (!response.ok) throw new Error(`${name} returned ${response.status}`);
  const payload = parser.parse(await response.text()) as Record<string, any>;
  const rssItems = arrayify(payload.rss?.channel?.item);
  const atomItems = arrayify(payload.feed?.entry);
  return [...rssItems, ...atomItems].flatMap((item): RadarCandidate[] => {
    const rawLink =
      typeof item.link === "string"
        ? item.link
        : Array.isArray(item.link)
          ? item.link.find((link: any) => link.rel === "alternate")?.href ?? item.link[0]?.href
          : item.link?.href;
    if (!rawLink) return [];
    const title = String(item.title?.["#text"] ?? item.title ?? "").trim();
    const summary = String(
      item.description ?? item.summary?.["#text"] ?? item.summary ?? item.content?.["#text"] ?? ""
    )
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 1600);
    let sourceDomain = "";
    try {
      sourceDomain = new URL(rawLink).hostname.replace(/^www\./, "");
    } catch {
      return [];
    }
    const base = {
      url: String(rawLink),
      title,
      summary,
      sourceName: name,
      sourceDomain,
      kind,
      publishedAt: toDate(item.pubDate ?? item.published ?? item.updated),
      sourceWeight: weight
    };
    return [{ ...base, score: scoreCandidate(base) }];
  });
}

async function readArxiv(): Promise<RadarCandidate[]> {
  const query = encodeURIComponent(
    'all:("artificial intelligence" AND (education OR learning OR evaluation OR agent OR safety))'
  );
  return readFeed(
    "arXiv",
    `https://export.arxiv.org/api/query?search_query=${query}&sortBy=submittedDate&sortOrder=descending&max_results=20`,
    "paper",
    5
  );
}

export async function discoverRadarCandidates(): Promise<RadarCandidate[]> {
  const batches = await Promise.allSettled([
    ...FEEDS.map(([name, url, kind, weight]) => readFeed(name, url, kind, weight)),
    readArxiv()
  ]);
  const sql = db();
  const usedRows = await sql<{ tweet_url: string }[]>`
    select tweet_url from app.posts
    where tweet_url is not null and tweet_url not like 'radar://%'
  `;
  const used = new Set(
    usedRows.flatMap(({ tweet_url }) => {
      try {
        return [normalizeUrl(tweet_url)];
      } catch {
        return [];
      }
    })
  );
  const seen = new Set<string>();
  const maxAgeMs = 7 * 24 * 60 * 60 * 1000;
  return batches
    .flatMap((batch) => (batch.status === "fulfilled" ? batch.value : []))
    .filter((candidate) => {
      let normalized: string;
      try {
        normalized = normalizeUrl(candidate.url);
      } catch {
        return false;
      }
      if (
        seen.has(normalized) ||
        used.has(normalized) ||
        isGeneralLlmLaunch(candidate) ||
        (candidate.publishedAt && Date.now() - candidate.publishedAt.valueOf() > maxAgeMs)
      ) {
        return false;
      }
      seen.add(normalized);
      return true;
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 40);
}

async function rankCandidates(
  candidates: RadarCandidate[],
  profile: string
): Promise<RadarDecision[]> {
  const fallback = candidates.map((candidate) => ({
    candidate,
    reason: "Mejor senal editorial disponible",
    intent: (candidate.kind === "tool" ? "invitar" : candidate.kind === "paper" ? "explicar" : "presentar") as EditorialIntent,
    angle: "utilidad concreta"
  }));
  try {
    const response = await generateText({
      system: [
        "Eres un radar editorial senior. Debes decidir, no automatizar.",
        "Elige hasta siete candidatas frescas y concretas.",
        "Prioriza papers utiles, noticias relevantes, herramientas de IA que no sean LLM generales y buenas practicas.",
        "Decide una intencion entre presentar, describir, invitar, explicar, advertir, analizar o reflexionar.",
        "Devuelve JSON valido: {\"ranked\":[{\"index\":1,\"reason\":\"...\",\"intent\":\"presentar\",\"angle\":\"...\"}]}."
      ].join("\n"),
      user: `MEMORIA:\n${profile.slice(0, 3000)}\n\nCANDIDATAS:\n${candidates
        .slice(0, 25)
        .map(
          (candidate, index) =>
            `${index + 1}. [${candidate.kind}] ${candidate.title}\n${candidate.sourceName}\n${candidate.summary.slice(0, 500)}`
        )
        .join("\n\n")}`,
      maxTokens: 1000
    });
    const parsed = extractJsonObject<{
      ranked: Array<{ index: number; reason: string; intent: EditorialIntent; angle: string }>;
    }>(response);
    const ranked = parsed.ranked.flatMap((item): RadarDecision[] => {
      const candidate = candidates[item.index - 1];
      return candidate
        ? [{ candidate, reason: item.reason, intent: item.intent, angle: item.angle }]
        : [];
    });
    return ranked.length ? ranked : fallback;
  } catch {
    return fallback;
  }
}

export async function ensureRadarSlots(daysAhead = 14): Promise<number> {
  const rows = await db()<[{ inserted: number }]>`
    with slots as (
      select
        day_value,
        slot_hour,
        ((day_value + make_interval(hours => slot_hour))::timestamp
          at time zone 'America/Mexico_City') as slot_at
      from generate_series(
        (now() at time zone 'America/Mexico_City')::date,
        (now() at time zone 'America/Mexico_City')::date + ${daysAhead - 1},
        interval '1 day'
      ) as day_value
      cross join unnest(array[5, 16]) as slot_hour
    ),
    inserted as (
      insert into app.posts (
        tweet_url, tweet_text, tweet_author, linkedin_text, image_urls,
        scheduled_at, status, media_type, source
      )
      select
        'radar://slot/' || to_char(slot_at at time zone 'America/Mexico_City', 'YYYY-MM-DD"T"HH24:MI:SS'),
        'Radar editorial pendiente',
        'Radar editorial',
        '',
        '[]'::jsonb,
        slot_at,
        'radar_slot',
        'none',
        'radar'
      from slots
      where slot_at > now()
      on conflict do nothing
      returning 1
    )
    select count(*)::integer as inserted from inserted
  `;
  return rows[0]?.inserted ?? 0;
}

export async function maintainRadarSchedule(): Promise<Record<string, number>> {
  const created = await ensureRadarSlots();
  const due = await db()<{ id: number }[]>`
    select id from app.posts
    where source = 'radar'
      and status = 'radar_slot'
      and scheduled_at <= now() + interval '48 hours'
    order by scheduled_at
  `;
  for (const post of due) {
    await enqueueJob({
      type: "radar_prepare",
      payload: { post_id: post.id },
      dedupeKey: `radar_prepare:${post.id}:1`,
      priority: 40
    });
  }
  return { created, queued: due.length };
}

export async function prepareRadarPost(
  postId: number,
  force = false
): Promise<RadarDecision> {
  const sql = db();
  const posts = await sql<{
    id: number;
    status: string;
    scheduled_at: Date;
    editorial_revision_notes: string | null;
  }[]>`
    select id, status, scheduled_at, editorial_revision_notes
    from app.posts where id = ${postId}
  `;
  const post = posts[0];
  if (!post || !["radar_slot", "approval_pending", "failed"].includes(post.status)) {
    throw new Error("Radar post is not editable");
  }
  if (post.status === "approval_pending" && !force) {
    throw new Error("Radar post is already prepared");
  }
  if (force) {
    await sql`
      update app.radar_candidates
      set excluded = true, selected = false, exclusion_reason = 'otra fuente solicitada'
      where post_id = ${postId} and selected = true
    `;
  }

  const excluded = await sql<{ normalized_url: string }[]>`
    select normalized_url from app.radar_candidates
    where post_id = ${postId} and excluded = true
  `;
  const excludedUrls = new Set(excluded.map((row) => row.normalized_url));
  const candidates = (await discoverRadarCandidates()).filter(
    (candidate) => !excludedUrls.has(normalizeUrl(candidate.url))
  );
  if (!candidates.length) throw new Error("Radar found no fresh non-repeated candidates");

  const profile = await loadOrBuildEditorialProfile();
  const decisions = await rankCandidates(candidates, profile);
  for (const [index, candidate] of candidates.entries()) {
    const decision = decisions.find((item) => item.candidate.url === candidate.url);
    await sql`
      insert into app.radar_candidates (
        post_id, source_url, normalized_url, title, summary, source_name,
        source_domain, source_kind, published_at, score, rank, decision_reason,
        intent, angle, selected
      ) values (
        ${postId}, ${candidate.url}, ${normalizeUrl(candidate.url)}, ${candidate.title},
        ${candidate.summary}, ${candidate.sourceName}, ${candidate.sourceDomain},
        ${candidate.kind}, ${candidate.publishedAt?.toISOString() ?? null},
        ${candidate.score}, ${decision ? decisions.indexOf(decision) + 1 : index + 1},
        ${decision?.reason ?? null}, ${decision?.intent ?? null}, ${decision?.angle ?? null},
        false
      )
      on conflict (post_id, normalized_url) do update
      set score = excluded.score,
          rank = excluded.rank,
          decision_reason = excluded.decision_reason,
          intent = excluded.intent,
          angle = excluded.angle
    `;
  }

  let selected: RadarDecision | undefined;
  let source;
  for (const decision of decisions.slice(0, 8)) {
    try {
      source = await scrapeSource(decision.candidate.url);
      if (source.text.length >= 80) {
        selected = decision;
        break;
      }
    } catch {
      await sql`
        update app.radar_candidates
        set excluded = true, exclusion_reason = 'source scrape failed'
        where post_id = ${postId}
          and normalized_url = ${normalizeUrl(decision.candidate.url)}
      `;
    }
  }
  if (!selected || !source) throw new Error("No radar candidate could be prepared");

  const settings = await sql<{ custom_prompt: string | null }[]>`
    select custom_prompt from app.settings where id = 1
  `;
  const copy = await generateLinkedInCopy({
    source,
    intent: selected.intent,
    angle: selected.angle,
    reason: selected.reason,
    profile,
    customPrompt: settings[0]?.custom_prompt ?? null,
    revisionNotes: post.editorial_revision_notes
  });
  const mediaType = source.images.length ? "image" : source.pdfUrl ? "document" : "none";

  await sql.begin(async (transaction) => {
    await transaction`
      update app.radar_candidates
      set selected = (normalized_url = ${normalizeUrl(selected!.candidate.url)})
      where post_id = ${postId}
    `;
    await transaction`
      update app.posts
      set tweet_url = ${source!.url},
          tweet_text = ${source!.text.slice(0, 20_000)},
          tweet_author = ${source!.author || selected!.candidate.sourceName},
          linkedin_text = ${copy},
          image_urls = ${transaction.json(mediaType === "image" ? source!.images : [])},
          use_first_image = ${mediaType === "image"},
          media_type = ${mediaType},
          pdf_url = ${source!.pdfUrl ?? null},
          document_title = ${source!.title.slice(0, 500) || "Documento"},
          generated_image_path = null,
          status = 'approval_pending',
          source = 'radar',
          source_metadata = ${transaction.json({
            title: selected!.candidate.title,
            reason: selected!.reason,
            intent: selected!.intent,
            angle: selected!.angle,
            candidate_hash: createHash("sha256").update(selected!.candidate.url).digest("hex")
          })},
          error_message = null,
          version = version + 1
      where id = ${postId}
    `;
  });

  const notificationTime = new Date(
    Math.max(Date.now(), new Date(post.scheduled_at).valueOf() - 60 * 60 * 1000)
  );
  await enqueueJob({
    type: "notify_approval",
    runAt: notificationTime,
    payload: { post_id: postId },
    dedupeKey: `notify_approval:${postId}`,
    priority: 20
  });
  await recordEvent({
    subsystem: "radar",
    eventType: "post_prepared",
    entityType: "post",
    entityId: postId,
    metadata: {
      source_url: selected.candidate.url,
      intent: selected.intent,
      media_type: mediaType
    },
    dedupeKey: `radar_prepared:${postId}:${createHash("sha256").update(selected.candidate.url).digest("hex")}`
  });
  return selected;
}

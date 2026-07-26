import { createHash } from "node:crypto";
import { db } from "./db.js";
import { extractJsonObject, generateText } from "./text-provider.js";
import type { SourceContent } from "./source.js";

export const DEFAULT_EDITORIAL_PROMPT = [
  "Escribe como una persona experta que comparte algo porque vale la pena conocerlo.",
  "Decide la estructura a partir de la fuente. No fuerces moraleja, pregunta final ni reflexion.",
  "Puedes presentar, describir, invitar a usar, explicar, advertir, analizar o reflexionar.",
  "No uses markdown, asteriscos, encabezados, listas con guiones ni frases de asistente.",
  "No inventes hechos. No copies frases de publicaciones anteriores.",
  "Si no existe multimedia real, vuelve especialmente fuerte y concreta la primera linea.",
  "Maximo 3000 caracteres."
].join("\n");

export type EditorialIntent =
  | "presentar"
  | "describir"
  | "invitar"
  | "explicar"
  | "advertir"
  | "analizar"
  | "reflexionar";

type HistoricalPost = {
  id: number;
  source: string;
  linkedin_text: string;
  published_at: Date | null;
  li_likes: number | null;
  li_comments: number | null;
  li_impressions: number | null;
  li_clicks: number | null;
  li_shares: number | null;
};

function metric(value: number | null): number {
  return Number(value ?? 0);
}

export function engagementScore(post: HistoricalPost): number {
  const actions =
    metric(post.li_likes) +
    metric(post.li_comments) * 2 +
    metric(post.li_clicks) +
    metric(post.li_shares) * 3;
  const impressions = metric(post.li_impressions);
  const rate = impressions ? (actions / impressions) * 100 : 0;
  return (
    metric(post.li_likes) * 2 +
    metric(post.li_comments) * 8 +
    metric(post.li_shares) * 10 +
    metric(post.li_clicks) * 2 +
    Math.min(impressions, 150_000) / 1000 +
    rate * 20
  );
}

function firstLine(text: string): string {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean)
    ?.slice(0, 220) ?? "";
}

function median(values: number[]): number {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2
    ? sorted[middle]!
    : Math.round((sorted[middle - 1]! + sorted[middle]!) / 2);
}

function profileFingerprint(posts: HistoricalPost[]): string {
  const stable = posts.map((post) => [
    post.id,
    post.linkedin_text.length,
    post.li_likes,
    post.li_comments,
    post.li_impressions,
    post.li_clicks,
    post.li_shares
  ]);
  return createHash("sha256").update(JSON.stringify(stable)).digest("hex");
}

function deterministicProfile(
  posts: HistoricalPost[],
  strong: HistoricalPost[],
  weak: HistoricalPost[],
  manual: HistoricalPost[]
): string {
  const lengths = strong.map((post) => post.linkedin_text.length);
  const paragraphs = strong.map(
    (post) => post.linkedin_text.split(/\n\s*\n/).filter(Boolean).length
  );
  return [
    `Base historica: ${posts.length} publicaciones con texto.`,
    `Longitud fuerte: mediana ${median(lengths)} caracteres.`,
    `Estructura fuerte: mediana ${median(paragraphs)} bloques.`,
    `Referencias manuales o pre-herramienta: ${manual.length}.`,
    "Las aperturas fuertes nombran pronto un caso, dato, paper, practica o herramienta concreta.",
    "La intencion cambia con la fuente; no se fuerza pregunta final ni reflexion.",
    `Aperturas fuertes: ${strong.slice(0, 6).map((post) => firstLine(post.linkedin_text)).join(" | ")}`,
    `Aperturas flojas a evitar como patron: ${weak.slice(0, 4).map((post) => firstLine(post.linkedin_text)).join(" | ")}`
  ].join("\n");
}

export async function loadOrBuildEditorialProfile(force = false): Promise<string> {
  const sql = db();
  const posts = await sql<HistoricalPost[]>`
    select id, source, linkedin_text, published_at, li_likes, li_comments,
           li_impressions, li_clicks, li_shares
    from app.posts
    where status = 'published' and length(linkedin_text) >= 80
    order by published_at asc nulls last, id asc
  `;
  if (!posts.length) return "Todavia no hay historia suficiente. Usa criterio fresco y concreto.";

  const fingerprint = profileFingerprint(posts);
  const existing = await sql<{ profile_text: string }[]>`
    select profile_text
    from app.editorial_profiles
    where metrics_fingerprint = ${fingerprint}
    order by version desc
    limit 1
  `;
  if (existing[0] && !force) return existing[0].profile_text;

  const ranked = [...posts].sort((a, b) => engagementScore(b) - engagementScore(a));
  const strong = ranked.slice(0, 28);
  const weak = ranked.filter((post) => engagementScore(post) > 0).slice(-8);
  const firstToolDate = posts.find((post) =>
    ["x_auto", "editorial", "radar"].includes(post.source)
  )?.published_at;
  const manual = posts
    .filter(
      (post) =>
        post.source === "manual" &&
        (!firstToolDate || !post.published_at || post.published_at < firstToolDate)
    )
    .slice(0, 14);

  const base = deterministicProfile(posts, strong, weak, manual);
  let profile = base;
  try {
    profile = await generateText({
      system: [
        "Eres analista editorial. Resume patrones de voz, longitud, estructura, temas e intenciones.",
        "Contrasta publicaciones fuertes y flojas. No copies frases. Devuelve texto operativo y conciso."
      ].join("\n"),
      user: base,
      maxTokens: 900
    });
  } catch {
    profile = base;
  }

  const versionRows = await sql<{ version: number }[]>`
    select coalesce(max(version), 0) + 1 as version from app.editorial_profiles
  `;
  await sql`
    insert into app.editorial_profiles (
      version, profile_text, sample_post_ids, strong_post_ids, weak_post_ids,
      metrics_fingerprint, generated_by
    ) values (
      ${versionRows[0]!.version},
      ${profile.slice(0, 5000)},
      ${sql.json(posts.map((post) => post.id))},
      ${sql.json(strong.map((post) => post.id))},
      ${sql.json(weak.map((post) => post.id))},
      ${fingerprint},
      ${profile === base ? "deterministic" : "text_provider"}
    )
  `;
  return profile.slice(0, 5000);
}

export function sanitizeLinkedInCopy(text: string): string {
  return text
    .replace(/\r\n?/g, "\n")
    .replace(/^[ \t]*[-*][ \t]+/gm, "")
    .replace(/\*/g, "")
    .replace(/^#{1,6}\s+/gm, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
    .slice(0, 3000);
}

export function hasStrongAnchor(text: string): boolean {
  const opening = firstLine(text);
  if (opening.length < 28 || opening.length > 180) return false;
  const concreteSignal =
    /\d|paper|estudio|herramienta|practica|caso|equipo|docente|estudiante|investig|codigo|curso|universidad|empresa/i;
  return concreteSignal.test(opening) && !/^(hoy quiero|en un mundo|la ia esta|reflexionemos)/i.test(opening);
}

const EDITORIAL_INTENTS = new Set<EditorialIntent>([
  "presentar",
  "describir",
  "invitar",
  "explicar",
  "advertir",
  "analizar",
  "reflexionar"
]);

export async function decideEditorialTreatment(
  source: SourceContent,
  profile = ""
): Promise<{ intent: EditorialIntent; angle: string; reason: string }> {
  const fallbackIntent: EditorialIntent =
    source.kind === "tool"
      ? "invitar"
      : source.kind === "paper"
        ? "explicar"
        : source.kind === "practice"
          ? "describir"
          : "presentar";
  try {
    const response = await generateText({
      system: [
        "Eres editor senior. Decide el tratamiento que mejor sirve a esta fuente.",
        "No lleves todo a la reflexion. Una herramienta suele invitar a probar; un paper puede explicar o analizar; una noticia puede presentar o advertir.",
        "Devuelve JSON valido con intent, angle y reason.",
        "intent debe ser presentar, describir, invitar, explicar, advertir, analizar o reflexionar."
      ].join("\n"),
      user: [
        profile ? `Memoria editorial:\n${profile.slice(0, 2500)}` : "",
        `Tipo: ${source.kind}`,
        `Titulo: ${source.title}`,
        `Fuente: ${source.author}`,
        `Contenido: ${source.text.slice(0, 4500)}`
      ]
        .filter(Boolean)
        .join("\n\n"),
      maxTokens: 450
    });
    const parsed = extractJsonObject<{
      intent: EditorialIntent;
      angle: string;
      reason: string;
    }>(response);
    if (!EDITORIAL_INTENTS.has(parsed.intent)) throw new Error("Invalid editorial intent");
    return {
      intent: parsed.intent,
      angle: String(parsed.angle ?? "").slice(0, 500),
      reason: String(parsed.reason ?? "").slice(0, 800)
    };
  } catch {
    return {
      intent: fallbackIntent,
      angle: "utilidad concreta para la audiencia",
      reason: `Tratamiento base para una fuente de tipo ${source.kind}`
    };
  }
}

export async function generateLinkedInCopy(input: {
  source: SourceContent;
  intent: EditorialIntent;
  angle?: string;
  reason?: string;
  profile?: string;
  customPrompt?: string | null;
  revisionNotes?: string | null;
}): Promise<string> {
  const noMedia = !input.source.images.length && !input.source.pdfUrl;
  const prompt = [
    DEFAULT_EDITORIAL_PROMPT,
    input.customPrompt ?? "",
    `Intencion decidida: ${input.intent}.`,
    input.angle ? `Angulo: ${input.angle}.` : "",
    input.reason ? `Motivo editorial: ${input.reason}.` : "",
    noMedia
      ? "No hay multimedia real. La primera linea debe ser una frase ancla concreta, irresistible y verificable."
      : "La fuente incluye multimedia real; el texto debe seguir siendo autosuficiente.",
    input.profile ? `Memoria editorial:\n${input.profile.slice(0, 3500)}` : "",
    input.revisionNotes ? `Cambios acumulados pedidos:\n${input.revisionNotes}` : ""
  ]
    .filter(Boolean)
    .join("\n\n");
  const sourceBrief = [
    `URL: ${input.source.url}`,
    `Tipo: ${input.source.kind}`,
    `Titulo: ${input.source.title}`,
    `Autor o fuente: ${input.source.author}`,
    `Contenido:\n${input.source.text.slice(0, 14_000)}`
  ].join("\n\n");
  let result = sanitizeLinkedInCopy(
    await generateText({ system: prompt, user: sourceBrief, maxTokens: 1800 })
  );

  if (noMedia && !hasStrongAnchor(result)) {
    result = sanitizeLinkedInCopy(
      await generateText({
        system: [
          prompt,
          "Reescribe el post completo. Corrige especialmente la primera linea: debe mencionar un elemento concreto de la fuente, sin clickbait ni pregunta generica."
        ].join("\n\n"),
        user: result,
        maxTokens: 1800
      })
    );
  }
  if (!result || result.length > 3000) {
    throw new Error("Generated copy failed LinkedIn length validation");
  }
  return result;
}

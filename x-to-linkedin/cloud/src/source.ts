import * as cheerio from "cheerio";
import { safeFetch } from "./external-url.js";

export type SourceContent = {
  url: string;
  title: string;
  text: string;
  author: string;
  images: string[];
  pdfUrl?: string;
  kind: "article" | "x_post" | "paper" | "tool" | "news" | "practice";
};

function compact(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

function uniqueUrls(urls: string[], base: URL): string[] {
  const output: string[] = [];
  const seen = new Set<string>();
  for (const raw of urls) {
    try {
      const url = new URL(raw, base);
      if (!["http:", "https:"].includes(url.protocol) || seen.has(url.href)) continue;
      seen.add(url.href);
      output.push(url.href);
    } catch {
      continue;
    }
  }
  return output.slice(0, 8);
}

async function scrapeX(url: URL): Promise<SourceContent | null> {
  const match = url.pathname.match(/\/status\/(\d+)/);
  if (!match?.[1]) return null;
  const endpoint = `https://cdn.syndication.twimg.com/tweet-result?id=${match[1]}&lang=es`;
  const response = await safeFetch(endpoint, {}, 2 * 1024 * 1024);
  if (!response.ok) return null;
  const payload = (await response.json()) as {
    text?: string;
    user?: { name?: string; screen_name?: string };
    photos?: Array<{ url?: string }>;
  };
  return {
    url: url.href,
    title: compact(payload.text ?? "").slice(0, 180),
    text: compact(payload.text ?? ""),
    author: payload.user?.name ?? payload.user?.screen_name ?? "",
    images: (payload.photos ?? []).flatMap((photo) => (photo.url ? [photo.url] : [])),
    kind: "x_post"
  };
}

export async function scrapeSource(rawUrl: string): Promise<SourceContent> {
  const initial = new URL(rawUrl);
  if (["x.com", "twitter.com", "www.x.com", "www.twitter.com"].includes(initial.hostname)) {
    const tweet = await scrapeX(initial);
    if (tweet?.text) return tweet;
  }

  const response = await safeFetch(rawUrl);
  if (!response.ok) {
    throw new Error(`Source returned HTTP ${response.status}`);
  }
  const contentType = response.headers.get("content-type") ?? "";
  const resolvedUrl =
    response.headers.get("x-x2li-final-url") || response.url || rawUrl;
  if (contentType.includes("application/pdf") || initial.pathname.endsWith(".pdf")) {
    return {
      url: resolvedUrl,
      title: initial.pathname.split("/").pop() || "Paper",
      text: "Documento PDF de la fuente.",
      author: initial.hostname,
      images: [],
      pdfUrl: resolvedUrl,
      kind: "paper"
    };
  }

  const html = await response.text();
  const finalUrl = new URL(resolvedUrl);
  const $ = cheerio.load(html);
  $("script, style, nav, footer, form, aside, noscript").remove();

  const title = compact(
    $("meta[property='og:title']").attr("content") ??
      $("meta[name='twitter:title']").attr("content") ??
      $("h1").first().text() ??
      $("title").text()
  );
  const description = compact(
    $("meta[property='og:description']").attr("content") ??
      $("meta[name='description']").attr("content") ??
      ""
  );
  const articleText = compact(
    $("article").text() ||
      $("main").text() ||
      $("[role='main']").text() ||
      $("body").text()
  ).slice(0, 18_000);
  const author = compact(
    $("meta[name='author']").attr("content") ??
      $("[rel='author']").first().text() ??
      finalUrl.hostname
  );
  const imageCandidates = [
    $("meta[property='og:image']").attr("content") ?? "",
    $("meta[name='twitter:image']").attr("content") ?? "",
    ...$("article img, main img")
      .map((_index, element) => $(element).attr("src") ?? "")
      .get()
  ];
  const pdf = $("a[href$='.pdf']").first().attr("href");
  const haystack = `${title} ${description} ${finalUrl.hostname}`.toLowerCase();
  const kind: SourceContent["kind"] =
    finalUrl.hostname.includes("arxiv.org") || haystack.includes("paper")
      ? "paper"
      : haystack.includes("tool") || haystack.includes("github")
        ? "tool"
        : haystack.includes("practice") || haystack.includes("guide")
          ? "practice"
          : "article";

  return {
    url: finalUrl.href,
    title,
    text: compact(`${description}\n\n${articleText}`).slice(0, 18_000),
    author,
    images: uniqueUrls(imageCandidates, finalUrl),
    ...(pdf ? { pdfUrl: new URL(pdf, finalUrl).href } : {}),
    kind
  };
}

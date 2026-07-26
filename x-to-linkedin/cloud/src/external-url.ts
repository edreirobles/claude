import { lookup } from "node:dns/promises";
import { isIP } from "node:net";
import { AppError } from "./http.js";

function isPrivateAddress(address: string): boolean {
  const normalized = address.toLowerCase();
  if (normalized.startsWith("::ffff:")) {
    return isPrivateAddress(normalized.slice("::ffff:".length));
  }
  if (normalized === "::" || normalized === "::1" || normalized === "0.0.0.0") {
    return true;
  }
  const octets = normalized.split(".").map(Number);
  if (octets.length === 4 && octets.every((part) => Number.isInteger(part))) {
    const [first, second] = octets as [number, number, number, number];
    return (
      first === 0 ||
      first === 10 ||
      first === 127 ||
      (first === 100 && second >= 64 && second <= 127) ||
      (first === 169 && second === 254) ||
      (first === 172 && second >= 16 && second <= 31) ||
      (first === 192 && second === 168) ||
      (first === 198 && (second === 18 || second === 19)) ||
      first >= 224
    );
  }
  return (
    normalized.startsWith("fc") ||
    normalized.startsWith("fd") ||
    normalized.startsWith("fe80:") ||
    normalized.startsWith("2001:db8:")
  );
}

export async function assertSafeExternalUrl(rawUrl: string): Promise<URL> {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new AppError("Invalid URL", 400, "invalid_url");
  }
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new AppError("Unsupported URL protocol", 400, "invalid_url");
  }
  if (
    url.username ||
    url.password ||
    ["localhost", "metadata.google.internal"].includes(url.hostname.toLowerCase())
  ) {
    throw new AppError("Unsafe URL", 400, "unsafe_url");
  }
  const addresses = isIP(url.hostname)
    ? [{ address: url.hostname }]
    : await lookup(url.hostname, { all: true });
  if (!addresses.length || addresses.some(({ address }) => isPrivateAddress(address))) {
    throw new AppError("Unsafe URL destination", 400, "unsafe_url");
  }
  return url;
}

export function normalizeUrl(raw: string): string {
  const url = new URL(raw);
  url.hash = "";
  for (const key of [...url.searchParams.keys()]) {
    if (/^(utm_|fbclid|gclid|ref$|source$)/i.test(key)) {
      url.searchParams.delete(key);
    }
  }
  url.hostname = url.hostname.toLowerCase().replace(/^www\./, "");
  url.pathname = url.pathname.replace(/\/+$/, "") || "/";
  return url.toString();
}

export async function cappedResponse(
  response: Response,
  maxBytes: number,
  finalUrl?: string
): Promise<Response> {
  if (!response.body) return response;
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw new AppError("Source is too large", 413, "source_too_large");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const body = Buffer.concat(chunks.map((chunk) => Buffer.from(chunk)));
  const headers = new Headers(response.headers);
  if (finalUrl) headers.set("x-x2li-final-url", finalUrl);
  return new Response(body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

export async function safeFetch(
  rawUrl: string,
  init: RequestInit = {},
  maxBytes = 5 * 1024 * 1024,
  redirectCount = 0
): Promise<Response> {
  if (redirectCount > 5) {
    throw new AppError("Too many redirects", 502, "source_redirect_limit");
  }
  const url = await assertSafeExternalUrl(rawUrl);
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetch(url, {
      ...init,
      redirect: "manual",
      signal: controller.signal,
      headers: {
        "user-agent": "x-to-linkedin-radar/1.0",
        accept: "text/html,application/json,application/xml,text/xml,*/*;q=0.5",
        ...init.headers
      }
    });
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (!location) throw new AppError("Invalid redirect", 502, "source_error");
      return safeFetch(new URL(location, url).href, init, maxBytes, redirectCount + 1);
    }
    const declared = Number(response.headers.get("content-length") ?? 0);
    if (declared > maxBytes) {
      throw new AppError("Source is too large", 413, "source_too_large");
    }
    return cappedResponse(response, maxBytes, url.href);
  } finally {
    clearTimeout(timeout);
  }
}

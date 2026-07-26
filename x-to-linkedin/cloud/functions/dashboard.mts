import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { Config } from "@netlify/functions";
import { requireUser } from "../src/auth.js";

let cachedHtml: string | null = null;

async function dashboardHtml(): Promise<string> {
  if (!cachedHtml) {
    cachedHtml = await readFile(resolve(process.cwd(), "dist/index.html"), "utf8");
  }
  return cachedHtml;
}

export default async function handler(request: Request): Promise<Response> {
  if (!["GET", "HEAD"].includes(request.method)) {
    return new Response(null, {
      status: 405,
      headers: { allow: "GET, HEAD", "cache-control": "no-store" }
    });
  }
  try {
    await requireUser(request);
  } catch {
    return Response.redirect(new URL("/login.html", request.url), 302);
  }
  return new Response(request.method === "HEAD" ? null : await dashboardHtml(), {
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff"
    }
  });
}

export const config: Config = {
  path: "/"
};

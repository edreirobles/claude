import { createClient, type User } from "@supabase/supabase-js";
import { env, requiredEnv } from "./env.js";
import { AppError } from "./http.js";

export const SESSION_COOKIE = "x2li_session";

export function readCookie(request: Request, name: string): string {
  for (const part of (request.headers.get("cookie") ?? "").split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return decodeURIComponent(value.join("="));
  }
  return "";
}

export function bearerToken(request: Request): string {
  const authorization = request.headers.get("authorization") ?? "";
  if (authorization.toLowerCase().startsWith("bearer ")) {
    return authorization.slice(7).trim();
  }
  return readCookie(request, SESSION_COOKIE);
}

export async function requireUser(request: Request): Promise<User> {
  const token = bearerToken(request);
  if (!token) {
    throw new AppError("Authentication required", 401, "unauthorized");
  }
  const supabase = createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_PUBLISHABLE_KEY"),
    { auth: { persistSession: false, autoRefreshToken: false } }
  );
  const { data, error } = await supabase.auth.getUser(token);
  if (error || !data.user) {
    throw new AppError("Invalid or expired session", 401, "unauthorized");
  }
  const allowed = requiredEnv("ALLOWED_USER_ID");
  if (data.user.id !== allowed) {
    throw new AppError("Forbidden", 403, "forbidden");
  }
  return data.user;
}

export function requireMutationGuard(request: Request): void {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method.toUpperCase())) return;
  const origin = request.headers.get("origin");
  const expectedOrigin = env("APP_ORIGIN");
  if (origin && expectedOrigin && origin !== expectedOrigin) {
    throw new AppError("Invalid origin", 403, "invalid_origin");
  }
  if (request.headers.get("x-app-request") !== "1") {
    throw new AppError("Missing mutation guard", 403, "csrf_guard");
  }
}

export function sessionCookie(token: string, maxAgeSeconds = 3600): string {
  return [
    `${SESSION_COOKIE}=${encodeURIComponent(token)}`,
    "Path=/",
    "HttpOnly",
    "Secure",
    "SameSite=Strict",
    `Max-Age=${maxAgeSeconds}`
  ].join("; ");
}

export function clearSessionCookie(): string {
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0`;
}

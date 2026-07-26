import type { Config } from "@netlify/functions";
import { recordEvent } from "../src/events.js";
import { finishLinkedInOAuth } from "../src/linkedin.js";
import { methodNotAllowed, requestId } from "../src/http.js";
import { enqueueJob } from "../src/queue.js";
import { redact } from "../src/redaction.js";

export default async function handler(request: Request): Promise<Response> {
  const id = requestId(request);
  if (request.method !== "GET") return methodNotAllowed(request, ["GET"], id);
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const origin = new URL(request.url).origin;
  if (!code || !state) {
    return Response.redirect(`${origin}/?error=linkedin_callback_incomplete`, 302);
  }
  try {
    await finishLinkedInOAuth(code, state);
    return Response.redirect(`${origin}/?connected=true`, 302);
  } catch (error) {
    const day = new Date().toISOString().slice(0, 10);
    await Promise.allSettled([
      recordEvent({
        subsystem: "linkedin",
        eventType: "oauth_failed",
        severity: "error",
        correlationId: id,
        message: redact(error),
        dedupeKey: `linkedin_oauth_failed:${day}`
      }),
      enqueueJob({
        type: "notify_alert",
        payload: {
          text: "Falló la conexión OAuth de LinkedIn. La publicación permanece bloqueada hasta reconectar.",
          alert_key: `linkedin_oauth_failed:${day}`
        },
        dedupeKey: `notify_alert:linkedin_oauth_failed:${day}`,
        maxAttempts: 4,
        priority: 5,
        correlationId: id
      })
    ]);
    return Response.redirect(`${origin}/?error=linkedin_connection_failed`, 302);
  }
}

export const config: Config = {
  path: "/api/auth/linkedin/callback"
};

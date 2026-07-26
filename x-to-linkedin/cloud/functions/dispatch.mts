import type { Config } from "@netlify/functions";
import { randomUUID } from "node:crypto";
import { recordFunctionUsage } from "../src/cost.js";
import { requiredEnv } from "../src/env.js";
import { json, methodNotAllowed, requestId, toErrorResponse } from "../src/http.js";
import { claimDueJobs } from "../src/queue.js";
import { secretMatches } from "../src/secrets.js";

export default async function handler(request: Request): Promise<Response> {
  const started = Date.now();
  const id = requestId(request);
  if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
  if (!secretMatches(request.headers.get("x-dispatch-secret"), "DISPATCH_SECRET")) {
    return json({ error: "unauthorized", request_id: id }, { status: 401, requestId: id });
  }
  try {
    const jobs = await claimDueJobs(`netlify-dispatch:${randomUUID()}`, 4);
    const workerUrl = new URL("/api/worker", requiredEnv("URL")).href;
    const results = await Promise.allSettled(
      jobs.map((job) =>
        fetch(workerUrl, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "x-worker-secret": requiredEnv("WORKER_SECRET"),
            "x-request-id": job.correlation_id ?? id
          },
          body: JSON.stringify({
            job_id: job.id,
            lease_token: job.lease_token
          }),
          signal: AbortSignal.timeout(8_000)
        })
      )
    );
    const accepted = results.filter(
      (result) => result.status === "fulfilled" && result.value.ok
    ).length;
    return json(
      { claimed: jobs.length, accepted, request_id: id },
      { status: 202, requestId: id }
    );
  } catch (error) {
    return toErrorResponse(error, id);
  } finally {
    await recordFunctionUsage({
      functionName: "dispatch",
      durationMs: Date.now() - started,
      correlationId: id
    }).catch(() => undefined);
  }
}

export const config: Config = {
  path: "/api/dispatch"
};

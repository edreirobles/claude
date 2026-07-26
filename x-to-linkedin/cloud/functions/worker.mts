import type { Config } from "@netlify/functions";
import { recordFunctionUsage } from "../src/cost.js";
import { db } from "../src/db.js";
import { DeferredJobError, handleDeadJob, runJob } from "../src/jobs.js";
import {
  json,
  methodNotAllowed,
  parseJson,
  requestId,
  toErrorResponse
} from "../src/http.js";
import {
  completeJob,
  deferJob,
  failJob,
  startJob,
  type JobRow
} from "../src/queue.js";
import { redact } from "../src/redaction.js";
import { secretMatches } from "../src/secrets.js";

type WorkerRequest = {
  job_id: number;
  lease_token: string;
};

export default async function handler(request: Request): Promise<Response> {
  const started = Date.now();
  const id = requestId(request);
  if (request.method !== "POST") return methodNotAllowed(request, ["POST"], id);
  if (!secretMatches(request.headers.get("x-worker-secret"), "WORKER_SECRET")) {
    return json({ error: "unauthorized", request_id: id }, { status: 401, requestId: id });
  }
  let job: JobRow | undefined;
  try {
    const body = await parseJson<WorkerRequest>(request, 8 * 1024);
    if (!Number.isSafeInteger(body.job_id) || !body.lease_token) {
      return json(
        { error: "invalid_job", request_id: id },
        { status: 400, requestId: id }
      );
    }
    const rows = await db()<JobRow[]>`
      select id, job_type, payload, attempts, max_attempts, lease_token, correlation_id
      from app.job_queue
      where id = ${body.job_id} and lease_token = ${body.lease_token}::uuid
    `;
    job = rows[0];
    if (!job || !(await startJob(job.id, job.lease_token))) {
      return json(
        { error: "lease_not_valid", request_id: id },
        { status: 409, requestId: id }
      );
    }
    const result = await runJob(job);
    await completeJob(job.id, job.lease_token, result);
    return json({ ok: true, job_id: job.id, request_id: id }, { requestId: id });
  } catch (error) {
    if (job && error instanceof DeferredJobError) {
      await deferJob(job.id, job.lease_token, error.delaySeconds, error.message);
      return json(
        { ok: true, deferred: true, job_id: job.id, request_id: id },
        { requestId: id }
      );
    }
    if (job) {
      const status = await failJob(job.id, job.lease_token, redact(error));
      if (status === "dead") await handleDeadJob(job, error);
    }
    return toErrorResponse(error, id);
  } finally {
    await recordFunctionUsage({
      functionName: "worker",
      durationMs: Date.now() - started,
      correlationId: job?.correlation_id ?? id
    }).catch(() => undefined);
  }
}

export const config: Config = {
  path: "/api/worker",
  background: true
};

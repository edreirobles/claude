import { db } from "./db.js";

export type JobRow = {
  id: number;
  job_type: string;
  payload: Record<string, unknown>;
  attempts: number;
  max_attempts: number;
  lease_token: string;
  correlation_id: string | null;
};

export async function enqueueJob(input: {
  type: string;
  runAt?: Date;
  payload?: Record<string, unknown>;
  dedupeKey: string;
  maxAttempts?: number;
  priority?: number;
  correlationId?: string;
}): Promise<number> {
  const sql = db();
  const rows = await sql<{ enqueue_job: number }[]>`
    select app.enqueue_job(
      ${input.type},
      ${input.runAt?.toISOString() ?? new Date().toISOString()}::timestamptz,
      ${sql.json((input.payload ?? {}) as never)}::jsonb,
      ${input.dedupeKey},
      ${input.maxAttempts ?? 5},
      ${input.priority ?? 100},
      ${input.correlationId ?? null}
    ) as enqueue_job
  `;
  return rows[0]!.enqueue_job;
}

export async function claimDueJobs(
  workerId: string,
  limit: number,
  leaseSeconds = 900
): Promise<JobRow[]> {
  return db()<JobRow[]>`
    select * from app.claim_due_jobs(
      ${workerId},
      ${Math.max(1, Math.min(limit, 20))},
      ${leaseSeconds}
    )
  `;
}

export async function startJob(id: number, leaseToken: string): Promise<boolean> {
  const rows = await db()<[{ start_job: boolean }]>`
    select app.start_job(${id}, ${leaseToken}::uuid) as start_job
  `;
  return rows[0]?.start_job ?? false;
}

export async function completeJob(
  id: number,
  leaseToken: string,
  result: Record<string, unknown> = {}
): Promise<void> {
  const sql = db();
  await sql`
    select app.complete_job(
      ${id},
      ${leaseToken}::uuid,
      ${sql.json(result as never)}::jsonb
    )
  `;
}

export async function failJob(
  id: number,
  leaseToken: string,
  error: string
): Promise<"retry_wait" | "dead"> {
  const rows = await db()<[{ fail_job: "retry_wait" | "dead" }]>`
    select app.fail_job(${id}, ${leaseToken}::uuid, ${error}) as fail_job
  `;
  return rows[0]?.fail_job ?? "dead";
}

export async function deferJob(
  id: number,
  leaseToken: string,
  delaySeconds: number,
  reason: string
): Promise<boolean> {
  const rows = await db()<[{ id: number }]>`
    update app.job_queue
    set status = 'retry_wait',
        run_at = now() + make_interval(secs => ${Math.max(30, delaySeconds)}),
        attempts = greatest(attempts - 1, 0),
        last_error = ${reason.slice(0, 500)},
        leased_until = null,
        lease_owner = null,
        lease_token = null
    where id = ${id}
      and lease_token = ${leaseToken}::uuid
      and status in ('claimed', 'running')
    returning id
  `;
  return Boolean(rows[0]);
}

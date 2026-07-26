import { db } from "./db.js";
import { switches } from "./env.js";

export type CostState = {
  estimatedCredits: number;
  limitCredits: number;
  remainingCredits: number;
  percentage: number;
  level: "normal" | "watch" | "conserve" | "critical" | "essential_only";
  noncriticalAllowed: boolean;
  hardLimitReached: boolean;
};

export type StorageState = {
  databaseBytes: number;
  databaseMegabytes: number;
  level: "normal" | "watch" | "critical";
};

const NETLIFY_FREE_CREDIT_LIMIT = 300;

export function costStateFromCredits(estimatedCredits: number): CostState {
  const safeCredits = Math.max(0, Number(estimatedCredits) || 0);
  const percentage = (safeCredits / NETLIFY_FREE_CREDIT_LIMIT) * 100;
  const level =
    percentage >= 90
      ? "essential_only"
      : percentage >= 85
        ? "critical"
        : percentage >= 70
          ? "conserve"
          : percentage >= 50
            ? "watch"
            : "normal";
  return {
    estimatedCredits: safeCredits,
    limitCredits: NETLIFY_FREE_CREDIT_LIMIT,
    remainingCredits: Math.max(0, NETLIFY_FREE_CREDIT_LIMIT - safeCredits),
    percentage,
    level,
    noncriticalAllowed:
      switches.noncriticalJobsEnabled() && percentage < 85,
    hardLimitReached: percentage >= 100
  };
}

export async function currentCostState(): Promise<CostState> {
  const rows = await db()<[{ credits: number }]>`
    select coalesce(sum(estimated_credits), 0)::float as credits
    from app.cost_usage
    where occurred_at >= date_trunc('month', now())
  `;
  return costStateFromCredits(Number(rows[0]?.credits ?? 0));
}

export function storageStateFromBytes(databaseBytes: number): StorageState {
  const safeBytes = Math.max(0, Number(databaseBytes) || 0);
  const databaseMegabytes = safeBytes / 1024 / 1024;
  return {
    databaseBytes: safeBytes,
    databaseMegabytes,
    level:
      databaseMegabytes >= 425
        ? "critical"
        : databaseMegabytes >= 350
          ? "watch"
          : "normal"
  };
}

export async function currentStorageState(): Promise<StorageState> {
  const rows = await db()<[{ database_bytes: number }]>`
    select pg_database_size(current_database())::bigint as database_bytes
  `;
  return storageStateFromBytes(Number(rows[0]?.database_bytes ?? 0));
}

export async function recordFunctionUsage(input: {
  functionName: string;
  durationMs: number;
  requests?: number;
  productionDeploys?: number;
  correlationId?: string;
}): Promise<void> {
  const sql = db();
  const computeGbHours = (input.durationMs / 3_600_000) * 0.5;
  const estimatedCredits =
    computeGbHours * 10 +
    ((input.requests ?? 1) / 10_000) * 2 +
    (input.productionDeploys ?? 0) * 15;
  await sql`
    insert into app.cost_usage (
      function_name, duration_ms, request_count, production_deploys,
      estimated_credits, correlation_id
    ) values (
      ${input.functionName},
      ${input.durationMs},
      ${input.requests ?? 1},
      ${input.productionDeploys ?? 0},
      ${estimatedCredits},
      ${input.correlationId ?? null}
    )
  `;
}

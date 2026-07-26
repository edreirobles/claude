import { db } from "./db.js";
import { redact } from "./redaction.js";

export async function recordEvent(input: {
  subsystem: string;
  eventType: string;
  severity?: "debug" | "info" | "warning" | "error" | "critical";
  correlationId?: string;
  entityType?: string;
  entityId?: string | number;
  message?: string;
  metadata?: Record<string, unknown>;
  dedupeKey?: string;
}): Promise<void> {
  const sql = db();
  await sql`
    insert into app.event_log (
      subsystem, event_type, severity, correlation_id, entity_type, entity_id,
      message, metadata, dedupe_key
    ) values (
      ${input.subsystem},
      ${input.eventType},
      ${input.severity ?? "info"},
      ${input.correlationId ?? null},
      ${input.entityType ?? null},
      ${input.entityId === undefined ? null : String(input.entityId)},
      ${input.message ? redact(input.message) : null},
      ${sql.json((input.metadata ?? {}) as never)},
      ${input.dedupeKey ?? null}
    )
    on conflict (dedupe_key) where dedupe_key is not null do nothing
  `;
}

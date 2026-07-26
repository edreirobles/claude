import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const migrationPath = resolve(
  process.cwd(),
  "supabase/migrations/20260726023410_initial_cloud_schema.sql"
);

describe("database invariants", () => {
  it("computes approval time in Postgres and keeps repeated approval idempotent", async () => {
    const sql = await readFile(migrationPath, "utf8");
    expect(sql).toContain("v_publish_at := v_now + interval '30 minutes'");
    expect(sql).toContain("already_processed");
    expect(sql).toContain("'publish_post:' || p_post_id::text");
  });

  it("uses private schema, durable leases and no approval expiration job", async () => {
    const sql = await readFile(migrationPath, "utf8");
    expect(sql).toContain("create schema if not exists app");
    expect(sql).toContain("for update skip locked");
    expect(sql).toContain("leased_until");
    expect(sql).not.toContain("expire_approval");
    expect(sql).toContain("revoke all on all tables in schema app from public, anon, authenticated");
  });

  it("avoids HTTP dispatch when no work is due", async () => {
    const sql = await readFile(migrationPath, "utf8");
    const functionText = sql.slice(sql.indexOf("create or replace function app.dispatch_due_jobs"));
    expect(functionText.indexOf("if v_due = 0")).toBeLessThan(
      functionText.indexOf("net.http_post")
    );
  });

  it("contains no active image generation provider", async () => {
    const files = [
      "cloud/src/editorial.ts",
      "cloud/src/radar.ts",
      "cloud/src/jobs.ts",
      "cloud/functions/api.mts"
    ];
    const code = (
      await Promise.all(files.map((file) => readFile(resolve(process.cwd(), file), "utf8")))
    ).join("\n");
    expect(code).not.toMatch(/imagegen|imagen-3|generateImage|google_api_key/i);
  });
});

import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("rollback export", () => {
  it("writes only an encrypted envelope and includes every local-compatible table", async () => {
    const source = await readFile(
      resolve(process.cwd(), "scripts/cloud/export_cloud_rollback.ts"),
      "utf8"
    );
    for (const table of [
      "settings",
      "linkedin_tokens",
      "posts",
      "x_liked_tweets",
      "linkedin_comments"
    ]) {
      expect(source).toContain(table);
    }
    expect(source).toContain("encryptSecret(plaintext)");
    expect(source).not.toMatch(/writeFile\([^,]+,\s*plaintext/);
  });
});

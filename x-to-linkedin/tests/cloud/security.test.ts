import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  assertSafeExternalUrl,
  cappedResponse,
  normalizeUrl
} from "../../cloud/src/external-url.js";
import { redact } from "../../cloud/src/redaction.js";
import { requestId } from "../../cloud/src/http.js";
import {
  approvalKeyboard,
  validTelegramSecret
} from "../../cloud/src/telegram.js";

afterEach(() => {
  delete process.env.TELEGRAM_WEBHOOK_SECRET;
});

describe("HTTP and secret security", () => {
  it("redacts credentials in headers, URLs and JSON-like text", () => {
    const value = redact(
      "Authorization: Bearer abc123 password=hello postgresql://user:pass@example.com/db"
    );
    expect(value).not.toContain("abc123");
    expect(value).not.toContain("hello");
    expect(value).not.toContain(":pass@");
    expect(redact(undefined)).toBe("undefined");
  });

  it("normalizes tracking parameters", () => {
    expect(normalizeUrl("https://www.Example.com/a/?utm_source=x&id=2#part")).toBe(
      "https://example.com/a?id=2"
    );
  });

  it("blocks local and metadata destinations", async () => {
    await expect(assertSafeExternalUrl("http://127.0.0.1/a")).rejects.toThrow();
    await expect(assertSafeExternalUrl("http://[::ffff:127.0.0.1]/a")).rejects.toThrow();
    await expect(assertSafeExternalUrl("http://metadata.google.internal/a")).rejects.toThrow();
  });

  it("enforces response size even without a content-length header", async () => {
    const oversized = new Response(
      new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array(8));
          controller.enqueue(new Uint8Array(8));
          controller.close();
        }
      })
    );
    await expect(cappedResponse(oversized, 12)).rejects.toThrow("too large");
  });

  it("validates Telegram secret and preserves post-specific buttons", () => {
    process.env.TELEGRAM_WEBHOOK_SECRET = "correct-value";
    expect(validTelegramSecret("correct-value")).toBe(true);
    expect(validTelegramSecret("wrong-value")).toBe(false);
    const keyboard = approvalKeyboard(42);
    expect(JSON.stringify(keyboard)).toContain("approve:42");
    expect(JSON.stringify(keyboard)).toContain("revise:42");
    expect(JSON.stringify(keyboard)).toContain("another:42");
    expect(JSON.stringify(keyboard)).toContain("cancel:42");
  });

  it("accepts only UUID request IDs that are safe for Postgres correlation fields", () => {
    const valid = "123e4567-e89b-42d3-a456-426614174000";
    expect(
      requestId(new Request("https://example.com", { headers: { "x-request-id": valid } }))
    ).toBe(valid);
    expect(
      requestId(
        new Request("https://example.com", {
          headers: { "x-request-id": "not-a-uuid" }
        })
      )
    ).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("does not expose local administrative endpoints in cloud", async () => {
    const api = await readFile(
      resolve(process.cwd(), "cloud/functions/api.mts"),
      "utf8"
    );
    expect(api).not.toMatch(/git-pull|pull-and-restart|\/restart/);
  });

  it("keeps generated media and a duplicate dashboard out of cloud builds", async () => {
    const buildScript = await readFile(
      resolve(process.cwd(), "cloud/scripts/build.mjs"),
      "utf8"
    );
    expect(buildScript).not.toContain('cp(staticDir, resolve(dist, "static")');
    expect(buildScript).toContain('resolve(staticDir, "css")');
    expect(buildScript).toContain('resolve(staticDir, "js")');
  });
});

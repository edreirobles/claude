import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { buildPostPayload } from "../../cloud/src/linkedin.js";

describe("LinkedIn versioned APIs", () => {
  it("builds the current Posts API shape for text and source media", () => {
    const text = buildPostPayload({
      personUrn: "person-1",
      text: "Una publicación"
    });
    expect(text).toMatchObject({
      author: "urn:li:person:person-1",
      commentary: "Una publicación",
      visibility: "PUBLIC",
      lifecycleState: "PUBLISHED"
    });
    expect(text).not.toHaveProperty("specificContent");

    const media = buildPostPayload({
      personUrn: "urn:li:person:person-1",
      text: "Un documento",
      assetUrn: "urn:li:document:doc-1",
      documentTitle: "Paper"
    });
    expect(media).toHaveProperty("content.media.id", "urn:li:document:doc-1");
    expect(media).toHaveProperty("content.media.title", "Paper");
  });

  it("does not call the replaced UGC Posts or Assets endpoints", async () => {
    const source = await readFile(
      resolve(process.cwd(), "cloud/src/linkedin.ts"),
      "utf8"
    );
    expect(source).not.toContain("/ugcPosts");
    expect(source).not.toContain("/assets?action=registerUpload");
    expect(source).toContain("/posts");
    expect(source).toContain("?action=initializeUpload");
  });
});

import { describe, expect, it } from "vitest";
import {
  engagementScore,
  hasStrongAnchor,
  sanitizeLinkedInCopy
} from "../../cloud/src/editorial.js";

describe("editorial rules", () => {
  it("removes markdown bullets and asterisks", () => {
    const value = sanitizeLinkedInCopy(
      "**Una herramienta concreta para docentes**\n\n- Primer punto\n* Segundo punto"
    );
    expect(value).toBe("Una herramienta concreta para docentes\n\nPrimer punto\nSegundo punto");
    expect(value).not.toMatch(/[*]/);
  });

  it("requires a concrete anchor when there is no media", () => {
    expect(hasStrongAnchor("Este paper compara 12 prácticas de evaluación con IA")).toBe(true);
    expect(hasStrongAnchor("Hoy quiero compartir una reflexión")).toBe(false);
  });

  it("weights comments and shares above likes", () => {
    const base = {
      id: 1,
      source: "manual",
      linkedin_text: "x",
      published_at: null,
      li_impressions: 1000,
      li_clicks: 0
    };
    const likes = engagementScore({
      ...base,
      li_likes: 5,
      li_comments: 0,
      li_shares: 0
    });
    const conversation = engagementScore({
      ...base,
      li_likes: 0,
      li_comments: 2,
      li_shares: 1
    });
    expect(conversation).toBeGreaterThan(likes);
  });
});

import { describe, expect, it } from "vitest";
import {
  costStateFromCredits,
  storageStateFromBytes
} from "../../cloud/src/cost.js";

describe("zero-cost guardrails", () => {
  it("degrades noncritical work at the documented thresholds", () => {
    expect(costStateFromCredits(149).level).toBe("normal");
    expect(costStateFromCredits(150).level).toBe("watch");
    expect(costStateFromCredits(210).level).toBe("conserve");
    expect(costStateFromCredits(255).noncriticalAllowed).toBe(false);
    expect(costStateFromCredits(270).level).toBe("essential_only");
    expect(costStateFromCredits(300).hardLimitReached).toBe(true);
  });

  it("classifies Supabase database storage without rounding away thresholds", () => {
    expect(storageStateFromBytes(349 * 1024 * 1024).level).toBe("normal");
    expect(storageStateFromBytes(350 * 1024 * 1024).level).toBe("watch");
    expect(storageStateFromBytes(425 * 1024 * 1024).level).toBe("critical");
  });
});

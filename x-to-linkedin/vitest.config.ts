import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["tests/cloud/**/*.test.ts"],
    environment: "node",
    coverage: {
      enabled: false
    }
  }
});

import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@shared": path.resolve(__dirname, "shared"),
      "@": path.resolve(__dirname, "client/src"),
    },
  },
  test: {
    include: [
      "server/__tests__/**/*.test.ts",
      "tests/integration/**/*.test.ts",
      "tests/fixtures/**/*.test.ts",
      "tests/contract/**/*.test.ts",
      "tests/tools/**/*.test.ts",
    ],
    environment: "node",
    globals: false,
  },
});

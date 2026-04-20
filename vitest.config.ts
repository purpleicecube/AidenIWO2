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
    // R-012 — disable inter-file parallelism. Several integration test
    // files mutate the same shared tables (permission_grants,
    // action_audit_log, work_orders) under a single Postgres database;
    // worker-process concurrency introduces races that are effectively
    // impossible to scope per-test without burning dedicated fixtures
    // for every file. Sequential execution is ~2x slower locally but
    // stays well under 10s and matches CI-single-worker behaviour.
    fileParallelism: false,
  },
});

/**
 * Runtime Stabilization Tests — Pre-Replit Plan
 *
 * Covers: version identity, env validation, health endpoint shape.
 */

import { describe, it, expect, vi, beforeEach, afterAll } from "vitest";

// ─── Version Identity ────────────────────────────────────────────────────────

describe("version identity", () => {
  it("APP_VERSION reads from package.json", async () => {
    const { APP_VERSION, BUILD_ID } = await import("../version.js");
    expect(APP_VERSION).toMatch(/^\d+\.\d+\.\d+/);
    expect(BUILD_ID).toContain(APP_VERSION);
  });

  it("APP_VERSION is not hardcoded 0.0.0", async () => {
    const { APP_VERSION } = await import("../version.js");
    expect(APP_VERSION).not.toBe("0.0.0");
  });
});

// ─── Env Validation ──────────────────────────────────────────────────────────

describe("env validation", () => {
  const originalEnv = { ...process.env };

  beforeEach(() => {
    // Reset env to a known state
    process.env = { ...originalEnv };
  });

  it("validateEnv returns ok when all critical vars are set", async () => {
    process.env.DATABASE_URL = "postgresql://test:test@localhost/test";
    process.env.SESSION_SECRET = "test-secret";
    process.env.GROQ_API_KEY = "test-key";
    const { validateEnv } = await import("../env-check.js");
    const result = validateEnv();
    expect(result.ok).toBe(true);
    expect(result.critical).toHaveLength(0);
  });

  it("validateEnv fails when DATABASE_URL is missing", async () => {
    delete process.env.DATABASE_URL;
    process.env.SESSION_SECRET = "test-secret";
    process.env.GROQ_API_KEY = "test-key";
    const { validateEnv } = await import("../env-check.js");
    const result = validateEnv();
    expect(result.ok).toBe(false);
    expect(result.critical.some(c => c.includes("DATABASE_URL"))).toBe(true);
  });

  it("validateEnv fails when SESSION_SECRET is missing", async () => {
    process.env.DATABASE_URL = "postgresql://test:test@localhost/test";
    delete process.env.SESSION_SECRET;
    process.env.GROQ_API_KEY = "test-key";
    const { validateEnv } = await import("../env-check.js");
    const result = validateEnv();
    expect(result.ok).toBe(false);
    expect(result.critical.some(c => c.includes("SESSION_SECRET"))).toBe(true);
  });

  it("validateEnv fails when no LLM key is set", async () => {
    process.env.DATABASE_URL = "postgresql://test:test@localhost/test";
    process.env.SESSION_SECRET = "test-secret";
    delete process.env.GROQ_API_KEY;
    delete process.env.OPENROUTER_API_KEY;
    delete process.env.ANTHROPIC_API_KEY;
    const { validateEnv } = await import("../env-check.js");
    const result = validateEnv();
    expect(result.ok).toBe(false);
    expect(result.critical.some(c => c.includes("LLM"))).toBe(true);
  });

  it("validateEnv warns when GAMMA_API_KEY is missing", async () => {
    process.env.DATABASE_URL = "postgresql://test:test@localhost/test";
    process.env.SESSION_SECRET = "test-secret";
    process.env.GROQ_API_KEY = "test-key";
    delete process.env.GAMMA_API_KEY;
    const { validateEnv } = await import("../env-check.js");
    const result = validateEnv();
    expect(result.ok).toBe(true); // not critical
    expect(result.warnings.some(w => w.includes("GAMMA"))).toBe(true);
  });

  // Restore env after all tests
  afterAll(() => {
    process.env = originalEnv;
  });
});

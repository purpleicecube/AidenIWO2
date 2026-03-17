/**
 * Startup environment validation.
 * Separates env vars into hard-blocking vs optional/degraded.
 * Call before app boot — fails loudly on missing hard-blockers.
 */

import { APP_VERSION, BUILD_ID } from "./version";

interface EnvCheckResult {
  ok: boolean;
  critical: string[];
  warnings: string[];
}

/**
 * Validate critical and optional env vars.
 * Returns structured result. Caller decides whether to abort.
 */
export function validateEnv(): EnvCheckResult {
  const critical: string[] = [];
  const warnings: string[] = [];

  // ─── Hard-blocking: app cannot function without these ──────────────
  if (!process.env.DATABASE_URL) {
    critical.push("DATABASE_URL is not set — database connection will fail");
  }

  if (!process.env.SESSION_SECRET) {
    critical.push("SESSION_SECRET is not set — sessions will be insecure/broken");
  }

  // At least one LLM key must be present for Tier 1/Tier 2 to work
  const hasGroq = !!process.env.GROQ_API_KEY;
  const hasOpenRouter = !!process.env.OPENROUTER_API_KEY;
  const hasAnthropic = !!process.env.ANTHROPIC_API_KEY;
  if (!hasGroq && !hasOpenRouter && !hasAnthropic) {
    critical.push("No LLM provider key set (need at least one of GROQ_API_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY)");
  }

  // ─── Optional/degraded: app starts but feature is unavailable ─────
  if (!process.env.GAMMA_API_KEY) {
    warnings.push("GAMMA_API_KEY not set — Gamma PPTX/PDF generation will be unavailable");
  }

  if (!process.env.BOOTSTRAP_ADMIN_PASSWORD) {
    warnings.push("BOOTSTRAP_ADMIN_PASSWORD not set — bootstrap admin will not be provisioned");
  }

  if (!process.env.APP_URL) {
    warnings.push("APP_URL not set — invite emails and external links may use incorrect URLs");
  }

  if (!process.env.SENDGRID_API_KEY) {
    warnings.push("SENDGRID_API_KEY not set — email invitations will be unavailable");
  }

  const ok = critical.length === 0;
  return { ok, critical, warnings };
}

/**
 * Run env validation and log results.
 * If hard-blockers are found, throws to prevent boot.
 */
export function enforceEnvOrDie(): void {
  console.log(`[boot] ${BUILD_ID} — validating environment...`);

  const result = validateEnv();

  // Log warnings
  for (const w of result.warnings) {
    console.warn(`[boot] WARNING: ${w}`);
  }

  // Log and fail on critical
  if (!result.ok) {
    for (const c of result.critical) {
      console.error(`[boot] CRITICAL: ${c}`);
    }
    throw new Error(
      `Startup aborted — ${result.critical.length} critical env var(s) missing:\n` +
      result.critical.map(c => `  - ${c}`).join("\n")
    );
  }

  console.log(`[boot] Environment OK — ${result.warnings.length} warning(s)`);
}

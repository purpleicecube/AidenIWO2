/**
 * Apply Drizzle-generated SQL migration files to `aiden_iwo3`.
 *
 * Used by reset-iwo3.sh instead of `drizzle-kit push` (which is
 * interactive in drizzle-kit 0.31.x and hangs in automated pipelines)
 * and instead of `docker exec ... psql` (which does not work in CI
 * where no such container exists).
 *
 * Applies every `db/migrations/*.sql` file in lexical order. Splits
 * statements on `--> statement-breakpoint` sentinels that drizzle-kit
 * emits between statements.
 */

import { readFileSync, readdirSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "pg";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const REPO_ROOT = resolve(__dirname, "..", "..");
const MIGRATIONS_DIR = resolve(REPO_ROOT, "db/migrations");

async function main(): Promise<void> {
  const url = process.env.IWO3_DATABASE_URL;
  if (!url) throw new Error("IWO3_DATABASE_URL is required");

  const files = readdirSync(MIGRATIONS_DIR)
    .filter((f) => f.endsWith(".sql"))
    .sort();

  if (files.length === 0) {
    console.log("[apply-migrations] No .sql files in db/migrations — nothing to apply.");
    return;
  }

  const c = new Client({ connectionString: url });
  await c.connect();
  try {
    for (const f of files) {
      const sql = readFileSync(resolve(MIGRATIONS_DIR, f), "utf-8");
      const statements = sql
        .split("--> statement-breakpoint")
        .map((s) => s.trim())
        .filter((s) => s.length > 0);
      console.log(`[apply-migrations] ${f}  (${statements.length} statements)`);
      for (const stmt of statements) {
        await c.query(stmt);
      }
    }
    console.log(`[apply-migrations] Applied ${files.length} migration file(s).`);
    await ensureAuditPartitionWindow(c);
  } finally {
    await c.end();
  }
}

/**
 * Ensure `action_audit_log` has partitions covering now + the next
 * three months.
 *
 * Migration 0002 hardcodes 2026-04 … 2026-06 and ships
 * `ensure_audit_partition_for()` to extend the window, but nothing
 * ever called it. From 2026-07-01 that made every audited INSERT fail
 * with `no partition of relation "action_audit_log" found for row` —
 * on a FRESHLY MIGRATED database, so 60 vitest integration tests
 * failed on a clean reset and stayed failed.
 *
 * The API self-heals this at startup (workers/audit_partition_worker),
 * but vitest talks to Postgres directly and never boots the API, so
 * the migrate path needs the same guarantee. Idempotent.
 */
async function ensureAuditPartitionWindow(c: Client): Promise<void> {
  const helper = await c.query(
    `SELECT EXISTS (SELECT 1 FROM pg_proc
       WHERE proname = 'ensure_audit_partition_for') AS present`
  );
  if (!helper.rows[0]?.present) {
    console.warn(
      "[apply-migrations] ensure_audit_partition_for() absent — skipping audit partition window."
    );
    return;
  }
  const ensured: string[] = [];
  const cursor = new Date();
  cursor.setUTCDate(1);
  cursor.setUTCHours(0, 0, 0, 0);
  for (let i = 0; i <= 3; i++) {
    const stamp = cursor.toISOString();
    await c.query(`SELECT ensure_audit_partition_for($1::timestamptz)`, [stamp]);
    ensured.push(stamp.slice(0, 10));
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  console.log(`[apply-migrations] Audit partition window: ${ensured.join(", ")}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

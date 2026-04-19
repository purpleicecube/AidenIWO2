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
  } finally {
    await c.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

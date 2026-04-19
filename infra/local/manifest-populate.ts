/**
 * Populates `migration_source_manifest` from an explicit registry.
 *
 * Rules (ADR-008 v0.1.1 per CODEX revision):
 *   - Every IWO3 table must be explicitly registered below.
 *   - Unknown public.* tables are NOT auto-classified. The
 *     `tests/integration/migration-ownership.test.ts` suite fails when
 *     it finds a table in the database that has no manifest row.
 *   - `source` values:
 *       iwo3_native   — table introduced natively for IWO3
 *                       (Loop 1 foundation tables fall here)
 *       iwo2_parity   — table mirrored into IWO3 from IWO2 schema
 *                       (reserved for Loop 2+ when actual IWO2 schema
 *                        is brought forward)
 *   - `owned_by` values:
 *       drizzle       — migration owned by Drizzle (schema lives in
 *                       db/schema/*.ts, SQL in db/migrations/*.sql)
 *       alembic       — migration owned by Alembic (schema lives in
 *                       apps/api-fastapi/alembic/versions/)
 */

import { Pool } from "pg";

interface ManifestEntry {
  name: string;
  source: "iwo2_parity" | "iwo3_native";
  sourceVersion: string;
  ownedBy: "drizzle" | "alembic";
  notes?: string;
}

const LOOP_1_VERSION = "iwo3@v0.1.0-loop1";

const KNOWN_TABLES: ManifestEntry[] = [
  { name: "clients",                    source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — tenant anchor" },
  { name: "users",                      source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — identity anchor" },
  { name: "client_memberships",         source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — tenant/role link" },
  { name: "template_profiles",          source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — render template anchor" },
  { name: "migration_source_manifest",  source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — manifest itself" },
];

// Tables that exist in the database but are deliberately NOT tracked
// in the manifest (alembic's internal bookkeeping).
const IGNORED_TABLES = new Set<string>(["alembic_version"]);

async function main(): Promise<void> {
  const url = process.env.IWO3_DATABASE_URL;
  if (!url) throw new Error("IWO3_DATABASE_URL is required");
  const pool = new Pool({ connectionString: url });
  try {
    for (const t of KNOWN_TABLES) {
      await pool.query(
        `INSERT INTO migration_source_manifest
           (table_name, source, source_version, owned_by, notes)
         VALUES ($1, $2, $3, $4, $5)
         ON CONFLICT (table_name) DO UPDATE SET
           source = EXCLUDED.source,
           source_version = EXCLUDED.source_version,
           owned_by = EXCLUDED.owned_by,
           notes = EXCLUDED.notes`,
        [t.name, t.source, t.sourceVersion, t.ownedBy, t.notes ?? null]
      );
    }

    // Report drift — any public.* table not registered.
    // This is informational; the regression test is authoritative.
    const { rows } = await pool.query<{ table_name: string }>(
      `SELECT table_name FROM information_schema.tables
       WHERE table_schema = 'public'`
    );
    const known = new Set(KNOWN_TABLES.map((t) => t.name));
    const drift: string[] = [];
    for (const r of rows) {
      if (known.has(r.table_name)) continue;
      if (IGNORED_TABLES.has(r.table_name)) continue;
      drift.push(r.table_name);
    }
    if (drift.length > 0) {
      console.warn(
        `[manifest-populate] WARNING: unregistered tables found: ${drift.join(", ")}.\n` +
          `  Add them to KNOWN_TABLES in infra/local/manifest-populate.ts or remove them.`
      );
    }

    console.log(
      `[manifest-populate] Registered ${KNOWN_TABLES.length} tables. ` +
        `Drift: ${drift.length}.`
    );
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

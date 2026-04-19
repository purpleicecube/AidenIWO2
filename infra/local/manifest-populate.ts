/**
 * Populates `migration_source_manifest` with one row per table that currently
 * exists in the IWO3 database. Run after Drizzle push + Alembic upgrade.
 *
 * Loop 1 convention:
 *   - Loop 1 narrow schema (clients, users, client_memberships,
 *     template_profiles, migration_source_manifest) = iwo2_parity / drizzle
 *     (they are the tenant/RBAC anchor that IWO3 inherits forward).
 *   - Later IWO3-native tables created by Alembic (output_packages,
 *     render_jobs, channel_events, etc.) = iwo3_native / alembic.
 */

import { Pool } from "pg";

const IWO2_BRANCH_POINT = "iwo2@1535c2f";
const IWO3_VERSION = "iwo3@v0.1.0-loop1";

const LOOP_1_DRIZZLE_TABLES: Array<{ name: string; notes?: string }> = [
  { name: "clients" },
  { name: "users" },
  { name: "client_memberships" },
  { name: "template_profiles" },
  { name: "migration_source_manifest" },
];

async function main(): Promise<void> {
  const url = process.env.IWO3_DATABASE_URL;
  if (!url) throw new Error("IWO3_DATABASE_URL is required");
  const pool = new Pool({ connectionString: url });
  try {
    const existing = await pool.query<{ table_name: string }>(`
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = 'public'
    `);
    const names = new Set(existing.rows.map((r) => r.table_name));

    for (const t of LOOP_1_DRIZZLE_TABLES) {
      if (!names.has(t.name)) continue;
      await pool.query(
        `INSERT INTO migration_source_manifest
           (table_name, source, source_version, owned_by, notes)
         VALUES ($1, 'iwo2_parity', $2, 'drizzle', $3)
         ON CONFLICT (table_name) DO UPDATE SET
           source = EXCLUDED.source,
           source_version = EXCLUDED.source_version,
           owned_by = EXCLUDED.owned_by,
           notes = EXCLUDED.notes`,
        [t.name, IWO2_BRANCH_POINT, t.notes ?? null]
      );
    }

    // Any additional table created by Alembic goes in as iwo3_native/alembic.
    for (const name of names) {
      if (LOOP_1_DRIZZLE_TABLES.some((t) => t.name === name)) continue;
      // Skip Alembic's own bookkeeping table; it is not "owned" in our sense.
      if (name === "alembic_version") continue;
      await pool.query(
        `INSERT INTO migration_source_manifest
           (table_name, source, source_version, owned_by)
         VALUES ($1, 'iwo3_native', $2, 'alembic')
         ON CONFLICT (table_name) DO UPDATE SET
           source = EXCLUDED.source,
           source_version = EXCLUDED.source_version,
           owned_by = EXCLUDED.owned_by`,
        [name, IWO3_VERSION]
      );
    }

    console.log(`[manifest-populate] Manifest rows up to date.`);
  } finally {
    await pool.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

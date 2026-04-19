import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

describeIwo3("Loop 1 — migration ownership invariant (ADR-008)", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("every public table (except alembic_version) has a manifest row", async () => {
    const { rows: tables } = await pool.query<{ table_name: string }>(
      `SELECT table_name FROM information_schema.tables WHERE table_schema='public'`
    );
    const { rows: manifest } = await pool.query<{ table_name: string }>(
      `SELECT table_name FROM migration_source_manifest`
    );
    const manifestNames = new Set(manifest.map((r) => r.table_name));
    const missing: string[] = [];
    for (const t of tables) {
      if (t.table_name === "alembic_version") continue;
      if (!manifestNames.has(t.table_name)) missing.push(t.table_name);
    }
    expect(missing).toEqual([]);
  });

  it("no table is owned by both drizzle and alembic", async () => {
    const { rows } = await pool.query<{ table_name: string }>(
      `SELECT table_name
       FROM migration_source_manifest
       GROUP BY table_name
       HAVING count(DISTINCT owned_by) > 1`
    );
    expect(rows).toHaveLength(0);
  });

  it("Loop 1 foundation schema is marked iwo3_native / drizzle (ADR-008 v0.1.1)", async () => {
    const expected = [
      "clients",
      "users",
      "client_memberships",
      "template_profiles",
      "migration_source_manifest",
    ];
    const { rows } = await pool.query<{
      table_name: string;
      source: string;
      owned_by: string;
    }>(
      `SELECT table_name, source, owned_by
       FROM migration_source_manifest
       WHERE table_name = ANY($1)`,
      [expected]
    );
    for (const r of rows) {
      expect(r.source).toBe("iwo3_native");
      expect(r.owned_by).toBe("drizzle");
    }
    expect(rows).toHaveLength(expected.length);
  });

  it("no unregistered public table exists (CODEX ADR-008 revision)", async () => {
    const { rows: tables } = await pool.query<{ table_name: string }>(
      `SELECT table_name FROM information_schema.tables
       WHERE table_schema = 'public'`
    );
    const { rows: manifest } = await pool.query<{ table_name: string }>(
      `SELECT table_name FROM migration_source_manifest`
    );
    const registered = new Set(manifest.map((r) => r.table_name));
    const ignored = new Set(["alembic_version"]);
    const unregistered = tables
      .map((r) => r.table_name)
      .filter((name) => !registered.has(name) && !ignored.has(name));
    expect(unregistered).toEqual([]);
  });
});

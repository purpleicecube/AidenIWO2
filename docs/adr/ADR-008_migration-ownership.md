# ADR-008 — Migration ownership: Drizzle vs Alembic boundary

Date: 2026-04-19
Status: Accepted (v0.1.1 — manifest semantics tightened per CODEX Loop 1 Phase 1 review)
Deciders: AI, DR, MD (per `IWO3_LOOP_1_PLAN_v0.1.0.md` §4.4 and CODEX revision #2), with CODEX v0.1.1 revision

## Context

IWO3 is a hybrid codebase:

- **TS/Drizzle** lane — carries IWO2 lineage, starting with the Loop 1 narrow durable schema (`clients`, `users`, `client_memberships`, `template_profiles`, `migration_source_manifest`). Mirrors IWO2 parity tables forward as the strangler proceeds.
- **Python/Alembic** lane — carries new IWO3-native tables introduced for FastAPI/render/adapter/channel services (output_packages, render_jobs, channel_events, etc.), starting in Loop 3.

Both lanes connect to the same IWO3 Postgres database (`aiden_iwo3` on port 5434). Without a boundary, the two migration tools can race on schema changes, produce conflicting history, or silently overwrite each other's work.

An earlier proposal suggested a `source_version` column on every table to disambiguate. **Rejected**: polluting every table with a provenance column is noisy and out of band. A dedicated provenance table is cleaner.

## Decision

1. **Drizzle owns** schema for IWO2-parity tables.
2. **Alembic owns** schema for IWO3-native tables.
3. Neither tool writes tables owned by the other. DR enforces at PR review.
4. A `migration_source_manifest` table records per-table lineage. Every migration (Drizzle or Alembic) that creates, renames, or drops a table also writes a row.

### `migration_source_manifest` schema

```text
table_name        varchar(128) PK
source            enum: iwo2_parity | iwo3_native
source_version    varchar(64)        e.g. 'iwo2@1535c2f' or 'iwo3@v0.1.0-loop1'
owned_by          enum: drizzle | alembic
introduced_at     timestamptz
notes             text nullable
```

See `db/schema/migration_source_manifest.ts`.

### Semantic definitions (tightened per CODEX v0.1.1 revision)

- **`source = iwo3_native`** — table introduced natively for IWO3. Covers all Loop 1 foundation tables (`clients`, `users`, `client_memberships`, `template_profiles`, `migration_source_manifest`) and any new table created as part of IWO3 feature work.
- **`source = iwo2_parity`** — reserved for tables brought forward from the IWO2 schema in mirrored shape (Loop 2+). The original proposal classified Loop 1 foundation tables as `iwo2_parity` because they carry IWO2 lineage; this was wrong — the tables did not exist in IWO2 shape and reserving `iwo2_parity` for actual mirroring is cleaner.
- **`owned_by`** is independent of `source`. An IWO3-native table can be owned by Drizzle (current Loop 1 case) or by Alembic (Loop 3+ render/adapter/channel tables).

### Enforcement

- `infra/local/manifest-populate.ts` registers tables from an **explicit `KNOWN_TABLES` list**. Unknown tables are NOT auto-classified — they remain absent from the manifest.
- `tests/integration/migration-ownership.test.ts` asserts:
  1. Every `public.*` table (except Alembic's own `alembic_version`) has a manifest row. A new table that lands in schema but is not added to `KNOWN_TABLES` fails this test.
  2. No table is owned by both Drizzle and Alembic.
  3. The Loop 1 foundation tables are specifically marked `iwo3_native / drizzle`.
  4. No unregistered public table exists.

### Adding a new table

When a migration introduces a new table:

1. Add the Drizzle or Alembic schema/migration as usual.
2. Add a row to `KNOWN_TABLES` in `infra/local/manifest-populate.ts` with the correct `source` / `owned_by` classification.
3. `reset-iwo3.sh` re-runs the populate step; the ownership test will pass because the table is now registered.
4. If step 2 is skipped, the ownership test fails with `unregistered public table exists`. That is the intended drift-detection signal.

## Rationale

- Clear ownership prevents silent migration conflicts.
- Manifest is queryable, auditable, and cheap to regenerate.
- Avoids polluting application tables with provenance metadata.
- Regression test catches drift at PR time.

## Alternatives considered

- **Single migration tool (Drizzle only, or Alembic only).** Forces either a Python rewrite (rejected as big-bang per CODEX §2) or losing Pydantic/FastAPI ergonomics on the Python side.
- **Per-table `source_version` column.** Rejected — noisy, not auditable, hard to regenerate.
- **Separate databases.** Rejected — destroys the ability to join across IWO2-parity and IWO3-native tables, which is needed for tenant-scoped queries.

## Consequences

- Loop 1 manifest-populate script and test exist.
- Loop 3 (WO/WF + output adapter) is the first loop where Alembic writes a real table. At that point the `iwo3_native` branch of the manifest is exercised.
- If IWO2-parity later needs to move a table from Drizzle to Alembic (or vice versa) the migration must: drop the row from the manifest under the old owner, add a new row under the new owner, and update the schema file in the new tool. Covered by a future ADR when it happens.

## Revisit triggers

- A single-tool approach becomes viable (e.g., Drizzle adds native Python bindings — unlikely).
- Migration conflicts recur despite this discipline.

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
const LOOP_2_VERSION = "iwo3@v0.2.0-loop2";
const LOOP_3_VERSION = "iwo3@v0.3.0-loop3";
const LOOP_4_VERSION = "iwo3@v0.4.0-loop4";
const LOOP_9_VERSION = "iwo3@v0.9.0-loop9";
const ALPHA_VERSION = "iwo3@v0.10.0-alpha";
const PRE_BETA_DELTA_VERSION = "iwo3@v0.11.0-pre-beta-delta";
const BETA_1_VERSION = "iwo3@v0.12.0-beta-1";
const BETA_2_PHASE_0_3_VERSION = "iwo3@v0.13.0-beta-2-phase-0.3";
const LOOP_ETA_VERSION = "iwo3@v0.14.0-loop-eta";
const MEGALOOP_THETA_VERSION = "iwo3@v0.15.0-loop-theta";

const KNOWN_TABLES: ManifestEntry[] = [
  // Loop 1 — foundation
  { name: "clients",                    source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — tenant anchor" },
  { name: "users",                      source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — identity anchor" },
  { name: "client_memberships",         source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — tenant/role link" },
  { name: "template_profiles",          source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — render template anchor" },
  { name: "migration_source_manifest",  source: "iwo3_native", sourceVersion: LOOP_1_VERSION, ownedBy: "drizzle", notes: "Loop 1 foundation — manifest itself" },

  // Loop 2 — multi-client data + prompt + repository foundation
  { name: "prompt_profiles",            source: "iwo3_native", sourceVersion: LOOP_2_VERSION, ownedBy: "drizzle", notes: "Loop 2 — per-client prompt profile" },
  { name: "prompt_profile_versions",    source: "iwo3_native", sourceVersion: LOOP_2_VERSION, ownedBy: "drizzle", notes: "Loop 2 — versioned prompt constraints" },
  { name: "prompt_rendered_snapshots",  source: "iwo3_native", sourceVersion: LOOP_2_VERSION, ownedBy: "drizzle", notes: "Loop 2 — execution-time rendered prompt provenance" },
  { name: "repository_bindings",        source: "iwo3_native", sourceVersion: LOOP_2_VERSION, ownedBy: "drizzle", notes: "Loop 2 — client-scoped read connectors" },
  { name: "data_source_bindings",       source: "iwo3_native", sourceVersion: LOOP_2_VERSION, ownedBy: "drizzle", notes: "Loop 2 — client-scoped structured data sources" },
  { name: "artifacts",                  source: "iwo3_native", sourceVersion: LOOP_2_VERSION, ownedBy: "drizzle", notes: "Loop 2 — tenant-scoped artifact storage (see ADR-009)" },
  { name: "action_audit_log",           source: "iwo3_native", sourceVersion: LOOP_2_VERSION, ownedBy: "drizzle", notes: "Loop 2 — privileged-action audit log (partitioned per ADR-010 Phase 1.5)" },

  // Loop 3 Phase 1 — WO / WF / execution cycles
  { name: "work_orders",                source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 — one-time execution (ADR-011)" },
  { name: "workflows",                  source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 — repeatable pipeline container (ADR-011)" },
  { name: "workflow_templates",         source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 — versioned template recipe (ADR-011)" },
  { name: "workflow_template_steps",    source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 — ordered steps within a template version (ADR-011)" },
  { name: "workflow_executions",        source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 — running instance of a template version (ADR-011)" },
  { name: "workflow_step_runs",         source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 — per-step run within an execution (ADR-011)" },
  { name: "execution_cycles",           source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 — retry/reopen attempt lineage (ADR-011)" },

  // Loop 3 Phase 2 — output packages + adapter registry + handoffs
  { name: "adapter_catalog",            source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — global adapter kind catalog (ADR-012)" },
  { name: "adapter_actions",            source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — actions each adapter supports (ADR-012)" },
  { name: "client_adapter_configs",     source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — per-tenant adapter enable/config (ADR-012)" },
  { name: "adapter_action_policies",    source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — per-tenant per-action approval gate (ADR-012)" },
  { name: "adapter_credentials",        source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — per-tenant credential reference (never raw secrets) (ADR-012)" },
  { name: "output_packages",            source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — typed output envelope (ADR-012)" },
  { name: "output_handoffs",            source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — 13-field adapter handoff provenance + candidate shape (ADR-012)" },
  { name: "external_execution_results", source: "iwo3_native", sourceVersion: LOOP_3_VERSION, ownedBy: "drizzle", notes: "Loop 3 Phase 2 — result payload from external adapter target (ADR-012)" },

  // Loop 4 Phase 1 — permission vocabulary + role mapping + per-user grants
  { name: "permissions",                source: "iwo3_native", sourceVersion: LOOP_4_VERSION, ownedBy: "drizzle", notes: "Loop 4 Phase 1 — locked-upfront permission vocabulary (ADR-014)" },
  { name: "role_permissions",           source: "iwo3_native", sourceVersion: LOOP_4_VERSION, ownedBy: "drizzle", notes: "Loop 4 Phase 1 — six-role default permission mapping (ADR-014)" },
  { name: "permission_grants",          source: "iwo3_native", sourceVersion: LOOP_4_VERSION, ownedBy: "drizzle", notes: "Loop 4 Phase 1 — per-user (user,client) allow/deny override (ADR-014)" },

  // Loop 9 Phase 9.3 — LLM Foundation
  { name: "llm_configs",                source: "iwo3_native", sourceVersion: LOOP_9_VERSION, ownedBy: "drizzle", notes: "Loop 9 Phase 9.3 — per-tenant per-role LLM provider/model/credential binding (ADR-021)" },

  // MegaLoop Alpha α.5 — channel layer (Telegram-first)
  { name: "channel_identities",         source: "iwo3_native", sourceVersion: ALPHA_VERSION, ownedBy: "drizzle", notes: "MegaLoop Alpha α.5 — chat_id ↔ user_id ↔ client_id binding via /start auth-code flow" },
  { name: "channel_auth_codes",         source: "iwo3_native", sourceVersion: ALPHA_VERSION, ownedBy: "drizzle", notes: "MegaLoop Alpha α.5 — one-time codes consumed by channel adapter to bind external principals" },
  { name: "channel_messages",           source: "iwo3_native", sourceVersion: ALPHA_VERSION, ownedBy: "drizzle", notes: "MegaLoop Alpha α.5 — inbound + outbound channel message log (outbox = pending outbound rows)" },

  // Pre-Beta Loop δ.1 — Workspace folder tree (artifacts table extended in place)
  { name: "workspace_folders",          source: "iwo3_native", sourceVersion: PRE_BETA_DELTA_VERSION, ownedBy: "drizzle", notes: "Pre-Beta Loop δ.1 — per-tenant workspace folder tree; files live in artifacts.workspace_folder_id" },

  // MegaLoop Beta-1 ε.1 — operator-facing cross-session chat persistence (architect Q7 lock)
  { name: "chat_sessions",              source: "iwo3_native", sourceVersion: BETA_1_VERSION, ownedBy: "drizzle", notes: "MegaLoop Beta-1 ε.1 — per-(operator, tenant) chat session row carrying message history + recent-context JSONB" },

  // Beta-2 phase 0.3 — versioned llm_configs history (CODEX universal-slice Phase 1)
  { name: "llm_config_versions",        source: "iwo3_native", sourceVersion: BETA_2_PHASE_0_3_VERSION, ownedBy: "drizzle", notes: "Beta-2 phase 0.3.1 — full-row snapshot per llm_configs mutation; rollback = pick prior + write new mutation; immutable (iwo3_app SELECT+INSERT only)" },

  // Loop Eta phase 0 — global tool catalog + per-(tenant, llm_config) tool assignments
  { name: "tool_catalog",               source: "iwo3_native", sourceVersion: LOOP_ETA_VERSION, ownedBy: "drizzle", notes: "Loop Eta phase 0 — tenant-agnostic tool registry; metadata + runtime_status only, executable handlers live in apps/api-fastapi/runtime/aiden_tools.py" },
  { name: "sub_agent_tools",            source: "iwo3_native", sourceVersion: LOOP_ETA_VERSION, ownedBy: "drizzle", notes: "Loop Eta phase 0 — per-(client, llm_config, tool_key) assignment row; FORCE RLS; soft-revoke via enabled=false" },

  // MegaLoop Theta — Tools Locker discovery metadata (UI surface deferred)
  { name: "tool_tags",                  source: "iwo3_native", sourceVersion: MEGALOOP_THETA_VERSION, ownedBy: "drizzle", notes: "MegaLoop Theta — flat tag dictionary for the Tools Locker; tag CRUD UI deferred per scope §Out-of-scope" },
  { name: "tool_tag_assignments",       source: "iwo3_native", sourceVersion: MEGALOOP_THETA_VERSION, ownedBy: "drizzle", notes: "MegaLoop Theta — many-to-many bridge between tool_catalog and tool_tags; CASCADE on both FKs" },
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
    // Partitions (per ADR-010 Phase 1.5) are excluded — they are
    // implementation detail of their parent, which IS registered.
    const { rows } = await pool.query<{ table_name: string }>(
      `SELECT t.table_name
       FROM information_schema.tables t
       JOIN pg_class c
         ON c.relname = t.table_name
        AND c.relnamespace = 'public'::regnamespace
       WHERE t.table_schema = 'public'
         AND c.relispartition = false`
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

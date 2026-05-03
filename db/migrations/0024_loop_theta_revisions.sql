-- 0024_loop_theta_revisions.sql
--
-- MegaLoop Theta CODEX architect-review revisions.
--
-- Per CODEX disposition on the Theta closeout (2026-05-03):
--
--   D1.1 — tool_catalog.tool_type now NOT NULL.
--          All 29 seeded rows backfilled in 0023; the column is the
--          UI's Identity-tab radio gate, the Pydantic create body
--          requires it, and a non-API insert path could otherwise
--          create rows with NULL tool_type that the UI conditional
--          tabs cannot render. Tightening to NOT NULL closes that gap
--          without a data change.
--
--   D9.2 — Redefine `tool_runtime_status` to pure execution truth:
--            runnable     → handler exists in aiden_tools.TOOL_REGISTRY
--            catalog_only → metadata-only entry, no runnable handler
--            planned      → declared but not yet shipped
--            legacy       → retired but kept for audit/history forensics
--
--          Old vocabulary `runnable | skill_only | mcp | planned` had
--          mixed semantics — `mcp` was a transport/integration mode,
--          not an execution-truth state. Theta's `tool_type` enum
--          already captures `mcp_server` as the integration kind, so
--          `runtime_status='mcp'` was redundant + semantically off.
--
--          Mapping:
--            skill_only → catalog_only   (16 rows: every *_skill row)
--            mcp        → runnable       (1 row: stitch_design — has a
--                                          real handler at
--                                          runtime/tools/stitch_mcp.py;
--                                          the fact it bridges to MCP
--                                          is captured by tool_type)
--            runnable   → runnable       (unchanged)
--            planned    → planned        (unchanged)
--
--          Postgres can't drop enum values in place; we recreate the
--          type with the new vocabulary, ALTER COLUMN with a USING
--          mapping, then DROP+RENAME so the column ends up under the
--          original `tool_runtime_status` type name.
--
--   D3 — global tool_catalog stays as the canonical definition. No
--        client_id added to this table. Per-tenant override needs are
--        deferred to a future `client_tool_overrides` table per
--        CODEX's recommendation; not part of this revision.
--
-- Dependencies: 0023_loop_theta_tool_locker.sql (tool_type column +
-- backfill).

-- ── D1.1: tool_type NOT NULL ──────────────────────────────────────
ALTER TABLE "tool_catalog"
  ALTER COLUMN "tool_type" SET NOT NULL;

-- ── D9.2: tool_runtime_status enum recreation + row remap ─────────
CREATE TYPE "tool_runtime_status_v2" AS ENUM (
  'runnable',
  'catalog_only',
  'planned',
  'legacy'
);

ALTER TABLE "tool_catalog"
  ALTER COLUMN "runtime_status" TYPE "tool_runtime_status_v2"
  USING (
    CASE "runtime_status"::text
      WHEN 'runnable'   THEN 'runnable'::tool_runtime_status_v2
      WHEN 'planned'    THEN 'planned'::tool_runtime_status_v2
      WHEN 'skill_only' THEN 'catalog_only'::tool_runtime_status_v2
      WHEN 'mcp'        THEN 'runnable'::tool_runtime_status_v2
    END
  );

DROP TYPE "tool_runtime_status";
ALTER TYPE "tool_runtime_status_v2" RENAME TO "tool_runtime_status";

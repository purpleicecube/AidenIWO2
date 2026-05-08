-- 0025_loop_iota_memory_v1.sql
--
-- Loop Iota — Memory V1 retrofit.
--
-- Adds three memory-affecting columns to `clients` plus a GENERATED
-- tsvector column with GIN index on `artifacts.extracted_text` so the
-- deterministic memory builder can do tenant-scoped full-text retrieval
-- without a follow-up scan or tsvector compute on every query.
--
-- Decisions referenced (`WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_IOTA_SCOPE_PROPOSAL_v0.1.0.md`):
--
--   D3 — canonical facts via `clients.canonical_facts_blob` rather than
--        a per-turn workspace folder scan. Operators author markdown
--        under the tenant's `Canonical Facts/` workspace folder; a
--        write-side hook concatenates the tree into the blob and bumps
--        `canonical_facts_revision`.
--
--   D5 — bundle lifetime is a single HTTP request. Per-tenant LRU cache
--        in the FastAPI process keys on
--        (client_id, "canonical_facts", revision); revision bump
--        invalidates cleanly without TTL guesswork.
--
--   §AC #16 — 95th-percentile chat-turn non-LLM overhead under 30ms.
--             GIN tsvector keeps retrieval search-cost bounded.
--
-- Firewall package mandates (`IWO3_LOOP_IOTA_TENANT_FIREWALL_PACKAGE_v0.1.0.md`):
--   Layer 1 — `clients` is already tenant-owned (the row IS the tenant);
--             new fields inherit that scope.
--   Layer 3 — explicit `client_id = $1` predicates required at every
--             memory query site even though RLS is the hard wall.
--
-- Dependencies: 0024_loop_theta_revisions.sql.

-- ── clients memory fields ─────────────────────────────────────────
ALTER TABLE "clients"
  ADD COLUMN IF NOT EXISTS "memory_enabled" boolean NOT NULL DEFAULT true;
--> statement-breakpoint

ALTER TABLE "clients"
  ADD COLUMN IF NOT EXISTS "canonical_facts_blob" text;
--> statement-breakpoint

ALTER TABLE "clients"
  ADD COLUMN IF NOT EXISTS "canonical_facts_revision" integer
    NOT NULL DEFAULT 0;
--> statement-breakpoint

-- ── artifacts.extracted_text full-text index ──────────────────────
-- Generated tsvector keeps the search column always in sync with
-- extracted_text without triggers; the cost lands on artifact INSERT
-- and UPDATE, which are not on the chat hot path. The GIN index
-- supports tenant-scoped retrieval via
--   WHERE client_id = $1 AND extracted_text_tsv @@ plainto_tsquery($2)
-- which is the only retrieval shape Memory V1 issues.
ALTER TABLE "artifacts"
  ADD COLUMN IF NOT EXISTS "extracted_text_tsv" tsvector
    GENERATED ALWAYS AS (
      to_tsvector('english', coalesce("extracted_text", ''))
    ) STORED;
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "artifacts_extracted_text_gin"
  ON "artifacts" USING GIN ("extracted_text_tsv");
--> statement-breakpoint

-- Loop Kappa — Memory V1.5 canonical facts CRUD table.
--
-- Adds a dedicated `canonical_facts` table as the authoritative
-- authoring source for tenant canonical facts. Backed by RLS-FORCE
-- tenant isolation (canonical_facts_tenant_iso policy). The existing
-- `clients.canonical_facts_blob` (migration 0025) becomes a
-- denormalized read cache rebuilt by `refresh_canonical_facts_from_table`
-- whenever the table has rows for the tenant. The folder-driven path
-- (`Canonical Facts/` workspace folder) stays alive as fallback for
-- tenants that have not adopted the CRUD UI — automatic switchover
-- when the first row lands.
--
-- Architectural locks honored (per IWO3_LOOP_KAPPA_SCOPE_PROPOSAL):
--   D-K2  — hybrid table-or-folder posture; non-breaking.
--   ADR-014 — RLS canonical pattern with nullif()::uuid GUC cast.
--
-- Dependencies: 0025_loop_iota_memory_v1.sql.

-- ── canonical_facts table ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS "canonical_facts" (
    "id"                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    "client_id"             uuid NOT NULL,
    "severity"              text NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    "version"               integer NOT NULL DEFAULT 1,
    "authored_by_user_id"   uuid,
    "body"                  text NOT NULL,
    "is_active"             boolean NOT NULL DEFAULT true,
    "created_at"            timestamp with time zone NOT NULL DEFAULT now(),
    "updated_at"            timestamp with time zone NOT NULL DEFAULT now()
);
--> statement-breakpoint

ALTER TABLE "canonical_facts"
  ADD CONSTRAINT "canonical_facts_client_id_clients_id_fk"
    FOREIGN KEY ("client_id") REFERENCES "public"."clients"("id")
    ON DELETE CASCADE;
--> statement-breakpoint

ALTER TABLE "canonical_facts"
  ADD CONSTRAINT "canonical_facts_authored_by_user_id_users_id_fk"
    FOREIGN KEY ("authored_by_user_id") REFERENCES "public"."users"("id")
    ON DELETE SET NULL;
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "canonical_facts_client_id_active_idx"
  ON "canonical_facts" ("client_id", "is_active");
--> statement-breakpoint

CREATE INDEX IF NOT EXISTS "canonical_facts_client_id_severity_idx"
  ON "canonical_facts" ("client_id", "severity");
--> statement-breakpoint

-- ── RLS tenant isolation (matches ADR-014 §Q4 keep_both posture) ──
ALTER TABLE "canonical_facts" ENABLE ROW LEVEL SECURITY;
--> statement-breakpoint

ALTER TABLE "canonical_facts" FORCE ROW LEVEL SECURITY;
--> statement-breakpoint

CREATE POLICY "canonical_facts_tenant_iso" ON "canonical_facts" FOR ALL
    USING ("client_id" = nullif(current_setting('app.current_client_id', true), '')::uuid)
    WITH CHECK ("client_id" = nullif(current_setting('app.current_client_id', true), '')::uuid);
--> statement-breakpoint

-- ── Grant baseline access to iwo3_app role ────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON "canonical_facts" TO "iwo3_app";
--> statement-breakpoint

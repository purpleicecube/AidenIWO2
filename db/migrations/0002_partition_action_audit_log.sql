-- ADR-010 Phase 1.5 — convert action_audit_log to a partitioned table.
--
-- Loop 2 Phase 1 created `action_audit_log` as a regular table so that Loop 2
-- could ship without Drizzle needing to declare `PARTITION BY RANGE`. This
-- migration replaces that regular table with a partitioned one keyed on
-- `created_at`, keyed monthly. It preserves any dev rows from Phase 2's
-- audit-log-invariant tests by copying from a renamed legacy table.
--
-- Gate: this migration MUST land before Loop 3 begins writing operational
-- audit rows (per ADR-010 and LOOP_2_RECORD.md §Next-session-actions).
--
-- Partition key requires the key columns to be part of every unique
-- constraint. PK is therefore (id, created_at); `id` remains bigserial and
-- globally unique by virtue of the shared sequence. The client_id + created_at
-- index is recreated on the new parent; PostgreSQL 12+ auto-propagates to
-- each attached partition.

ALTER TABLE action_audit_log RENAME TO action_audit_log_legacy;
--> statement-breakpoint

ALTER INDEX action_audit_log_client_created_idx
  RENAME TO action_audit_log_legacy_client_created_idx;
--> statement-breakpoint

CREATE TABLE action_audit_log (
  id            bigserial    NOT NULL,
  client_id     uuid         NOT NULL,
  actor_user_id uuid,
  action        varchar(128) NOT NULL,
  target_type   varchar(64),
  target_id     varchar(128),
  metadata      jsonb,
  created_at    timestamptz  NOT NULL DEFAULT now(),
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);
--> statement-breakpoint

ALTER TABLE action_audit_log
  ADD CONSTRAINT action_audit_log_client_id_clients_id_fk
  FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE RESTRICT;
--> statement-breakpoint

ALTER TABLE action_audit_log
  ADD CONSTRAINT action_audit_log_actor_user_id_users_id_fk
  FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL;
--> statement-breakpoint

CREATE INDEX action_audit_log_client_created_idx
  ON action_audit_log (client_id, created_at DESC);
--> statement-breakpoint

-- Initial monthly partitions: current + next two. Production deployments
-- will extend via the ensure_audit_partition_for() helper below; dev seeds
-- prime the first three so reset+seed is fully self-contained.
CREATE TABLE action_audit_log_y2026m04
  PARTITION OF action_audit_log
  FOR VALUES FROM ('2026-04-01') TO ('2026-05-01');
--> statement-breakpoint

CREATE TABLE action_audit_log_y2026m05
  PARTITION OF action_audit_log
  FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
--> statement-breakpoint

CREATE TABLE action_audit_log_y2026m06
  PARTITION OF action_audit_log
  FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');
--> statement-breakpoint

-- Copy dev rows (if any) from the legacy regular table. Each row routes to
-- the correct partition by its created_at value. If a legacy row is outside
-- the three seeded partitions this migration fails loudly (no silent loss).
INSERT INTO action_audit_log
  (id, client_id, actor_user_id, action, target_type, target_id, metadata, created_at)
SELECT id, client_id, actor_user_id, action, target_type, target_id, metadata, created_at
FROM action_audit_log_legacy;
--> statement-breakpoint

-- Re-align the shared sequence with max(id).
SELECT setval(
  pg_get_serial_sequence('action_audit_log', 'id'),
  COALESCE((SELECT MAX(id) FROM action_audit_log), 0) + 1,
  false
);
--> statement-breakpoint

DROP TABLE action_audit_log_legacy;
--> statement-breakpoint

-- Helper: ensure a partition exists for the given timestamp. Idempotent.
-- Callers (the audit writer in Loop 3+) SELECT this immediately before
-- INSERT to self-heal a missing next-month partition in production.
CREATE OR REPLACE FUNCTION ensure_audit_partition_for(ts timestamptz)
RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
  part_start date := date_trunc('month', ts)::date;
  part_end   date := (date_trunc('month', ts) + interval '1 month')::date;
  part_name  text := format(
    'action_audit_log_y%sm%s',
    to_char(part_start, 'YYYY'),
    to_char(part_start, 'MM')
  );
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relname = part_name
  ) THEN
    EXECUTE format(
      'CREATE TABLE IF NOT EXISTS %I PARTITION OF action_audit_log FOR VALUES FROM (%L) TO (%L)',
      part_name, part_start, part_end
    );
  END IF;
END;
$$;

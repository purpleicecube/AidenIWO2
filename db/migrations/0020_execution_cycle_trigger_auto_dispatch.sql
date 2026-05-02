-- Beta-2 phase 0.2 — auto-dispatch worker idempotence.
-- The Phase 0.2 worker writes one execution_cycles row per WO it picks
-- up, using `trigger='auto_dispatch'` as the rowmark. The cycle row is
-- written BEFORE the LLM call so a worker restart mid-dispatch cannot
-- re-fire (R-047 mitigation per scope proposal).
--
-- ALTER TYPE ... ADD VALUE is non-transactional in Postgres ≥ 12, so
-- the migration is safe to apply with apply-migrations.ts (which does
-- NOT wrap files in BEGIN/COMMIT).

ALTER TYPE execution_cycle_trigger ADD VALUE IF NOT EXISTS 'auto_dispatch';

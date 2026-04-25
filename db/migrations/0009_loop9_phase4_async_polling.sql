-- Loop 9 Phase 9.4 — async polling state on output_handoffs.
-- Scope-proposal §3.4 (originally numbered 9.3; the LLM Foundation
-- slice shipped as 9.3 ahead of this, so async-polling carries 9.4
-- and closeout becomes 9.5 per LOOP_9_RECORD.md).
--
-- Darrel Q3: WO stays in `processing` during legitimate Gamma
-- rendering. Async progress lives here on output_handoffs, not on
-- the parent WO. Watchdog fires only on stale-poll timeout OR true
-- terminal adapter failure.
--
-- Renamed from drizzle-kit's emitted 0007_lyrical_zaladane so the
-- file-order matches the migration sequence (0007 = Phase 9.1; 0008
-- = Phase 9.3 LLM; 0009 = Phase 9.4 async polling).
ALTER TABLE "output_handoffs" ADD COLUMN "last_poll_status" varchar(32);--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD COLUMN "last_poll_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "output_handoffs" ADD COLUMN "poll_count" integer DEFAULT 0 NOT NULL;

-- Pre-Beta β.1 — sub-agent metadata model v1.
-- Adds display_name + description to llm_configs so the operator
-- console can render meaningful labels and descriptions per sub-agent
-- without inventing a parallel sub_agent_profiles table.
-- See IWO3_PRE_BETA_GAP_CLOSURE_PLAN_v0.1.0.md § β.1 schema decision.

-- 1) Add columns nullable so we can backfill from agent_role.
ALTER TABLE "llm_configs"
  ADD COLUMN IF NOT EXISTS "display_name" varchar(160),
  ADD COLUMN IF NOT EXISTS "description"  text;
--> statement-breakpoint

-- 2) Backfill display_name by humanising agent_role for existing rows.
--    "aiden_tier_1"  → "Aiden (Tier 1)"
--    "pm_tier_15"    → "PM (Tier 1.5)"
--    "mark_tier_2"   → "Mark (Tier 2)"
--    "tom_tier_2"    → "Tom (Tier 2)"
--    etc.
UPDATE "llm_configs"
   SET "display_name" = CASE agent_role
         WHEN 'aiden_tier_1' THEN 'Aiden (Tier 1)'
         WHEN 'pm_tier_15'   THEN 'PM (Tier 1.5)'
         WHEN 'mark_tier_2'  THEN 'Mark (Tier 2 — content)'
         WHEN 'tom_tier_2'   THEN 'Tom (Tier 2 — decks)'
         WHEN 'hank_tier_2'  THEN 'Hank (Tier 2 — web)'
         WHEN 'paul_tier_2'  THEN 'Paul (Tier 2 — deployment)'
         ELSE initcap(replace(agent_role, '_', ' '))
       END
 WHERE "display_name" IS NULL;
--> statement-breakpoint

-- 3) Lock display_name NOT NULL going forward.
ALTER TABLE "llm_configs"
  ALTER COLUMN "display_name" SET NOT NULL;

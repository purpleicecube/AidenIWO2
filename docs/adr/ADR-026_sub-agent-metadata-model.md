# ADR-026 — Sub-agent metadata model v1

Date: 2026-04-24
Status: Accepted (Pre-Beta β.1)
Predecessors: ADR-021 (LLM runtime), ADR-025 (LLM config CRUD).
Companions: `IWO3_PRE_BETA_GAP_CLOSURE_PLAN_v0.1.0.md` § β.1.

## Context

Alpha treated sub-agents as bare `agent_role` strings (`pm_tier_15`, `mark_tier_2`, etc) with provider + model + credential_ref attached. The IWO2 console renders sub-agents with display names, descriptions, type/category chips, and a control-mode dropdown. The Pre-Beta directive's acceptance criterion #9 requires "minimum metadata model needed so sub-agents are manageable as real system entities, not just role strings."

## Decision

### 1. Extend `llm_configs` rather than add a parallel table

Add two columns:

```
display_name  varchar(160) NOT NULL  -- human-readable label
description   text          NULL     -- one-paragraph operator note
```

Migration `0012_pre_beta_phase_1_llm_configs_metadata.sql` is additive + idempotent + backfills `display_name` from `agent_role` for existing rows so seeded tenants are intact:

```
aiden_tier_1  → "Aiden (Tier 1)"
pm_tier_15    → "PM (Tier 1.5)"
mark_tier_2   → "Mark (Tier 2 — content)"
tom_tier_2    → "Tom (Tier 2 — decks)"
hank_tier_2   → "Hank (Tier 2 — web)"
paul_tier_2   → "Paul (Tier 2 — deployment)"
otherwise     → initcap(replace(agent_role, '_', ' '))
```

After backfill the column is `SET NOT NULL` so future rows must carry a label.

### Why one table, not two

A parallel `sub_agent_profiles` table joining to `llm_configs` by `agent_role` would split the source-of-truth across two records. CRUD code on either side would have to keep them in sync. The IWO2 reference renders as one record per sub-agent — same shape we're adopting. If a future capability genuinely needs many-to-one (e.g. one persona shared across tenants) we'll branch the model then.

### 2. What's intentionally NOT modeled in v1

The IWO2 modal carries a richer surface that is **not** part of this ADR:

- **Control Mode** ("Aiden-controlled vs independent"). IWO3's tier model is uniform — every Tier 2 invocation flows through the same dispatch path. We didn't fabricate a toggle that wouldn't change runtime behavior.
- **Type / Status enums.** `enabled` already covers the binary. Adding a `status` enum (active/paused/archived) without a state machine would just be cosmetic.
- **Tool Access ACL + Runtime Tools + Tool History.** Those require a tool registry IWO3 doesn't have. Per ADR-024 deferred list, this is Beta.
- **Independent LLM toggle.** Each agent_role row already has its own provider/model — there is no "global model" to override. The IWO2 toggle is meaningful in IWO2's two-tier-with-shared-default architecture; in IWO3 it would be a no-op switch.

### 3. Browser surface

The Sub-Agents page renders `display_name` in expander headers (`agent_role` is shown as a parenthetical for clarity). The Edit form exposes display_name + description as first-class fields. The "New Sub-Agent" form requires both alongside provider + model + credential_ref.

## Consequences

- Operators see meaningful labels in the operator console — "Aiden (Tier 1)" not `aiden_tier_1`.
- Adding a new sub-agent (e.g. "Ada (Tier 2 — research)") is a single browser interaction.
- The schema doesn't pretend to model capabilities it doesn't have. When IWO3 grows a tool registry the metadata model can extend rather than retract.

## Out-of-scope (deferred)

- Tool ACL + runtime tool registry (Beta, Loop 11+).
- Persona libraries / shared system prompt versioning (Beta).
- Type enum if/when status semantics warrant a state machine.
- Multi-tenant template profiles for cloning sub-agents across tenants.

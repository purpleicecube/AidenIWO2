# ADR-011 — Work Order / Workflow / Execution-Cycle schema (Loop 3 Phase 1)

Date: 2026-04-19
Status: Accepted (Loop 3 Phase 1)
Deciders: AI, WR (per `IWO3_LOOP_3_APPROVAL_DECISIONS_v0.1.0.md` §Q2 + §Q6; `IWO3_LOOP_3_SCOPE_PROPOSAL_v0.1.0.md` §3.1)

## Context

Loop 3 Phase 1 lands the first set of IWO3-native **operational** tables. Loops 1 + 2 shipped the foundation (tenants, users, RBAC anchor, prompt profiles, repository bindings, artifacts, audit log). Loop 3 Phase 1 turns that foundation into something that can run work.

The approval memo locked two constraints that shape this ADR:

1. **No state machine.** Loop 3 persists `status`, `cycle_number`, `trigger`, `terminal_status` and whatever else the lifecycle semantics of Loop 6 will need, but does NOT implement retry / reopen / unblock / watchdog / terminal-transition governance. That code lands in Loop 6.
2. **Audit vocabulary locked at phase start.** Phase 3.1 registers its 13 event names in `packages/contracts/audit/events.ts` and does not preload future-loop events.

## Decision

### Seven new Drizzle tables, all `iwo3_native / drizzle` under `LOOP_3_VERSION = iwo3@v0.3.0-loop3`

| Table | Purpose |
| --- | --- |
| `work_orders` | One-time execution (per ADR-003). Tenant-scoped via `client_id`. Status enum covers nine values Loop 6's state machine will traverse. |
| `workflows` | Repeatable-pipeline logical container. Tenant-scoped. `key` is the business slug (`weekly_marketing_brief`). Status covers active/paused/archived. |
| `workflow_templates` | Versioned template recipe for a workflow. `version` is a free-form string (semver or monotonic integer). `config` holds template-level settings (category, preferred PM, default render route) so step rows stay clean. |
| `workflow_template_steps` | Ordered steps within a template version. Unique per `(template_id, step_key)` and `(template_id, step_order)`. `prompt_ref` is a loose JSON the Loop 2 resolver will learn to consume; `assigned_sub_agent_key` is a string (no `sub_agents` FK yet). |
| `workflow_executions` | Running instance of a template version. `work_order_id` is nullable (WF can run standalone). `client_id` is denormalized from the template's workflow for fast tenant-scoped queries. |
| `workflow_step_runs` | Per-step record within an execution. Unique per `(execution_id, step_key)`. Carries `revision_attempt`, `pm_review`, and input/output blobs. |
| `execution_cycles` | Retry/reopen/unblock attempts against a WO. `cycle_number` monotonic per WO; `prior_cycle_id` self-references the previous cycle. `trigger` enum covers the seven cycle-initiating events. |

All seven carry `client_id` where applicable — either directly or transitively via their parent. Tenant isolation is enforced at the service layer in Loop 3+; RLS lands in Loop 4 (per Loop 3 approval memo §Q1 — deferred).

### Status enums

Enum values Loop 3 Phase 1 persists (Loop 6 expands as needed):

- `work_order_status`: `pending | processing | blocked | awaiting_operator | completed | done | failed | deferred | cancelled` (9)
- `work_order_priority`: `low | medium | high | critical` (4)
- `workflow_status`: `active | paused | archived` (3)
- `workflow_template_status`: `draft | published | deprecated` (3)
- `workflow_execution_status`: `pending | running | completed | failed | cancelled` (5)
- `workflow_step_run_status`: `pending | running | completed | failed | skipped` (5)
- `execution_cycle_trigger`: `new | retry | reopen | unblock | watchdog | admin_repair | candidate_request_more` (7)

### Indexes (performance seeds)

- `work_orders (client_id, status, created_at DESC)` — tenant-filtered status dashboards
- `workflow_executions (client_id, status, created_at DESC)` — same pattern for WF runs
- `execution_cycles (client_id, started_at DESC)` — cycle lineage queries
- `workflow_step_runs (execution_id, step_key)` — unique constraint doubles as step lookup

### Foreign-key cascade policy

- `ON DELETE RESTRICT` for tenant anchors (cannot delete a client with live WOs).
- `ON DELETE SET NULL` for nullable user references (orphan-tolerant).
- `ON DELETE CASCADE` only for strict parent→child (template → template_steps, execution → step_runs, work_order → execution_cycles) because those children are meaningless without their parent.

### What Loop 3 Phase 1 does NOT do

- **No state machine** — persistence only. Loop 6 wires transition logic.
- **No candidate review tables** — they land in Phase 3.2 alongside `output_packages` and `output_handoffs`, per the hybrid decision in `IWO3_LOOP_3_APPROVAL_DECISIONS_v0.1.0.md` §Q5.
- **No tool execution** — `workflow_template_steps.tool_ids` is persisted but not consumed.
- **No PM escalation code** — `workflow_step_runs.pm_review` holds payload but Loop 3 Phase 1 writes no rows to these tables.
- **No RLS** — deferred to Loop 4.
- **No FastAPI routes** — Loop 7.

## Enforcement

- `infra/local/manifest-populate.ts` registers all seven tables under `LOOP_3_VERSION`.
- `tests/integration/migration-ownership.test.ts` asserts the Loop 3 Phase 1 schema classification.
- Tenant-isolation suite (`tenant-wo-isolation.test.ts`, `tenant-workflow-isolation.test.ts`, `tenant-execution-cycle-isolation.test.ts`) proves the canonical service-layer JOIN pattern works for both tenants + the intruder user.
- Audit events registered in `AUDIT_EVENTS` (13 Loop 3 Phase 1 names); `LOOP_3_PHASE_1_AUDIT_EVENTS` exported for the invariant test.

## Alternatives considered

- **Mirror IWO2's `work_orders` schema column-for-column.** Rejected — IWO2 has drift (missing tenant column, inconsistent casing, unused fields). Starting fresh with tenant-first shape is cheaper long-term.
- **Single giant `pipelines` table instead of workflows + templates + template_steps.** Rejected — versioning a pipeline means rewriting the pipeline row, which destroys audit trail. Versioned templates hanging off stable workflow containers is cleaner.
- **State machine in Loop 3.** Rejected explicitly by approval-memo §Q2. Loop 6 owns it.
- **Polymorphic `work_items` supertype for WO + WF runs.** Rejected — WOs and WF runs have genuinely different shapes and lifecycles. Separate tables kept simpler joins and avoids the polymorphism tax.

## Consequences

- Loop 6 adds state-machine logic on top of these tables without needing schema changes (status enums are pre-populated).
- Loop 3 Phase 2 adds `output_packages`, `output_handoffs`, adapter registry, and the candidate-review data model.
- Loop 3 Phase 3 adds the DigiFLOW intake contract + routing.
- Loop 3 Phase 4 (Gamma test-double) wires audit events + demonstrates the end-to-end path against these tables.
- If a future loop adds a `work_order_type` dimension (e.g., DigiFLOW-origin vs operator-submitted), `work_orders.type` is already a varchar — widen rather than replace.

## Revisit triggers

- Loop 6 opens and discovers the WO status enum needs more values (e.g., `reopened_awaiting_cycle`). Amend this ADR + emit a migration that extends the enum.
- First real WO throughput reveals an unindexed hot query path. Add migration + document under a short ADR amendment.
- Loop 3 Phase 2 discovers the candidate review model wants to live in `workflow_step_runs` (or elsewhere) rather than on `output_handoffs`. Amend §"What Loop 3 Phase 1 does NOT do".

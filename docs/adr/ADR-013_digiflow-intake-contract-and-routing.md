# ADR-013 — DigiFLOW intake contract + deterministic routing

Date: 2026-04-19
Status: Accepted (Loop 3 Phase 3)
Deciders: AI, WR, OA (per `IWO3_LOOP_3_APPROVAL_DECISIONS_v0.1.0.md` §Q4 `contract_only` + CODEX response-packet §2)

## Context

DigiFLOW is the upstream campaign/strategy planner. Intake packets from DigiFLOW land in IWO3 and must route to one of:

- a one-time **Work Order** (single run, single or multiple outputs in one campaign),
- a repeatable **Workflow** (template with a run schedule), or
- a **needs_clarification** state for operator review.

CODEX response packet §2 locked the packet shape (22 fields) and the routing decision order. The Loop 3 approval memo §Q4 locked Phase 3.3 scope to `contract_only`: ship the TypeScript type + Zod validator, the deterministic router, a Python parity mirror with a byte-identical CLI, and a 6-fixture contract test. **No FastAPI endpoint.** The endpoint lands in Loop 7 when the FastAPI runtime API opens.

Phase 3.3 does not persist intake packets. They flow through validation + routing + into a WO / WF create call (Phase 3.4 demonstrator + Loop 6 state machine).

## Decision

### Packet shape (TypeScript canonical — `packages/contracts/digiflow/intake.ts`)

Fields (per CODEX §2):

- `id`, `schema_version: "v0"`, `source_system: "digiflow"`, `source_ref`
- `client_designation` (e.g. `"IWO | Klear.ai"`) **OR** `client_id` (either required)
- `requester` (kind, id/email/display_name)
- `intake_type` (default `"content"`)
- `requested_execution_mode` (`wo | wf | auto`, default `auto`)
- `title`, `objective` (both required, non-empty)
- `business_context`, `campaign_or_project_goal`, `audience`, `offer_or_message_strategy`
- `desired_outputs[]` (at least one entry, each with `output_kind` + optional template/adapter hints)
- `destination_preferences[]`, `assets[]`, `constraints`, `compliance_notes`, `due_at`
- `recurrence` (kind + optional frequency/until; `kind='custom'` requires frequency)
- `approval_preferences`, `priority` (default `medium`), `correlation_id`

Validation (Zod, canonical):

- `client_designation` OR `client_id` must be present.
- `desired_outputs.length >= 1`.
- `title.trim().length >= 1` and `objective.trim().length >= 1`.
- Every `assets[].credential_ref` must begin with `credential_ref:` or be `null` (enforces the cross-loop `credential_ref` placeholder discipline; blocks raw-secret leakage at the intake boundary).
- `recurrence.kind === "custom"` requires `frequency`.

Python mirror (`apps/api-fastapi/digiflow/intake.py`) implements the subset of validation rules most likely to diverge if someone edits only one side (tenant resolution, credential_ref, required fields, custom recurrence). Full Zod parity stays in TS; Python is the safety net.

### Routing algorithm (byte-identical TS + Python)

Order:

1. If `requested_execution_mode === "wo"` → `{kind: "wo", rationale: "… explicit override"}`.
2. If `requested_execution_mode === "wf"` → `{kind: "wf", rationale: "… explicit override"}`.
3. (`auto` mode.) If `recurrence.kind` present AND not `"once"` → `{kind: "wf", rationale: "recurrence.kind='X' → repeatable workflow"}`.
4. If `desired_outputs.length === 1` → `{kind: "wo", rationale: "single one-time output, no recurrence"}`.
5. If `desired_outputs.length > 1` → `{kind: "wo", rationale: "N one-time outputs, single run → WO with multiple output packages"}`.
6. Otherwise → `{kind: "needs_clarification", rationale: "ambiguous — …"}`.

Pure functions. No clock, no RNG, no DB, no network. Given the same packet, returns the same decision.

### Phase 3.3 scope (contract_only, §Q4)

- TS types + validator + router.
- Python types + validator + router.
- CLI (`apps/api-fastapi/digiflow/intake_cli.py`) used only by the Vitest parity contract test.
- 6 fixture packets under `tests/fixtures/digiflow/` covering the routing decision space.
- Parity test + 10-case TS validation test + 12-case Python unit test.

### Phase 3.3 NON-scope

- **No FastAPI endpoint.** That's Loop 7.
- **No DB table.** Intake packets are ephemeral in-flight objects until a downstream writer (Phase 3.4 demonstrator or Loop 6 state machine) converts them to WO/WF rows.
- **No audit events.** Phase 3.3 triggers zero writes. DigiFLOW audit events land when a real persister (Loop 3.4 or Loop 6) starts writing rows; that phase locks the events per approval memo §Q6.
- **No operator UI.** Loop 8.

## Enforcement

- TS `DigiFlowIntakePacketSchema` is the only sanctioned validator on the TS side.
- Python `validate_intake_packet(packet)` is the only sanctioned validator on the Python side.
- `packages/contracts/digiflow/routing.ts` is the single source of routing logic in TS.
- `apps/api-fastapi/digiflow/intake.py` is the single source in Python.
- `tests/contract/digiflow-routing-parity.test.ts` fails CI the moment TS and Python disagree on any of the 6 fixture packets.

## Alternatives considered

- **Persist every intake packet.** Rejected for Phase 3.3 — a persistent `digiflow_intake_packets` table is only useful if Loop 3 has a real consumer; Phase 3.4's demonstrator is the first consumer and can persist what it needs. Loop 6+ may revisit.
- **Ship a FastAPI endpoint now.** Rejected per approval memo §Q4 `contract_only`. The contract must stabilize before the endpoint; premature endpoints bake in Loop 3 assumptions that Loop 7+ work might revise.
- **Looser routing (all modes emit WF).** Rejected — `auto` mode should default to the cheapest option (WO for one-time work), and only escalate when signals justify.
- **Python-first with TS parity.** Rejected — matches `IWO3_LOOP_3_APPROVAL_DECISIONS §Q5` (TS-first). TS is the strangler's authoritative lane while the IWO2 Node core remains the runtime.
- **More routing signals than recurrence** (e.g. infer WF from "multiple phases" language in the objective). Rejected — NLP-driven routing is not deterministic; it fails the parity-contract-test invariant. Signals Loop 6+ adds must themselves be deterministic (presence of a phase list, explicit reusable step marker, etc.).

## Consequences

- Phase 3.4 consumes this contract: demonstrator receives an intake packet, validates, routes, creates a WO using the Phase 3.1 `work_orders` table + an `output_package` + an `output_handoff` via the Phase 3.2 adapter registry.
- Loop 7 adds the FastAPI route `/digiflow/intake` that imports the same TS validator + router. The endpoint cannot reinterpret the routing rules — it must delegate.
- New routing signals (Loop 6+) require:
  1. Amendment to this ADR.
  2. Update to both TS + Python with matching rationale strings.
  3. New fixture(s) in `tests/fixtures/digiflow/` exercising the new signal.
- DigiFLOW audit events land when a real writer starts persisting intake packets (Phase 3.4 demonstrator — lock names per §Q6 at that phase's start).

## Revisit triggers

- Loop 3.4 demonstrator reveals a missing packet field. Amend the schema + bump `schema_version` to `v1`; both TS and Python update together.
- NLP-driven routing becomes necessary in Loop 6+. Keep the deterministic core; wrap an NLP layer that returns a structured "routing hint" the deterministic router can consume.
- Loop 7 FastAPI endpoint exposes the contract publicly. Revisit error-message exposure + rate limits.

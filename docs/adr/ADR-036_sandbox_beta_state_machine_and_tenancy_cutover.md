# ADR-036 — Sandbox β-line State Machine + Tenancy Cutover Plan

**Status:** Accepted (CODEX β.0 brief, 2026-05-17; WS024 baseline `edce652`)
**Authors:** CODEX (architect direction) + Claude Opus 4.7 (implementation)
**Loop:** Sandbox-Hosted-In-App-β.0 (foundation slice — schema, contracts,
permissions, audit vocab; no transition logic, no UI, no routes)
**Predecessor:** ADR-035 (sandbox internal utility + Node adapter carve-out),
ADR-014 (RBAC), ADR-015 (RLS enforcement mode), ADR-002 (multi-client data)
**Successor:** β.1+ (transition validator + helpers); β.x tenancy cutover
(toggles FORCE RLS + makes `client_id` NOT NULL); β.7 React-surface
retirement (decision-gated)

---

## Context

The Sandbox-Hosted-In-App correction (`WS024_IWO3[Branch]/05_Artifacts/
SANDBOX_HOSTED_IN_APP_SCOPE_v0.1.1.md`) reframes the sandbox from a
launcher-to-external-React-surface pattern into a self-contained
evaluate → test → review → accept workflow under the FastAPI/
Streamlit operator console. CODEX accepted the scope with revisions
(WS024 commit `edce652`) and disposed all 7 decisions D-B1..D-B7.

β.0 is the foundation-only slice. Per the brief: schema +
contracts + permissions + audit vocab + this ADR. **No UI, no
transition logic, no upload flow, no filetype implementation, no
render-worker.** Those belong to β.1+.

Pre-β.0 sandbox truth (ADR-035 carve-out, 2026-05-11):

- `sandbox_sessions` exists as a flat IWO2-inherited table with no
  `client_id` column and no RLS.
- Visibility/mutation is gated at the Node route layer by a
  creator-or-admin check against `req.user.claims.sub`
  (`server/routes.ts:3175`).
- The carve-out was deliberate (Path A-prime) with the Path B
  follow-on loop documented in ADR-035 §Successor. **β.0 is that
  follow-on loop's foundation phase.**

---

## Decision

### 1. Acceptance state machine vocabulary (D-B2)

V1 ships exactly 7 states:

```
uploaded → evaluating → tested → under_review → accepted
                                              ↘ rejected → reopened → uploaded
```

Wait — actually `reopened → evaluating` (not back to `uploaded`),
because the artifact bytes haven't changed. If an operator wants
to upload a fresh artifact, they create a new session.

Per D-B2: **no pass/fail detail in the state machine itself.**
Test evidence (pass/fail counts, per-filetype-check results, etc.)
lives in audit metadata + future test-result tables — not as
additional states.

Vocabulary mirrored across:
- `sandbox_sessions.acceptance_state` CHECK constraint (migration 0033)
- `packages/contracts/sandbox/state_machines.ts` `SANDBOX_ACCEPTANCE_STATES`
- `tests/fixtures/contract-enums.snapshot.json` (locked vocabulary)

Adding a new state requires updating all three surfaces in lockstep.

### 2. Permission model (D-B6)

Per-action gating only. V1 ships 4 keys:

| Key | Display | Roles granted |
| --- | --- | --- |
| `sandbox:evaluate` | Evaluate sandbox artifact | owner, admin, operator |
| `sandbox:test` | Test sandbox artifact | owner, admin, operator |
| `sandbox:review` | Review sandbox artifact | owner, admin, operator, reviewer |
| `sandbox:accept` | Accept sandbox artifact | owner, admin, operator |

Rationale:
- `evaluate` + `test` are operator-tier work; reviewer doesn't run
  them.
- `review` is read-only attestation; safe to grant to reviewer (who
  may not be an operator but should be able to read + comment).
- `accept` is the terminal acceptance authority — explicitly NOT
  granted to reviewer because per D-B6 the decision-to-accept is
  privileged. Reviewer can attest; only operator-tier roles can
  finalize.

**Rejection** is gated on `sandbox:accept` (same gate as acceptance)
— both are terminal acceptance-authority decisions; the gate name
reflects the privilege tier, not the verb. The audit event
distinguishes them. β.1+ may surface a separate `sandbox:reject`
permission if operator review shows the coupling is too tight;
that's an OPEN_NOTE here, not a β.0 decision.

**No per-filetype permissions in V1** (per D-B6 explicit override).
A future loop can add `sandbox:accept_pdf` / `sandbox:accept_docx`
/ etc. if operator review shows uniform per-action gating is too
loose.

### 3. Audit vocabulary

6 events under the `sandbox.*` namespace, registered as
`LOOP_SANDBOX_BETA_0_AUDIT_EVENTS`:

| Event | Fired by |
| --- | --- |
| `sandbox.evaluated` | `uploaded → evaluating` AND `reopened → evaluating` |
| `sandbox.tested` | `evaluating → tested` |
| `sandbox.under_review` | `tested → under_review` |
| `sandbox.accepted` | `under_review → accepted` (terminal) |
| `sandbox.rejected` | `under_review → rejected` (terminal) |
| `sandbox.reopened` | `rejected → reopened` |

Every event MUST be written through the canonical
`writeAuditRow()` path (`packages/contracts/audit/writer.ts` TS or
`apps/api-fastapi/authz/audit_writer.py` Python). Raw `INSERT INTO
action_audit_log` is forbidden by the `no-raw-audit-insert` lint
rule. β.1+ wiring must respect this.

### 4. Tenancy posture + cutover plan (D-B3)

**β.0 (this slice):**

- Migration 0033 adds `client_id uuid` NULL to `sandbox_sessions`.
- Legacy rows from the ADR-035 carve-out continue to have NULL
  `client_id`.
- New rows MAY set `client_id` but are not yet required to.
- RLS is **NOT** enabled. The ADR-035 route-layer gate remains
  authoritative.

**β.x cutover (separate slice, NOT in β.0):**

- All sandbox writes must pass a tenant context (Node side: add
  `withTenantContext()` wrapper to `server/routes.ts` sandbox
  routes; FastAPI side: standard tenant-scoped connection pattern).
- Backfill: every existing `sandbox_sessions` row gets a `client_id`
  inferred from `created_by`'s primary `client_memberships` row.
  Rows where the inference is ambiguous (cross-tenant operators) get
  flagged for operator review.
- `ALTER TABLE sandbox_sessions ALTER COLUMN client_id SET NOT NULL`.
- `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` on
  `sandbox_sessions`.
- `CREATE POLICY` mirroring the Loop 4 Phase 4.3 tenant-scoped
  pattern: `USING (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)`.
- `GRANT` already covers (migration 0028); the role-based RLS gate
  is what enforces tenancy.

**Why staged, not done in β.0:** the Node sandbox path currently
issues queries on an un-tenanted Drizzle connection. Toggling FORCE
RLS without the Node-side coexistence work would break the existing
Node sandbox surface today. The staged approach lets β.0 land the
foundation cleanly (no operational impact) and β.x do the
coordinated cutover.

### 5. Enforcement edge (D-B7)

Acceptance gates **dispatch**, not output_package creation.

Specifically: an `output_packages` row that references a
`sandbox_session_id` MUST have the referenced session in
`acceptance_state = 'accepted'` before `output_handoffs` will
dispatch. Block error code: **`sandbox_not_accepted` (HTTP 409)**.
Exported as `SANDBOX_DISPATCH_GATE_ERROR_CODE` in
`packages/contracts/sandbox/state_machines.ts`.

Creation, review, and acceptance can happen in any order; only
the handoff dispatch is blocked. This matches D-B7 verbatim.

β.0 records the contract in code (the exported error code constant)
+ ADR (this section). β.1+ wires the actual gate in
`dispatchToAdapter` (or equivalent dispatch helper).

### 6. Render-worker note (D-B4)

Per CODEX D-B4 override (WS024 `edce652` §11): the
HTML→PDF / HTML→PPTX export work in β.4 ships as a **separate
`iwo3-render-worker` Railway service**, NOT bundled into the
FastAPI image. FastAPI is the runtime/API plane; heavyweight
browser/render dependencies belong in a service that can scale
independently.

β.0 does not implement the render-worker — that's β.4 scope. This
ADR reaffirms the default so β.4 doesn't relitigate it.

### 7. React surface coexistence (D-B5)

The React `/sandbox` route stays operational throughout β.0..β.6.
β.7 retires it **only after** the new flow proves parity. β.0
introduces no behavior changes to the React surface; the
acceptance state defaults to `uploaded` on existing rows, and
the React surface ignores `acceptance_state` until it's wired to
read it (a β.1+ concern).

---

## Consequences

**Positive:**

- The tenant-scoping debt from ADR-035 has a real cutover plan with
  a documented gate (β.x) instead of "it'll happen eventually".
- The acceptance state machine is locked at the vocabulary level
  before any code consumes it, preventing later inconsistency
  between schema CHECK / TS constants / Python mirror.
- The dispatch-time enforcement edge (D-B7) is recorded as a
  constant (`SANDBOX_DISPATCH_GATE_ERROR_CODE`) so β.1+ helpers
  reference it instead of redefining.
- The render-worker default (D-B4) is reaffirmed here so β.4 opens
  with the decision locked.

**Negative:**

- The ADR-035 carve-out persists through β.0..β.x (multiple loops).
  Operators continue to see "no RLS on sandbox_sessions" until the
  cutover lands. This is documented as a planned debt-window, not
  a forgotten gap.
- Acceptance gates dispatch but not creation; an operator can
  create + review + reject an output_package's sandbox link without
  the package itself being aware. β.1+ surfaces should make this
  visible via the Streamlit Output Packages view + handoff page.
- The `sandbox:accept` permission gates both acceptance and
  rejection. If operators want a separate `sandbox:reject` gate,
  that's a future ADR amendment (OPEN_NOTE in §2 above).

**Neutral (β.0 boundary):**

- β.0 ships **no runtime behavior change** — every change is
  schema, vocabulary, or governance. Existing Node sandbox flows
  continue to work because:
  - `acceptance_state` defaults to `'uploaded'` for every existing
    row.
  - `client_id` is nullable; existing rows get NULL.
  - RLS is OFF (deliberately deferred to β.x).
  - The new permission keys are seeded but not yet consumed by any
    route.
  - The new audit events are registered but not yet emitted.

---

## Open notes (carry into future loops)

- **OPEN_NOTE_ADR036_1** — `sandbox:reject` separation. If
  operator review of β.1+ shows that coupling acceptance + rejection
  under `sandbox:accept` is too tight, surface `sandbox:reject` as
  a separate permission. Decision-gated; not a β.0 concern.
- **OPEN_NOTE_ADR036_2** — Output-package dispatch gate
  enforcement code path. β.0 records the error code constant but
  does not implement the gate. β.1+ must add the check inside the
  dispatch helper (e.g. `dispatchToAdapter` or whichever path
  output_handoffs is created on).
- **OPEN_NOTE_ADR036_3** — Sandbox session → output_package
  reference column. Today `sandbox_sessions` has no FK to
  `output_packages` and vice versa. β.1+ (or the dispatch-gate
  wiring loop) needs to decide how the link is represented:
  - `output_packages.sandbox_session_id` (FK on packages side), OR
  - `sandbox_sessions.output_package_id` (FK on sandbox side), OR
  - a join table.
  ADR-036 doesn't lock this; the dispatch-gate slice does.
- **OPEN_NOTE_ADR036_4** — β.x cutover preconditions:
  - Every sandbox-touching Node route must use
    `withTenantContext()` (or equivalent).
  - Backfill script + manifest entry must be authored.
  - `client_id` SET NOT NULL only after backfill is verified.
  - FORCE RLS + CREATE POLICY in the same migration as the SET
    NOT NULL to avoid intermediate inconsistent state.

---

## Cross-references

- β.0 brief: `WS024_IWO3[Branch]/02_Execution/` (CODEX's β.0 opening
  brief in the conversation thread; not yet captured as a static
  artifact)
- B scope proposal: `WS024_IWO3[Branch]/05_Artifacts/SANDBOX_HOSTED_IN_APP_SCOPE_v0.1.1.md`
- A runbook: `WS024_IWO3[Branch]/05_Artifacts/SANDBOX_HOSTED_DEPLOY_RUNBOOK_v0.1.0.md`
- ADR-035: `docs/adr/ADR-035_sandbox_internal_utility_and_node_adapter_carveout.md`
- ADR-015: `docs/adr/ADR-015_*.md` (RLS enforcement mode)
- Migration: `db/migrations/0033_sandbox_beta_0_foundation.sql`
- Drizzle schema: `shared/schema.ts` `sandboxSessions`
- TS contracts: `packages/contracts/sandbox/state_machines.ts`
- Audit events: `packages/contracts/audit/events.ts` (`AUDIT_EVENTS.SANDBOX_*`)
- Permissions seed: `db/seeds/permissions.json` (`sandbox:*`)
- Role grants seed: `db/seeds/role_permissions.json`
- Tests: `tests/contract/sandbox-beta-0-foundation.test.ts`
- Manifest: `infra/local/manifest-populate.ts` `SANDBOX_BETA_0_VERSION`

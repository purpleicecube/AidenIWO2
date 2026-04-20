# ADR-018 — FastAPI runtime API foundation + Python transition port

Date: 2026-04-20
Status: Accepted (Loop 7 Phase 7.3 closeout)
Predecessors: ADR-014, ADR-015, ADR-016, ADR-017.

## Context

Loops 1–6 built the schema, runtime helpers, contract surface, and
lifecycle state machines in TypeScript. Loop 5's contract barrel
already exposed the Python enum + shape mirror. Loop 7 is the first
loop that ships an HTTP surface — the minimum set of FastAPI routes
Loop 8 Streamlit needs for a browser-visible operator console.

Two design questions had to land:

1. How do TS helpers reach a Python runtime? The Loop 7 scope
   proposal flagged this as an optional approval ask: Option A spawn
   TS helpers as a CLI per request; Option B port the helpers to
   Python.

2. How should FastAPI handlers enforce the Loop 4 RBAC + RLS model
   without duplicating TS `requirePermission` logic?

## Decision

### Python transition port (R-011 in CODEX log)

Adopted Option B: port the Loop 6 transition helpers +
candidate-review helpers to Python under
`apps/api-fastapi/wo_wf/`. Rationale:

- Subprocess spawns per request add ~50–100ms latency and fragile
  error handling (signal propagation, Node cold start, subprocess
  lifecycle).
- The declarative state-machine tables
  (`packages/contracts/wo-wf/state_machines.ts` +
  `apps/api-fastapi/contracts/state_machines.py`) are the DAG
  source of truth; the Phase 6.1 parity test asserts byte-identical
  transition tables between TS and Python.
- Helper semantics (load status → check perms → update → audit +
  optional cycle) are captured in ADR-017 and implemented narrowly
  in both languages.

The parity surface grows, but the risk is bounded: both helpers
consume the same table, write audit rows with identical metadata
shape, and fire the same declared event per transition. A future
loop may add a fixture-driven helper-parity test that exercises
both implementations against the same DB state.

### RBAC enforcement via FastAPI Depends

`apps/api-fastapi/deps.py` exposes:

- `require_permission_dep(permission)` — factory returning a
  FastAPI `Depends`. Reads role + role_permissions +
  permission_grants, runs `checkPermissionDecide` (Loop 4 Phase 2
  pure function), writes `authz.denied` on deny via
  `authz.audit_writer.write_audit_row`, raises
  `HTTPException(403)` with the standard
  `{error, permission, reason, role}` body.
- `current_user_context` — dev bearer pair
  `X-IWO3-User` + `X-IWO3-Client` headers. Production auth is
  Loop 9+.
- `get_tenant_scoped_connection` — BEGIN + SET LOCAL ROLE iwo3_app
  + SET LOCAL app.current_client_id; RLS policies from Phase 4.3
  fire on every query.
- `get_db_connection` — bypass-path connection for admin/system
  queries (e.g. the dep factory itself, which writes authz.denied
  rows for callers with no tenant membership — that write would
  otherwise fail RLS's WITH CHECK).

### Route surface

Read routes:
- `GET /tenants` (list member tenants — admin endpoint, no RLS)
- `GET /work_orders` + `/{id}` (RLS-scoped)
- `GET /workflows` + `/{id}`
- `GET /output_packages` + `/{id}`
- `GET /output_handoffs` + `/{id}`
- `GET /audit_log` (owner-only via `audit_log:read`)
- `GET /permissions/check?permission=...` (decider verdict for
  current user; no audit write; Streamlit uses for UI hide/show)

Mutations:
- `POST /work_orders/{id}/transition` (operator/admin gates via
  helper; candidate states 9 → 9 per table)
- `POST /work_orders/{id}/watchdog_expire` (agent_system +
  equivalent)
- `POST /workflows/{id}/transition`
- `POST /output_handoffs/{id}/select_candidate` (reviewer-only)
- `POST /output_handoffs/{id}/reject_candidate` (reviewer-only)

Error mapping is uniform across mutations:
- `PermissionDenied`    → 403 `{error, permission, reason, role}`
- `IllegalTransition`   → 409 `{error, code, from, to}`
- `RowNotFound` / `CandidateHandoffNotFound` → 404
- `CandidateNotEligible` → 409 `{error, handoff_id, current_status}`

### Canonical Python audit writer (R-010 extension)

`apps/api-fastapi/authz/audit_writer.py` is the single allowlisted
path that may `INSERT INTO action_audit_log` on the Python side
(Phase 4.4 lint rule). All FastAPI handlers + Depends that need to
write audit rows must call `write_audit_row(...)`. This keeps the
Phase 4.4 discipline intact across languages.

## Consequences

**Positive**

- Streamlit (Loop 8) has a stable HTTP contract to consume.
- RBAC gates at the HTTP boundary are mechanical: every privileged
  mutation goes through `require_permission_dep(...)` or a
  transition helper that gates internally. No handler invents its
  own permission check.
- Tenant isolation is enforced by RLS on the tenant-scoped
  connection dep; handlers don't construct WHERE clauses for
  isolation — the DB does.
- Same error-shape discipline as the Phase 7.2 transition routes
  means Streamlit's error rendering stays uniform.

**Negative**

- Python port of the transition helpers is new parity surface.
  Mitigated by the declarative tables + ADR-017 semantics + future
  helper-parity test. For Loop 7 the risk is accepted.
- `fileParallelism: false` (R-012) slows the Vitest suite ~2x.
  Acceptable until CI budget ever becomes an issue. The underlying
  race (integration tests mutating shared tables) would need a
  dedicated-fixtures-per-file refactor to fix properly; the
  sequential flag is the pragmatic patch.

**Neutral**

- Dev auth via headers is obviously unsuitable for production.
  Loop 9+ replaces it with a signed token provider; the dep
  signature stays the same, so handlers don't change.

## Alternatives considered

- **TS CLI spawn per request (scope-proposal default)** — rejected
  (R-011): per-request subprocess overhead + fragility outweigh the
  zero-drift benefit. Helper-parity test strategy covers drift
  risk.
- **Asynchronous message bus between TS and Python** — rejected
  for Loop 7 scope: massive infra for no new capability.
- **Gate permissions inside each route handler individually** —
  rejected: duplicates `requirePermission` semantics N times.
  Depends factory is the idiomatic FastAPI pattern.

## References

- `IWO3_LOOP_7_SCOPE_PROPOSAL_v0.1.0.md` §3
- Loop 7 Phase 7.1 commit `43cb21d` / CI run `24659660756`
- Loop 7 Phase 7.2 commit `8e6c4b8` / CI run `24660008762`
- `apps/api-fastapi/deps.py`
- `apps/api-fastapi/wo_wf/transitions.py` +
  `wo_wf/candidate_review.py`
- `apps/api-fastapi/routes/`
- R-011 (Python port) + R-012 (fileParallelism=false) in the CODEX
  overnight log.

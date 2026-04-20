# ADR-014 — RBAC permission model

Date: 2026-04-19
Status: Accepted (Loop 4 Phase 1 + Phase 2; CI green on `c1ab00c` and later `e21b47b`)
Predecessor: ADR-002 (multi-client data boundaries), ADR-011 (WO/WF schema), ADR-012 (output + adapter registry)

## Context

Loop 1 created a six-role enum on `client_memberships.role` but treated
the roles as opaque strings consulted by ad-hoc code paths. Loop 2
added prompt profiles, artifacts, and audit logging; Loop 3 added
WO/WF and the adapter registry. At end-of-Loop-3, privileged mutations
across all of these layers were protected by one of three
inconsistent mechanisms: (a) role-string checks in individual
handlers, (b) service-layer `WHERE client_id = $1` JOINs, and (c)
the adapter registry's `adapter_action_policies` approval-required /
disallowed table.

This left three gaps:

- No typed permission vocabulary. "Admin" meant one thing in prompt
  handlers and another at the adapter boundary; the meaning was
  encoded in each call-site's conditional.
- No per-user override. A specific operator could not be granted a
  single extra permission (e.g. `audit_log:read` for a compliance
  investigator) without widening their role for the whole tenant.
- No forensic trail on denials. A role-string check that refused an
  operator's action left no row in `action_audit_log`.

## Decision

Ship a three-table RBAC model and two helper functions in Loop 4
Phase 1 + Phase 2:

### Schema (Phase 4.1, migration `0005_loop4_phase1_permissions.sql`)

- `permissions(id uuid, permission_key varchar(96) UNIQUE,
  display_name, description, scope enum(global|tenant|resource),
  ...)` — flat vocabulary keyed by `permission_key`. Scope enum is
  metadata for the checker.
- `role_permissions(id, role membership_role, permission_id,
  UNIQUE(role, permission_id))` — role-default mapping.
- `permission_grants(id, user_id, client_id, permission_id,
  grant_type enum(allow|deny), granted_by_user_id nullable, reason
  nullable, UNIQUE(user_id, client_id, permission_id))` — per-user
  per-tenant override. Empty at seed time; populated by runtime
  admin actions.

### Vocabulary (locked upfront, §Q1)

69 permissions covering: client, user, membership, prompt_profile,
prompt_override (style / profile_swap / external_send),
repository_binding, data_source_binding, adapter_config,
adapter_policy, adapter_credential, work_order (create / read /
update / submit / cancel), workflow (create / read / update /
cancel), workflow_template (create / read / update / publish),
workflow_execution (read / update), workflow_step_run (read /
create / update), execution_cycle (create / reopen), output_package
(create / read / update / validate / submit / delete),
output_handoff (create / read / update / record / approve_send),
output_candidate (select / reject), external_execution_result
(create / read), audit_log (read), system:admin.

Locking the vocabulary upfront (per §Q1 `lock_upfront`) trades a
larger initial surface for a stable contract: additive RBAC drift is
much faster than additive audit-event drift, because every handler
references the vocabulary.

### Role defaults (§Q2 Darrel-revised mapping, seeded as 213 rows)

| role         | perms | notes                                                           |
| ------------ | ----- | --------------------------------------------------------------- |
| owner        | 69    | all — including `system:admin` and `user:revoke`                |
| admin        | 67    | all except `system:admin` + `user:revoke` (owner-only)          |
| operator     | 27    | read-within-tenant + WO/WF/execution_cycle write + output       |
|              |       | package up to `submit` + `prompt_override:apply_style`.         |
|              |       | No candidate select/reject, no adapter_config/policy, no        |
|              |       | approve_send, no audit_log:read.                                |
| reviewer     | 17    | read-within-tenant + `output_package:validate` +                |
|              |       | `output_candidate:select/reject` + `apply_style`.               |
| viewer       | 13    | read-within-tenant only.                                        |
| agent_system | 20    | automation identity: narrow + fully explicit (no wildcards).    |
|              |       | WO create/update, workflow update, workflow_execution update,   |
|              |       | workflow_step_run create/update, execution_cycle reopen,        |
|              |       | output_package up to `submit`, output_handoff                   |
|              |       | create/record/update (NEVER `approve_send`),                    |
|              |       | external_execution_result:create. Explicitly excludes           |
|              |       | approve_send, audit_log:read, adapter_credential:rotate,        |
|              |       | any user/membership/client mutation, any delete, any publish.   |

### Resolver (Phase 4.1) — `resolveUserPermissions(db, {userId, clientId})`

Returns `{ role, permissions: Set<string> }` by:
1. Finding the active `client_memberships` row on (user_id,
   client_id). None → empty set, role = null.
2. Loading `role_permissions` for that role.
3. Overlaying `permission_grants` for (user_id, client_id): allow
   adds, then deny removes (deny wins).

### Decision function (Phase 4.2) — `checkPermissionDecide(input)` (pure)

Returns `{ allowed, reason }` where `reason ∈ { role_default |
allow_override | deny_override | no_membership |
role_lacks_permission | unknown_permission }`.

- Shared byte-identically with Python mirror at
  `apps/api-fastapi/authz/check_permission.py`.
- Parity fixtures under `tests/fixtures/authz/*.json`;
  `tests/contract/authz-parity.test.ts` runs the TS implementation
  against the Python CLI for each fixture and asserts equal
  `{allowed, reason, role}`.

### DB-bound + throwing wrappers (Phase 4.2)

- `checkPermission(db, input)` — vocabulary-guards via the
  `permissions` table (unknown keys → `unknown_permission` fail-closed),
  then calls the pure decider.
- `requirePermission(client, input, ctx)` — calls `checkPermission`;
  on deny writes an `authz.denied` audit row (with decision_reason,
  permission, role, target metadata) then throws `PermissionDenied`;
  on allow returns silently. `authz.granted` is deliberately NOT
  emitted — allowed calls are implied by the subsequent typed
  mutation audit row.

### Dispatcher integration (Phase 4.2)

`dispatchToAdapter` gates every dispatch on
`output_package:submit`. Missing `actorUserId` → `authz.denied`
with `decision_reason=no_actor` + `permission_denied` return.
Policy-disallowed / approval-required checks still run downstream
as additive layers (§Q4 `keep_both`).

### FastAPI helper

Deferred to Loop 7 (§Q5 `loop7`). `apps/api-fastapi/authz/` ships
only the pure decision function + CLI until the FastAPI runtime
foundation lands.

## Consequences

**Positive**

- A single typed vocabulary closes the drift risk between handlers
  and external boundaries (adapter registry, channel layer, future
  FastAPI/Streamlit).
- Per-user overrides let compliance / ops hand out minimal extra
  scope without widening a role.
- Every denied privileged action leaves a forensic `authz.denied`
  row; operators can trace who hit which guard when.
- Python parity ensures the FastAPI layer (Loop 7) inherits the
  same decisions, reducing drift risk.

**Negative**

- 69 permissions is larger than the naive "role alone" check. All
  call-sites now pass a permission key instead of a role string,
  adding a small amount of code. Mitigated by `requirePermission`
  being the idiom everywhere.
- The pure decision function loads `role_permissions` + any
  `permission_grants` on every call; Loop 5+ may add a request-
  scoped cache when profiles show this matters.
- Vocabulary is locked upfront, so new privileged actions at later
  loops require a migration to add a permission key. Acceptable vs.
  the RBAC drift risk of additive growth.

## Alternatives considered

- **Role-alone check, no permission table** — rejected because
  cross-layer drift becomes unmanageable by Loop 10.
- **Permission + grant-only (no role_permissions)** — would require
  provisioning every user individually; no default role semantics.
  Rejected for operational overhead.
- **Grow vocabulary additively per phase** — Claude's initial
  preference. Rejected per §Q1: RBAC drifts faster than audit
  vocabulary, and the initial cost of locking upfront is small.

## References

- `IWO3_LOOP_4_SCOPE_PROPOSAL_v0.1.0.md` §3.1 + §3.2
- `IWO3_LOOP_4_APPROVAL_DECISIONS_v0.1.0.md` (Darrel's §Q2 revised
  operator + agent_system mappings)
- Loop 4 Phase 1 commit `d54900c` / CI run `24640946826`
- Loop 4 Phase 2 commit `c1ab00c` / CI run `24641578101`
- Loop 4 Phase 4 commit `e21b47b` (lint rule enforcement) / CI run
  `24644417686`

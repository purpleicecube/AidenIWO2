# ADR-035 — Sandbox as Internal Operator Utility + Node Storage Adapter Carve-Out

**Status:** Accepted with revisions (CODEX, 2026-05-11)
**Authors:** CODEX (architect direction) + Claude Opus 4.7 (implementation)
**Loops:** Sandbox Operational Darkmode (partial, stop-and-escalate) +
            Node Storage Adaptation Darkmode (this loop)
**Predecessor:** ADR-002 (multi-client data architecture), ADR-014 (RBAC),
            ADR-015 (RLS enforcement mode), Loop 4 Phase 4.3 (FORCE RLS on 25 tables)
**Successor:** Path B-b sandbox-only cross-service adapter (next bounded loop, scope-locked per §CODEX Disposition below)

## Context

IWO3 inherited a fully-built Node sandbox surface from IWO2 — schema,
routes, React UI — but the **deployment shape**, the **table itself**,
and the **broader Node storage layer** had never been carried forward.
The Sandbox Operational Darkmode loop (2026-05-10) discovered this in
recon:

1. `sandbox_sessions` table absent from IWO3 Postgres (Node routes 500
   on first call).
2. IWO2-era `sandbox_sessions` schema is **global** (no `client_id`)
   — incompatible with IWO3's FORCE-RLS-on-25-tables tenant posture.
3. The broader Node app's `server/storage.ts` is hardwired to IWO2
   column shapes (`users.first_name/last_name`, `users.role`,
   `work_orders.assigned_sub_agent_id`, `work_orders.tier1_result/tier2_result`,
   `artifacts.name`, etc.). IWO3's Loop 1+ re-shaped most of those
   tables. The Node app cannot read or write them cleanly.
4. The Node auth layer (`server/replit_integrations/auth/`) depends on
   `users.first_name/last_name` and a top-level `users.role` that don't
   exist in IWO3. Login 500s before any operator can reach a route.

Two architectural decisions are required to operationalize the
sandbox in IWO3 without forcing a full Node-IWO3 convergence:

- **Sandbox tenancy posture** — where does `sandbox_sessions` sit on
  the multi-tenant spectrum?
- **Node-side storage adapter posture** — how much of `server/storage.ts`
  do we adapt to IWO3 schema, and where does the line of bounded
  adaptation fall?

## Decision

### 1. Sandbox tenancy — Path A-prime

The `sandbox_sessions` table is migrated into IWO3 as an **internal
operator utility**:

- **No `client_id` column.** The IWO2 shape is preserved verbatim.
- **No FORCE RLS.** Other 25 tenant-scoped tables stay RLS-forced;
  this one is the documented carve-out.
- **Route-level creator-or-admin gate.** `server/routes.ts:_canAccessSandboxSession`
  enforces visibility/mutation only to the row's `created_by` operator
  or to any admin-level user. The gate sits in front of every
  `app.{get,put,delete,post}('/api/sandbox-sessions...')` route.
- **`createdBy` is server-set, not client-trusted.** `POST` overrides
  any caller-supplied `createdBy` with the authenticated user id.
- **Provenance:** migration `0028_sandbox_sessions_internal_utility.sql`;
  manifest entry tagged `iwo2_parity` with explicit ADR-035 note;
  Drizzle parity mirror at `db/schema/sandbox_sessions.ts` carrying
  the carve-out docstring.

### 2. Node storage adapter — Minimum-Viability Carve-Out

Adapt **only** the Node code paths blocking auth + sandbox V1:

- `shared/models/auth.ts` users model rewritten to IWO3 shape
  (`displayName`, `status`, `password_hash`, no firstName/lastName/role).
- `shared/models/auth.ts` adds `clientMemberships` so role lookups
  read from the tenant-scoped membership table (IWO3's source of
  truth) rather than the non-existent `users.role`.
- `server/replit_integrations/auth/storage.ts:authStorage` becomes
  IWO3-aware: `upsertUser` strips IWO2-only fields (firstName,
  lastName, profileImageUrl, role) and writes `display_name`;
  `setUserRole` writes to the user's first `client_memberships` row;
  new `getUserEffectiveRole` resolves the highest-privilege role
  across all memberships.
- `server/routes.ts:requireRole` is adapted to call
  `getUserEffectiveRole` + map IWO3 role names (owner / admin /
  operator / agent_system / reviewer / viewer) onto the legacy
  three-tier (admin / operator / viewer) hierarchy. The synthesized
  `appUser.role` is populated for downstream legacy callers.
- `server/replit_integrations/auth/replitAuth.ts` dev auto-login uses
  a real seeded IWO3 user UUID (`owner_klear@dev.local`) so role
  resolution + sandbox creator gate work naturally without inventing
  a new identity.
- `server/storage.ts:updateUserRole` delegates to
  `authStorage.setUserRole` (memberships path) instead of writing the
  non-existent `users.role` column.

The remaining tables (`workOrders`, `artifacts`, `executionLogs`,
`workflowExecutions`, etc.) the Node app references through
`server/storage.ts` are **deliberately NOT adapted in this loop**.
Touching them would broaden into porting the entire Node app's
storage layer to IWO3 shape — the explicit stop boundary documented
in both the Sandbox Operational scope and the Node Storage Adaptation
scope. The cost is documented in §Consequences below.

### 3. Operational V1 sandbox path

The **operationally usable** sandbox V1 chain on IWO3 is now:

1. Operator authenticates (dev: GET /api/login; prod: POST /api/login
   with credentials).
2. POST `/api/sandbox-sessions` → create session bound to the
   operator's UUID.
3. PUT `/api/sandbox-sessions/:id` with body
   `{result: {html: "...", renderable: true}}` → operator pastes /
   uploads the HTML draft they want to preview.
4. GET `/api/sandbox-sessions/:id/preview` → serves the HTML.
5. POST `/api/sandbox-sessions/:id/publish` → **blocked** until the
   Node `artifacts` schema is adapted (see Consequences).
6. POST `/api/sandbox-sessions/:id/rerender` → **blocked** until the
   Node `workOrders` schema is adapted (see Consequences).

Routes 5 + 6 are operationally useful but require the storage layer
to be adapted further. Per the loop's stop-and-escalate rule, that's
the **next bounded loop**, not this one.

## Consequences

### Positive

- **Sandbox is migrated + secured.** The table exists, the route gate
  is in place, the carve-out is documented, the operator can create
  sessions today.
- **Node auth is viable on IWO3.** Login works. Role resolution works.
  The bulk of `requireRole` callsites (18+ in routes.ts) keep working
  because we synthesize the legacy three-tier role on `appUser.role`.
- **Identity coherence across services.** Dev login binds to a real
  seeded IWO3 user UUID, so the same operator id appears in FastAPI
  audit, Streamlit `appUser`, and Node `appUser` — useful for
  cross-service forensics.
- **Bounded loop discipline preserved.** Both scope briefs (Sandbox
  Operational + Node Storage Adaptation) stopped at the documented
  boundary. Neither absorbed the broader Node-IWO3 storage convergence.

### Negative

- **Sandbox is not tenant-scoped.** A future malicious operator
  could create sessions visible only to themselves but the data
  flowing through `environment.sourceId` could theoretically pull
  cross-tenant data IF the linked source's underlying read is not
  itself tenant-gated. We mitigate by: (a) `rerender` is currently
  blocked on IWO3 anyway, (b) when re-enabled, the rerender code
  must be re-audited to ensure its source-id reads honor RLS or
  tenant scoping. Path B (full `client_id` + FORCE RLS + auth-bridge)
  is the architecturally clean answer but is the next loop, not this
  one.
- **`work_orders` schema mismatch is not fixed.** Any Node code path
  that calls `storage.getWorkOrder(...)` or
  `storage.getWorkOrders()` will 500 on IWO3 because the Drizzle
  schema in `shared/schema.ts` still declares
  `assigned_sub_agent_id`, `tier1_result`, `tier2_result`,
  `processing_attempt_id`, `heartbeat_at`, `gcc_memory`, etc. Known
  hits: `recoverOrphanedProcessingOrders`, `watchdogSweep`,
  `/api/sandbox-sessions/:id/rerender`, and 80% of the rest of
  `routes.ts`. The latter two are non-blocking warnings; sandbox
  rerender returns 500.
- **`artifacts` schema mismatch is not fixed.** Sandbox publish hits
  `column "name" does not exist` because IWO3 artifacts use a
  different column set. Same root cause.
- **Console error spam.** Recovery + watchdog spam the Node log every
  30s with `column "assigned_sub_agent_id" does not exist`. Annoying
  but non-blocking; left as-is for bounded discipline.

### Neutral

- **Hosted deploy is partially unblocked.** Login + create + PUT +
  preview work end-to-end. Rerender + publish do not. A hosted V1
  ship could target only the operator-paste-HTML use case (preview
  only, no publish) — useful but narrow. A useful hosted V1 likely
  wants publish to work, which requires the artifacts-schema
  adaptation that's outside this loop.

## Path B — Successor Loop Scope

When the sandbox is genuinely useful enough that hosted deploy is
worth doing, the **next bounded loop** should be one of:

### Option B-a — Storage-adapter narrow loop

Adapt `shared/schema.ts:workOrders` and `shared/schema.ts:artifacts`
to IWO3 shape. Drop IWO2-only columns. Add IWO3-only columns
(`submitted_by_user_id`, `requested_outputs`, `client_id` on
artifacts, etc.). Update `server/storage.ts` callers that reference
dropped columns to be guards or no-ops. Re-validate rerender + publish.

Estimated ~4-6h of bounded surgery. Result: full sandbox chain
viable on IWO3.

### Option B-b — Sandbox-only adapter loop

Don't touch the broader Node storage layer. Instead: build a
sandbox-specific Node storage helper that:

- Reads work-order data via FastAPI (cross-service) instead of direct
  Drizzle.
- Writes artifacts via FastAPI's `/workspace` route instead of direct
  Drizzle.

Estimated ~3-4h. Result: full sandbox chain viable on IWO3 without
broader Node storage adaptation. Slight performance cost (extra HTTP
hops). Cleaner architectural fit with IWO3's FastAPI-centric posture.

### Option B-c — Full tenancy + auth bridge

The original Path B. Add `client_id` + FORCE RLS + tenant policy to
`sandbox_sessions`. Update Node auth to set the `iwo3_app` role +
`app.current_client_id` GUC like FastAPI's tenant-scoped helper.
Drop the route-level creator-or-admin gate in favor of RLS.

Estimated ~6-8h. Largest loop. Architecturally cleanest. Required
before sandbox is exposed as a tenant-facing product surface (vs
the current "internal operator utility" framing).

## Trigger Conditions for the Successor Loop

Open a Path B loop when **any** of the following becomes true:

1. Operator wants to hosted-deploy the sandbox UI publicly.
2. Operator wants rerender to work against an actual IWO3 WO.
3. Operator wants publish to GitHub Pages working.
4. A tenant other than Klear / FFAI needs access and sandbox
   visibility must be tenant-scoped.
5. The console error spam from recovery/watchdog becomes
   operationally annoying.

Until any of those trigger, the current carve-out is
operationally sufficient for the "paste HTML draft + preview"
use case.

## References

- Sandbox Operational Darkmode scope:
  `WS024_IWO3[Branch]/05_Artifacts/IWO3_DARKMODE_ONESHOT_SCOPE_SANDBOX_OPERATIONAL_v0.1.0.md`
- Node Storage Adaptation Darkmode scope:
  `WS024_IWO3[Branch]/05_Artifacts/IWO3_DARKMODE_ONESHOT_SCOPE_NODE_STORAGE_ADAPTATION_v0.1.0.md`
- Sandbox Operational Darkmode instruction block:
  `WS024_IWO3[Branch]/02_Execution/CLAUDE_INSTRUCTION_BLOCK_SANDBOX_OPERATIONAL_DARKMODE_2026-05-11.md`
- Node Storage Adaptation Darkmode instruction block:
  `WS024_IWO3[Branch]/02_Execution/CLAUDE_INSTRUCTION_BLOCK_NODE_STORAGE_ADAPTATION_DARKMODE_2026-05-11.md`
- Migration: `db/migrations/0028_sandbox_sessions_internal_utility.sql`
- Manifest registration: `infra/local/manifest-populate.ts:113`
- Sandbox route gate: `server/routes.ts:_canAccessSandboxSession`
- Auth adapter: `server/replit_integrations/auth/storage.ts`
- Role resolver: `server/routes.ts:requireRole` + `IWO3_ROLE_TO_LEGACY`

## CODEX Disposition (2026-05-11)

**Verdict:** ACCEPT WITH REVISIONS — accept the V1 partial ship; do not call sandbox "operational" beyond paste/preview yet; open Option B-b as the next bounded loop; keep hosted deploy as a separate loop after B-b, not folded into it.

| Decision | Verdict | Implication |
| --- | --- | --- |
| D-NSA-1 (Path A-prime carve-out) | ACCEPT | Keep as V1 internal-operator-utility framing. Not the final tenancy model. |
| D-NSA-2 (Successor preference) | ACCEPT WITH REVISIONS | Open Option B-b next. **Constraint: keep B-b sandbox-bounded. Do not let it become generic Node/FastAPI data access unification.** |
| D-NSA-3 (Console spam) | ACCEPT | Residual debt, not loop-blocking. Leave alone for now. |
| D-NSA-4 (Client React TS errors) | ACCEPT | Leave alone in this loop. **Make explicit gate in the later hosted-deploy loop. Do not forget them.** |
| D-NSA-5 (Dev login binding) | ACCEPT | Keep dev auto-login bound to seeded Klear owner UUID — least confusing identity posture for now. |
| D-NSA-6 (Bootstrap admin path) | ACCEPT WITH REVISIONS | Current warning-and-return is misleading. Either provision a real membership OR explicitly downgrade/document as non-privileged. **Revised implementation: bootstrap admin now provisions a fresh-UUID user with no membership + emits an explicit `NON-PRIVILEGED (no client_membership)` warning so operators don't assume admin access from env-var-only provisioning. Real-admin-via-env-var requires either auto-membership against a designated tenant OR deprecating this path entirely; both deferred to follow-on.** |
| D-NSA-7 (Internal-utility framing) | ACCEPT | Keep the "internal operator utility" framing in UI surfaces. |

**Explicit gate for the hosted-deploy follow-on loop (post-B-b):**
The 21 client/src/* TS errors on `user.firstName/lastName/profileImageUrl/role` (carried in §Consequences "Negative" above) MUST be addressed before hosted deploy can ship — production `tsc` build of the React app will fail otherwise. This is a hard pre-condition, not an optional cleanup.

**Path B-b scope lock (from CODEX revisions):**
The successor loop is a **sandbox-only** cross-service adapter. Reads work-order data via FastAPI calls; writes artifacts via FastAPI `/workspace`. Does NOT touch:

- Generic Node `server/storage.ts` methods unrelated to sandbox
- Any non-sandbox client/server feature
- The broader Node-IWO3 schema convergence question

Any drift into generic Node/FastAPI data access unification is a stop-and-escalate trigger.

## Path B-b — Shipped Shape (2026-05-11)

The successor loop landed on `iwo3/main` with three operator-locked choices applied:

### sourceId model — Option (a) Artifact UUID only

`session.environment.sourceId` is now an IWO3 workspace artifact UUID, not a work-order UUID. The sandbox rerender route fetches the artifact's text content via a thin Node→FastAPI helper at `server/sandbox-crossservice.ts` calling the existing `GET /workspace/files/:id/content` route. No new FastAPI route was needed. No WO-preview seam was added. Auto-detect was rejected.

### Publish recording — Option (a) Skip IWO3 artifact write

The `storage.createArtifact` call (which was the IWO2-artifacts-schema crash point) was removed entirely. Successful publish now returns the GitHub Pages URL only; the publish outcome is recorded in the sandbox session's `logs` array and `result.publish` subfield. The sandbox session IS the record. No FastAPI workspace-write seam, no auth bridge.

### GITHUB_TOKEN validation — Option (b) Validate up to missing-token boundary

`publishToGitHubPages` returns `{success: false, error: "GITHUB_TOKEN env var is required..."}` when the token is missing. The sandbox publish route translates that specific error into **HTTP 412 PRECONDITION REQUIRED** with `kind: "github_token_missing"` so operators see a clear "provision a token" signal. Real-token provisioning is an operator follow-on, not a B-b loop deliverable.

### Cross-service seam shape

The single new module — `server/sandbox-crossservice.ts` — exports exactly one public function: `fetchSandboxArtifactContent(artifactId, actorUserId)`. It:

- Looks up the operator's primary client_id via `client_memberships` (single-tenant V1 assumption)
- Calls FastAPI at `process.env.IWO3_FASTAPI_BASE_URL || http://127.0.0.1:8000`
- Authenticates via the FastAPI dev-auth headers (`X-IWO3-User` + `X-IWO3-Client`)
- Returns `SandboxArtifactContent` on success or `SandboxArtifactReadError` (with `kind` discriminant) on failure

**The module is intentionally not a generic platform adapter.** Module-level docstring + scope-lock comments call this out explicitly. The single export is sandbox-shaped.

### Validated chain on IWO3 (2026-05-11)

```text
GET  /api/login                                 → 200 (dev auto-login, Klear owner)
POST /api/sandbox-sessions                      → 201 (createdBy server-set)
PUT  /api/sandbox-sessions/:id                  → 200 (environment.sourceId = artifact UUID)
POST /api/sandbox-sessions/:id/rerender         → 200 (1745b HTML from markdown artifact)
GET  /api/sandbox-sessions/:id/preview          → 200 (HTML served verbatim)
POST /api/sandbox-sessions/:id/publish          → 412 (github_token_missing, clean operator signal)
```

8/8 sandbox chain steps now functional. The chain is operationally complete pending GITHUB_TOKEN provisioning for live publish.

### Residual debt remaining after B-b

1. **Auth bridge for hosted deploy.** The dev-header path the cross-service seam uses works for local validation only. Hosted deploy needs a real session-cookie ↔ FastAPI-bearer-token bridge. Deferred to the hosted-deploy loop.
2. **21 client/src/* TS errors.** Unchanged (still deferred per D-NSA-4). **Hard precondition for the React app's production build — addressed in the TS-errors/UI loop that precedes hosted deploy** (per CODEX D-BB-5/D-BB-7).
3. **Sandbox React UI page (`client/src/pages/sandbox.tsx`).** Still references the old WO-based source-id model and the old publish response shape (artifactId). Must be updated in lockstep with the TS-errors loop — **gating precondition for hosted deploy** per CODEX D-BB-7.
4. **WO-source-id rerender path.** Option (b) from the original pre-flight (`session.environment.sourceId = work-order UUID`) was deliberately not built. **CODEX D-BB-5 explicitly deprioritized this** — no evidence yet that it's the highest-value operator win. Open only if a concrete demand surfaces.
5. **Non-text artifact rendering.** Path B-b V1 only handles `encoding: utf-8` artifacts. Binary/image preview from base64-encoded artifacts is a follow-on if demand surfaces.
6. **Single-tenant client_id assumption — local/dev posture only.** `fetchSandboxArtifactContent` picks the actor's first membership. Per CODEX D-BB-4: **this MUST NOT silently survive into hosted deploy.** The hosted-deploy loop is required to make tenant binding explicit — most likely via `session.environment.clientId` set at session creation or a per-request `X-IWO3-Client` header surfaced through the operator UI. Recorded here as a hard pre-condition for hosted-deploy scope.

## CODEX Disposition on Path B-b (2026-05-11)

**Verdict:** ACCEPT WITH REVISIONS — Path B-b is the canonical sandbox V1 cross-service seam; treat sandbox as operationally complete for local/dev use, with live publish gated only by token provisioning. Two revisions integrated:

| Decision | Verdict | Action taken |
| --- | --- | --- |
| D-BB-1 (Seam shape) | ACCEPT | No change. Sandbox-bounded helper stands. No extra abstraction work. |
| D-BB-2 (412 for missing token) | ACCEPT | No change. 412 matches the locked precondition model. |
| D-BB-3 (Env var name) | ACCEPT | No change. `IWO3_FASTAPI_BASE_URL` with `FASTAPI_BASE_URL` fallback. |
| D-BB-4 (Single-tenant first-membership) | ACCEPT WITH REVISIONS | **Local/dev posture only.** Recorded as a hard pre-condition for hosted-deploy in §Residual debt #6. Hosted deploy must make tenant binding explicit. |
| D-BB-5 (Next-loop ordering) | ACCEPT | Open the next loop as: (1) TS errors + sandbox React UI updates, then (2) hosted deploy / auth bridge. Do NOT open the WO-source-id extension next. |
| D-BB-6 (Console spam) | ACCEPT | No change. Stays deferred. Fold cleanup into hosted-deploy loop if it still matters then. |
| D-BB-7 (Sandbox UI bundle scope) | ACCEPT WITH REVISIONS | **Bundle sandbox UI updates with the TS-errors loop, NOT with hosted deploy.** Cleaner pre-hosting gate: (a) fix client/src/* typing; (b) update sandbox page to artifact-UUID source model; (c) update publish response handling; (d) THEN hosted deploy / auth bridge. |

## Next-Loop Ordering (Locked)

Per CODEX D-BB-5 / D-BB-7 (Path B-b) and D-AEP-A5 / D-AEP-A6 (Aiden Evaluator Parity), the next three bounded loops are sequenced:

### Loop α — TS errors + sandbox React UI updates (next)

Combined scope:

- Fix the 21 `client/src/*` TS errors on `user.firstName/lastName/profileImageUrl/role`
- Update `client/src/pages/sandbox.tsx`:
  - Send artifact UUID (not work-order UUID) when linking a session
  - Consume the new publish response shape (no `artifactId` field)
- Validate `tsc` clean (production React build viable)
- Stop. Do NOT roll hosted deploy into this loop. Do NOT absorb evaluator-page polish (D-AEP-A7 lock).

### Loop γ — Evaluator/Operator-action sweep (after Loop α; before Loop β)

Inserted per D-AEP-A5 + D-AEP-A6. Cleans up the legacy IWO2 React buttons that still call broken IWO2 Express handlers on the evaluator page. Per D-AEP-A6 "visible-but-broken is NOT a stable posture":

For each legacy button (process / retry / archive / kill / refile / defer / repair / unblock-reissue / unblock-close):

- **Hide** if the action has no IWO3-side equivalent and isn't operationally necessary, OR
- **Disable with an explicit "not yet supported in IWO3" tooltip / inline message** if the action will eventually return, OR
- **Rewire to FastAPI** where a bounded path already exists or can be added cheaply

Scope-lock for Loop γ:

- React work-order-detail page button cleanup only
- No new FastAPI route work unless it's a thin proxy for an existing IWO3-native action
- No Streamlit work
- No hosted deploy work
- No new operator-action vocabularies invented

### Loop β — Hosted deploy + auth bridge (after Loop γ)

Combined scope, gated by Loop α + Loop γ:

- Auth bridge: session-cookie ↔ FastAPI-bearer-token mapping
- **Explicit tenant binding** for the cross-service seam (per D-BB-4 + D-AEP-A5 revisions)
- Hosted Node service on Railway (Dockerfile + railway.json second service)
- Streamlit hop / operator entry surface decision
- Live publish validation against an operator-provisioned `GITHUB_TOKEN`
- Console-spam cleanup (per D-BB-6) if still operationally annoying

Either loop can be scoped + opened by CODEX when ready. The WO-source-id rerender extension is NOT on the critical path — open only on concrete operator demand.

## CODEX Disposition on Aiden Evaluator Parity Loop (2026-05-11)

**Verdict:** ACCEPT WITH REVISIONS — accept the shipped loop; keep the explicit review-role allowlist; keep the dual audit events; insert a new bounded evaluator/operator-action sweep loop (Loop γ) before hosted deploy; do NOT let Loop α sprawl into evaluator parity part two.

| Decision | Verdict | Action taken |
| --- | --- | --- |
| D-AEP-A1 (Audit-derive role-tag allowlist) | ACCEPT WITH REVISIONS | Keep the explicit allowlist as canonical V1. NO fuzzy `contains("review")` heuristic. **Inline comment added in `routes/work_orders.py:_AIDEN_REVIEW_ROLES` documenting the posture: extend only from observed audit evidence when a real miss appears, not speculatively.** |
| D-AEP-A2 (Express-proxy module scope) | ACCEPT | No change. Convention-based scope-lock comments in `server/fastapi-proxy.ts` are sufficient. No lint enforcement loop opened. |
| D-AEP-A3 (State-machine extension scope) | ACCEPT | No change. `awaiting_operator → completed` is the right kind of narrow lifecycle addition for a first-class accept action. |
| D-AEP-A4 (Dual-write `accepted` + `transitioned`) | ACCEPT | No change. Transition tells you what changed; accept tells you why in evaluator semantics. Do not collapse them. |
| D-AEP-A5 (Next-loop ordering update) | ACCEPT WITH REVISIONS | **Loop γ inserted between Loop α and Loop β** (see §Next-Loop Ordering above). The evaluator surface still has visible legacy buttons that 500 on IWO3; clean those before hosted deploy. |
| D-AEP-A6 (Legacy IWO2 React buttons posture) | ACCEPT WITH REVISIONS | **"Visible-but-broken" is NOT a stable posture.** Loop γ owns the cleanup per three-option playbook (hide / disable-with-explicit-message / rewire-to-FastAPI). |
| D-AEP-A7 (Loop α scope growth) | ACCEPT | Loop α stays scoped to TS/build + sandbox React only. Evaluator-page polish belongs in Loop γ, not in Loop α. |

**Bottom line per CODEX:**

- Accept the AEP loop as shipped
- Keep the explicit review-role allowlist + the dual audit events
- Insert Loop γ (evaluator/operator-action sweep) before hosted deploy
- Loop α does not grow to absorb evaluator parity part two

## Aiden Evaluator Parity Loop — Shipped Shape (2026-05-11)

A separate bounded loop opened and closed the evaluator-parity gap distinct from the sandbox surface. Note this is technically outside ADR-035's original sandbox scope, but documented here because the loop reuses the same Express→FastAPI proxy posture B-b established and shares the four locked-choice discipline.

### Four operator-locked choices

| Lock | Choice | Implementation |
| --- | --- | --- |
| D-AEP-1 (Aiden review storage) | (b) best-effort audit-derive with strict `aiden_review: null` fallback | New `GET /work_orders/{id}/evaluator_summary` scans `action_audit_log` for `llm.invoked` events with `metadata.agentRole` in `{aiden_review_pm, pm_review, quality_review, aiden_quality, aiden_judge}`; most-recent-wins; null when no match. NO persistent review-write path opened. |
| D-AEP-2 (Operator accept) | (a) thin new FastAPI route | New `POST /work_orders/{id}/accept` route. Dedicated `work_order.accepted` audit event distinct from the routine `work_order.transitioned`. State machine extended with `awaiting_operator → completed` spec (TS + Py parity). |
| D-AEP-3 (React → FastAPI auth) | (b) Express proxy | New `server/fastapi-proxy.ts` module. Translates `req.user.claims.sub` → `X-IWO3-User` + first-membership client_id → `X-IWO3-Client` dev-auth headers. React session model unchanged. No client-side auth bridge opened. |
| D-AEP-4 (TS error overlap with Loop α) | (a) minimal unblocker fixes only | Zero TS errors introduced. The 21 pre-existing client/src/* errors remain deferred to Loop α (hard pre-condition for hosted-deploy). |

### Shipped surfaces

- **FastAPI** (`apps/api-fastapi/routes/work_orders.py` — 2 new endpoints):
  - `GET /work_orders/{id}/evaluator_summary` — unified read returning `{work_order, aiden_review, done_contract, candidate_review, checklist, reopen_metadata}`
  - `POST /work_orders/{id}/accept` — explicit operator-accept with rationale, writes `work_order.accepted` audit row distinct from the routine transition event

- **State machine** (`apps/api-fastapi/contracts/state_machines.py` + `packages/contracts/wo-wf/state_machines.ts`):
  - New `awaiting_operator → completed` transition (event=`work_order.transitioned`, requires=`work_order:update`). The dedicated `work_order.accepted` audit event is written by the route handler on top of the transition.

- **Audit vocabulary** (`packages/contracts/audit/events.ts`):
  - New event `WORK_ORDER_ACCEPTED = "work_order.accepted"`
  - New per-loop array `LOOP_AEP_AUDIT_EVENTS = [WORK_ORDER_ACCEPTED]`
  - Contract snapshot regenerated: 148 audit events (was 147), 92 permission keys (unchanged), 49 db enums (unchanged)

- **Express proxy** (`server/fastapi-proxy.ts` — new module, 138 lines):
  - Single export `proxyToFastApi(fastapiPathFn, opts)`
  - Sandbox-bounded scope (evaluator-only); explicit module-level scope-lock comment
  - 7 paths wired through:
    - `GET /api/work-orders/:id/evaluator-summary`
    - `PUT /api/work-orders/:id` (inline edit)
    - `POST /api/work-orders/:id/reopen`
    - `POST /api/work-orders/:id/redispatch`
    - `POST /api/work-orders/:id/accept`
    - `POST /api/work-orders/:id/candidates/:recordId/select`
    - `POST /api/work-orders/:id/candidates/:recordId/reject`
  - Proxy routes registered BEFORE legacy Express handlers so Express's first-match wins

- **React work-order detail page** (`client/src/pages/work-order-detail.tsx`):
  - New `useQuery<EvaluatorSummary>` for `/api/work-orders/:id/evaluator-summary`
  - `QualityReviewSummary` component extended with `aidenReviewFromSummary` prop; falls back to audit-derived review when IWO2-shape `order.gccMemory["gcc.metadata"].qualityReview` is absent
  - `acceptMutation` re-pointed from `/api/work-orders/:id/unblock?reprocess=false` to `/api/work-orders/:id/accept` (Express proxy → FastAPI accept route)
  - Zero new TS errors introduced

### Validated chain on IWO3

```text
GET  /api/login                                                  → 200 (Klear owner)
GET  /api/work-orders/:id/evaluator-summary                     → 200
  work_order.status: awaiting_operator
  aiden_review: { score: 0.68, recommendation: "revise",
                  flagged: True, agent_role: "pm_review",
                  source: "audit_derived" }
  done_contract: { status: "awaiting_operator",
                   required_action: "Operator review required — accept or send back" }
  candidate_review: null
  checklist entries: 1 (the seeded llm.invoked event)
  reopen_metadata: null

POST /api/work-orders/:id/accept (Express proxy → FastAPI)     → 200
  body: { reason: "Loop AEP validation — accepting the deliverable." }
  response: { from: "awaiting_operator", to: "completed",
              event: "work_order.transitioned", cycle_id: null }

DB state after accept:
  work_orders.status = completed
  audit events: ['llm.invoked', 'work_order.transitioned', 'work_order.accepted']
                — three rows; `work_order.accepted` forensically
                  separable from the routine transition event.
```

### Test coverage

- **AEP pytest suite** (`apps/api-fastapi/tests/test_work_orders_aep_route.py`): 13/13 green
  - `evaluator_summary`: basic shape, audit-derive happy path, alternative role-tag, unknown role doesn't match, cross-tenant 404, checklist contains audit rows
  - `accept`: happy path from awaiting_operator, happy path from processing, no reason still works, rejected from completed, rejected from pending, viewer denied, cross-tenant 404
- **Loop Xi suite**: 20/20 unchanged
- **WO route base suite**: 20/20 unchanged
- **Combined**: 53/53 across the three WO suites

### Residual gaps after Aiden Evaluator Parity

1. **No persistent quality-review-write surface.** Audit-derive is best-effort; downstream feature work that wants to PUT a structured review (separate from a generic llm.invoked event) needs its own bounded loop. Per D-AEP-1 lock, NOT opened here.
2. **Same single-tenant `client_id` assumption as Path B-b.** The Express proxy uses the operator's first `client_memberships` row. Path B-b §Residual debt #6 already records this as a hard pre-condition for hosted deploy.
3. **Legacy IWO2 Express handlers for non-evaluator paths still exist** in `server/routes.ts` (process / retry / unblock / archive / kill / refile / etc.). They 500 on IWO3 schema when invoked. The React page has buttons for these. **Per CODEX D-AEP-A6 disposition: "visible-but-broken" is NOT a stable posture.** Cleanup is owned by Loop γ (evaluator/operator-action sweep), inserted between Loop α and Loop β per §Next-Loop Ordering — each button gets hidden, disabled with an explicit "not yet supported in IWO3" message, or rewired to FastAPI.
4. **`order.tier1Result` / `order.tier2Result` / `order.gccMemory` / `order.bdmMarker`** field reads in the React page still query IWO2-shape fields. `QualityReviewSummary` has the fallback; other sections do not. Out of scope per minimal-unblocker rule; the sections degrade gracefully (TypeScript `as` casts return `undefined`/`null` rather than throw).
5. **The 21 client/src/* TS errors** are unchanged. Loop α responsibility (hard pre-condition for hosted deploy).

---

## Sandbox Everywhere Darkmode (2026-05-11)

### Loop posture

This loop partially supersedes the α/γ/β ordering for sandbox-critical
work only. It absorbs:

- the **sandbox-critical** slice of Loop α (the React shell brand string
  + role-display fix that hid the Sandbox menu link)
- the **sandbox-critical** slice of Loop β (the Node service hosted
  deploy artifacts)

Loop γ remains scoped at the evaluator/operator-action button sweep and
is **NOT** absorbed. Loop α retains the remaining 17 TS errors across
dashboard / submit-order / user-management / work-order pages.

### Locked positions

1. **Canonical sandbox UI** is the React page at
   `client/src/pages/sandbox.tsx`. There is no parallel Streamlit
   sandbox surface and there must not be one.
2. **Streamlit `/sandbox`** at `apps/console-streamlit/views/sandbox.py`
   is a launcher / health card / setup-notes page only. It probes
   `/api/health` on the Node service and renders a primary "Open
   Sandbox ↗" link. Source URL: `IWO3_SANDBOX_URL` or
   `IWO3_NODE_BASE_URL` env var, defaulting to `http://localhost:5050`.
3. **Hosted reachability**: a second Railway service runs the Node/
   React surface alongside the existing FastAPI service. `Dockerfile.node`
   + `railway.node.json` ship at repo root. Operator runbook at
   `docs/runbooks/sandbox_hosted_deploy.md`. Auth uses the existing
   `BOOTSTRAP_ADMIN_PASSWORD` path.
4. **Source artifact support**: md / html / code / text natively;
   PDF / PPTX / DOCX **when** `artifacts.extracted_text` is populated
   and not prefixed with `b64:`.
5. **HTML→PDF / HTML→PPTX export** wires the existing repo scripts
   (`server/scripts/html-to-{pdf,pptx}.cjs`) behind a new endpoint
   `GET /api/sandbox-sessions/:id/export?format=pdf|pptx`. Returns
   `412 skills_unavailable` when Playwright / claude-office-skills are
   absent. **Local: works** with `SKILLS_DIR` + `PLAYWRIGHT_PATH` set.
   **Hosted: 412** until the Railway image bundles or mounts those
   dependencies (residual, captured below).
6. **React shell fixes**: `AIDEN_IWO2 → AIDEN_IWO3` brand strings in
   `app-sidebar.tsx`; user.firstName fallback to displayName/email;
   `GET /api/auth/user` now returns `role` (mapped from the user's
   highest-rank `client_memberships` role via the `IWO3_ROLE_TO_LEGACY`
   table — owner/admin → admin, operator/agent_system → operator,
   reviewer/viewer → viewer). The Sandbox menu link is no longer
   hidden for operators.

### Shipped shape

| Surface | File | Status |
| --- | --- | --- |
| Canonical React sandbox | `client/src/pages/sandbox.tsx` | Aligned to Path B-b: dropped `publishedArtifactId` + broken unpublish flow, hydrate `publishedUrl` from `session.result.publish`, new-session dialog accepts artifact UUID, Re-publish button replaces Unpublish, Export PDF + Export PPTX buttons |
| Sandbox cross-service helper | `server/sandbox-crossservice.ts` | `SandboxArtifactContent.extractedFrom?: string` added |
| Sandbox rerender route | `server/routes.ts` | Surfaces `extractedFrom` on the rerender log; gives a specific "PDF/PPT/DOC with no extracted text" error when the binary path is empty |
| Sandbox export route | `server/routes.ts` | New `GET /api/sandbox-sessions/:id/export?format=pdf|pptx` |
| FastAPI content endpoint | `apps/api-fastapi/routes/workspace.py` | New `_EXTRACTABLE_BINARY_MIMES` branch returns utf-8 + `extracted_from=<mime>` for PDF/PPTX/DOC artifacts with populated `extracted_text` |
| Auth user endpoint | `server/replit_integrations/auth/routes.ts` | Returns `{...user, role, effectiveRole}` so the React sidebar role gate stops defaulting to viewer |
| React shell branding | `client/src/components/app-sidebar.tsx` | `AIDEN_IWO2` → `AIDEN_IWO3`; displayName-driven initials + footer name |
| Streamlit launcher | `apps/console-streamlit/views/sandbox.py` | Launcher card + live Node health probe + local + hosted setup notes |
| Hosted Node Dockerfile | `Dockerfile.node` (repo root) | Node 20 slim builder→runtime two-stage |
| Hosted Node Railway config | `railway.node.json` (repo root) | Dockerfile builder, healthcheck `/api/health` |
| Hosted Node ignore list | `.dockerignore` (repo root) | Trims context for Node image build |
| Hosted Node operator runbook | `docs/runbooks/sandbox_hosted_deploy.md` | Service relationship diagram + env-var matrix + Streamlit wiring |

### Tests

- `apps/api-fastapi/tests/test_workspace_route.py`: +2 tests
  (`test_file_content_fetch_surfaces_pdf_extracted_text_as_utf8`,
  `test_file_content_fetch_returns_base64_for_binary_pdf`). Total
  pytest = **555 passed / 1 skipped**.
- Streamlit smoke = **27 passed** (25 view-imports + 2 app-loads).
- `npx tsc --noEmit`: 17 errors on `client/src/pages/{dashboard,
  submit-order, user-management, work-orders, work-order-detail}.tsx`
  — **all pre-existing, none in sandbox.tsx or app-sidebar.tsx**.
- `npm test` (vitest): 2 failures pre-existing and untouched by this
  loop (state-machine transition count drift + lint-clean flag on
  unrelated `test_work_orders_aep_route.py`). Not regressions.

### Residual debt after Sandbox Everywhere

1. **Hosted HTML→PDF / HTML→PPTX export** returns `412 skills_unavailable`
   on Railway because the Node image is intentionally lean. Fix
   options: bundle Playwright + skills into the Node image (~150 MB+
   added) or stand up a dedicated render worker. Captured as Sandbox
   Export Worker follow-on; not in scope here.
2. **`SKILLS_DIR` defaults to `/home/virgina/claude-office-skills`** in
   the script header. This is fine locally; operators outside that
   path must set `SKILLS_DIR` + `PLAYWRIGHT_PATH` explicitly. Hard-
   coded path is a known IWO2 carry-over that the render-worker loop
   should normalize.
3. **No live PDF/PPTX test data in IWO3** as of this loop. The
   extracted-text utf-8 path is unit-tested via the synthetic
   `mime_type=application/pdf, content_text="..."` shape but no real
   PDF upload + extract chain has been exercised end-to-end on
   `aiden_iwo3`.
4. **17 remaining client/src/* TS errors** stay Loop α responsibility.
   Sandbox + sidebar are now clean.
5. **Single-tenant `client_id` assumption** in `sandbox-crossservice.ts`
   (`getUserPrimaryClientId` returns the first membership) — same
   condition as Path B-b §Residual debt #6 and AEP §Residual gap #2.
6. **Two vitest pre-existing failures** (state-machine transition
   count = 37 vs expected 36; lint-clean flag on
   `test_work_orders_aep_route.py:92`) need a follow-up cleanup loop
   to lock the canonical numbers in tests. Sandbox-untouched.

# ADR-035 — Sandbox as Internal Operator Utility + Node Storage Adapter Carve-Out

**Status:** Accepted (2026-05-11)
**Authors:** CODEX (architect direction) + Claude Opus 4.7 (implementation)
**Loops:** Sandbox Operational Darkmode (partial, stop-and-escalate) +
            Node Storage Adaptation Darkmode (this loop)
**Predecessor:** ADR-002 (multi-client data architecture), ADR-014 (RBAC),
            ADR-015 (RLS enforcement mode), Loop 4 Phase 4.3 (FORCE RLS on 25 tables)

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

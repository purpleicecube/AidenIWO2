# ADR-015 — PostgreSQL RLS enforcement mode + `withTenantContext` pattern

Date: 2026-04-19
Status: Accepted (Loop 4 Phase 3; CI green on `9fe8e0f`, run `24644220627`)
Predecessor: ADR-002 (tenant isolation deferred RLS to Loop 4),
             ADR-010 (audit log partitioning), ADR-011 / ADR-012
             (tenant-scoped runtime schema)

## Context

Through end-of-Loop-3, tenant isolation in IWO3 was enforced entirely
in the application layer — every handler that read or wrote a
client-scoped table carried a `WHERE client_id = $1` predicate or
JOINed through `client_memberships`. The service-layer filter was
captured by 11 isolation test files and the Loop 4 Phase 4.4 lint
rule, but it remained one forgotten predicate away from a cross-
tenant bleed.

Risk D02 from the v0.1.2 register has tracked this gap since Loop 1:
"App-layer-only tenant enforcement relies on developer discipline."
Loop 2 Phase 1 decision memo (§Q1) deferred RLS explicitly to Loop 4.
Loop 4 Phase 3 is where it lands.

## Decision

Adopt PostgreSQL Row-Level Security with `FORCE ROW LEVEL SECURITY`
on 25 tenant-scoped tables + a narrow `iwo3_app` runtime role +
`withTenantContext` helper.

### Role model

Two Postgres roles:

| role       | attributes                                        | used by                                                                        |
| ---------- | ------------------------------------------------- | ------------------------------------------------------------------------------ |
| `iwo3`     | SUPERUSER + BYPASSRLS + LOGIN (POSTGRES_USER default) | migrations, seeds, admin ops, existing Loop 1/2/3 integration tests          |
| `iwo3_app` | NOLOGIN, no BYPASSRLS, non-superuser. Granted to `iwo3` for SET ROLE. | runtime handlers via `withTenantContext` transaction scope                      |

The `iwo3_app` role is deliberately **not** a credentialed LOGIN role;
it is only reachable via `SET LOCAL ROLE iwo3_app` within a
transaction started by an `iwo3` connection. Loop 7 FastAPI may elect
to provision a credentialed LOGIN role with identical attributes for
the runtime; that is a Loop 7 decision and does not change the RLS
policies.

### Enforcement mode — FORCE ROW LEVEL SECURITY (§Q3 `confirm`)

Every tenant-scoped table sets both:

```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE ROW LEVEL SECURITY;
```

`FORCE` means the table owner is also subject to policy — except
that the `iwo3` owner also has BYPASSRLS, so it bypasses RLS
entirely. This is the intended two-track design:

- `iwo3` paths: RLS silently bypasses → migrations, seeds, admin,
  and Loop 1/2/3 tests continue unchanged.
- `iwo3_app` paths: RLS is fully enforced → runtime queries must go
  through `withTenantContext`.

### Policy template

**Tables with a direct `client_id` column** (18 tables):

```sql
CREATE POLICY <t>_tenant_iso ON <t> FOR ALL
  USING      (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid)
  WITH CHECK (client_id = nullif(current_setting('app.current_client_id', true), '')::uuid);
```

`nullif(..., '')` is critical: when the GUC is unset,
`current_setting` returns an empty string, and `''::uuid` raises
`invalid input syntax for type uuid`. `nullif` turns empty → NULL
→ `client_id = NULL` → NULL (falsy) → 0 rows. Fail-closed
without error noise.

**`clients` (special)**: `id = nullif(...)::uuid` — the id IS the tenant.

**`users` (special)**: read-only via shared membership. No
INSERT/UPDATE/DELETE policy → writes blocked for iwo3_app. Superuser
(`iwo3`) bypasses and can write.

```sql
CREATE POLICY users_tenant_read ON users FOR SELECT
  USING (id IN (
    SELECT user_id FROM client_memberships
    WHERE client_id = nullif(current_setting('app.current_client_id', true), '')::uuid
      AND status = 'active'
  ));
```

**Nested tables** (5 tables: `workflow_templates`,
`workflow_template_steps`, `workflow_step_runs`,
`prompt_profile_versions`, `external_execution_results`): EXISTS
against the closest parent that carries `client_id`. Transitive
because the parent table's own policy also filters by the GUC; the
nested EXISTS subquery is a two-hop verification.

**Partitioning**: `action_audit_log` is partitioned by
`created_at`; in PG 16, policies on the parent auto-apply to all
partition children, and new monthly partitions created by
`ensure_audit_partition_for()` inherit automatically.

### Excluded tables (tenant-agnostic — 5 tables)

- `permissions` — locked vocabulary, shared across tenants
- `role_permissions` — role defaults, shared across tenants
- `adapter_catalog` + `adapter_actions` — adapter kind registry
- `migration_source_manifest` — schema ownership ledger

### `withTenantContext` helper

```ts
await withTenantContext(pool, { clientId }, async (c) => {
  const { rows } = await c.query(
    `INSERT INTO output_packages (...) VALUES (...) RETURNING id`
  );
  return rows[0].id;
});
```

Internals:

```
BEGIN
SELECT set_config('app.current_client_id', '<uuid>', true)  -- SET LOCAL
SET LOCAL ROLE iwo3_app
<fn(client)>
COMMIT  (or ROLLBACK on throw)
```

`SET LOCAL` scopes both the role and GUC to the transaction; the
connection returns to the pool in a neutral state. A sibling
`useTenantContext(client, opts)` variant sets the role + GUC on a
caller-owned transaction for tests that need finer control.

### Defense-in-depth (§Q4 `keep_both`)

Loop 4 explicitly keeps the service-layer `client_id = $1` JOIN
filters through at least Loop 10. RLS is the belt; the service-layer
filter is the suspenders. Phase 4.4 lint rule
`require-tenant-scope-on-client-tables` closes the human-error risk
on the service-layer side.

The dispatcher transition from `iwo3` → `withTenantContext(iwo3_app)`
is a Loop 5+ concern; for Loop 4 it continues to run under `iwo3`
superuser + the new authz gate, proving the RLS suspenders work
through dedicated tests (`rls-tenant-isolation.test.ts`) without
rewriting existing code paths.

## Consequences

**Positive**

- D02 (app-layer-only enforcement) closes. Any future handler that
  connects via `iwo3_app` gets tenant isolation automatically, even
  if the developer forgets the JOIN predicate.
- `WITH CHECK` prevents cross-tenant writes at the DB layer. An
  operator context cannot INSERT an `artifacts` row with a
  different tenant's `client_id`, regardless of what the service
  code says.
- `authz.denied` + `permission_denied` (ADR-014) + RLS + JOIN
  filter + lint rule form a four-layer defense. The per-layer
  failure surface shrinks dramatically.

**Negative**

- Requires a transaction for every runtime query (the `SET LOCAL`
  scoping mechanism). Callers who previously used `pool.query(...)`
  directly now wrap in `withTenantContext`. Net: one more level of
  indentation + a commit/rollback round-trip. Acceptable for the
  safety gain.
- The empty-GUC cast trap (R-003 in the CODEX log) means future
  policy authors must remember the `nullif(..., '')` pattern. The
  migration + lint tests are the canonical examples.
- Nested-table policies pay an EXISTS lookup per row. Performance
  impact trivial at Loop 4 fixture size; Loop 5+ should re-evaluate
  if scale pushes this.

## Alternatives considered

- **Leave RLS out entirely; rely on JOIN filters + lint** —
  rejected because it leaves D02 open indefinitely. The lint rule
  catches the discipline issue at PR-time, but a live production
  path that's already merged remains vulnerable.
- **ENABLE RLS without FORCE** — rejected per §Q3. Without FORCE,
  the table owner (iwo3) bypasses RLS through ownership-exemption
  alone, and the safety net exists only for non-owner connections.
  Adding `iwo3_app` without `FORCE` would mean connecting as
  iwo3_app specifically is still a caller choice, not an invariant.
- **Credentialed `iwo3_app` LOGIN role instead of SET ROLE** —
  rejected for Loop 4. Adds credential-management surface before
  FastAPI needs it. Loop 7 may revisit.
- **Drop the JOIN filters in Loop 5** — rejected per §Q4 at
  Darrel's direction. Belt-and-suspenders through Loop 10; the
  overlap cost is minimal and the failure mode visibility is
  maximal.

## References

- `IWO3_LOOP_4_SCOPE_PROPOSAL_v0.1.0.md` §3.3
- `IWO3_LOOP_4_APPROVAL_DECISIONS_v0.1.0.md` §Q3 / §Q4
- `db/migrations/0006_rls_tenant_isolation.sql`
- `packages/contracts/db/tenant_context.ts`
- `tests/integration/rls-force-enabled.test.ts`
- `tests/integration/rls-tenant-isolation.test.ts`
- Loop 4 Phase 3 commit `9fe8e0f` / CI run `24644220627`
- Risk register v0.1.7 (D02 closed; D08 drizzle-kit meta drift still
  open; D09 new: RLS GUC empty-string cast trap — mitigated by
  `nullif` pattern, lint tests are canonical example)

# ADR-009 — Tenant-scoped artifact storage

Date: 2026-04-19
Status: Accepted (Loop 2 Phase 1)
Deciders: AI, DR (per `IWO3_LOOP_2_SCOPE_PROPOSAL_v0.1.0.md` §2.4 and approval memo §Q1)

## Context

Loop 2 introduces `artifacts` — the first client-owned operational table that stores arbitrary content (uploads, generated outputs, imported data). Every artifact must:

- be **tenant-scoped**: readable only by users with active membership on the owning client;
- have a **stable addressing scheme** so the same artifact can be referenced by later loops (WO execution, output package assembly, adapter handoffs);
- survive **UUID collisions** safely (they shouldn't happen, but the scheme must not rely on uniqueness of human-visible filenames);
- **not leak** across tenants via shared filesystem paths.

Loop 2 also deliberately defers PostgreSQL Row-Level Security (per the approval memo §Q1 — RLS lands in Loop 4 with the full RBAC layer). So tenant isolation in Loop 2 is enforced at the app/service layer only. The storage scheme must still make cross-tenant leakage *physically impossible* under correct code.

## Decision

### Addressing scheme

Every `artifacts.storage_ref` is a path of the shape:

```text
clients/<client_slug>/artifacts/<artifact_id>/<filename>
```

- `<client_slug>` = the slug of `clients.designation` (e.g. `klear-ai`, `freedomforge-ai`). Derived once at client creation and stored on `clients` (added in a Loop 2.1 migration when needed; for Loop 2 seeds the slug is computed at seed time and embedded directly in `storage_ref`).
- `<artifact_id>` = the artifact's UUID. Guarantees no collision even if two tenants happen to use the same `<filename>`.
- `<filename>` = the human-readable name from upload or generation. Informational; storage is keyed by `<artifact_id>`.

Examples (from the Loop 2 seed fixtures):

```text
clients/klear-ai/artifacts/klear_onepager.md                    ← seed shorthand
clients/ffai/artifacts/ffai_bench_run_2026_04.json              ← seed shorthand
clients/klear-ai/artifacts/00000000-.../klear_onepager.md       ← production form
```

The seed fixtures use the shorthand (no `<artifact_id>` segment) to keep fixture paths readable; production writes use the full form. ADR-011 (future) will lock the production path when the artifact-upload service lands in Loop 3 or later.

### Per-client storage root

Deployment-specific. Loop 2 ships only the **logical** addressing; physical roots are resolved by a future `StorageProvider` interface:

- Local dev: `./db/fixtures/assets/` used as a namespaced prefix.
- Cloud: prefix = `s3://<bucket>/iwo3/<deployment>/` or equivalent.
- DESIGNLAB: out of scope for ADR-009; uses its own provider.

A `StorageProvider.resolve(client_id, storage_ref)` method (Loop 3+) refuses any `storage_ref` that does not start with `clients/<client_slug>/` **for that** `client_id`. This is the physical-impossibility guarantee.

### Cross-tenant collision safety

Three defenses:

1. **`client_id` filter** — every query against `artifacts` is scoped by `client_id`. The tenant-isolation test suite (§2.3 of the Loop 2 proposal, lands in Phase 2) proves this with Klear / FFAI / intruder fixtures.
2. **UUID path segment** in the production form — even if two tenants upload `klear_onepager.md`, the paths differ at `<artifact_id>`.
3. **Slug prefix** — any cross-tenant read attempt against a `storage_ref` that starts with the wrong slug fails at `StorageProvider.resolve()`.

### Garbage collection

Out of scope for Loop 2. GC policy is deferred until WOs / WFs reference artifacts (Loop 3+) and we know which artifacts are reachable vs orphaned. ADR-009.1 will cover retention, soft-delete, and orphan cleanup when that context arrives.

## Consequences

- The `artifacts.storage_ref` column is required, `varchar(1024)`, client-scoped by construction.
- Loop 2 seed paths use the shorthand form; a Loop 2.1 follow-up adds the UUID segment for production uploads.
- `StorageProvider` is a Loop 3 deliverable; Loop 2 only records references, does not fetch bytes.
- The `clients.slug` column is added as part of a Loop 2.1 follow-up (not Loop 2 Phase 1 — we compute it at seed time for now).
- Cross-tenant leakage is a **test-enforced invariant**, not a schema constraint — Loop 4 RBAC plus future RLS strengthen this.

## Alternatives considered

- **Opaque blob store with database-only references.** Rejected — loses the ability to directly serve artifacts from object storage without copying through the API.
- **Flat filesystem keyed by UUID only.** Rejected — loses the tenant-visible prefix that makes cross-tenant leakage obvious in audit logs.
- **PostgreSQL LOB storage for artifact bytes.** Rejected — blocks deploying behind a CDN and scales poorly for large uploads.

## Revisit triggers

- Artifact-upload service design in Loop 3 needs the production UUID segment locked (ADR-011).
- First real multi-client production deployment needs the slug → client-id resolution formalized.
- RLS lands in Loop 4 and the `StorageProvider` resolve-check can be tightened or retired depending on how RLS covers the file system side.

# ADR-016 — IWO3 contract surface + TS/Python parity policy

Date: 2026-04-20
Status: Accepted (Loop 5 Phase 5.3 closeout)
Predecessors: all prior ADRs whose contracts are consolidated here (ADR-002, 007–015).

## Context

By end-of-Loop-4 IWO3 had 24+ Drizzle schemas, multiple contract
modules under `packages/contracts/` (audit, authz, adapter, digiflow,
prompt, db), three TS/Python parity pairs (prompt resolver, digiflow
intake, authz decide), and a locked permission vocabulary + audit
event vocabulary. There was no single import surface. Loop 7
(FastAPI) and Loop 8 (Streamlit) would each end up reaching into
40+ deep paths, and a silent drift between TS and Python (for the
enums that cross HTTP) could only be caught by humans at PR time.

Loop 5 consolidates the TS contract surface under a single barrel,
mirrors the enums + API-boundary shapes to Python, and adds freeze
tests that fail CI when either side drifts without a matching
update to the snapshot.

## Decision

### TS contract barrel

- `packages/contracts/index.ts` re-exports six area namespaces:
  `audit`, `authz`, `adapter`, `digiflow`, `prompt`, `db`.
- Each area has its own sub-barrel `packages/contracts/<area>/index.ts`.
- Downstream code (Loop 7 FastAPI routes, Loop 8 Streamlit adapters,
  Loop 10 live adapters) imports from `packages/contracts` only —
  reaching into sub-module paths is discouraged and subject to
  future lint enforcement.

### Module layering (no cycles — risk A08)

Imports flow in one direction; the order below is from leaf to trunk:

```
  db            (tenant context primitives)
  audit         (event vocabulary + writer)
  rbac / authz  (resolver + decider + throwing wrapper; reads audit)
  adapter       (contract types + dispatcher; reads audit + authz)
  digiflow      (intake + routing; no downstream deps)
  prompt        (resolver; no downstream deps)
```

New contract areas must declare their layer position and stay within
the existing DAG. A cycle is a blocking PR comment; a lint rule
candidate for Loop 6+.

### Python contract mirror

- `apps/api-fastapi/contracts/` holds the Python-side enum + shape
  mirror.
- `contracts/enums.py` declares every Postgres enum as a
  `Final[tuple[str, ...]]` constant (e.g. `MEMBERSHIP_ROLE`) plus a
  `Literal[...]` type alias (e.g. `MembershipRole`) for use in
  Pydantic models. A `ALL_ENUMS: Final[dict[str, tuple[str, ...]]]`
  registry exposes the full set for the parity CLI.
- `contracts/shapes.py` declares TypedDicts for rows that cross the
  HTTP boundary (Loop 7): `WorkOrderRow`, `WorkflowRow`,
  `WorkflowExecutionRow`, `OutputPackageRow`, `OutputHandoffRow`,
  `AuditRow`, `PermissionDecision`, `DispatchInput`, and the seven
  `DispatchResult` variant TypedDicts united into `DispatchResult`.
- `contracts/enum_dump.py` is the CLI (`python3 -m contracts.enum_dump`)
  that emits the full enum registry as JSON on stdout.

### Parity enforcement

Three levels, each hard-gated in CI:

1. **Enum byte-parity.** The TS side queries Postgres + snapshots the
   result in `tests/fixtures/contract-enums.snapshot.json`; the
   Python side declares the same values as tuples and dumps them
   through `enum_dump.py`. The test at
   `tests/contract/enum-parity.test.ts` spawns the CLI and asserts
   `python.enums ≡ snapshot.dbEnums` byte-for-byte. Any divergence
   (value rename, missing enum, ordering change, new enum) fails CI.
2. **Decision-function parity** (pre-existing from Loops 2–4). Shared
   decision functions (`prompt resolver`, `digiflow route`,
   `checkPermissionDecide`) each have a TS canonical implementation,
   a Python mirror, a fixture set, and a parity test that spawns the
   Python CLI and diffs the output.
3. **Contract freeze snapshot.** `tests/contract/contract-enums.test.ts`
   also freezes AUDIT_EVENTS vocabulary + per-loop arrays +
   `permission_key` vocabulary. Any change requires the snapshot
   update in the same commit.

### Shape parity — structural, human-reviewed

TypedDicts in `shapes.py` are hand-maintained to mirror the Drizzle-
inferred TS shapes. A TS type does not cross-compile into Python, so
structural parity relies on:

- Both sides importing the **same** Python enum / TS enum values
  (enforced by the enum-parity test).
- PR review at the Loop 7 boundary, when FastAPI first serializes
  these shapes, must confirm field-by-field agreement.
- A structural parity test is a Loop 7+ candidate; in Loop 5 the
  shapes are declared but not diff-tested.

### What is NOT mirrored

- Internal-only TS types that never leave the server (e.g.
  `DispatchInput`'s private `deploymentId`-like fields that the
  dispatcher reads but never serializes).
- DB schema types (`typeof work_orders.$inferSelect`) — these are TS-
  specific Drizzle inferred types; the Python mirror uses its own
  TypedDicts in `shapes.py`.
- TS internal resolver state (e.g. `resolveUserPermissions`'s
  intermediate `Set<string>`).

## Consequences

**Positive**

- One import path for every downstream consumer. Adding a new
  contract area means: create `packages/contracts/<new>/` + its
  `index.ts` + a re-export line in the top-level barrel.
- Snapshot-freeze tests catch silent drift (enum rename, vocabulary
  change) mechanically — no reliance on human PR memory.
- TS ↔ Python parity for enums + shared decision functions is
  CI-enforced; a FastAPI handler cannot serialize a value that the
  TS side doesn't recognize.

**Negative**

- Every new enum value requires three coordinated changes:
  (a) Drizzle migration, (b) TS snapshot update, (c) Python `enums.py`
  update. Acceptable — that's the whole point.
- Shape parity is still human-reviewed. A silent struct mismatch in
  `shapes.py` vs the Drizzle type survives until Loop 7's first
  FastAPI handler exercises the field.

**Neutral**

- The top-level barrel re-exports everything as namespaces
  (`contracts.audit.AUDIT_EVENTS`). Callers can still import from
  sub-barrels directly if they prefer named imports. Loop 7 style
  guide will nudge toward one pattern.

## Alternatives considered

- **No barrel, just better import conventions** — rejected. Loop 7
  will open 20+ handlers that all import from contract modules; the
  deep-path churn is large and future-refactor-hostile.
- **TS-to-Python type generator** — rejected for now. A tool like
  `ts-to-py` could auto-generate shapes, but the setup + ongoing
  maintenance burden is higher than hand-maintained TypedDicts with
  PR review at the boundary. Loop 7+ can revisit if shape drift
  becomes a real problem.
- **Python as source of truth, TS mirror** — rejected. IWO3's TS
  runtime (Drizzle + Node) owns the authoritative schema + runtime;
  Python runs FastAPI + Streamlit on top. TS stays canonical for
  enums that originate in DB migrations.

## References

- `IWO3_LOOP_5_SCOPE_PROPOSAL_v0.1.0.md` §3
- Loop 5 Phase 5.1 commit `f009f5e` / CI run `24655705688`
- Loop 5 Phase 5.2 commit `f65025a` / CI run `24655931281`
- `packages/contracts/index.ts` (barrel)
- `apps/api-fastapi/contracts/enums.py` (Python mirror)
- `tests/fixtures/contract-enums.snapshot.json` (frozen surface)
- Risk register v0.1.8 (A08 contract barrel cycle hazard — mitigated
  by this ADR's layering rule)

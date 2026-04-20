# Contracts runbook

How to add, modify, or retire a typed contract in IWO3 without breaking
the barrel surface or the TS/Python parity guarantees. See ADR-016 for
the governing policy.

## TL;DR

| Change | Files to touch in the same commit |
| --- | --- |
| Add a new Postgres enum value | Drizzle schema file + regenerated migration + `tests/fixtures/contract-enums.snapshot.json` + matching `apps/api-fastapi/contracts/enums.py` tuple + matching `Literal[...]` alias |
| Rename an enum value | Same files as "add" + downstream consumers updated in same PR |
| Add a new audit event | `packages/contracts/audit/events.ts` (add to `AUDIT_EVENTS` + per-loop array) + snapshot update |
| Add a new permission | Phase 4.1 seed JSONs (`db/seeds/permissions.json` + `db/seeds/role_permissions.json`) + snapshot update. §Q1 `lock_upfront` means this is a rare, intentional change. |
| Add a new contract area | `packages/contracts/<area>/` sub-module + sub-barrel `index.ts` + re-export in top-level `packages/contracts/index.ts` + barrel test assertion |
| Add a new API-boundary shape | TS type in the owning module + matching TypedDict in `apps/api-fastapi/contracts/shapes.py`. PR review confirms structural parity. |

## The contract freeze story

Two test suites stand between you and silent contract drift:

- **`tests/contract/contract-enums.test.ts`** — freezes the TS side:
  DB enums (39) + AUDIT_EVENTS vocabulary (56 events across 6
  per-loop arrays) + locked permission keys (69).
- **`tests/contract/enum-parity.test.ts`** — freezes TS ↔ Python:
  spawns `python3 -m contracts.enum_dump` inside
  `apps/api-fastapi/` and asserts byte-for-byte match with
  `tests/fixtures/contract-enums.snapshot.json`.

If you change an enum / event / permission without updating the
snapshot (and, for enums, without also updating the Python mirror),
CI fails. That is by design.

## Workflows

### Adding a new enum value

Example: add `prompt_override:apply_inline` as a permission.

1. Edit `db/seeds/permissions.json` — insert the new row with a
   deterministic UUID.
2. Edit `db/seeds/role_permissions.json` if any existing role should
   get the new permission by default.
3. Regenerate the contract-enum snapshot:
   ```sh
   IWO3_DATABASE_URL=... bash infra/local/reset-iwo3.sh
   IWO3_DATABASE_URL=... bash infra/local/seed-iwo3.sh
   IWO3_DATABASE_URL=... npx tsx -e "
     import { Pool } from 'pg';
     import { buildContractSnapshot } from './tests/contract/_snapshot-helpers';
     import { writeFileSync } from 'node:fs';
     (async () => {
       const pool = new Pool({ connectionString: process.env.IWO3_DATABASE_URL });
       const snap = await buildContractSnapshot(pool);
       writeFileSync('tests/fixtures/contract-enums.snapshot.json', JSON.stringify(snap, null, 2) + '\\n');
       await pool.end();
     })();
   "
   ```
4. If you added an enum that FastAPI will serialise, regenerate the
   Python mirror:
   ```sh
   python3 /tmp/gen_py_enums.py   # helper script lives in the Phase 5.2 scratch area; a
                                  # dedicated regenerator lives at tools/contracts/regen_py_enums.py
                                  # (Loop 6+ cleanup).
   ```
5. Update any role_permissions defaults if a role should gain or
   lose the permission.
6. Run `npm run check` + `npm run test`. The freeze tests should
   pass; if they complain, you forgot one of steps 1–4.

### Adding a new audit event

1. Edit `packages/contracts/audit/events.ts`:
   - Add the new constant to the `AUDIT_EVENTS` object literal.
   - Add it to the relevant per-loop array (e.g.
     `LOOP_5_PHASE_3_AUDIT_EVENTS`).
2. Regenerate the snapshot (same script as above).
3. Run `npm run test`; the freeze test should now show the new
   event in the live output matching the snapshot.

### Adding a new contract area (e.g. `channel`)

1. Create `packages/contracts/channel/` with the area's types and
   functions.
2. Create `packages/contracts/channel/index.ts` re-exporting the
   public surface.
3. Add `export * as channel from "./channel";` to
   `packages/contracts/index.ts`.
4. Add an assertion to `tests/contract/contract-barrel.test.ts`
   that `contracts.channel` is a truthy namespace.
5. Check for import cycles — the new area must fit the layering DAG
   documented in ADR-016 §Module layering.

### Adding a new API-boundary shape

1. Declare the TS type in the owning module (usually
   `packages/contracts/<area>/`).
2. Add the matching TypedDict to
   `apps/api-fastapi/contracts/shapes.py`, referencing any enum
   aliases it depends on.
3. Commit both in the same PR. No automated parity test exists for
   shapes (ADR-016 §Shape parity) — PR review confirms.

## Common pitfalls

- **Forgetting `::text[]` in enum-dump queries.** If you write a new
  Postgres query that returns `name[]` (e.g. aggregating
  `pg_enum.enumlabel`), cast to `text[]` explicitly — pg's Node
  driver does not parse arrays of `name` into JS arrays. See R-008
  in the CODEX overnight log.
- **Snapshot format vs snapshot values.** The snapshot file's JSON
  must be authored such that array values are arrays, not strings.
  The helper at `tests/contract/_snapshot-helpers.ts` does this
  correctly; downstream snapshot-generation scripts must match.
- **Adding an enum value in TS but not in the DB (or vice-versa).**
  Both sides must move in the same commit. A Drizzle migration +
  the Drizzle `pgEnum` declaration must match; the snapshot then
  reflects the new state.
- **Calling sub-module paths instead of the barrel.** Works today;
  discouraged. Future lint rule candidate (Loop 6+) will enforce
  `from "packages/contracts"` over deep imports outside the
  `packages/contracts/` tree.

## Escape hatches

Almost none. If you find yourself needing one:

- **Add a new enum at migration time only.** Requires a Drizzle
  migration + snapshot regen + Python mirror update in the same
  commit. No exceptions.
- **Emit an audit event without adding it to the per-loop array.**
  Don't. The array is the vocabulary; the writer ignores events that
  aren't in `AUDIT_EVENTS` because TypeScript's type system refuses
  to compile. If you need a one-shot audit row, add it to
  `AUDIT_EVENTS` under the current loop's per-loop array.

## Related

- ADR-014 — RBAC permission model (locked vocabulary §Q1)
- ADR-015 — RLS enforcement + withTenantContext
- ADR-016 — Contract surface + parity policy (this ADR)
- IWO3_OVERNIGHT_DEV_RESOLUTION_LOG_FOR_CODEX_REVIEW.md — every
  discretionary decision made during contract work, including R-008
  (snapshot format fix).

/**
 * IWO3 contract surface — single public import point.
 *
 * Loop 5 Phase 5.1 consolidates every public contract from Loops 1–4
 * under one barrel so downstream consumers (Loop 7 FastAPI routes,
 * Loop 8 Streamlit adapters, future Loop 10 live adapters) can import
 * from `@iwo3/contracts` (or the relative path) without reaching into
 * deep sub-module paths.
 *
 * Policy (ADR-016):
 *
 *   - Every stable, external-facing type / function / enum is
 *     re-exported here through a sub-barrel (`packages/contracts/<area>/
 *     index.ts`). Internal helpers stay sub-module-local.
 *   - The set of snapshotted enums + audit-event vocabularies is locked
 *     by `tests/contract/contract-enums.test.ts` — any change must also
 *     update `tests/fixtures/contract-enums.snapshot.json` or CI fails.
 *   - Python parity for API-boundary shapes lives in
 *     `apps/api-fastapi/contracts/` (Phase 5.2). Parity is enforced by
 *     `tests/contract/enum-parity.test.ts` which spawns a Python CLI
 *     and compares enum values byte-for-byte.
 *
 * Module layering (no cycles, risk A08):
 *
 *   db       → tenant context primitives
 *   audit    → events vocabulary + writer
 *   authz    → resolver + decider + throwing wrapper (reads audit)
 *   adapter  → contract types + dispatcher (reads audit + authz)
 *   digiflow → intake + routing (no downstream deps)
 *   prompt   → resolver (no downstream deps)
 */

export * as audit from "./audit";
export * as authz from "./authz";
export * as adapter from "./adapter";
export * as digiflow from "./digiflow";
export * as prompt from "./prompt";
export * as db from "./db";
export * as woWf from "./wo-wf";
export * as sandbox from "./sandbox";

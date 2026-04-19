# IWO3 Strangler Ledger

Source of truth: `IWO3_INITIAL_CODEBASE_DISCOVERY_REPORT_v0.1.0.md` §11.
Maintained by: CC (Codebase Cartographer). Updated at every loop closeout.

IWO2 branch point for IWO3: `1535c2f`.

## Seam Table

Ranked by strangler priority. A seam moves to FastAPI **only** once a contract test proves parity in both layers.

| Rank | Seam | Current Node location | FastAPI target | Status |
| --- | --- | --- | --- | --- |
| 1 | Channel webhooks | none today | `/webhooks/telegram`, `/webhooks/gamma-callback`, `/webhooks/slack` (Loop 9+) | Greenfield — claim in Loop 9 |
| 2 | RBAC enforcement layer | `requireRole` in `server/routes.ts` | FastAPI dependency `require_role(min_role, client_scope)` | Plan in Loop 4 |
| 3 | Candidate review HITL | `server/routes.ts:4659+` | `/gamma/candidates/{wo_id}`, `/gamma/candidates/{record_id}/select` | Move in Loop 10 |
| 4 | Gamma generation orchestration | `server/gamma-client.ts` | `/gamma/generate`, `/gamma/poll/{id}` | Move in Loop 10 |
| 5 | KnowHow retrieval | `server/knowhow.ts`, `POST /api/context/retrieve` | `/context/retrieve` | Move in Loop 3–5 |
| 6 | Read-only query layer | `GET /api/work-orders`, `/api/artifacts`, etc. | FastAPI cache-friendly shell | Move in Loop 7 |
| 7 | Output package contract + adapter registry | absent | `/packages/*`, `/adapters/*` | Greenfield — Loop 3 |
| 8 | Workflow state machine | `server/orchestration.ts:673+` | `/work-order/process`, `/workflow/advance` | Last — Loop 6+ |

Areas that stay in Node for v0: Tier 1/Tier 2 LLM execution (`pocketflow.ts`, `llm-client.ts`), Drizzle-backed transactional writes to WO/WF state (until strangler reaches them), the existing Vitest test suite.

## Move Protocol (applies to every row above)

1. Contract lands in `packages/contracts/` with Pydantic + TS mirrors.
2. Parity test: same input against Node path and FastAPI path must produce equivalent output.
3. Deprecation note in the Node file with target removal loop.
4. CC updates this ledger row to `Moved in Loop N`.
5. Remove Node path after two subsequent loops of stability.

## Changelog

| Date | Changes |
| --- | --- |
| 2026-04-19 | Seeded from discovery report §11. Loop 1 Phase 1 (scaffolding) — no seams moved yet. |

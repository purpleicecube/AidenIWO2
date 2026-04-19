# AIDEN IWO3

Successor architecture track for AIDEN IWO. Starts from the IWO2 codebase (branch point: `1535c2f`).

- Branch: `iwo3/main`
- IWO2 remains the stable/maintenance line at `/home/virgina/VS_AIDEN_IWO2`.
- All planning and governance lives in `/home/virgina/VS_PDOE/WS024_IWO3[Branch]/`.

## Current loop

Loop 1 — Production floor + clean data baseline. See `WS024_IWO3[Branch]/05_Artifacts/IWO3_LOOP_1_PLAN_v0.1.0.md` (internal v0.1.1).

## Quick starts

- `docs/runbooks/startup.md` — how to clone, install, run dev, run tests.
- `docs/runbooks/python-toolchain.md` — uv commands.
- `docs/architecture/strangler-ledger.md` — IWO2 → IWO3 seam map.
- `docs/adr/` — ADR-007 (Python toolchain), ADR-008 (migration ownership).

## Rules

- IWO2 code under `server/`, `client/`, `shared/`, `migrations/`, `script/` is **untouched** in Loop 1. Strangler moves only.
- Multi-tenant from day one. Two tenants seeded: `IWO | Klear.ai` (primary) and `IWO | FreedomForge.AI` (secondary).
- No secrets in git. `credential_ref:` placeholders only in fixtures/seeds. Enforced by `gitleaks`.

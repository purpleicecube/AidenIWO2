# IWO3 Startup Runbook

Loop 1 — production floor. Read this first.

## Prereqs

- Node 20 (see `.nvmrc`)
- Python 3.11 (see `.python-version`)
- `uv` (install: `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker + Docker Compose
- `gitleaks` (install: https://github.com/gitleaks/gitleaks — `brew install gitleaks` or binary from the GitHub releases page). If absent locally, `baseline-check.sh` soft-skips the scan and prints install guidance; CI runs `gitleaks/gitleaks-action@v2` as a separate authoritative step.

## Clone + env

```bash
# You are in the IWO3 worktree:
cd /home/virgina/VS_AIDEN_IWO3

cp infra/local/.env.example .env
# Edit .env if you need different Postgres creds. Defaults work for local dev.
```

## Install deps

```bash
# Node (Drizzle, tsx, pg, Vitest)
npm ci

# Python api-fastapi
cd apps/api-fastapi && uv sync --extra dev && cd -
```

## Start IWO3 Postgres

Preferred (Docker Compose v2):

```bash
docker compose -f infra/local/docker-compose.iwo3-postgres.yml up -d
```

Fallback (Docker Compose v1 or hosts with broken port forwarding —
matches the pattern IWO2's `aiden-postgres` already uses on these hosts):

```bash
docker run -d \
  --name aiden-iwo3-postgres \
  --network host \
  --restart unless-stopped \
  -e POSTGRES_DB=aiden_iwo3 \
  -e POSTGRES_USER=iwo3 \
  -e POSTGRES_PASSWORD=iwo3 \
  -e PGPORT=5434 \
  -v aiden-iwo3-pgdata:/var/lib/postgresql/data \
  postgres:16
```

Both paths end with Postgres listening on `localhost:5434`, db `aiden_iwo3`.

## Reset + seed

```bash
bash infra/local/reset-iwo3.sh
bash infra/local/seed-iwo3.sh
```

After seed, the database contains:
- 2 clients (`IWO | Klear.ai`, `IWO | FreedomForge.AI`)
- 12 users (6 per tenant)
- 12 client memberships (one per user)
- 5 template profiles (3 Klear Gamma + 2 FFAI gamma_basic)
- manifest rows for every created table

## Run FastAPI (bootstrap)

```bash
cd apps/api-fastapi
uv run uvicorn main:app --reload --port 5500
# GET http://localhost:5500/health
```

## Run tests

IWO3 uses **two explicit local-DB lanes** (Test DB Split Darkmode 2026-05-10):

| Lane | Env var | Purpose | Drift posture |
| --- | --- | --- | --- |
| `local-live` | `IWO3_DATABASE_URL` | Operator app/dev DB. Click around, run real WOs, exercise the UI. | Allowed to drift |
| `local-test-fresh` | `IWO3_TEST_DATABASE_URL` | Disposable integration-test DB. Always reset+reseeded before tests. | Always destroyed and rebuilt |

**Which DB is which:**

- Live: `aiden_iwo3` — safe to click around in. Holds your operator state.
- Test: `aiden_iwo3_test` — safe to destroy. Reset on every `npm run test:integration` run.

Both share the same Postgres host/port; only the database name differs.

**Canonical local integration validation (recommended):**

```bash
# Reset + reseed the disposable test DB, then run vitest + pytest.
# Operator's lived-in IWO3_DATABASE_URL is NOT touched.
npm run test:integration
```

The wrapper at `infra/local/test-integration-iwo3.sh` enforces three guards:

1. Refuses if `IWO3_TEST_DATABASE_URL` is unset.
2. Refuses if the test URL equals the live URL.
3. Refuses if the test DB name does not end with `_test` (defense against accidental live-DB wipe).

**Drift-tolerant quick check (optional, vitest only):**

```bash
# Run vitest against whatever IWO3_DATABASE_URL points at (may be live).
# Use this for fast iteration when you already know your DB is in a
# good state. Exact-count integration assertions may fail under drift.
# This script intentionally runs vitest only — it does NOT run pytest;
# that's why the name says "vitest" and not "integration".
npm run test:vitest:live

# Python pytest against the live DB (separate manual step)
cd apps/api-fastapi && uv run pytest && cd -
```

**Source of truth:** `npm run test:integration` is the source of truth for local integration validation. CI (`baseline-check.sh`) runs the equivalent flow against a fresh DB service container, so green-locally-via-`test:integration` ≡ green-on-CI.

## Full baseline check (what CI runs)

```bash
bash infra/ci/baseline-check.sh
```

## Push policy

First push of `iwo3/main` to remote: `git push -u origin iwo3/main`.

Do **not** `git push` without `-u` before upstream is set to `origin/iwo3/main` — the worktree was created tracking `origin/main` (IWO2), and a bare `git push` would try to fast-forward IWO2's `main`. After the first `-u` push, `git push` is safe.

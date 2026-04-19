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

```bash
# Node (Vitest) — IWO3 integration tests require IWO3_DATABASE_URL in env
npm run test

# Python
cd apps/api-fastapi && uv run pytest && cd -
```

## Full baseline check (what CI runs)

```bash
bash infra/ci/baseline-check.sh
```

## Push policy

First push of `iwo3/main` to remote: `git push -u origin iwo3/main`.

Do **not** `git push` without `-u` before upstream is set to `origin/iwo3/main` — the worktree was created tracking `origin/main` (IWO2), and a bare `git push` would try to fast-forward IWO2's `main`. After the first `-u` push, `git push` is safe.

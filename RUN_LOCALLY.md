# Running AIDEN_IWO Locally

Last updated: 2026-03-04

## Prerequisites

| Software | Version | How Installed |
| --- | --- | --- |
| Node.js | v20.20.0 (pinned in `.nvmrc`) | nvm (`~/.nvm/`) |
| npm | v10.8.2 | Bundled with Node.js |
| Docker | 20.10+ | System package |

PostgreSQL runs inside Docker — no system-level Postgres install needed.

## Quick Start

```bash
cd /home/virgina/VS_AIDEN
./script/local-dev.sh start
```

This single command:

1. Sources nvm and switches to the pinned Node.js version
2. Starts (or creates) the `aiden-postgres` Docker container
3. Pushes the Drizzle schema to the database
4. Launches the dev server on <http://localhost:5000>

Open <http://localhost:5000/api/login> in your browser to auto-login as "Local Admin" (no password).

## Convenience Script

| Command | What It Does |
| --- | --- |
| `./script/local-dev.sh start` | Start DB + push schema + launch dev server |
| `./script/local-dev.sh stop` | Stop both the app and Postgres container |
| `./script/local-dev.sh status` | Show what's running |
| `./script/local-dev.sh reset` | **Destructive** — deletes container + volume (all data lost) |

## Environment Variables

The `.env` file in the project root is loaded automatically by `npm run dev` (via `tsx --env-file=.env`). It is git-ignored.

| Variable | Purpose | Required? |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string | **Yes** |
| `SESSION_SECRET` | Random string for session cookies | **Yes** |
| `GROQ_API_KEY` | Tier 1 (Aiden) + fast sub-agents | **Yes** (currently primary) |
| `OPENROUTER_API_KEY` | Sub-agents using OpenRouter models | **Yes** (currently used by A010) |
| `OPENAI_API_KEY` | Sub-agents using OpenAI models | Optional |
| `ANTHROPIC_API_KEY` | Sub-agents using Anthropic/Claude models | Optional |
| `SENDGRID_API_KEY` | Email notifications via SendGrid | Optional |

Current `.env` values (credentials redacted):

```
DATABASE_URL=postgresql://aiden:****@localhost:5433/aiden_iwo
SESSION_SECRET=****
GROQ_API_KEY=gsk_****
OPENROUTER_API_KEY=sk-or-****
```

## Authentication

Authentication has been rewritten for local dev. The original Replit OIDC flow was replaced with **password-based login**:

- `POST /api/login` — authenticate with email + password (bcryptjs hashed)
- `GET /api/login` — auto-login fallback (logs in as "Local Admin", no password)
- `GET /api/logout` — destroys the session
- Sessions persist in PostgreSQL for 1 week
- Backup admin: `darrel.vaughn@gmail.com` (created on first run if no users exist)
- File: `server/replit_integrations/auth/replitAuth.ts`

## Database

| Property | Value |
| --- | --- |
| Engine | PostgreSQL 16 (Alpine) |
| Container | `aiden-postgres` |
| Port | 5433 (mapped to container's 5432) |
| User | `aiden` |
| Password | `aiden_local` |
| Database | `aiden_iwo` |
| Volume | `aiden_pgdata` (Docker named volume) |
| Restart Policy | `unless-stopped` (survives reboots) |

Schema is managed by Drizzle ORM. Push changes with:

```bash
npm run db:push
```

### Workspace Initialization

After first database setup, seed the workspace folders:

```bash
curl -X POST -b cookies http://localhost:5000/api/workspace/seed
```

This creates 10 organizational folders (00_Planning through 06_Tests, plus #Documents, #Images, #Code_Blocks) and 2 root files (AGENTS.md, CLAUDE.md).

## Backups

Automated daily backups are configured:

- **Script:** `script/backup-db.sh`
- **Schedule:** Cron job at 2:00 AM daily
- **Location:** `backups/` (git-ignored)
- **Retention:** 7 days (auto-pruned)
- **Format:** Compressed `pg_dump` (`.sql.gz`)

Manual backup:

```bash
./script/backup-db.sh
```

Restore from backup:

```bash
gunzip -c backups/aiden_iwo_YYYYMMDD_HHMMSS.sql.gz | docker exec -i aiden-postgres psql -U aiden aiden_iwo
```

## Isolation

The app is fully isolated from the host system:

| Layer | Mechanism |
| --- | --- |
| Node.js runtime | nvm + `.nvmrc` (pinned to v20.20.0) |
| npm dependencies | Project-local `node_modules/` |
| Database | Docker container + named volume |
| Environment | `.env` file (git-ignored) |
| Global packages | None installed |

No system-level packages are modified. Other Node.js projects can use different versions via nvm without conflict.

## Available Commands

| Command | What It Does |
| --- | --- |
| `npm run dev` | Start dev server (Express + Vite on port 5000, auto-loads `.env`) |
| `npm run build` | Build for production (compiles frontend + bundles backend) |
| `npm run start` | Run production build (`NODE_ENV=production node dist/index.cjs`) |
| `npm run db:push` | Push Drizzle schema to PostgreSQL |
| `npm run check` | Run TypeScript type checking |

## Project Structure

```
server/              Express backend
  orchestration.ts   Work order processing pipeline
  pocketflow.ts      PocketFlow execution engine (plan → exec → evaluate → refine)
  llm-client.ts      LLM provider abstraction (Groq, OpenRouter, OpenAI, Anthropic)
  routes.ts          API routes
  storage.ts         Database access layer
  workspace-filing.ts  Auto-filing of deliverables into workspace folders
  replit_integrations/auth/  Authentication (rewritten for local dev)
client/src/          React frontend (pages, components, hooks)
shared/              Shared types + Drizzle schema
  schema.ts          All database table definitions
  models/            Model-specific schemas (auth, artifacts, etc.)
script/              Dev scripts (local-dev.sh, backup-db.sh, build.ts)
attached_assets/     Spec docs and uploaded assets
backups/             Database backups (git-ignored)
```

## Key Dependencies

**Backend:** Express 5, Drizzle ORM + PostgreSQL, OpenAI SDK, Anthropic SDK, Passport, connect-pg-simple, SendGrid (optional)

**Frontend:** React 18, Vite 7, TanStack React Query, Tailwind CSS + shadcn/ui, Wouter, Recharts, Framer Motion

## Known Issues

See `BUGFIX_LOG.md` for the full bug fix log and code review findings.

# IWO3 Alpha — Operator runbook

Date: 2026-04-24
Audience: Operators bringing up IWO3 Alpha for a tenant.
Scope: dev / staging environment; production posture is Beta (see ADR-024).

## Prerequisites

- Postgres 16 running (compose file: `infra/local/docker-compose.iwo3-postgres.yml`).
- Node 20.x + Python 3.11 + uv 0.10.x.
- For Telegram: a bot token from `@BotFather` per tenant.
- For LLM: at least one of `GROQ_API_KEY` or `OPENROUTER_API_KEY` exported in the runtime environment.

## First-boot

```
# 1. Bring up Postgres
docker compose -f infra/local/docker-compose.iwo3-postgres.yml up -d

# 2. Apply migrations + seed (idempotent)
IWO3_DATABASE_URL=postgresql://iwo3:iwo3@localhost:5434/aiden_iwo3 \
  npx tsx infra/local/apply-migrations.ts
IWO3_DATABASE_URL=postgresql://iwo3:iwo3@localhost:5434/aiden_iwo3 \
  npx tsx infra/local/seed-loader.ts

# 3. Start the FastAPI runtime
cd apps/api-fastapi && \
  IWO3_DATABASE_URL=postgresql://iwo3:iwo3@localhost:5434/aiden_iwo3 \
  GROQ_API_KEY=... \
  OPENROUTER_API_KEY=... \
  TELEGRAM_BOT_TOKEN_KLEAR_AI=... \
  .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000

# 4. Start the Streamlit operator console
cd apps/console-streamlit && \
  IWO3_API_BASE_URL=http://localhost:8000 \
  .venv/bin/streamlit run Home.py --server.port 8501
```

## Telegram setup per tenant

1. **Create the bot.** DM `@BotFather` → `/newbot` → name it (e.g. `Klear IWO3 Bot`). Save the token.
2. **Set the env var.** Token name follows `TELEGRAM_BOT_TOKEN_<TENANT>` where `<TENANT>` is the upper-snake of the part of `client.designation` after the `|` (e.g. `IWO | Klear.ai` → `KLEAR_AI`). Code path: `channel.telegram.env_var_for_telegram_bot_token`.
3. **Issue an auth code.** Operator console → Aiden Settings → "Channel auth codes" → choose `telegram` → click "Issue code". A 12-character code displays.
4. **Bind the chat.** From the operator's Telegram client, message the bot: `/start <code>`. The polling worker consumes the code, binds the chat, replies "bound".
5. **Verify.** Operator console → Aiden Settings → "Bound identities" shows the new row.

## Daily operations

- **Adding a new LLM provider key**: export the env var and restart the FastAPI runtime. The seed `llm_configs` rows already point at `credential_ref:env:<NAME>`.
- **Rotating a Telegram bot token**: update the env var → restart FastAPI. Inbound polling resumes within one tick (≤30s).
- **Revoking a chat**: Aiden Settings → "Bound identities" → "Revoke". Subsequent inbound messages get the unbound prompt.
- **Checking LLM spend**: Audit Log → filter by event `llm.invoked`. Each row carries `metadata.totalTokens`. Per-WO ceiling breaches show as `llm.budget_exceeded`.

## Health checks

```
curl -s http://localhost:8000/health         # API liveness
curl -s http://localhost:8000/llm/providers  # Without auth: 401 (expected).
                                              # With X-IWO3-User + X-IWO3-Client: provider list.
```

## Common errors

| Symptom                                                | Likely cause                                     | Fix                                         |
| ------------------------------------------------------ | ------------------------------------------------ | ------------------------------------------- |
| Telegram `/status` replies "WO id not valid"            | Operator pasted a non-UUID                       | Copy WO id from operator console.           |
| `/llm/test` returns ok=false credential_missing        | Provider env var not set in FastAPI's process    | Restart FastAPI with the env var.           |
| Operator console says "Could not connect"              | FastAPI not running on `IWO3_API_BASE_URL`       | Start FastAPI / fix the env var.            |
| Telegram `/start` says "code not found"                | Code expired (15 min default) or already consumed | Issue a new code.                          |
| Aiden Tier 1 returns 409 no_aiden_config                | Tenant has no `aiden_tier_1` row in `llm_configs` | Run seed loader / insert row.              |
| `llm.budget_exceeded` in audit log                     | A WO blew past 50K tokens                        | Reset or split the WO; retune the prompt.   |

## F2 verification flows (closeout gate)

See `IWO3_ALPHA_F2_MANUAL_VERIFICATION.md` for the canonical 9-flow checklist. All 9 must show ✅ before promoting Alpha.

## Logs and audit

- FastAPI logs on stdout (uvicorn).
- Streamlit logs on stdout.
- Polling worker logs to the `iwo3.workers.poll` logger; visible in FastAPI stdout.
- The audit log is the source of truth for tenant-side activity. Browse via the operator console or query directly:

```
SELECT created_at, action, target_type, metadata
  FROM action_audit_log
 WHERE client_id = '<tenant-uuid>'
 ORDER BY created_at DESC
 LIMIT 100;
```

## Backup / restore

Alpha posture is dev/staging — backups are not part of the SLA. The Postgres volume in the compose file is the single source of truth; copy it before destructive migrations. Beta hardens this (Loop 11+).

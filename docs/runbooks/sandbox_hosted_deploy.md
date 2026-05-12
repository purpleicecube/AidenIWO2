# Sandbox Hosted Deploy — IWO3 Node Service

Sandbox Everywhere Darkmode (2026-05-11).

This runbook documents the hosted deployment of the canonical Node/React
sandbox alongside the existing FastAPI service on Railway. Both services
share the same Postgres instance. The Streamlit Cloud console reads
`IWO3_SANDBOX_URL` to launch the canonical sandbox; it never duplicates
the sandbox surface itself.

## Service relationship

```text
Streamlit Cloud (operator console)
    │ (launcher only — opens canonical sandbox in new tab)
    ▼
Railway: iwo3-node              Railway: iwo3-api
  Express + React sandbox  ←──  FastAPI runtime/data plane
  /api/sandbox-sessions/*       /workspace/* /chat /work_orders ...
       │                              │
       └──── shared Postgres ─────────┘
```

The Node service hosts the sandbox UI and Express routes. The FastAPI
service remains the runtime/data-plane authority for workspace,
work-order, chat, audit, and memory surfaces. The Node sandbox calls
FastAPI through the existing sandbox-bounded cross-service helper
(`server/sandbox-crossservice.ts`) for the rerender + workspace-content
read path; it does not bypass FastAPI for any tenant-scoped read.

## Railway provisioning steps

1. From the existing IWO3 Railway project, **create a new service**
   pointing at the same repo / branch.
2. In service settings → **Build**:
   - Builder: Dockerfile
   - Config file: `railway.node.json` (this repo ships it)
   - Or set Dockerfile Path directly to `Dockerfile.node` if the
     dashboard does not pick up the config file.
3. **Environment variables** (mirror the local `.env` minimum):

   | Key | Purpose |
   | --- | --- |
   | `NODE_ENV` | `production` |
   | `IWO3_DATABASE_URL` | Same Postgres connection string as the FastAPI service |
   | `DATABASE_URL` | Same value (some legacy Node modules read this) |
   | `SESSION_SECRET` | Long random string (do not reuse FastAPI's JWT key) |
   | `BOOTSTRAP_ADMIN_PASSWORD` | Initial admin password for hosted login |
   | `IWO3_FASTAPI_BASE_URL` | Internal URL of the FastAPI Railway service |
   | `GITHUB_TOKEN` | Optional — required for `/sandbox/.../publish` |
   | `PORT` | Railway injects this; Express server already honors it |

4. Healthcheck path: `/api/health` (set by `railway.node.json`).
5. After first deploy, log in once with the bootstrap admin to confirm.

## Streamlit Cloud wiring

On the existing Streamlit Cloud `aiden-iwo3.streamlit.app` deployment,
add **one** environment variable:

```text
IWO3_SANDBOX_URL=https://iwo3-node-production.up.railway.app
```

(Use whatever public URL Railway hands out — the repo defaults to local
`http://localhost:5050` when unset.)

The Streamlit `/sandbox` page reads this and renders a launcher card
plus a live `/api/health` probe.

## What this image deliberately does NOT bundle

- **Playwright Chromium** — the `Dockerfile.node` image is intentionally
  lean. The HTML→PDF / HTML→PPTX export endpoint
  (`GET /api/sandbox-sessions/:id/export?format=pdf|pptx`) returns a
  clean `412 skills_unavailable` until either Playwright + the
  `claude-office-skills` tree are bundled, or a separate render worker
  is provisioned. This is the residual debt captured in the Sandbox
  Everywhere handback.
- **claude-office-skills checkout** — same reason. Operators who need
  hosted export should either (a) set `SKILLS_DIR` + `PLAYWRIGHT_PATH`
  in env to a mounted volume, or (b) run export locally during the
  follow-on hosted-export loop.

## What works hosted today

| Surface | Status |
| --- | --- |
| Streamlit launcher card | ✓ |
| Open canonical sandbox in new tab | ✓ |
| Session create / list / delete | ✓ |
| Rerender from workspace artifact UUID (md/html/code/text) | ✓ |
| Rerender from PDF/PPTX/DOC with extracted text | ✓ |
| HTML preview | ✓ |
| HTML publish to GitHub Pages | ✓ (when `GITHUB_TOKEN` provisioned) |
| HTML→PDF export | residual — 412 until Playwright bundled |
| HTML→PPTX export | residual — 412 until Playwright + html2pptx bundled |

## What works locally today

Same as hosted, plus HTML→PDF and HTML→PPTX export when:

```bash
export SKILLS_DIR=/home/virgina/claude-office-skills
export PLAYWRIGHT_PATH=$SKILLS_DIR/node_modules/playwright
```

are set in the Node process's environment before `npm run dev`.

## Cross-environment handoff gotcha

The Streamlit launcher + the workspace "Review in Sandbox ↗" link
both build URLs of the shape `{IWO3_SANDBOX_URL}/sandbox?source=<id>`.
The React sandbox at that target then asks **its own** FastAPI for the
artifact content. **Both Streamlit and the React Node service must
point at the SAME Postgres** for this to work — otherwise the artifact
UUID resolves on Streamlit's side but doesn't exist on the Node side's
DB, and the rerender returns `not_found`.

Failure modes this produces and how they surface now:
- Streamlit Cloud (hosted) + `IWO3_SANDBOX_URL=http://localhost:5050`
  → sandbox session created, rerender fails with `not_found`, operator
  sees a destructive toast + an error log entry in the session
- Streamlit local + hosted Node sandbox → same shape, opposite direction

Correct setups:
- Streamlit hosted + Node hosted (both on the same Railway Postgres)
- Streamlit local + Node local (both on `aiden_iwo3` at `127.0.0.1:5434`)

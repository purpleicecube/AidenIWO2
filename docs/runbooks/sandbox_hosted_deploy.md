# Sandbox Hosted Deploy — IWO3 Node Service

**Last revised:** 2026-05-19 (Hosted Sandbox Bring-Up loop — adds
`IWO3_SERVICE_TOKEN` service-auth seam).

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
Railway: iwo3-node                Railway: iwo3-api
  Express + React sandbox  ←────  FastAPI runtime/data plane
  /api/sandbox-sessions/*         /workspace/* /chat /work_orders ...
       │       │
       │       │ Node-side cross-service helper sends:
       │       │   X-IWO3-User
       │       │   X-IWO3-Client
       │       │   X-IWO3-Service-Token  ← shared secret
       │       └──────────────────────────────────────┐
       ▼                                              ▼
              shared Postgres (Railway add-on)
```

The Node service hosts the sandbox UI and Express routes. The FastAPI
service remains the runtime/data-plane authority for workspace,
work-order, chat, audit, and memory surfaces. The Node sandbox calls
FastAPI through the sandbox-bounded cross-service helper
(`server/sandbox-crossservice.ts`) for the rerender + workspace-content
read path; it does not bypass FastAPI for any tenant-scoped read.

## Why a service-token bridge is required hosted

Hosted FastAPI runs in `IWO3_AUTH_MODE=jwt`. That rejects the dev-auth
headers (`X-IWO3-User` / `X-IWO3-Client`) the Node sandbox uses for
internal service-to-service calls. Without a bridge, every internal
Node→FastAPI hop 401s.

The bridge is a single env var shared by both services:

- `IWO3_SERVICE_TOKEN` — opaque deployment secret, ≥32 random bytes.

When FastAPI sees `X-IWO3-Service-Token: <value>` matching the env
var, it accepts the dev-auth headers regardless of mode. Posture:

- Token unset on FastAPI → header ignored, normal auth mode wins.
  Local dev (FastAPI in `dev_bearer`) keeps working unchanged.
- Token set, header matches → dev-auth headers accepted.
- Token set, header value WRONG → explicit 401 `invalid_service_token`
  (no silent fallback to JWT/dev_bearer probe).
- Token set, header missing → falls through to global auth mode
  (so JWT-mode hosted login still works for operator browser flows).

The Node-side helper reads the same env var and adds the header to
every cross-service request. Empty env var = header omitted = local
parity preserved.

## Railway provisioning steps (operator dashboard)

These are the manual clicks Claude cannot perform from a coding
session — Railway service creation is dashboard-side.

### Step 1 — Create the Node service

1. Open the existing IWO3 Railway project (`iwo3`).
2. **+ New** → **GitHub Repo** → pick `purpleicecube/AidenIWO2`.
3. Service name: `iwo3-node` (or any name; we'll reference it as such).
4. Service settings → **Build**:
   - Builder: Dockerfile
   - **Config Path**: `railway.node.json`
     (If the dashboard doesn't pick up the config file, set
     **Dockerfile Path** directly to `Dockerfile.node`.)
5. Service settings → **Networking** → enable a public domain.

### Step 2 — Mint the service token

```bash
# Anywhere — terminal, vault, password manager:
openssl rand -hex 32
```

Copy the value. You'll paste it into BOTH services' env in step 3.

### Step 3 — Env vars on `iwo3-node` (Node service)

| Key | Value |
| --- | --- |
| `NODE_ENV` | `production` |
| `IWO3_DATABASE_URL` | Same Postgres connection string as the existing `iwo3-api` service |
| `DATABASE_URL` | Same value (some legacy Node modules read this) |
| `SESSION_SECRET` | A separate long random string (do NOT reuse the JWT key or the service token) |
| `BOOTSTRAP_ADMIN_PASSWORD` | Initial admin password for hosted Node login |
| `IWO3_FASTAPI_BASE_URL` | Internal URL of the FastAPI Railway service (Railway shows it in the FastAPI service's Networking tab — usually `https://iwo3-api-production.up.railway.app` or the internal `*.railway.internal` shape) |
| **`IWO3_SERVICE_TOKEN`** | **The hex string from step 2** — must be IDENTICAL to the value on `iwo3-api` |
| **`GROQ_API_KEY`** *and/or* **`OPENROUTER_API_KEY`** *and/or* **`ANTHROPIC_API_KEY`** | **At least one is required** — Node boot validation (`server/env-check.ts`) hard-aborts if none are present. Mirror whichever key(s) the `iwo3-api` service already has. |
| `GITHUB_TOKEN` | Optional — required only for `/api/sandbox-sessions/.../publish` |
| `PORT` | Leave unset — Railway injects this; Express reads `process.env.PORT` |

Healthcheck path is already set by `railway.node.json` to `/api/health`.

> **Note on LLM keys.** Even though the sandbox surface itself does
> not invoke an LLM, the Node server boots with hard-block validation
> covering work-order processing (Mark / Tom / Hank / Paul sub-agents)
> which IS still in this image. Without at least one provider key the
> process exits before binding the port and Railway healthchecks fail.

### Step 4 — Add `IWO3_SERVICE_TOKEN` to existing `iwo3-api` (FastAPI service)

The token must match on BOTH services. On the existing FastAPI service:

| Key | Value |
| --- | --- |
| `IWO3_SERVICE_TOKEN` | The SAME hex string from step 2 |

Confirm `IWO3_AUTH_MODE=jwt` is also set on this service (existing
production posture; the service-token path only fires when both env
vars are present).

### Step 5 — Trigger deploys + verify

1. Click **Deploy** on `iwo3-node`. First build takes ~2–3 min.
2. Click **Restart** on `iwo3-api` so the new `IWO3_SERVICE_TOKEN`
   env var is picked up.
3. Copy the public URL of `iwo3-node` from its Networking tab
   (e.g. `https://iwo3-node-production.up.railway.app`).

### Step 6 — Smoke test from terminal

```bash
NODE_URL="https://iwo3-node-production.up.railway.app"   # ← yours
SVC_TOKEN="<the hex from step 2>"

# (a) Node service healthcheck
curl -s "$NODE_URL/api/health" | jq .
# expect: {"status":"ok", ...}

# (b) Node→FastAPI cross-service handshake (service-token path).
# Substitute a real user id + client id from your tenant; this is a
# minimal probe that proves the bridge is wired correctly.
curl -s "https://iwo3-api-production.up.railway.app/workspace/brand" \
  -H "X-IWO3-User: <some-user-uuid>" \
  -H "X-IWO3-Client: <some-client-uuid>" \
  -H "X-IWO3-Service-Token: $SVC_TOKEN" | jq .
# expect: 200 JSON with {client_id, has_brand_profile, palette, ...}

# (c) Negative test — wrong token must 401:
curl -i "https://iwo3-api-production.up.railway.app/workspace/brand" \
  -H "X-IWO3-User: <some-user-uuid>" \
  -H "X-IWO3-Client: <some-client-uuid>" \
  -H "X-IWO3-Service-Token: wrong" | head -1
# expect: HTTP/1.1 401
```

## Streamlit Cloud wiring

On the existing Streamlit Cloud `aiden-iwo3.streamlit.app` deployment,
add **one** secret:

```text
IWO3_SANDBOX_URL = "https://iwo3-node-production.up.railway.app"
```

(Use whatever public URL Railway hands out — the repo defaults to local
`http://localhost:5050` when unset.)

The Streamlit `/sandbox` page reads this on every render: it probes
`<base>/api/health` and renders the green "Node sandbox reachable"
badge when the probe succeeds.

Note: Streamlit does NOT need `IWO3_SERVICE_TOKEN` itself. The
service-token bridge is only used on the Node→FastAPI seam. Streamlit
calls FastAPI via the operator's own JWT (issued at login), which
already works hosted.

## What this image deliberately does NOT bundle

- **Playwright Chromium** — the `Dockerfile.node` image is intentionally
  lean. The HTML→PDF / HTML→PPTX export endpoints return a clean
  `412 skills_unavailable` until either Playwright + the
  `claude-office-skills` tree are bundled, or a separate render worker
  is provisioned. Residual carried forward in the Sandbox Everywhere +
  Markdown Review handbacks.
- **claude-office-skills checkout** — same reason. Operators who need
  hosted export should either (a) set `SKILLS_DIR` + `PLAYWRIGHT_PATH`
  in env to a mounted volume, or (b) wait for the render-worker loop.

## What works hosted after this bring-up

| Surface | Status |
| --- | --- |
| Streamlit launcher card with green reachability badge | ✓ |
| Open canonical sandbox in new tab | ✓ |
| Sign in (BOOTSTRAP_ADMIN_PASSWORD flow on Node) | ✓ |
| Session create / list / delete | ✓ |
| Rerender from workspace artifact UUID (md/html/code/text) | ✓ |
| Rerender from PDF/PPTX/DOC with extracted text | ✓ |
| HTML preview with **tenant-branded** palette + fonts | ✓ (Markdown Review Layer, 2026-05-18) |
| HTML publish to GitHub Pages | ✓ (when `GITHUB_TOKEN` provisioned) |
| Canonical export `/api/output-packages/:id/export` | ✓ (returns 412 skills_unavailable until Playwright bundled — but reaches the bridge) |
| HTML→PDF export (sandbox session-bound) | residual — 412 |
| HTML→PPTX export | residual — 412 + html2pptx not bundled |

## What works locally today

Same as hosted, plus HTML→PDF and HTML→PPTX export when:

```bash
export SKILLS_DIR=/home/virgina/claude-office-skills
export PLAYWRIGHT_PATH=$SKILLS_DIR/node_modules/playwright
```

are set in the Node process's environment before `npm run dev`.
Local FastAPI runs in `IWO3_AUTH_MODE=dev_bearer` so no service token
is needed for local Node→FastAPI calls.

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
  sees a destructive toast + an error log entry in the session.
- Streamlit local + hosted Node sandbox → same shape, opposite direction.
- Hosted Node service with `IWO3_SERVICE_TOKEN` missing OR mismatched
  → cross-service rerender returns `fastapi_error` (401) and the
  operator sees an error in the session preview. Step 6 smoke test
  catches this before operator-facing traffic.

Correct setups:

- Streamlit hosted + Node hosted (both on the same Railway Postgres,
  both with matching `IWO3_SERVICE_TOKEN` on Node + FastAPI).
- Streamlit local + Node local (both on `aiden_iwo3` at
  `127.0.0.1:5434`; `IWO3_SERVICE_TOKEN` not required in dev_bearer
  mode).

## Operator checklist (the remaining manual steps)

The code side is complete. The remaining work is dashboard-only:

1. ⬜ Generate `openssl rand -hex 32` → keep handy.
2. ⬜ Create `iwo3-node` service on Railway (steps 1–3 above).
3. ⬜ Paste env vars onto `iwo3-node` including the new
       `IWO3_SERVICE_TOKEN`.
4. ⬜ Add the SAME `IWO3_SERVICE_TOKEN` to existing `iwo3-api` env vars.
5. ⬜ Deploy `iwo3-node` + restart `iwo3-api`.
6. ⬜ Copy `iwo3-node` public URL.
7. ⬜ Run step 6 smoke tests (curl health + curl brand + curl wrong
       token = 401).
8. ⬜ Set `IWO3_SANDBOX_URL` secret on Streamlit Cloud to the
       `iwo3-node` URL.
9. ⬜ Reload `aiden-iwo3.streamlit.app/sandbox` → expect green
       "Node sandbox reachable" badge.
10. ⬜ Click "Open Sandbox ↗" → expect Node sign-in screen → enter
        `BOOTSTRAP_ADMIN_PASSWORD` → confirm canonical sandbox loads.

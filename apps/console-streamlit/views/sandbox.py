"""Sandbox Everywhere Darkmode (2026-05-11) — Streamlit front-door
launcher for the canonical Node/React sandbox.

This page is NOT a parallel sandbox. The real sandbox UI lives at the
Node/React app's `/sandbox` route. This Streamlit surface is a thin
launcher + health card + local-vs-hosted instructions.

Sandbox-bounded:
- one canonical sandbox UI lives in Node/React
- Streamlit is a launcher, not the execution surface
- when the canonical URL isn't configured, show local + hosted
  setup instructions instead of a misleading placeholder
"""

from __future__ import annotations

import os

import streamlit as st

try:
    import httpx
except Exception:  # pragma: no cover - httpx ships with the api_client
    httpx = None  # type: ignore[assignment]


_DEFAULT_LOCAL = "http://localhost:5050"


def _resolve_sandbox_url() -> tuple[str, str]:
    """Return (url, source). Source is 'env' or 'local-default'."""
    env_url = os.environ.get("IWO3_SANDBOX_URL") or os.environ.get(
        "IWO3_NODE_BASE_URL"
    )
    if env_url:
        return env_url.rstrip("/") + "/sandbox", "env"
    return _DEFAULT_LOCAL + "/sandbox", "local-default"


def _probe_health(base_url: str) -> dict:
    if httpx is None:
        return {"ok": False, "kind": "no_httpx", "detail": "httpx not available"}
    health_url = base_url.replace("/sandbox", "") + "/api/health"
    try:
        r = httpx.get(health_url, timeout=2.0)
        if r.status_code == 200:
            try:
                payload = r.json()
            except Exception:
                payload = {}
            return {"ok": True, "version": payload.get("version"), "url": health_url}
        return {
            "ok": False,
            "kind": "http_error",
            "status": r.status_code,
            "url": health_url,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "kind": "unreachable", "detail": str(exc), "url": health_url}


st.markdown("# Sandbox")
st.caption(
    "Canonical sandbox UI lives in the Node/React surface. This page is a launcher, not a duplicate sandbox."
)

sandbox_url, source = _resolve_sandbox_url()
health = _probe_health(sandbox_url)

c1, c2 = st.columns([3, 2])

with c1:
    st.markdown("### Open the canonical sandbox")
    # The Node app requires a browser session cookie. First-time
    # operators get a 302 redirect to a login screen when they click
    # straight to /sandbox, which looks like the sandbox is "broken."
    # The dev-bypass (NODE_ENV=development) sets the cookie + redirects
    # to /; surface that as the first step so the click flow is
    # deterministic. Hosted deploys disable the dev-bypass and use the
    # BOOTSTRAP_ADMIN_PASSWORD path documented in Hosted setup below.
    base = sandbox_url.replace("/sandbox", "")
    login_url = base + "/api/login"
    st.markdown("**Step 1 — sign in (first visit only):**")
    st.link_button(
        "Sign in to Node app (dev bypass) ↗",
        login_url,
        type="secondary",
        help=(
            "Opens /api/login in a new tab. Dev-only bypass: sets the "
            "session cookie + redirects to /. Hosted deploys block this "
            "route — use the BOOTSTRAP_ADMIN_PASSWORD email/password "
            "form instead."
        ),
    )
    st.caption(login_url)
    st.markdown("**Step 2 — open the sandbox:**")
    st.link_button("Open Sandbox ↗", sandbox_url, type="primary")
    st.code(sandbox_url, language="text")
    if source == "env":
        st.caption(
            "Configured via `IWO3_SANDBOX_URL` / `IWO3_NODE_BASE_URL` env var."
        )
    else:
        st.caption(
            "No `IWO3_SANDBOX_URL` set; defaulting to local Node dev URL."
        )

with c2:
    st.markdown("### Reachability")
    if health.get("ok"):
        st.success(
            f"Node sandbox reachable. version={health.get('version') or 'unknown'}"
        )
    else:
        kind = health.get("kind", "unknown")
        if kind == "unreachable":
            st.warning(
                "Node sandbox not reachable from this Streamlit host. See setup notes below."
            )
        elif kind == "http_error":
            st.warning(
                f"Node sandbox returned HTTP {health.get('status')}. See setup notes below."
            )
        else:
            st.warning(f"Could not probe sandbox health: {kind}")
        st.caption(health.get("url", sandbox_url))


st.divider()

st.markdown("### Local setup")
st.markdown(
    "1. From the IWO3 repo root: `npm run dev` (boots the Node/React app on http://localhost:5050)\n"
    "2. Sign in (BOOTSTRAP_ADMIN_PASSWORD or local Replit dev auth)\n"
    "3. Navigate to `/sandbox` or click **Open Sandbox** above\n"
    "4. Create a session, paste a workspace artifact UUID to drive rerender / preview / publish"
)

st.markdown("### Hosted setup")
st.markdown(
    "On hosted IWO3, point `IWO3_SANDBOX_URL` (or `IWO3_NODE_BASE_URL`) at the "
    "Node/React Railway service URL — for example `https://iwo3-node-production.up.railway.app`. "
    "The Streamlit Cloud app reads that env var and renders the launcher; the sandbox itself "
    "runs in the Node service, not in Streamlit. Operator login on the hosted Node service "
    "uses the `BOOTSTRAP_ADMIN_PASSWORD` path documented in the deploy notes."
)

st.markdown("### Source artifacts supported")
st.markdown(
    "- Markdown (`text/markdown`)\n"
    "- Self-contained HTML (`text/html`)\n"
    "- Code / text artifacts (any `text/*`)\n"
    "- PDF / PPTX / DOCX **when** extracted text is present (FastAPI surface\n"
    "  returns `extracted_from: <mime>` for those rows)\n"
    "- Binary uploads without extracted text fail cleanly, not silently"
)

st.markdown("### Outputs")
st.markdown(
    "- HTML preview + HTML publish (to GitHub Pages, via `GITHUB_TOKEN`)\n"
    "- Best-effort HTML→PDF and HTML→PPTX export via existing `server/scripts/html-to-{pdf,pptx}.cjs`\n"
    "  scripts when Playwright + claude-office-skills are available; returns a\n"
    "  clean `412 skills_unavailable` otherwise (typical on hosted Railway today)."
)

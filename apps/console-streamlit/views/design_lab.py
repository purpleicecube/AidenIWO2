"""Design Lab — live-adapter status surface + MCP-design-tool portal.

Two parallel lanes:

  1. Output adapters (Loop 9 Phase 9.5) — Gamma is wired to the real
     `/adapter_status/{key}` route. The four states surface exactly what
     the dispatcher's dual gate sees:
         live_confirmed          Green chip; adapter will dispatch live
         pending_confirmation    Amber chip; admin must confirm first invocation
         disabled                Gray chip; env flag not set to "true"
         credential_missing      Red chip; no adapter_credentials row for tenant
     Figma / Claude Design Studio / Sandbox PPTX/PDF remain Loop 10+
     placeholders pending their adapter implementations (non-Gamma
     symmetry preserved per IWO3_LOOP_8_3_CODEX_DECISIONS §Q4).

  2. MCP design tools (Loop Eta phase 1.4 post-close) — Stitch shipped
     as a runnable MCP tool, NOT as a Gamma-style output adapter, so its
     status is read from `/tools/stitch_design/test_connection` (live
     stdio session + list_tools enumeration), not from
     `/adapter_status/`. The Stitch Projects card below also exposes an
     in-page iframe portal + an external-launch button (operator's
     browser session against stitch.google.com).
"""

from __future__ import annotations

from html import escape

import streamlit as st

from api_client import APIError, AdapterStatus
from shell import page_requires_api


def _status_chip(status: str) -> str:
    """Return an inline-styled span matching the shell's iwo3 chip look."""
    mapping = {
        "live_confirmed": ("Live", "iwo3-chip green"),
        "pending_confirmation": ("Pending confirmation", "iwo3-chip amber"),
        "disabled": ("Disabled", "iwo3-chip blue"),
        "credential_missing": ("Credential missing", "iwo3-chip red"),
    }
    label, cls = mapping.get(status, (status, "iwo3-chip blue"))
    return f'<span class="{cls}">{escape(label)}</span>'


def _gamma_live_card(status: AdapterStatus) -> None:
    # The card renders the raw status machine + the operator actions
    # implied by each state. No fake status values anywhere — every
    # field came back from /adapter_status/gamma just now.
    state_line_map = {
        "live_confirmed": (
            "Gamma live is authorized for this tenant. Dispatches will "
            "go to the real Gamma API using the env-injected credential."
        ),
        "pending_confirmation": (
            "Credential is bound, env flag is true, but no first "
            "invocation has been confirmed. An admin must POST to "
            "/adapter_credentials/{id}/confirm_first_invocation before "
            "live dispatch is allowed."
        ),
        "disabled": (
            "GAMMA_LIVE_ENABLED is not set to \"true\" in the runtime "
            "environment. All Gamma dispatches will fall through the "
            "Loop 9 Phase 9.1 gate with `adapter_dispatch.live_disabled`."
        ),
        "credential_missing": (
            "No adapter_credentials row exists for (this tenant, gamma). "
            "Create one with credential_ref=credential_ref:env:NAME, "
            "then ask an admin to confirm the first invocation."
        ),
    }
    state_body = state_line_map.get(
        status.status, "Unknown status returned by /adapter_status/gamma."
    )

    confirmed_line = (
        f"<div class=\"d\">Confirmed at: <code>{escape(status.first_invocation_confirmed_at)}</code></div>"
        if status.first_invocation_confirmed_at
        else ""
    )
    cred_line = (
        f"<div class=\"d\">Credential ref: <code>{escape(status.credential_ref)}</code></div>"
        if status.credential_ref
        else ""
    )
    env_line = (
        f"<div class=\"d\">Env flag: <code>{escape(status.env_flag_name)}</code> — "
        f"{'✓ true' if status.env_flag_enabled else '✗ not true'}</div>"
        if status.env_flag_name
        else ""
    )

    html = (
        '<div class="iwo3-tier-card">'
        '<div class="t">Gamma (live render) '
        f'{_status_chip(status.status)}</div>'
        f'<div class="d">{escape(state_body)}</div>'
        f'{env_line}{cred_line}{confirmed_line}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _tool_card(name: str, status: str, blurb: str) -> None:
    status_chip = "iwo3-chip-ok" if status == "ready" else "iwo3-chip-m"
    st.markdown(
        f"""
        <div class="iwo3-tier-card">
          <div class="t">{name} <span class="{status_chip}">{status}</span></div>
          <div class="d">{blurb}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ── Stitch (MCP — Loop Eta phase 1.4) ─────────────────────────────────
#
# Stitch is NOT a Gamma-style output adapter. It shipped via Loop Eta
# Worker I as a runnable MCP tool: the runtime spawns the bundled
# stdio proxy at vendor/stitch-mcp-proxy.mjs, list_tools enumerates the
# Stitch toolset, Tier 2 sub-agents (Hank, Darla) call individual
# Stitch tools mid-generation through the tool-call loop. The card
# below proves liveness via the same connection-test endpoint that
# Worker I shipped (/tools/stitch_design/test_connection) plus exposes
# an iframe portal so operators can browse their Stitch projects from
# inside Design Lab without leaving the console.

_STITCH_PUBLIC_URL = "https://stitch.google.com"


def _stitch_live_card(api) -> None:
    """Render the Stitch MCP live-status card with portal affordances."""
    try:
        result = api.test_stitch_connection()
    except APIError as err:
        # Down-but-detailed: surface the runtime kind so an operator
        # knows whether to fix env vars (kind=config_missing) or check
        # the upstream Stitch service (kind=handshake_failed/timeout).
        result = {
            "ok": False,
            "server_name": "stitch",
            "tool_count": None,
            "latency_ms": None,
            "sample_tool_names": [],
            "error": err.detail or str(err),
            "kind": "api_error",
        }

    ok = bool(result.get("ok"))
    if ok:
        chip = '<span class="iwo3-chip green">Live (MCP)</span>'
        body = (
            "Stitch MCP stdio session connects from the IWO3 runtime, "
            "enumerates "
            f"<strong>{int(result.get('tool_count') or 0)}</strong> tool(s), "
            "and is callable mid-generation by Hank and Darla via the "
            "Tier 2 tool-call loop. See <em>Sub-Agents → Hank / Darla → "
            "Tool Access</em> to grant or revoke per-agent assignment."
        )
        latency_ms = result.get("latency_ms")
        sample = result.get("sample_tool_names") or []
    else:
        chip = '<span class="iwo3-chip red">Unreachable</span>'
        kind = escape(str(result.get("kind") or "unknown"))
        detail = escape(str(result.get("error") or "(no detail)"))
        body = (
            f"Stitch MCP connection failed: <code>{kind}</code> — {detail}. "
            "Check Railway env vars (<code>STITCH_API_KEY</code>) and that "
            "the bundled proxy at "
            "<code>apps/api-fastapi/vendor/stitch-mcp-proxy.mjs</code> "
            "is reachable inside the FastAPI container."
        )
        latency_ms = None
        sample = []

    latency_line = (
        f'<div class="d">Last test: <code>{int(latency_ms)} ms</code></div>'
        if latency_ms is not None
        else ""
    )
    sample_line = (
        f'<div class="d">Sample tools: <code>{escape(", ".join(sample[:5]))}</code></div>'
        if sample
        else ""
    )

    html = (
        '<div class="iwo3-tier-card">'
        f'<div class="t">Google Stitch {chip}</div>'
        f'<div class="d">{body}</div>'
        f'{latency_line}{sample_line}'
        '</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def _stitch_projects_portal() -> None:
    """In-page iframe portal for Stitch projects + external eject button.

    Google Stitch may set X-Frame-Options or CSP frame-ancestors that
    blocks iframe embedding. The eject button is the always-works
    fallback. The fallback caption tells operators which one to use.
    """
    st.markdown("#### Stitch Projects")
    st.caption(
        "Browse your Stitch projects in-place, or open them in a new "
        "tab using your existing Google session."
    )

    col_open, col_eject = st.columns([1, 1])
    with col_open:
        if st.button(
            "Open in panel",
            type="primary",
            key="stitch_panel_toggle",
        ):
            st.session_state.stitch_panel_open = not st.session_state.get(
                "stitch_panel_open", False
            )
    with col_eject:
        st.link_button(
            "Open Stitch in a new tab ↗",
            _STITCH_PUBLIC_URL,
            type="secondary",
            use_container_width=True,
        )

    if st.session_state.get("stitch_panel_open"):
        st.components.v1.iframe(
            _STITCH_PUBLIC_URL,
            height=900,
            scrolling=True,
        )
        st.caption(
            "The panel above renders Stitch using your browser's "
            "existing Google session. If it's blank, Google is "
            "blocking embedded display via X-Frame-Options or CSP — "
            "use the new-tab button on the right instead. Either path "
            "lands at the same Stitch projects view."
        )


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Design Lab</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Design tooling lane — Gamma live dispatch status, sandbox fallbacks,
          MCP design tools (Stitch live), and future design environments.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    # Live Gamma status — real call to /adapter_status/gamma.
    st.markdown("### Template PPT / PDF production")
    try:
        status = api.get_adapter_status("gamma")
        _gamma_live_card(status)
    except APIError as err:
        st.error(
            f"{err.status_code} — could not read /adapter_status/gamma: "
            f"{err.detail}"
        )

    _tool_card(
        "Sandbox PPTX / PDF",
        "Loop 10+",
        "Local fallback for fidelity/privacy-sensitive renders. "
        "Will ship under /adapter_status/sandbox_pptx once the adapter "
        "registers — same 4-state shape as Gamma.",
    )

    # MCP design tools — Stitch live (Loop Eta phase 1.4 post-close).
    st.markdown("### Design tools (MCP)")
    _stitch_live_card(api)
    _stitch_projects_portal()

    # Adapter-style design environments — still Loop 10+ pending the
    # Gamma-symmetric output-adapter implementations. Stitch deliberately
    # NOT in this section anymore because Stitch shipped via the MCP tool
    # lane, not the output-adapter lane.
    st.markdown("### Design environments (output adapters)")
    _tool_card(
        "Figma",
        "Loop 10+",
        "Future adapter for handing off live Figma artboards.",
    )
    _tool_card(
        "Claude Design Studio",
        "Loop 10+",
        "Future adapter for Claude-assisted design workflows.",
    )

    st.info(
        "Design Lab is a product lane, not a dev scratchpad. The 4-state "
        "Gamma card reflects the real runtime gate — "
        "GAMMA_LIVE_ENABLED + adapter_credentials + "
        "first_invocation_confirmed_at — and any live invocation "
        "traverses the Phase 9.1 dual gate + Phase 9.2 live adapter + "
        "Phase 9.4 async polling. The Stitch card is read live from "
        "/tools/stitch_design/test_connection (Loop Eta phase 1.4); "
        "Stitch shipped via the MCP tool lane, not the adapter lane, "
        "and is callable mid-generation by Hank/Darla."
    )


main()

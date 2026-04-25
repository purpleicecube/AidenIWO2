"""Design Lab — live-adapter status surface.

Loop 9 Phase 9.5 wires this page to the real `/adapter_status/{key}`
route. The four states surface exactly what the dispatcher's dual gate
(env flag + first_invocation_confirmed_at) sees, so the UI is never
out-of-date with runtime behaviour:

  live_confirmed          Green chip; adapter will dispatch live
  pending_confirmation    Amber chip; admin must confirm first invocation
  disabled                Gray chip; env flag not set to "true"
  credential_missing      Red chip; no adapter_credentials row for tenant

Non-Gamma adapters (Figma / Stitch / Claude Design / Sandbox PPTX/PDF)
stay as static Loop-10+ placeholder cards — they will move to live
status rows as they ship, using the same `/adapter_status/{key}` shape
(non-Gamma symmetry preserved per IWO3_LOOP_8_3_CODEX_DECISIONS §Q4).
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


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Design Lab</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Design tooling lane — Gamma live dispatch status, sandbox fallbacks,
          and future design environments. All non-Gamma adapters remain Loop 10+
          and go through separate approval.
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

    st.markdown("### Design environments")
    _tool_card(
        "Google Stitch",
        "Loop 10+",
        "Figma-style design environment; contract-gated adapter lands "
        "alongside the other non-Gamma adapters.",
    )
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
        "Gamma card above reflects the real runtime gate — "
        "GAMMA_LIVE_ENABLED + adapter_credentials + "
        "first_invocation_confirmed_at. Any live invocation traverses "
        "the Phase 9.1 dual gate + Phase 9.2 live adapter + Phase 9.4 "
        "async polling."
    )


main()

"""Design Lab — placeholder sections for the IWO3 design environment.

Reflects WS024 intent that DESIGNLAB be the lane for Figma / Stitch /
Claude Design / Gamma template PPT·PDF production. No live external
integrations here; those are Loop 10+ with explicit approval.
"""

from __future__ import annotations

import streamlit as st

from shell import page_requires_api


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
          Design tooling lane — Gamma / sandbox PPTX/PDF production plus
          Figma / Stitch / Claude Design hooks. All live integrations are
          Loop 10+ and go through separate approval.
        </div>
        """,
        unsafe_allow_html=True,
    )

    if page_requires_api() is None:
        return

    st.markdown("### Template PPT / PDF production")
    _tool_card(
        "Gamma (live render)",
        "Loop 9",
        "Authorized Klear template registry lives in the DB; live "
        "Gamma dispatch is Loop 9 off-test-double.",
    )
    _tool_card(
        "Sandbox PPTX / PDF",
        "Loop 10+",
        "Local fallback for fidelity/privacy-sensitive renders. "
        "Policy-selected per template + client.",
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
        "Design Lab is a product lane, not a dev scratchpad. Any live "
        "integration has to come with an explicit approval gate before "
        "we make an outbound network call (adapter policy `disallowed` "
        "or `approval_required` per the Phase 3.2 contract)."
    )


main()

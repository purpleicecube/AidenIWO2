"""Shared builder for placeholder pages — minimum content + IWO2-parity
shell so the sidebar looks right even for routes that land in later loops."""

from __future__ import annotations

import streamlit as st

from shell import page_requires_api


def render_placeholder(
    icon: str, title: str, subtitle: str, deferred_to: str, items: list[str]
) -> None:
    st.markdown(f"## {icon} {title}")
    st.caption(subtitle)
    if page_requires_api() is None:
        return
    st.warning(f"🏗️  This surface is a **placeholder** — full implementation is {deferred_to}.")
    st.markdown("### What will live here")
    for item in items:
        st.markdown(f"- {item}")
    st.divider()
    st.caption("Scope is fixed in the IWO3 loop plan; this page renders so the sidebar matches the final product shell.")

"""Shared helper for IWO3 placeholder pages.

Renders as a designed "pending product surface" block (IWO2-aligned),
not as default-Streamlit copy, so placeholder pages don't cheapen the
sidebar that links to them.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from shell import page_requires_api


def render_placeholder(
    title: str,
    subtitle: str,
    deferred_to: str,
    items: list[str],
) -> None:
    if page_requires_api() is None:
        # Still render the heading so the page isn't blank.
        pass
    st.markdown(
        f"""
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">{escape(title)}</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          {escape(subtitle)}
        </div>
        """,
        unsafe_allow_html=True,
    )
    items_html = "".join(f"<li>{escape(i)}</li>" for i in items)
    st.markdown(
        f"""
        <div class="iwo3-placeholder">
          <h4>Pending product surface — {escape(deferred_to)}</h4>
          <div style="font-size:0.88rem; color:#4B5563; margin-bottom:10px;">
            Scope is fixed in the IWO3 loop plan. The sidebar links here so
            the product shell matches the final IWO2 structure; the full
            implementation lands in the named loop.
          </div>
          <div style="font-size:0.82rem; color:#6B7280; font-weight:600; text-transform:uppercase;
                      letter-spacing:0.04em; margin-bottom:6px;">What will live here</div>
          <ul style="margin:0; padding-left:18px; color:#374151; font-size:0.9rem;">{items_html}</ul>
        </div>
        """,
        unsafe_allow_html=True,
    )

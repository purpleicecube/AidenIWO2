"""Sub-Agents — MegaLoop Alpha α.7 live wiring.

Lists the tenant's per-role LLM configs and exposes a one-shot
connection-test button per row. Each test runs a real chat completion
against the resolved config (admin-only) and returns provider /
model / latency / sample text. Token usage is audit-logged via
`llm_provider.connection_tested`.

The Loop 8.3 placeholder has been removed.
"""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


_ROLE_LABELS = {
    "aiden_tier_1": "Aiden (Tier 1)",
    "pm_tier_15": "PM (Tier 1.5)",
    "mark_tier_2": "Mark (content)",
    "tom_tier_2": "Tom (decks)",
    "hank_tier_2": "Hank (web)",
    "paul_tier_2": "Paul (deployment)",
}


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Sub-Agents</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tier-1 / Tier-1.5 / Tier-2 LLM configs for this tenant. Each
          row is the resolved (provider, model) the runtime will call.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    try:
        configs = api.list_llm_configs()
        can_admin = api.check_permission("system:admin")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    if not configs:
        st.info(
            "No LLM configs for this tenant yet. The seed loader writes the "
            "default Klear configs (Aiden / PM / Mark / Tom / Hank / Paul); "
            "if you're seeing this on a fresh DB, run the seed loader."
        )
        return

    st.caption(
        f"{len(configs)} config row(s). Connection test requires the "
        f"system:admin permission."
    )

    for cfg in sorted(configs, key=lambda c: c["agent_role"]):
        label = _ROLE_LABELS.get(cfg["agent_role"], cfg["agent_role"])
        chip = "🟢" if cfg["enabled"] else "⚪"
        with st.expander(
            f"{chip} **{label}** — `{cfg['provider']}` / `{cfg['model']}`",
            expanded=False,
        ):
            cols = st.columns([2, 1, 1])
            with cols[0]:
                st.markdown(f"**Role:** `{cfg['agent_role']}`")
                st.markdown(f"**Provider:** `{cfg['provider']}`")
                st.markdown(f"**Model:** `{cfg['model']}`")
                st.markdown(
                    f"**Has system prompt:** "
                    f"{'yes' if cfg['has_system_prompt'] else 'no'}"
                )
            with cols[1]:
                st.markdown(
                    f"**Enabled:** {'✅' if cfg['enabled'] else '⛔'}"
                )
            with cols[2]:
                btn_key = f"test-{cfg['id']}"
                disabled = not can_admin.allowed
                help_text = (
                    None
                    if can_admin.allowed
                    else f"system:admin required (your role: {can_admin.role})"
                )
                if st.button(
                    "Run connection test",
                    key=btn_key,
                    disabled=disabled,
                    help=help_text,
                ):
                    with st.spinner("calling provider…"):
                        try:
                            r = api.test_llm(agent_role=cfg["agent_role"])
                        except APIError as err:
                            st.error(f"❌ {err.status_code} — {err.detail}")
                            r = None
                    if r:
                        if r.get("ok"):
                            st.success(
                                f"✅ ok — {r['provider']}/{r['model']} · "
                                f"{r['latency_ms']}ms · "
                                f"{r['completion_chars']} chars"
                            )
                            if r.get("sample"):
                                st.caption(f"Sample: {r['sample']}")
                        else:
                            st.warning(
                                f"⚠️ ok=false — {r.get('error')}"
                            )


main()

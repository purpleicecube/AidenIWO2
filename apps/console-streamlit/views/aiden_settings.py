"""Aiden Settings — MegaLoop Alpha α.7 live wiring.

Three sections (each backed by real API calls — no placeholders):

  1. Provider availability         GET /llm/providers
  2. Resolved Tier-1 LLM config    GET /llm/configs (filtered to aiden_tier_1)
                                   + POST /llm/test connection check
  3. Channel auth-code issuance    POST /channel/auth_codes per Stage A § B7
                                   + GET  /channel/identities live list
                                   + POST /channel/identities/{id}/revoke

Operators bring up a Telegram bot for this tenant by:
  (a) Issuing an auth code here.
  (b) DM the tenant's Telegram bot with `/start <code>`.
  (c) The polling worker consumes the code, binds the chat, and the
      identity appears in the list below.
"""

from __future__ import annotations

import streamlit as st

from api_client import APIError
from shell import page_requires_api


_CHANNEL_KINDS = ["telegram", "slack", "email", "sms"]


def _section_providers(api) -> None:  # noqa: ANN001
    st.subheader("LLM provider availability")
    try:
        providers = api.list_llm_providers()
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return
    cols = st.columns(len(providers))
    for i, p in enumerate(providers):
        with cols[i]:
            chip = "🟢" if p["callable_in_phase_9_3"] else "⚪"
            st.markdown(f"**{chip} {p['name']}**")
            st.caption(
                "callable" if p["callable_in_phase_9_3"] else "registered"
            )


def _section_aiden_config(api) -> None:  # noqa: ANN001
    st.subheader("Aiden (Tier 1) — resolved config")
    try:
        configs = api.list_llm_configs()
        can_admin = api.check_permission("system:admin")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return
    aiden = next(
        (c for c in configs if c["agent_role"] == "aiden_tier_1"), None
    )
    if aiden is None:
        st.warning(
            "No `aiden_tier_1` config for this tenant. Run the seed "
            "loader or insert a config row before using Chat with Aiden."
        )
        return
    cols = st.columns([2, 2, 1])
    with cols[0]:
        st.markdown(f"**Provider:** `{aiden['provider']}`")
        st.markdown(f"**Model:** `{aiden['model']}`")
    with cols[1]:
        st.markdown(
            f"**Enabled:** {'✅' if aiden['enabled'] else '⛔'}"
        )
        st.markdown(
            f"**System prompt:** "
            f"{'yes' if aiden['has_system_prompt'] else 'default'}"
        )
    with cols[2]:
        if st.button(
            "Test connection",
            key="aiden-test",
            disabled=not can_admin.allowed,
            help=(
                None
                if can_admin.allowed
                else f"system:admin required (your role: {can_admin.role})"
            ),
        ):
            with st.spinner("calling provider…"):
                try:
                    r = api.test_llm(agent_role="aiden_tier_1")
                except APIError as err:
                    st.error(f"❌ {err.status_code} — {err.detail}")
                    return
            if r.get("ok"):
                st.success(
                    f"✅ {r['provider']}/{r['model']} · "
                    f"{r['latency_ms']}ms"
                )
            else:
                st.warning(f"⚠️ {r.get('error')}")


def _section_auth_codes(api) -> None:  # noqa: ANN001
    st.subheader("Channel auth codes (Stage A § B7)")
    can_issue = None
    try:
        can_issue = api.check_permission("channel_auth_code:issue")
        can_revoke = api.check_permission("channel_identity:revoke")
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    cols = st.columns([2, 1, 1])
    with cols[0]:
        kind = st.selectbox(
            "Channel", _CHANNEL_KINDS, index=0, key="auth-code-kind"
        )
    with cols[1]:
        ttl = st.number_input(
            "TTL (min)", min_value=1, max_value=1440, value=15,
            key="auth-code-ttl",
        )
    with cols[2]:
        if st.button(
            "Issue code",
            key="auth-code-issue",
            disabled=not can_issue.allowed,
            help=(
                None
                if can_issue.allowed
                else (
                    f"channel_auth_code:issue required "
                    f"(your role: {can_issue.role})"
                )
            ),
        ):
            try:
                resp = api.issue_channel_auth_code(
                    channel_kind=kind, ttl_minutes=int(ttl)
                )
                st.success(
                    f"✅ Code: `{resp['code']}` (expires "
                    f"{resp['expires_at']})"
                )
                st.code(resp["instructions"], language="text")
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")

    st.markdown("**Bound identities**")
    try:
        identities = api.list_channel_identities(only_active=False)
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return
    if not identities:
        st.caption("No identities bound yet for this tenant.")
        return
    for ident in identities:
        with st.container():
            cols = st.columns([3, 1, 1, 1])
            with cols[0]:
                st.markdown(
                    f"`{ident['channel_kind']}` · `{ident['external_id']}` "
                    f"→ user `{ident['user_id'][:8]}…`"
                )
            with cols[1]:
                st.markdown(
                    "🟢 active" if ident["status"] == "active" else "⚪ revoked"
                )
            with cols[2]:
                if ident.get("last_seen_at"):
                    st.caption(f"last seen: {ident['last_seen_at']}")
            with cols[3]:
                if ident["status"] == "active":
                    if st.button(
                        "Revoke",
                        key=f"rev-{ident['id']}",
                        disabled=not can_revoke.allowed,
                        help=(
                            None
                            if can_revoke.allowed
                            else (
                                "channel_identity:revoke required "
                                f"(your role: {can_revoke.role})"
                            )
                        ),
                    ):
                        try:
                            api.revoke_channel_identity(ident["id"])
                            st.success("Revoked.")
                            st.rerun()
                        except APIError as err:
                            st.error(f"❌ {err.detail}")


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Aiden Settings</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Live LLM configuration + channel binding for this tenant.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    _section_providers(api)
    st.divider()
    _section_aiden_config(api)
    st.divider()
    _section_auth_codes(api)


main()

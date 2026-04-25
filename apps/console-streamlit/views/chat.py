"""Chat with Aiden — MegaLoop Alpha α.7 live wiring.

Sends each operator message to `POST /aiden/chat`, which runs Aiden
Tier 1 against the tenant's resolved LLM config (Groq or OpenRouter
per Stage A § A2). The decision (work_order_brief / workflow_brief /
clarification) is rendered inline. No work_order is persisted by the
chat surface — the operator can confirm and promote a brief into a
real WO via Submit Order or by the dispatch path.

Removed: the Loop 8.3 local-dev placeholder reply.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def _seed_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": (
                "Hi — this is **Chat with Aiden**.\n\n"
                "Send anything. I'll classify it (Tier 1) and either:\n"
                "  • return a single-step **work_order_brief** assigned to "
                "a sub-agent (Mark/Tom/Hank/Paul), or\n"
                "  • propose a multi-step **workflow_brief** for the PM, or\n"
                "  • ask a **clarification** if your request is ambiguous.\n\n"
                "Token use is audit-logged; per-WO budget caps apply."
            ),
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source": "system",
        }
    ]


def _render_decision(reply: dict[str, Any]) -> str:
    if not reply.get("ok"):
        return f"❌ **Aiden could not classify this:** {reply.get('error')}"

    kind = reply.get("decision_kind")
    head = (
        f"_(Aiden · {reply.get('provider')}/{reply.get('model')} · "
        f"{reply.get('latency_ms')}ms)_\n\n"
    )

    if kind == "work_order_brief":
        b = reply.get("work_order_brief") or {}
        return (
            head
            + f"**Decision:** `work_order_brief`\n\n"
            + f"**Title:** {reply.get('title')}\n\n"
            + f"**Summary:** {reply.get('summary')}\n\n"
            + f"**Assigned role:** `{b.get('assigned_role')}`\n\n"
            + f"**Priority:** `{b.get('priority')}`\n\n"
            + "Promote into a real WO via Submit Order."
        )
    if kind == "workflow_brief":
        b = reply.get("workflow_brief") or {}
        return (
            head
            + f"**Decision:** `workflow_brief`\n\n"
            + f"**Title:** {reply.get('title')}\n\n"
            + f"**Template key:** `{b.get('workflow_template_key')}`\n\n"
            + f"**Summary:** {reply.get('summary')}"
        )
    if kind == "clarification":
        c = reply.get("clarification") or {}
        return (
            head
            + f"**Decision:** `clarification`\n\n"
            + f"**Question:** {c.get('question')}"
        )
    return head + f"Unknown decision shape: ```{reply}```"


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Chat with Aiden</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Live Tier-1 LLM classification. Token-budgeted, audit-logged.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    if "iwo3_chat_messages" not in st.session_state:
        st.session_state["iwo3_chat_messages"] = _seed_messages()

    messages: list[dict[str, Any]] = st.session_state["iwo3_chat_messages"]

    for m in messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            st.caption(m.get("ts", ""))

    user_text = st.chat_input("Ask Aiden anything…")
    if user_text:
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        messages.append(
            {"role": "user", "content": user_text, "ts": now, "source": "user"}
        )
        with st.spinner("Aiden is classifying…"):
            try:
                reply = api.aiden_chat(user_text)
                rendered = _render_decision(reply)
            except APIError as err:
                rendered = (
                    f"❌ **API error {err.status_code}:** {err.detail}"
                )
        messages.append(
            {
                "role": "assistant",
                "content": rendered,
                "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "source": "aiden",
            }
        )
        st.session_state["iwo3_chat_messages"] = messages
        st.rerun()

    if st.button("Clear history", key="chat-clear"):
        st.session_state["iwo3_chat_messages"] = _seed_messages()
        st.rerun()


main()

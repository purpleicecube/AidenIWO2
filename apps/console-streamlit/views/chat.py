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
from typing import Any, Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


def _seed_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": (
                "Hi — this is **Chat with Aiden**.\n\n"
                "This is the fastest way to scope real work in IWO3.\n\n"
                "Best results come from a concrete request with a deliverable, "
                "goal, and audience. I can:\n"
                "  • turn a request into a single-step work order,\n"
                "  • recommend a multi-step workflow,\n"
                "  • ask a clarifying question when the ask is underspecified,\n"
                "  • answer quick questions about how this intake surface works.\n\n"
                "When a request is clear, you can create and run it directly "
                "from the chat."
            ),
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source": "system",
        }
    ]


def _short_model_name(model: Optional[str]) -> str:
    if not model:
        return "unknown-model"
    return model.split("/")[-1]


def _provider_line(reply: dict[str, Any]) -> str:
    provider = reply.get("provider")
    model = _short_model_name(reply.get("model"))
    latency = reply.get("latency_ms")
    if provider and latency is not None:
        return f"_(Aiden used **{provider}** · `{model}` · {latency}ms)_\n\n"
    if provider:
        return f"_(Aiden used **{provider}** · `{model}`)_\n\n"
    return ""


def _render_decision(reply: dict[str, Any]) -> str:
    if not reply.get("ok"):
        error = reply.get("error") or "unknown_error"
        if "credential_missing" in error:
            return (
                "⚠️ **The live model is unavailable right now.**\n\n"
                "Aiden's provider credentials are missing in the running API "
                "environment, so only local assistant-reply shortcuts will work "
                "until the LLM key is restored."
            )
        return f"❌ **Aiden could not classify this:** {reply.get('error')}"

    kind = reply.get("decision_kind")
    head = _provider_line(reply)

    if kind == "assistant_reply":
        a = reply.get("assistant_reply") or {}
        lines = []
        if a.get("headline"):
            lines.append(f"**{a['headline']}**")
        if a.get("message"):
            lines.append(a["message"])
        suggestions = a.get("suggested_requests") or []
        if suggestions:
            lines.append(
                "**Try one of these:**\n"
                + "\n".join(f"- {item}" for item in suggestions)
            )
        return head + "\n\n".join(lines)

    if kind == "work_order_brief":
        b = reply.get("work_order_brief") or {}
        return (
            head
            + "**Here is what I think you need:** a single-step work order.\n\n"
            + f"**Title:** {reply.get('title')}\n\n"
            + f"**Summary:** {reply.get('summary')}\n\n"
            + f"**Recommended owner:** `{b.get('assigned_role')}`\n\n"
            + f"**Priority:** `{b.get('priority')}`\n\n"
            + "You can create it directly from this chat."
        )
    if kind == "workflow_brief":
        b = reply.get("workflow_brief") or {}
        return (
            head
            + "**This looks like a workflow, not a single-step work order.**\n\n"
            + f"**Title:** {reply.get('title')}\n\n"
            + f"**Template key:** `{b.get('workflow_template_key')}`\n\n"
            + f"**Summary:** {reply.get('summary')}\n\n"
            + "You can create the WO and instantiate the workflow from here."
        )
    if kind == "clarification":
        c = reply.get("clarification") or {}
        return (
            head
            + "**I need one more detail before I can route this cleanly.**\n\n"
            + f"**Question:** {c.get('question')}"
        )
    return head + f"Unknown decision shape: ```{reply}```"


def _append_status_message(
    messages: list[dict[str, Any]], content: str
) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source": "system",
        }
    )


def _promote_reply(
    api,
    messages: list[dict[str, Any]],
    reply: dict[str, Any],
    *,
    create_only: bool,
    key_seed: str,
) -> None:
    kind = reply.get("decision_kind")
    title = reply.get("title") or "Untitled request"
    summary = reply.get("summary")
    wo_type = "workflow_brief" if kind == "workflow_brief" else "content_brief"
    priority = (
        (reply.get("work_order_brief") or {}).get("priority")
        if kind == "work_order_brief"
        else "medium"
    ) or "medium"
    correlation_id = f"chat:{key_seed}"

    created = api.create_work_order(
        title=title,
        description=summary,
        wo_type=wo_type,
        priority=priority,
        correlation_id=correlation_id,
    )
    wo_id = created["id"]

    if create_only:
        _append_status_message(
            messages,
            f"✅ Created work order `{wo_id}` from this chat brief.",
        )
        return

    dispatch = api.dispatch_work_order(wo_id)
    if dispatch.get("ok"):
        if dispatch.get("decision_kind") == "work_order_brief":
            _append_status_message(
                messages,
                f"✅ Created and ran work order `{wo_id}`.\n\n"
                f"Output package: `{dispatch.get('output_package_id')}`",
            )
            return
        if dispatch.get("decision_kind") == "workflow_brief":
            _append_status_message(
                messages,
                f"✅ Created work order `{wo_id}` and instantiated workflow "
                f"`{dispatch.get('workflow_execution_id')}` "
                f"({len(dispatch.get('step_run_ids') or [])} steps).",
            )
            return

    if dispatch.get("decision_kind") == "clarification":
        _append_status_message(
            messages,
            f"⚠️ Created work order `{wo_id}`, but Aiden still needs a "
            f"clarification before dispatching:\n\n"
            f"{dispatch.get('clarification_question')}",
        )
    else:
        _append_status_message(
            messages,
            f"⚠️ Created work order `{wo_id}`, but dispatch did not complete:\n\n"
            f"{dispatch.get('error')}",
        )


def _render_actions(api, messages: list[dict[str, Any]], idx: int, reply: dict[str, Any]) -> None:
    kind = reply.get("decision_kind")
    if kind not in {"work_order_brief", "workflow_brief"}:
        return

    col1, col2 = st.columns([1, 1])
    label_create = "Create WO" if kind == "work_order_brief" else "Create workflow WO"
    label_run = (
        "Create + run now"
        if kind == "work_order_brief"
        else "Create + instantiate"
    )
    with col1:
        if st.button(label_create, key=f"chat-create-{idx}"):
            try:
                _promote_reply(
                    api,
                    messages,
                    reply,
                    create_only=True,
                    key_seed=f"{idx}-create",
                )
                st.session_state["iwo3_chat_messages"] = messages
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")
    with col2:
        if st.button(label_run, key=f"chat-run-{idx}", type="primary"):
            try:
                _promote_reply(
                    api,
                    messages,
                    reply,
                    create_only=False,
                    key_seed=f"{idx}-run",
                )
                st.session_state["iwo3_chat_messages"] = messages
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")


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

    for idx, m in enumerate(messages):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            st.caption(m.get("ts", ""))
            if m.get("source") == "aiden" and m.get("reply"):
                _render_actions(api, messages, idx, m["reply"])

    user_text = st.chat_input("Ask Aiden anything…")
    if user_text:
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        messages.append(
            {"role": "user", "content": user_text, "ts": now, "source": "user"}
        )
        reply = None
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
                "reply": reply,
            }
        )
        st.session_state["iwo3_chat_messages"] = messages
        st.rerun()

    if st.button("Clear history", key="chat-clear"):
        st.session_state["iwo3_chat_messages"] = _seed_messages()
        st.rerun()


main()

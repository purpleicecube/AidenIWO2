"""Chat with Aiden — Alpha closeout γ.1+γ.2.

Sends operator messages to `POST /aiden/chat`, renders the decision
inline, and lets the operator promote a brief into a real WO directly
from chat. After a successful create+run the chat tracks the resulting
WO/package/handoff in `iwo3_chat_context` so:

  - subsequent action buttons can deep-link to the artefact
  - follow-up prompts like "where is the output" resolve against the
    last-created package without burning a Tier 1 call

Idempotency: Streamlit's button rerun model can fire the same callback
twice on quick double-clicks; `iwo3_chat_promoted` keys per-action so a
second click is a no-op with an explanatory caption.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

import streamlit as st

from api_client import APIError
from shell import page_requires_api


# ── Session-state keys ────────────────────────────────────────────────

_MESSAGES_KEY = "iwo3_chat_messages"
_CONTEXT_KEY = "iwo3_chat_context"
_PROMOTED_KEY = "iwo3_chat_promoted"


def _seed_messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "assistant",
            "content": (
                "Hi — this is **Chat with Aiden**.\n\n"
                "Best results come from a concrete request with a deliverable, "
                "goal, and audience. I can:\n"
                "  • turn a request into a single-step work order,\n"
                "  • recommend a multi-step workflow,\n"
                "  • ask a clarifying question when the ask is underspecified,\n"
                "  • answer quick questions about how this surface works.\n\n"
                "Once a brief is clear you can create and run it from this "
                "chat — and follow up with `where is the output?` to find it."
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
    messages: list[dict[str, Any]],
    content: str,
    *,
    context_actions: Optional[dict[str, Any]] = None,
) -> None:
    """Append an assistant-side status message. `context_actions` carries
    `{work_order_id, output_package_id, workflow_execution_id}` so the
    renderer can attach Open-X buttons inline without re-walking history.
    """
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "source": "system",
            "context_actions": context_actions or {},
        }
    )


# ── Context tracker ───────────────────────────────────────────────────

def _set_context(
    *,
    work_order_id: Optional[str] = None,
    output_package_id: Optional[str] = None,
    workflow_execution_id: Optional[str] = None,
    title: Optional[str] = None,
) -> None:
    """Remember the most recent chat-created artefacts so follow-up
    prompts can answer "where is the output" without a Tier 1 call."""
    ctx = st.session_state.get(_CONTEXT_KEY) or {}
    if work_order_id:
        ctx["work_order_id"] = work_order_id
    if output_package_id:
        ctx["output_package_id"] = output_package_id
    if workflow_execution_id:
        ctx["workflow_execution_id"] = workflow_execution_id
    if title:
        ctx["title"] = title
    ctx["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    st.session_state[_CONTEXT_KEY] = ctx


def _current_context() -> dict[str, Any]:
    return st.session_state.get(_CONTEXT_KEY) or {}


# Follow-up prompts that resolve against recent chat context instead of
# routing to Tier 1. Kept tight — the goal is to catch the obvious
# operator follow-ups, not to be a full conversation router.
_FOLLOWUP_RE = re.compile(
    r"\b("
    r"where('?s| is)? (the |my )?(output|result|deck|deliverable|file)|"
    r"show me( the)? (output|result|deck|deliverable)|"
    r"open it|open the output|open the result|"
    r"what (happened|did you do|did it produce)|"
    r"did it (finish|run|complete|work)|"
    r"how did (it|that) (go|do)|"
    r"where do i find (it|the output|the result)"
    r")\b",
    re.IGNORECASE,
)


def _maybe_followup_reply(
    user_text: str,
) -> Optional[dict[str, Any]]:
    """Return a synthetic reply dict if the message is a follow-up about
    recent context. Otherwise None so the caller routes to Tier 1."""
    if not _FOLLOWUP_RE.search(user_text):
        return None
    ctx = _current_context()
    if not ctx:
        return None
    title = ctx.get("title") or "(untitled)"
    parts = [
        f"**Here's what I created last from this chat:**",
        f"- **Title:** {title}",
    ]
    if ctx.get("work_order_id"):
        parts.append(f"- **Work order:** `{ctx['work_order_id']}`")
    if ctx.get("output_package_id"):
        parts.append(f"- **Output package:** `{ctx['output_package_id']}`")
    if ctx.get("workflow_execution_id"):
        parts.append(
            f"- **Workflow execution:** `{ctx['workflow_execution_id']}`"
        )
    parts.append(
        "\nUse the buttons below to open it on the right surface."
    )
    return {
        "ok": True,
        "decision_kind": "context_followup",
        "_context": ctx,
        "_rendered": "\n".join(parts),
    }


# ── Promote (create / create+run) ────────────────────────────────────


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
    _set_context(work_order_id=wo_id, title=title)

    if create_only:
        _append_status_message(
            messages,
            f"✅ Created work order from this chat brief.\n\n"
            f"**Title:** {title}\n\n"
            f"You can dispatch it from Work Orders, or from the button below.",
            context_actions={"work_order_id": wo_id, "title": title},
        )
        return

    dispatch = api.dispatch_work_order(wo_id)
    if dispatch.get("ok"):
        if dispatch.get("decision_kind") == "work_order_brief":
            pkg_id = dispatch.get("output_package_id")
            _set_context(output_package_id=pkg_id, title=title)
            _append_status_message(
                messages,
                f"✅ Created and ran the work order.\n\n"
                f"**Title:** {title}\n\n"
                f"Aiden produced an output package. Use the buttons below "
                f"to open it.",
                context_actions={
                    "work_order_id": wo_id,
                    "output_package_id": pkg_id,
                    "title": title,
                },
            )
            return
        if dispatch.get("decision_kind") == "workflow_brief":
            exec_id = dispatch.get("workflow_execution_id")
            _set_context(workflow_execution_id=exec_id, title=title)
            steps = len(dispatch.get("step_run_ids") or [])
            _append_status_message(
                messages,
                f"✅ Created the work order and instantiated the workflow.\n\n"
                f"**Title:** {title} · **Steps:** {steps}\n\n"
                f"Open the work order to advance steps, or open the audit "
                f"trail to see what's running.",
                context_actions={
                    "work_order_id": wo_id,
                    "workflow_execution_id": exec_id,
                    "title": title,
                },
            )
            return

    if dispatch.get("decision_kind") == "clarification":
        _append_status_message(
            messages,
            f"⚠️ Created the work order, but Aiden needs a clarification "
            f"before dispatching:\n\n{dispatch.get('clarification_question')}",
            context_actions={"work_order_id": wo_id, "title": title},
        )
    else:
        _append_status_message(
            messages,
            f"⚠️ Created the work order, but dispatch did not complete:\n\n"
            f"{dispatch.get('error')}",
            context_actions={"work_order_id": wo_id, "title": title},
        )


# ── Renderers ─────────────────────────────────────────────────────────


def _render_context_actions(actions: dict[str, Any], idx: int) -> None:
    """Render Open-X buttons for a status message. Routes via
    st.session_state to the destination page so the same filter/picker
    pattern from CODEX's Audit Log handoff applies."""
    if not actions:
        return
    cols = st.columns(3)
    if actions.get("work_order_id"):
        with cols[0]:
            if st.button(
                "Open Work Order",
                key=f"goto-wo-{idx}",
            ):
                st.session_state["work_orders_focus_id"] = actions["work_order_id"]
                st.switch_page("views/work_orders.py")
    if actions.get("output_package_id"):
        with cols[1]:
            if st.button(
                "Open Output Package",
                key=f"goto-pkg-{idx}",
            ):
                st.session_state["output_packages_focus_id"] = actions["output_package_id"]
                st.switch_page("views/output_packages.py")
    if actions.get("work_order_id"):
        with cols[2]:
            if st.button(
                "Open Audit Log",
                key=f"goto-audit-{idx}",
            ):
                st.session_state["audit_log_work_order_filter"] = actions["work_order_id"]
                st.switch_page("views/audit_log.py")


def _render_actions(api, messages: list[dict[str, Any]], idx: int, reply: dict[str, Any]) -> None:
    kind = reply.get("decision_kind")
    if kind not in {"work_order_brief", "workflow_brief"}:
        return

    promoted_set: set = st.session_state.setdefault(_PROMOTED_KEY, set())
    promoted_create = f"create-{idx}" in promoted_set
    promoted_run = f"run-{idx}" in promoted_set

    if promoted_create or promoted_run:
        st.caption(
            "_This brief has already been actioned in this chat. "
            "Use the action buttons on the resulting status message to open "
            "the artefact, or send a new request to create another._"
        )
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
            promoted_set.add(f"create-{idx}")
            st.session_state[_PROMOTED_KEY] = promoted_set
            try:
                _promote_reply(
                    api,
                    messages,
                    reply,
                    create_only=True,
                    key_seed=f"{idx}-create",
                )
                st.session_state[_MESSAGES_KEY] = messages
                st.rerun()
            except APIError as err:
                # Unwind the guard so the operator can retry after fixing
                # the error (e.g. transient 5xx).
                promoted_set.discard(f"create-{idx}")
                st.session_state[_PROMOTED_KEY] = promoted_set
                st.error(f"❌ {err.status_code} — {err.detail}")
    with col2:
        if st.button(label_run, key=f"chat-run-{idx}", type="primary"):
            promoted_set.add(f"run-{idx}")
            st.session_state[_PROMOTED_KEY] = promoted_set
            try:
                _promote_reply(
                    api,
                    messages,
                    reply,
                    create_only=False,
                    key_seed=f"{idx}-run",
                )
                st.session_state[_MESSAGES_KEY] = messages
                st.rerun()
            except APIError as err:
                promoted_set.discard(f"run-{idx}")
                st.session_state[_PROMOTED_KEY] = promoted_set
                st.error(f"❌ {err.status_code} — {err.detail}")


def _render_context_followup(reply: dict[str, Any]) -> str:
    return reply.get("_rendered") or ""


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

    if _MESSAGES_KEY not in st.session_state:
        st.session_state[_MESSAGES_KEY] = _seed_messages()

    messages: list[dict[str, Any]] = st.session_state[_MESSAGES_KEY]

    for idx, m in enumerate(messages):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            st.caption(m.get("ts", ""))
            if m.get("source") == "aiden" and m.get("reply"):
                _render_actions(api, messages, idx, m["reply"])
            actions = m.get("context_actions") or {}
            if actions:
                _render_context_actions(actions, idx)

    user_text = st.chat_input("Ask Aiden anything…")
    if user_text:
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        messages.append(
            {"role": "user", "content": user_text, "ts": now, "source": "user"}
        )

        # Try local follow-up resolver first — keeps chat from
        # blasting tokens on "where is the output" style prompts.
        followup = _maybe_followup_reply(user_text)
        if followup is not None:
            ctx = followup["_context"]
            messages.append(
                {
                    "role": "assistant",
                    "content": _render_context_followup(followup),
                    "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "source": "system",
                    "context_actions": {
                        "work_order_id": ctx.get("work_order_id"),
                        "output_package_id": ctx.get("output_package_id"),
                        "title": ctx.get("title"),
                    },
                }
            )
            st.session_state[_MESSAGES_KEY] = messages
            st.rerun()

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
        st.session_state[_MESSAGES_KEY] = messages
        st.rerun()

    if st.button("Clear history", key="chat-clear"):
        st.session_state[_MESSAGES_KEY] = _seed_messages()
        st.session_state[_CONTEXT_KEY] = {}
        st.session_state[_PROMOTED_KEY] = set()
        st.rerun()


main()

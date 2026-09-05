"""Chat with Aiden — Alpha closeout γ.1+γ.2.
   Beta-1.5 phase 2 — cross-session persistence wired to /chat_sessions/me.

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

Persistence (Beta-1.5 phase 2 / Q7):
  GET /chat_sessions/me on first render hydrates messages + context.
  PUT /chat_sessions/me on every successful turn / promote / clear so
  refreshing the page or coming back tomorrow lands on the same thread.
  If the API is unavailable, the page falls back to session-state-only
  (the Alpha γ behaviour) so chat still works in offline dev.
"""

from __future__ import annotations

import hashlib
import json
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
_HYDRATED_KEY = "iwo3_chat_hydrated_session_id"
_PERSIST_DISABLED_KEY = "iwo3_chat_persist_disabled"
_TEMPLATE_PICK_KEY = "iwo3_chat_template_pick"  # idx -> template_profile_id


# ── Beta-1.5 phase 2 — server-side persistence helpers ───────────────


def _hydrate_from_server(api) -> None:  # noqa: ANN001
    """Load /chat_sessions/me into session_state on first render.

    Marks the session as hydrated by id so subsequent reruns within
    the same Streamlit session don't re-fetch. If the call fails
    (API unreachable, RBAC denial), we fall back to session-state-only
    and surface a non-blocking caption so the operator knows.
    """
    if st.session_state.get(_HYDRATED_KEY):
        return
    try:
        session = api.get_my_chat_session()
    except APIError:
        st.session_state[_PERSIST_DISABLED_KEY] = True
        if _MESSAGES_KEY not in st.session_state:
            st.session_state[_MESSAGES_KEY] = _seed_messages()
        return

    persisted_msgs = session.get("messages") or []
    persisted_ctx = session.get("context") or {}
    # Empty server state = first-ever visit; seed a welcome message and
    # keep the session marked hydrated so we don't loop on every rerun.
    st.session_state[_MESSAGES_KEY] = (
        list(persisted_msgs) if persisted_msgs else _seed_messages()
    )
    st.session_state[_CONTEXT_KEY] = persisted_ctx
    st.session_state[_HYDRATED_KEY] = session.get("id") or "hydrated"


def _persist_to_server(api) -> None:  # noqa: ANN001
    """PUT current state to /chat_sessions/me. Best-effort; the chat
    keeps working if the API is unavailable.

    Strips Streamlit-side ephemeral keys (e.g. `reply` carries pydantic
    objects from the API client; we keep only the raw dict)."""
    if st.session_state.get(_PERSIST_DISABLED_KEY):
        return
    msgs = st.session_state.get(_MESSAGES_KEY) or []
    ctx = st.session_state.get(_CONTEXT_KEY) or {}
    try:
        api.put_my_chat_session(messages=msgs, context=ctx)
    except APIError:
        st.session_state[_PERSIST_DISABLED_KEY] = True


def _clear_on_server(api) -> None:  # noqa: ANN001
    if st.session_state.get(_PERSIST_DISABLED_KEY):
        return
    try:
        api.clear_my_chat_session()
    except APIError:
        st.session_state[_PERSIST_DISABLED_KEY] = True


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
        body = (
            head
            + "**Here is what I think you need:** a single-step work order.\n\n"
            + f"**Title:** {reply.get('title')}\n\n"
            + f"**Summary:** {reply.get('summary')}\n\n"
            + f"**Recommended owner:** `{b.get('assigned_role')}`\n\n"
            + f"**Priority:** `{b.get('priority')}`\n\n"
        )
        # Loop Eta post-close — surface the resolved Gamma template so
        # the operator confirms before promoting. When no template
        # matched but the intake clearly wanted one, the picker renders
        # below the message body via _render_actions().
        tpl_key = b.get("template_profile_key")
        tpl_label = b.get("template_label") or tpl_key
        if tpl_key:
            terms = b.get("template_match_terms") or []
            terms_clause = (
                f" (matched on: {', '.join(terms)})" if terms else ""
            )
            body += (
                f"**Template:** `{tpl_key}` — {tpl_label}{terms_clause}\n\n"
            )
        elif b.get("template_choice_required"):
            body += (
                "_⚠️ I couldn't pick a template confidently — choose one "
                "below before creating the WO so Gamma renders with your "
                "branded artwork instead of defaults._\n\n"
            )
        body += "You can create it directly from this chat."
        return body
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


def _correlation_id_for_turn(
    messages: list[dict[str, Any]],
    idx: int,
    action: str,
) -> str:
    """Build a session-unique correlation_id for a chat-driven WO create.

    Bug fix (2026-05-03): Prior implementation used `chat:{idx}-{action}`,
    where `idx` reset to 0 every time the operator cleared chat history
    or refreshed the page. The work_orders table has a partial UNIQUE on
    `(client_id, correlation_id) WHERE correlation_id LIKE 'chat:%'`
    (added Beta-1 ε.3 / Q8 to prevent fast-double-click duplicates within
    a single session). When idx 2 came round again in a new session, the
    DB rejected with 409 even though the operator's intent was a brand
    new WO.

    Fix: incorporate the message's own ISO timestamp + the bound title
    into a short hash, so the same brief in the same session keeps its
    idempotency (same hash on every click) while different sessions /
    different briefs always get distinct hashes.
    """
    msg = messages[idx] if 0 <= idx < len(messages) else {}
    ts = msg.get("ts") or ""
    title = (
        (msg.get("reply") or {}).get("title")
        or msg.get("content", "")[:80]
    )
    seed = f"{ts}|{idx}|{title}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"chat:{digest}-{action}"


def _existing_wo_from_409(detail: Any) -> Optional[dict[str, str]]:
    """Pull `existing_work_order_id` + `existing_title` out of an
    APIError 409 detail. Returns None if the shape doesn't match the
    duplicate-correlation contract.

    The FastAPI 409 body is the dict raised in
    routes/work_orders.py::create_work_order. ApiClient surfaces it as
    err.detail — usually a parsed dict, sometimes a JSON-encoded
    string when the client took a string codepath."""
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except (json.JSONDecodeError, ValueError):
            return None
    if not isinstance(detail, dict):
        return None
    if detail.get("error") != "duplicate_correlation_id":
        return None
    wo_id = detail.get("existing_work_order_id")
    title = detail.get("existing_title")
    if not wo_id:
        return None
    return {"work_order_id": str(wo_id), "title": str(title or "(untitled)")}


def _promote_reply(
    api,
    messages: list[dict[str, Any]],
    reply: dict[str, Any],
    *,
    create_only: bool,
    correlation_id: str,
    template_profile_id: Optional[str] = None,
) -> None:
    kind = reply.get("decision_kind")
    title = reply.get("title") or "Untitled request"
    summary = reply.get("summary")
    wo_type = "workflow_brief" if kind == "workflow_brief" else "content_brief"
    brief = reply.get("work_order_brief") or {}
    priority = (
        brief.get("priority")
        if kind == "work_order_brief"
        else "medium"
    ) or "medium"

    # Loop Eta post-close — pass operator-confirmed template through to
    # the WO so dispatch_gamma_for_package targets the right Gamma
    # template instead of falling back to defaults. Resolver match wins
    # by default; a chat-side picker (clarification path) overrides it.
    tpl_id = template_profile_id or brief.get("template_profile_id")

    created = api.create_work_order(
        title=title,
        description=summary,
        wo_type=wo_type,
        priority=priority,
        correlation_id=correlation_id,
        template_profile_id=tpl_id,
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


# Loop Iota — "Grounded by" chips. One small caption row under each
# assistant reply showing which memory sources were injected. Empty
# memory bundles render nothing (don't draw operator attention to a
# negative). Source kinds:
#   canonical_facts → ⭐ Canonical facts (rev N)
#   chat_history    → 💬 Chat history (N turns)
#   workspace_retrieval → 📄 filename (score=0.92)
#   scratch_retrieval   → 🗒️ filename (score=0.81)
_KIND_LABELS = {
    "canonical_facts": "⭐ Canonical facts",
    "chat_history": "💬 Chat history",
    "workspace_retrieval": "📄",
    "scratch_retrieval": "🗒️",
}


def _format_grounded_entry(entry: dict[str, Any]) -> str:
    kind = entry.get("kind")
    if kind == "canonical_facts":
        rev = entry.get("revision")
        return (
            f"{_KIND_LABELS[kind]} (rev {rev})"
            if rev is not None
            else _KIND_LABELS[kind]
        )
    if kind == "chat_history":
        n = entry.get("turn_count")
        return (
            f"{_KIND_LABELS[kind]} ({n} turns)"
            if n is not None
            else _KIND_LABELS[kind]
        )
    if kind in ("workspace_retrieval", "scratch_retrieval"):
        fn = entry.get("filename") or "(unnamed)"
        score = entry.get("score")
        score_label = f" · {score:.2f}" if isinstance(score, (int, float)) else ""
        return f"{_KIND_LABELS[kind]} {fn}{score_label}"
    return str(kind)


def _render_grounded_chips(reply: dict[str, Any]) -> None:
    """Render the Grounded-by source chip row. No-op when memory was
    bypassed or the bundle was empty."""
    sources = (reply or {}).get("memory_sources") or []
    if not sources:
        return
    chips = " &nbsp; ".join(_format_grounded_entry(s) for s in sources)
    st.caption(f"_Grounded by:_ {chips}")


# Open-search surfacing — "Searched the web" row under an answer that
# was produced from a live search or scrape. Distinct from the memory
# chips above: those say what was recalled, this says what was fetched
# this turn. Renders nothing when no tool ran, so silence still means
# "answered without a tool" rather than "tool row failed to draw".
_TOOL_LABELS = {
    "web_search_brave": "🔎 Brave",
    "web_search_perplexity": "🔎 Perplexity",
    "web_search_ddg": "🔎 DuckDuckGo",
    "web_scrape": "📄 Page fetch",
}


def _render_web_sources(reply: dict[str, Any]) -> None:
    """Render the live-search provenance row: which tool ran, the query
    it ran, and every source URL it returned."""
    reply = reply or {}
    tool = reply.get("tool_used")
    if not tool:
        return
    sources = reply.get("web_sources") or []
    if tool not in _TOOL_LABELS and not sources:
        # A runtime tool (health / counts) — name it, no links to show.
        st.caption(f"_Ran tool:_ `{tool}`")
        return

    label = _TOOL_LABELS.get(tool, f"`{tool}`")
    query = reply.get("tool_query")
    header = f"_Searched the web via_ {label}"
    if query:
        header += f" — “{query}”"
    st.caption(header)
    if not sources:
        st.caption("_No sources returned._")
        return
    links = "  ·  ".join(
        f"[{(s.get('title') or s.get('url') or '')[:48]}]({s.get('url')})"
        for s in sources
        if s.get("url")
    )
    if links:
        st.caption(f"_Sources:_ {links}")


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


def _render_template_picker(idx: int, brief: dict[str, Any]) -> Optional[str]:
    """Loop Eta post-close — render a radio picker for the template
    candidates Aiden surfaced when the resolver couldn't auto-match.
    Returns the operator's selected `template_profile_id` (or None when
    no choice yet). Selection is persisted in session_state so a rerun
    triggered by clicking Create/Run preserves the pick.
    """
    choices = brief.get("template_choices") or []
    if not choices:
        return None
    pick_state: dict = st.session_state.setdefault(_TEMPLATE_PICK_KEY, {})
    options = [c.get("template_profile_id") for c in choices]
    labels = {
        c.get("template_profile_id"): (
            f"{c.get('profile_key')} — "
            f"{c.get('label') or c.get('profile_key')} "
            f"({c.get('output_kind')} / {c.get('engine')})"
        )
        for c in choices
    }
    current = pick_state.get(str(idx))
    default_index = options.index(current) if current in options else 0

    selected = st.radio(
        "Pick the Gamma template for this WO:",
        options=options,
        index=default_index,
        format_func=lambda v: labels.get(v, v),
        key=f"chat-tpl-pick-{idx}",
    )
    pick_state[str(idx)] = selected
    st.session_state[_TEMPLATE_PICK_KEY] = pick_state
    return selected


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

    # Loop Eta post-close — when Aiden flagged the brief as needing a
    # template choice, render the picker first and pass the selection
    # into _promote_reply. When the resolver auto-matched a template,
    # we skip the picker (the brief already carries template_profile_id).
    selected_template_id: Optional[str] = None
    brief_dict = reply.get("work_order_brief") or {}
    if kind == "work_order_brief" and brief_dict.get("template_choice_required"):
        selected_template_id = _render_template_picker(idx, brief_dict)

    col1, col2 = st.columns([1, 1])
    label_create = "Create WO" if kind == "work_order_brief" else "Create workflow WO"
    label_run = (
        "Create + run now"
        if kind == "work_order_brief"
        else "Create + instantiate"
    )

    def _handle_action_error(err: APIError, action_key: str) -> None:
        """Friendly error rendering. Catches the duplicate_correlation_id
        409 specifically (cross-session collision) and points the
        operator at the existing WO instead of dumping the raw JSON."""
        promoted_set.discard(action_key)
        st.session_state[_PROMOTED_KEY] = promoted_set
        if err.status_code == 409:
            existing = _existing_wo_from_409(err.detail)
            if existing is not None:
                st.warning(
                    f"This brief was already submitted as "
                    f"**{existing['title']}** "
                    f"(`{existing['work_order_id']}`). Open the existing "
                    f"work order from the buttons below, or send a fresh "
                    f"message to create a new one."
                )
                _append_status_message(
                    messages,
                    f"⚠️ Skipped duplicate — existing WO **{existing['title']}** "
                    f"(`{existing['work_order_id']}`).",
                    context_actions={
                        "work_order_id": existing["work_order_id"],
                        "title": existing["title"],
                    },
                )
                st.session_state[_MESSAGES_KEY] = messages
                _persist_to_server(api)
                return
        st.error(f"❌ {err.status_code} — {err.detail}")

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
                    correlation_id=_correlation_id_for_turn(
                        messages, idx, "create"
                    ),
                    template_profile_id=selected_template_id,
                )
                st.session_state[_MESSAGES_KEY] = messages
                _persist_to_server(api)
                st.rerun()
            except APIError as err:
                _handle_action_error(err, f"create-{idx}")
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
                    correlation_id=_correlation_id_for_turn(
                        messages, idx, "run"
                    ),
                    template_profile_id=selected_template_id,
                )
                st.session_state[_MESSAGES_KEY] = messages
                _persist_to_server(api)
                st.rerun()
            except APIError as err:
                _handle_action_error(err, f"run-{idx}")


def _render_context_followup(reply: dict[str, Any]) -> str:
    return reply.get("_rendered") or ""


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Chat with Aiden</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:6px;">
          Live Tier-1 LLM classification. Token-budgeted, audit-logged.
        </div>
        <div style="
          background:#F3F4F6; border-left:3px solid #1E5F91;
          padding:8px 12px; margin-bottom:14px; font-size:0.85rem;
          color:#374151; border-radius:3px;
        ">
          <strong>Templated artifacts:</strong> mention the template by
          name (e.g. <em>&ldquo;Klear template&rdquo;</em>,
          <em>&ldquo;RMIS PDF&rdquo;</em>,
          <em>&ldquo;klearai-pptx&rdquo;</em>) and Aiden will resolve it
          automatically. For full control of every template field, use
          <strong>Submit Order</strong> in the sidebar &mdash; it has the
          explicit dropdown of every active template for this tenant.
        </div>
        """,
        unsafe_allow_html=True,
    )

    api = page_requires_api()
    if api is None:
        return

    # Beta-1.5 phase 2 / Q7 — pull server-persisted history on first
    # render. After hydrate, every successful turn writes back via
    # _persist_to_server so a refresh / new tab continues the thread.
    _hydrate_from_server(api)

    messages: list[dict[str, Any]] = st.session_state[_MESSAGES_KEY]

    for idx, m in enumerate(messages):
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            st.caption(m.get("ts", ""))
            if m.get("source") == "aiden" and m.get("reply"):
                # Loop Iota — Grounded by chips render before the action
                # buttons so operators see the memory provenance first.
                _render_grounded_chips(m["reply"])
                _render_web_sources(m["reply"])
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
            _persist_to_server(api)
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
        _persist_to_server(api)
        st.rerun()

    if st.button("Clear history", key="chat-clear"):
        st.session_state[_MESSAGES_KEY] = _seed_messages()
        st.session_state[_CONTEXT_KEY] = {}
        st.session_state[_PROMOTED_KEY] = set()
        _clear_on_server(api)
        st.rerun()

    if st.session_state.get(_PERSIST_DISABLED_KEY):
        st.caption(
            "💡 Cross-session persistence offline — chat will not be "
            "saved when you refresh. Verify the FastAPI runtime is "
            "reachable and you have client:read."
        )


main()

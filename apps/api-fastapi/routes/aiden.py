"""MegaLoop Alpha α.7 — Aiden Tier 1 chat surface for the browser.

  POST /aiden/chat       send `message`; receive a parsed AidenDecision
                         (work_order_brief / workflow_brief /
                         clarification) without persisting a work_order.
                         The browser renders the decision and may ask
                         the operator to confirm before promoting it
                         into a real WO via the existing
                         /work_orders + workflow instantiation paths.

This route is the runtime-truthful equivalent of `views/chat.py`'s
prior Loop 8.3 placeholder. RBAC: `work_order:create` (Aiden Tier 1
classification is the read-side of the WO submission flow; if the
operator can't create a WO they shouldn't be able to spend tokens
classifying intake either).

Audit:
  - llm.invoked / llm.failed / llm.budget_exceeded emitted by
    invoke_aiden_tier_1 + runtime.budgets — no extra writes here.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from runtime.budgets import LlmBudgetExceeded
from runtime.template_resolver import (
    TemplateResolution,
    resolve_template_for_client,
)
from runtime.tier_1_aiden import (
    AidenDecision,
    AidenInvocationError,
    AidenNoConfig,
    AidenWorkOrderBrief,
    invoke_aiden_tier_1,
)


router = APIRouter(prefix="/aiden", tags=["aiden"])


class AidenChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class AidenChatResponse(BaseModel):
    ok: bool
    decision_kind: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    work_order_brief: Optional[dict[str, Any]] = None
    workflow_brief: Optional[dict[str, Any]] = None
    clarification: Optional[dict[str, Any]] = None
    assistant_reply: Optional[dict[str, Any]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None


def _decision_to_payload(dec) -> dict[str, Any]:  # noqa: ANN001
    """Flatten AidenDecision dataclass → JSON-serialisable dict for the
    response model. dataclasses.asdict already nests sub-dataclasses."""
    return dataclasses.asdict(dec)


def _choice_to_dict(choice) -> dict[str, Any]:  # noqa: ANN001
    return {
        "template_profile_id": choice.template_profile_id,
        "profile_key": choice.profile_key,
        "output_kind": choice.output_kind,
        "engine": choice.engine,
        "label": choice.label,
        "external_ref": choice.external_ref,
    }


def _apply_template_resolution(
    decision: AidenDecision,
    resolution: TemplateResolution,
) -> AidenDecision:
    """Fold a template-resolver result into Aiden's work_order_brief.

    Three cases:
      matched       → write template_profile_id + identifying metadata.
      needs_choice  → flag template_choice_required + attach choices so
                      chat surface can render a picker.
      no_template   → leave the brief untouched (original behaviour).

    Only mutates work_order_brief decisions. Workflow / clarification /
    assistant_reply / tool_call decisions pass through unchanged.
    """
    if decision.decision_kind != "work_order_brief" or decision.work_order_brief is None:
        return decision

    brief = decision.work_order_brief

    if resolution.kind == "matched" and resolution.match is not None:
        new_brief = AidenWorkOrderBrief(
            assigned_role=brief.assigned_role,
            content_blocks=brief.content_blocks,
            priority=brief.priority,
            template_profile_id=resolution.match.template_profile_id,
            template_profile_key=resolution.match.profile_key,
            template_output_kind=resolution.match.output_kind,
            template_engine=resolution.match.engine,
            template_label=resolution.match.label,
            template_match_terms=resolution.matched_terms,
            template_choice_required=False,
            template_choices=(),
        )
    elif resolution.kind == "needs_choice" and resolution.choices:
        new_brief = AidenWorkOrderBrief(
            assigned_role=brief.assigned_role,
            content_blocks=brief.content_blocks,
            priority=brief.priority,
            template_profile_id=None,
            template_profile_key=None,
            template_output_kind=resolution.detected_output_kind,
            template_engine=None,
            template_label=None,
            template_match_terms=(),
            template_choice_required=True,
            template_choices=tuple(
                _choice_to_dict(c) for c in resolution.choices
            ),
        )
    else:
        return decision

    return AidenDecision(
        decision_kind=decision.decision_kind,
        title=decision.title,
        summary=decision.summary,
        assistant_reply=decision.assistant_reply,
        tool_call=decision.tool_call,
        work_order_brief=new_brief,
        workflow_brief=decision.workflow_brief,
        clarification=decision.clarification,
        provider=decision.provider,
        model=decision.model,
        latency_ms=decision.latency_ms,
        prompt_tokens=decision.prompt_tokens,
        completion_tokens=decision.completion_tokens,
        total_tokens=decision.total_tokens,
    )


_GREETING_RE = re.compile(
    r"^(hi|hello|hey|yo|good morning|good afternoon|good evening)"
    r"([ ,.!-]+aiden)?[!. ]*$",
    re.IGNORECASE,
)
_CAPABILITY_RE = re.compile(
    r"\b(what do you do|what can you do|how can you help|who are you)\b",
    re.IGNORECASE,
)
_SMALLTALK_RE = re.compile(
    r"\b(how are you|thanks|thank you|goodbye|bye|nice to meet you)\b",
    re.IGNORECASE,
)
_WEB_ACCESS_RE = re.compile(
    r"\b("
    r"do you have web access|"
    r"can you search the web|"
    r"can you browse the web|"
    r"web access|"
    r"internet access|"
    r"web search|"
    r"search the web|"
    r"search the internet|"
    r"browse the web"
    r")\b",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"\b("
    r"status of (this )?(workspace|system|tenant)|"
    r"workspace status|"
    r"system status|"
    r"how is the workspace doing"
    r")\b",
    re.IGNORECASE,
)


def _looks_like_greeting(body: str) -> bool:
    if _GREETING_RE.match(body):
        return True

    words = re.findall(r"[a-z]+", body.lower())
    if not words:
        return False

    greetingish = {"h", "he", "hi", "hey", "hello", "yo"}
    if len(words) <= 3 and "aiden" in words and any(
        word in greetingish for word in words
    ):
        return True

    return False


def _shortcut_reply(message: str) -> Optional[AidenChatResponse]:
    """Keep the chat from feeling like a raw classifier for tiny social
    or capability prompts. Concrete work requests still flow to Tier 1."""
    body = message.strip()
    if not body:
        return None

    if _looks_like_greeting(body):
        return AidenChatResponse(
            ok=True,
            decision_kind="assistant_reply",
            assistant_reply={
                "headline": "Hi, I'm Aiden.",
                "message": (
                    "I help turn requests into real IWO3 work. Give me a "
                    "concrete ask like a landing page, a deck, a content "
                    "brief, or a deployment task, and I'll scope the next step."
                ),
                "suggested_requests": [
                    "Create a marketing landing page for the 3M GTM campaign",
                    "Draft a Klear pricing deck for an executive review",
                    "Set up a workflow for content -> deck -> deployment",
                ],
            },
        )

    if _CAPABILITY_RE.search(body):
        return AidenChatResponse(
            ok=True,
            decision_kind="assistant_reply",
            assistant_reply={
                "headline": "Here is what I can do.",
                "message": (
                    "I can clarify ambiguous requests, recommend whether "
                    "something should be a single work order or a workflow, "
                    "and prepare it for the right downstream agent. The best "
                    "results come from specific requests with a deliverable, "
                    "audience, and goal."
                ),
                "suggested_requests": [
                    "Build a landing page for our new product launch",
                    "Create a workflow to draft, design, and deliver a sales deck",
                    "Turn this rough ask into a real work order",
                ],
            },
        )

    if _SMALLTALK_RE.search(body):
        return AidenChatResponse(
            ok=True,
            decision_kind="assistant_reply",
            assistant_reply={
                "headline": "Happy to help.",
                "message": (
                    "I am here to turn rough asks into clear work, but I "
                    "can also help you frame a request before we route it. "
                    "If you are not ready to create work yet, tell me what "
                    "you are trying to achieve and I will help shape it."
                ),
                "suggested_requests": [
                    "Help me turn an idea into a real work order",
                    "I need a landing page but I am not sure what to ask for",
                    "Walk me through what happens after I submit a request",
                ],
            },
        )

    if _WEB_ACCESS_RE.search(body):
        return AidenChatResponse(
            ok=True,
            decision_kind="assistant_reply",
            assistant_reply={
                "headline": "Web access is a governed capability.",
                "message": (
                    "Aiden will need web research and search access as part "
                    "of the platform, but this chat surface is not yet wired "
                    "to execute live web lookup directly. Right now I can help "
                    "you frame a research request or route work that will need "
                    "web-enabled tooling later."
                ),
                "suggested_requests": [
                    "Turn this topic into a web research brief",
                    "Create a work order for competitive web research",
                    "Help me scope a current-events or market scan request",
                ],
            },
        )

    if _STATUS_RE.search(body):
        return AidenChatResponse(
            ok=True,
            decision_kind="assistant_reply",
            assistant_reply={
                "headline": "Use the console surfaces for live status.",
                "message": (
                    "For actual runtime status, check System Health, Work Orders, "
                    "Handoffs, Output Packages, and Audit Log in the left navigation. "
                    "This chat can explain the system and help scope work, but it is "
                    "not the live status dashboard."
                ),
                "suggested_requests": [
                    "Summarize what this intake surface is for",
                    "Help me turn a rough ask into a work order",
                    "Explain when to use Chat with Aiden versus Submit Order",
                ],
            },
        )

    return None


@router.post(
    "/chat",
    response_model=AidenChatResponse,
    dependencies=[Depends(require_permission_dep("work_order:create"))],
)
async def aiden_chat(
    body: AidenChatRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> AidenChatResponse:
    # 2026-05-01 — regex `_shortcut_reply` intercepts removed. Aiden
    # Tier 1 now has a real `assistant_reply` decision kind, so casual
    # / exploratory / platform-question intake is handled in Aiden's
    # CEO voice instead of being routed to canned hardcoded responses.
    # Empty messages still short-circuit (no point spending LLM tokens).
    if not body.message or not body.message.strip():
        return AidenChatResponse(
            ok=True,
            decision_kind="assistant_reply",
            assistant_reply={
                "headline": "I'm here.",
                "message": "Tell me what's on your mind — I can talk through what's running, what we've built, or what to do next.",
                "suggested_requests": [],
            },
        )

    try:
        decision = await invoke_aiden_tier_1(
            conn,
            intake_text=body.message,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
        )
    except AidenNoConfig as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_aiden_config", "detail": str(exc)},
        )
    except LlmBudgetExceeded as exc:
        return AidenChatResponse(
            ok=False,
            error=(
                f"llm_budget_exceeded: tenant has used {exc.already_used} "
                f"tokens against ceiling {exc.ceiling}; raise the ceiling "
                f"and retry."
            ),
        )
    except AidenInvocationError as exc:
        return AidenChatResponse(
            ok=False,
            error=f"{exc.kind}: {exc}",
        )

    # Beta-2 — tool_call → execute → re-invoke loop. Aiden returns a
    # tool_call when the operator asks about runtime state; the runtime
    # executes the tool with the live tenant-scoped connection, then
    # invokes Aiden a second time with the tool result as context. Cap
    # at 1 tool round-trip per chat turn (token-budget hygiene).
    if decision.decision_kind == "tool_call" and decision.tool_call:
        from runtime.aiden_tools import (
            ToolExecutionError,
            ToolNotFoundError,
            execute_tool,
        )

        tool_call = decision.tool_call
        try:
            tool_result = await execute_tool(
                conn,
                tool_name=tool_call.tool_name,
                args=tool_call.args,
                client_id=ctx["client_id"],
                actor_user_id=ctx["user_id"],
            )
        except (ToolNotFoundError, ToolExecutionError) as exc:
            return AidenChatResponse(
                ok=False,
                decision_kind="tool_call",
                title=decision.title,
                error=f"tool_failed: {exc}",
            )

        # Re-invoke Aiden with the original message + tool result as
        # context. Aiden composes the final assistant_reply using REAL
        # data instead of fabricating it.
        followup_intake = (
            f"{body.message}\n\n"
            f"[TOOL RESULT — {tool_call.tool_name}]\n"
            f"{json.dumps(tool_result, default=str, indent=2)}\n"
            f"[END TOOL RESULT]\n\n"
            f"Compose your final assistant_reply using the data above. "
            f"Do not call another tool."
        )
        try:
            decision = await invoke_aiden_tier_1(
                conn,
                intake_text=followup_intake,
                client_id=ctx["client_id"],
                actor_user_id=ctx["user_id"],
            )
        except (
            AidenNoConfig,
            LlmBudgetExceeded,
            AidenInvocationError,
        ) as exc:
            return AidenChatResponse(
                ok=False,
                decision_kind="tool_call",
                title=decision.title if decision else None,
                error=f"followup_invoke_failed: {exc}",
            )

    # Loop Eta post-close — resolve template from operator's intake.
    # Runs only for work_order_brief decisions; all other decision_kinds
    # pass through unchanged. Resolver is deterministic + tenant-scoped
    # via the same RLS-bound connection used above. Failures are
    # tolerated (template-resolution is best-effort over a pure-LLM
    # baseline, never blocking).
    if decision.decision_kind == "work_order_brief":
        try:
            resolution = await resolve_template_for_client(
                conn,
                client_id=ctx["client_id"],
                intake_text=body.message,
            )
            decision = _apply_template_resolution(decision, resolution)
        except Exception:  # noqa: BLE001
            # Never fail the chat over template enrichment. Operator
            # still gets the brief; Submit Order is the explicit fallback.
            pass

    payload = _decision_to_payload(decision)
    return AidenChatResponse(
        ok=True,
        decision_kind=payload.get("decision_kind"),
        title=payload.get("title"),
        summary=payload.get("summary"),
        assistant_reply=payload.get("assistant_reply"),
        work_order_brief=payload.get("work_order_brief"),
        workflow_brief=payload.get("workflow_brief"),
        clarification=payload.get("clarification"),
        provider=payload.get("provider"),
        model=payload.get("model"),
        latency_ms=payload.get("latency_ms"),
    )

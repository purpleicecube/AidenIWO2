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
from runtime.tier_1_aiden import (
    AidenInvocationError,
    AidenNoConfig,
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
    shortcut = _shortcut_reply(body.message)
    if shortcut is not None:
        return shortcut

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

    payload = _decision_to_payload(decision)
    return AidenChatResponse(
        ok=True,
        decision_kind=payload.get("decision_kind"),
        title=payload.get("title"),
        summary=payload.get("summary"),
        work_order_brief=payload.get("work_order_brief"),
        workflow_brief=payload.get("workflow_brief"),
        clarification=payload.get("clarification"),
        provider=payload.get("provider"),
        model=payload.get("model"),
        latency_ms=payload.get("latency_ms"),
    )

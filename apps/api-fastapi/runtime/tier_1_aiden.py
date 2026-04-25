"""MegaLoop Alpha α.2 — Tier 1 Aiden runtime invocation.

Aiden's job (Tier 1, per the IWO2 lineage):
  - read intake (operator request, channel inbound, DigiFLOW packet)
  - decide which downstream path to take:
      `work_order_brief`     single-step delivery → direct to Tier 2 sub-agent
      `workflow_brief`       multi-step → hand to Tier 1.5 PM
      `clarification`        ask the operator a question; do nothing else
  - return a strict JSON decision the caller can mechanically consume

Stage A constraints:
  - § A1: Aiden must use a real LLM provider (Groq or OpenRouter) in Alpha.
  - § A5: strict structured JSON output; no free-form text.
  - § A7: per-call max_tokens 8192; per-WO ceiling 50K; circuit-break
    via `llm.budget_exceeded` + `LlmBudgetExceeded` exception.
  - § E3: no first-invocation gate (LLMs run continuously).
  - § E4: spend caps tracked-not-enforced; audit-only visibility.

Audit emissions:
  - `llm.invoked` on each successful call, metadata = {provider, model,
    promptTokens, completionTokens, totalTokens, latencyMs, workOrderId,
    agentRole, decisionKind}
  - `llm.failed`  on each failed call, metadata = {kind, httpStatus,
    detail, provider, model, workOrderId, agentRole}
  - `llm.budget_exceeded` from runtime.budgets when ceiling breached
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Literal, Optional

import asyncpg

from authz.audit_writer import write_audit_row
from llm.config_resolver import EffectiveLlmConfig, resolve_llm_config
from llm.credentials import LlmCredentialError, resolve_credential
from llm.providers import LlmProviderError, call_openai_compatible
from runtime.budgets import (
    DEFAULT_PER_CALL_MAX_TOKENS,
    LlmBudgetExceeded,
    check_or_raise_wo_budget,
    resolve_max_tokens,
)


AIDEN_TIER_1_ROLE = "aiden_tier_1"
AIDEN_CONTRACT_VERSION = "v1.alpha"


# Roles that Aiden may delegate a single-step work_order_brief to.
KNOWN_TIER_2_ROLES = {
    "mark_tier_2",
    "tom_tier_2",
    "hank_tier_2",
    "paul_tier_2",
}


AIDEN_SYSTEM_PROMPT = """You are Aiden, the Tier 1 orchestration agent for IWO3.

Your job is to read intake from an operator (browser, Telegram, or
DigiFLOW packet) and decide what should happen next. You do NOT
produce content yourself; you decide who should.

You must respond with strict JSON matching this schema:

{
  "decision_kind": "work_order_brief" | "workflow_brief" | "clarification",
  "title": "short human-readable title for the work",
  "summary": "one-paragraph summary of intent",

  // When decision_kind == "work_order_brief":
  "work_order_brief": {
    "assigned_role": "mark_tier_2" | "tom_tier_2" | "hank_tier_2" | "paul_tier_2",
    "content_blocks": { ...sub-agent specific input... },
    "priority": "low" | "medium" | "high" | "critical"
  },

  // When decision_kind == "workflow_brief":
  "workflow_brief": {
    "workflow_template_key": "KEY of an existing workflow_template",
    "step_inputs": { "stepKey": { ...input for that step... } }
  },

  // When decision_kind == "clarification":
  "clarification": {
    "question": "what the operator must answer",
    "missing_fields": ["list", "of", "fields"]
  }
}

Rules:
- Pick `work_order_brief` for single-step deliverables (one sub-agent
  produces output, e.g. a content brief or a deck).
- Pick `workflow_brief` for multi-step deliverables (e.g. content +
  deck + deploy).
- Pick `clarification` only when the intake is ambiguous and you
  genuinely cannot route it.
- assigned_role values must be one of the known Tier 2 roles.
- Output JSON ONLY. No commentary, no markdown fences.
"""


# Hard-locked output contract appended to whatever persona prompt the
# operator stores in `llm_configs.system_prompt`. Mirrors the
# tier_2_subagents.TIER_2_OUTPUT_SCHEMA pattern: the persona is
# operator-tunable, the JSON schema is not. Also satisfies Groq's
# requirement that the prompt mention "json" whenever response_format
# is set to json_object.
AIDEN_OUTPUT_SCHEMA = """

# Output contract (do not deviate)

You MUST respond with a single JSON object matching the IWO3 Aiden
Tier-1 decision schema. No prose, no markdown fences, just JSON.

{
  "decision_kind": "work_order_brief" | "workflow_brief" | "clarification",
  "title": "short human-readable title",
  "summary": "one-paragraph summary",
  "work_order_brief": {
     "assigned_role": "mark_tier_2" | "tom_tier_2" | "hank_tier_2" | "paul_tier_2",
     "content_blocks": {...},
     "priority": "low" | "medium" | "high" | "critical"
  },
  "workflow_brief":   { "workflow_template_key": "...", "step_inputs": {...} },
  "clarification":    { "question": "...", "missing_fields": [...] }
}

Routing hints for `assigned_role`:
  - mark_tier_2  → marketing / content / copy / brief / written assets
  - tom_tier_2   → presentations / decks / slides / pptx
  - hank_tier_2  → web / landing pages / HTML / mini-sites
  - paul_tier_2  → deployment / publishing / handoff to external systems

NEVER invent a new role. If the request doesn't fit one of those four,
return decision_kind="clarification" instead.

Only include the brief subobject that matches `decision_kind`.
"""


@dataclass(frozen=True)
class AidenWorkOrderBrief:
    assigned_role: str
    content_blocks: dict
    priority: str


@dataclass(frozen=True)
class AidenWorkflowBrief:
    workflow_template_key: str
    step_inputs: dict


@dataclass(frozen=True)
class AidenClarification:
    question: str
    missing_fields: list[str]


@dataclass(frozen=True)
class AidenDecision:
    decision_kind: Literal[
        "work_order_brief", "workflow_brief", "clarification"
    ]
    title: str
    summary: Optional[str]
    work_order_brief: Optional[AidenWorkOrderBrief] = None
    workflow_brief: Optional[AidenWorkflowBrief] = None
    clarification: Optional[AidenClarification] = None
    # Provenance (filled at call site)
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class AidenInvocationError(Exception):
    """Generic Aiden runtime failure. Wraps the underlying error kind
    so callers can pattern-match without importing every provider type."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class AidenDecisionMalformed(AidenInvocationError):
    def __init__(self, detail: str) -> None:
        super().__init__("decision_malformed", detail)


class AidenNoConfig(AidenInvocationError):
    def __init__(self, detail: str) -> None:
        super().__init__("no_llm_configured", detail)


def _parse_decision(raw_text: str) -> AidenDecision:
    """Strict-mode JSON parse. Tolerates one accidental ```json fence
    pair around the payload (some providers add it even with json mode)."""
    body = raw_text.strip()
    if body.startswith("```"):
        # Strip first fence line + trailing fence
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        body = "\n".join(lines)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AidenDecisionMalformed(
            f"json decode failed: {exc}; first 200 chars: {body[:200]!r}"
        )

    kind = data.get("decision_kind")
    if kind not in {"work_order_brief", "workflow_brief", "clarification"}:
        raise AidenDecisionMalformed(
            f"decision_kind must be work_order_brief|workflow_brief|"
            f"clarification, got {kind!r}"
        )
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise AidenDecisionMalformed("title missing or non-string")
    summary = data.get("summary") if isinstance(data.get("summary"), str) else None

    wob = None
    wfb = None
    cl = None

    if kind == "work_order_brief":
        sub = data.get("work_order_brief")
        if not isinstance(sub, dict):
            raise AidenDecisionMalformed(
                "decision_kind=work_order_brief but work_order_brief missing"
            )
        role = sub.get("assigned_role")
        if role not in KNOWN_TIER_2_ROLES:
            raise AidenDecisionMalformed(
                f"assigned_role must be one of {sorted(KNOWN_TIER_2_ROLES)}, "
                f"got {role!r}"
            )
        priority = sub.get("priority", "medium")
        if priority not in {"low", "medium", "high", "critical"}:
            priority = "medium"
        cb = sub.get("content_blocks")
        if not isinstance(cb, dict):
            cb = {}
        wob = AidenWorkOrderBrief(
            assigned_role=role,
            content_blocks=cb,
            priority=priority,
        )

    elif kind == "workflow_brief":
        sub = data.get("workflow_brief")
        if not isinstance(sub, dict):
            raise AidenDecisionMalformed(
                "decision_kind=workflow_brief but workflow_brief missing"
            )
        tpl = sub.get("workflow_template_key")
        if not isinstance(tpl, str) or not tpl.strip():
            raise AidenDecisionMalformed(
                "workflow_template_key missing or non-string"
            )
        si = sub.get("step_inputs", {})
        if not isinstance(si, dict):
            si = {}
        wfb = AidenWorkflowBrief(workflow_template_key=tpl, step_inputs=si)

    elif kind == "clarification":
        sub = data.get("clarification")
        if not isinstance(sub, dict):
            raise AidenDecisionMalformed(
                "decision_kind=clarification but clarification missing"
            )
        q = sub.get("question")
        if not isinstance(q, str) or not q.strip():
            raise AidenDecisionMalformed("clarification.question missing")
        mf = sub.get("missing_fields", [])
        if not isinstance(mf, list):
            mf = []
        cl = AidenClarification(
            question=q, missing_fields=[str(x) for x in mf]
        )

    return AidenDecision(
        decision_kind=kind,
        title=title.strip(),
        summary=summary,
        work_order_brief=wob,
        workflow_brief=wfb,
        clarification=cl,
    )


async def _emit_invoked(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: EffectiveLlmConfig,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    decision_kind: str,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.invoked",
        target_type="work_order" if work_order_id else "llm_config",
        target_id=work_order_id or cfg.config_id,
        metadata={
            "provider": cfg.provider,
            "model": cfg.model,
            "agentRole": cfg.resolved_role,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": prompt_tokens + completion_tokens,
            "latencyMs": latency_ms,
            "workOrderId": work_order_id,
            "decisionKind": decision_kind,
            "contractVersion": AIDEN_CONTRACT_VERSION,
        },
    )


async def _emit_failed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: Optional[EffectiveLlmConfig],
    kind: str,
    detail: str,
    http_status: Optional[int] = None,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.failed",
        target_type="work_order" if work_order_id else "llm_config",
        target_id=work_order_id or (cfg.config_id if cfg else None),
        metadata={
            "kind": kind,
            "detail": detail,
            "httpStatus": http_status,
            "provider": cfg.provider if cfg else None,
            "model": cfg.model if cfg else None,
            "agentRole": cfg.resolved_role if cfg else None,
            "workOrderId": work_order_id,
            "contractVersion": AIDEN_CONTRACT_VERSION,
        },
    )


async def invoke_aiden_tier_1(
    conn: asyncpg.Connection,
    *,
    intake_text: str,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str] = None,
    intake_metadata: Optional[dict] = None,
    transport=None,
) -> AidenDecision:
    """Run Aiden Tier 1 against `intake_text`; return a parsed decision.

    Caller (Submit Order route, Telegram intake handler, Chat-with-
    Aiden route) is responsible for acting on the decision: creating
    the WO, instantiating the workflow_execution, or surfacing the
    clarification question.

    Raises:
      AidenNoConfig          tenant has no aiden_tier_1 LLM config
      LlmBudgetExceeded      per-WO ceiling would be breached
      AidenDecisionMalformed provider returned non-conforming JSON
      AidenInvocationError   credential / provider / network error
    """
    cfg = await resolve_llm_config(
        conn, client_id=client_id, agent_role=AIDEN_TIER_1_ROLE
    )
    if cfg is None or not cfg.enabled:
        raise AidenNoConfig(
            f"no enabled aiden_tier_1 LLM config for tenant {client_id}"
        )

    # Pre-flight budget — uses naive token estimate (chars/4) as a
    # cheap gate; the real per-call usage is logged after the call
    # completes with the provider-reported counts.
    estimate = max(
        128,
        min(
            DEFAULT_PER_CALL_MAX_TOKENS,
            (len(AIDEN_SYSTEM_PROMPT) + len(intake_text)) // 4,
        ),
    )
    await check_or_raise_wo_budget(
        conn,
        work_order_id=work_order_id,
        client_id=client_id,
        actor_user_id=actor_user_id,
        next_call_estimate=estimate,
    )

    try:
        api_key = resolve_credential(cfg.credential_ref)
    except LlmCredentialError as exc:
        await _emit_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            kind="credential_missing",
            detail=str(exc),
        )
        raise AidenInvocationError("credential_missing", str(exc))

    options = dict(cfg.options or {})
    options.setdefault("max_tokens", resolve_max_tokens(cfg.options))
    options.setdefault("response_format", {"type": "json_object"})

    started = time.monotonic()
    try:
        result = call_openai_compatible(
            provider=cfg.provider,
            model=cfg.model,
            api_key=api_key,
            base_url=cfg.base_url,
            system_prompt=(
                (cfg.system_prompt or AIDEN_SYSTEM_PROMPT)
                + AIDEN_OUTPUT_SCHEMA
            ),
            user_message=intake_text,
            options=options,
            transport=transport,
        )
    except LlmProviderError as exc:
        await _emit_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            kind=exc.kind,
            detail=str(exc),
            http_status=exc.http_status,
        )
        raise AidenInvocationError(exc.kind, str(exc))

    latency_ms = int((time.monotonic() - started) * 1000)

    # Parse before audit so a malformed response doesn't get tagged
    # as `llm.invoked` (which would suggest success).
    try:
        decision = _parse_decision(result.text)
    except AidenDecisionMalformed as exc:
        await _emit_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            kind="malformed_output",
            detail=str(exc),
        )
        raise

    # Token counts reported by provider when available; fall back to
    # our chars/4 estimate.
    raw = result.raw or {}
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if isinstance(usage, dict):
        prompt_t = int(usage.get("prompt_tokens") or 0)
        completion_t = int(usage.get("completion_tokens") or 0)
    else:
        prompt_t = result.prompt_chars // 4
        completion_t = result.completion_chars // 4

    await _emit_invoked(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        work_order_id=work_order_id,
        cfg=cfg,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        latency_ms=latency_ms,
        decision_kind=decision.decision_kind,
    )

    # Hydrate decision with provenance fields for downstream callers.
    return AidenDecision(
        decision_kind=decision.decision_kind,
        title=decision.title,
        summary=decision.summary,
        work_order_brief=decision.work_order_brief,
        workflow_brief=decision.workflow_brief,
        clarification=decision.clarification,
        provider=cfg.provider,
        model=cfg.model,
        latency_ms=latency_ms,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        total_tokens=prompt_t + completion_t,
    )

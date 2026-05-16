"""MegaLoop Alpha α.4 — Tier 2 sub-agent runtime.

One execution path used by both:
  - Aiden's direct `work_order_brief` route (single-step delivery)
  - PM's `workflow_step_run` advancement (multi-step delivery)

Each Tier 2 sub-agent has its own LLM config (mark_tier_2,
tom_tier_2, hank_tier_2, paul_tier_2) and produces:
  - markdown content (the actual deliverable)
  - structured JSON metadata (output_kind + summary + sub-agent-specific)

The runtime parses the response, writes an `output_packages` row,
emits `output_package.created` audit, and returns the package id +
provenance. Dispatch (handoff via Gamma or other adapter) is the
caller's responsibility — keeping content production and adapter
dispatch as separable surfaces.

Stage A constraints:
  - § A1: Tier 2 must use a real LLM (live).
  - § A5: Tier 2 returns JSON envelope wrapping markdown content +
    metadata so callers can mechanically build the output_package.
  - § A7: same per-call/per-WO budget enforcement as Tier 1 / 1.5.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional, Union

import asyncpg

from authz.audit_writer import write_audit_row
from llm.config_resolver import EffectiveLlmConfig, resolve_llm_config
from llm.credentials import LlmCredentialError, resolve_credential
from llm.providers import LlmProviderError, call_openai_compatible
from runtime.budgets import (
    check_or_raise_wo_budget,
    resolve_max_tokens,
)


TIER_2_CONTRACT_VERSION = "v1.alpha"


# Loop Eta — Tier 2 tool-call cap. After 3 tool round-trips the runtime
# injects a "[TOOL CAP REACHED]" prompt fragment and re-invokes once
# with tool_call disabled in the schema, forcing the LLM to compose a
# final envelope using whatever data it has gathered so far.
MAX_TIER_2_TOOL_CALLS = 3


# Roles that are always known to be Tier 2 in IWO3. Legacy
# template seeds may use the un-suffixed forms ("mark", "tom", ...);
# normalisation happens at the dispatch boundary.
NORMALIZE_TIER_2 = {
    "jamie": "jamie_tier_2",
    "mark": "mark_tier_2",
    "nyx": "nyx_tier_2",
    "polaris": "polaris_tier_2",
    "darla": "darla_tier_2",
    "sop_master": "sop_master_tier_2",
    "sop-master": "sop_master_tier_2",
    "sop": "sop_master_tier_2",
    "tom": "tom_tier_2",
    "hank": "hank_tier_2",
    "paul": "paul_tier_2",
    "jamie_tier_2": "jamie_tier_2",
    "mark_tier_2": "mark_tier_2",
    "nyx_tier_2": "nyx_tier_2",
    "polaris_tier_2": "polaris_tier_2",
    "darla_tier_2": "darla_tier_2",
    "sop_master_tier_2": "sop_master_tier_2",
    "tom_tier_2": "tom_tier_2",
    "hank_tier_2": "hank_tier_2",
    "paul_tier_2": "paul_tier_2",
}


# Default per-role system prompts. Used when the resolved llm_configs
# row has no system_prompt of its own. Tier 2 sub-agents are
# producers; they output a strict JSON envelope.
DEFAULT_SYSTEM_PROMPTS = {
    "jamie_tier_2": (
        "You are Jamie, the Tier 2 executive-assistant sub-agent for "
        "IWO3. Handle scheduling, stakeholder coordination, and vendor "
        "follow-up work. Respond with strict JSON wrapping a markdown "
        "content block."
    ),
    "mark_tier_2": (
        "You are Mark, the Tier 2 marketing/content sub-agent for IWO3. "
        "Produce content briefs and marketing copy. Respond with strict "
        "JSON wrapping a markdown content block."
    ),
    "nyx_tier_2": (
        "You are Nyx, the Tier 2 security/compliance sub-agent for "
        "IWO3. Review PII, audit boundaries, and policy risk. Respond "
        "with strict JSON wrapping a markdown content block."
    ),
    "polaris_tier_2": (
        "You are Polaris, the Tier 2 operations sub-agent for IWO3. "
        "Handle SLA, KPI, capacity, and escalation analysis. Respond "
        "with strict JSON wrapping a markdown content block."
    ),
    "darla_tier_2": (
        "You are Darla, the Tier 2 design + brand-QA sub-agent for IWO3. "
        "Two operating modes:\n\n"
        "MODE 1 — design briefs (default). Produce visual design direction, "
        "review notes, and structured design briefs. Respond with strict "
        "JSON wrapping a markdown content block.\n\n"
        "MODE 2 — brand_attestation (when content_blocks.qa_mode = "
        "'brand_attestation'). You are a brand QA gate. Score the package "
        "content against the BRAND PROFILE TO SCORE AGAINST section in the "
        "intake. Return strict JSON with these fields in `metadata`:\n"
        "  overall: 'pass' | 'needs_revision' | 'block'\n"
        "  palette_pass: bool — does content honor the brand palette?\n"
        "  fonts_pass: bool — does content honor heading/body font choices?\n"
        "  voice_pass: bool — does content match brand voice + tone?\n"
        "  asset_pass: bool — are brand assets (logo, imagery) used correctly?\n"
        "  notes: array of short actionable strings (≤ 8) for the render "
        "step to address on a 'needs_revision' verdict.\n"
        "Verdict semantics:\n"
        "  pass — all four pass flags true; content ships to delivery.\n"
        "  needs_revision — one or more pass flags false but recoverable; "
        "render step regenerates with notes.\n"
        "  block — egregious violation (off-brand colors, wrong product "
        "domain, brand-confusion risk, prohibited content); operator must "
        "adjudicate. Use sparingly; prefer needs_revision when fixable."
    ),
    "sop_master_tier_2": (
        "You are SOP Master, the Tier 2 process-documentation sub-agent "
        "for IWO3. Produce SOPs, workflow templates, onboarding docs, "
        "and process audit notes. Respond with strict JSON wrapping a "
        "markdown content block."
    ),
    "tom_tier_2": (
        "You are Tom, the Tier 2 deck-builder sub-agent for IWO3. "
        "Produce structured presentation content blocks for Gamma. "
        "Respond with strict JSON wrapping a markdown content block."
    ),
    "hank_tier_2": (
        "You are Hank, the Tier 2 web-builder sub-agent for IWO3. "
        "Produce HTML / landing page snippets. Respond with strict "
        "JSON wrapping a markdown content block."
    ),
    "paul_tier_2": (
        "You are Paul, the Tier 2 intelligent-delivery sub-agent for IWO3. "
        "Two operating modes:\n\n"
        "MODE 1 — deployment briefs (default). Coordinate publishing / "
        "packaging / external handoffs. Respond with strict JSON wrapping "
        "a markdown content block.\n\n"
        "MODE 2 — intelligent delivery (when content_blocks.delivery_mode = "
        "'intelligent'). You are the delivery decider for a branded "
        "deliverable. You receive: the requested output_kind, the primary "
        "adapter key, the available fallback adapter keys, the full list "
        "of template variants the tenant has registered for this output_kind, "
        "and (if Darla ran) a brand-attestation summary. Decide:\n"
        "  - Which template variant to use (the package may already carry "
        "one; honor it unless attestation suggests a different variant fits "
        "better).\n"
        "  - Whether to dispatch via the primary adapter or fall back.\n"
        "  - Whether to halt with operator notice (when no path is viable).\n"
        "Return strict JSON with these fields in `metadata`:\n"
        "  outcome: 'primary_dispatch' | 'fallback_dispatch' | 'blocked'\n"
        "  template_profile_id: chosen UUID, or null if blocked.\n"
        "  adapter_key: which adapter to dispatch through.\n"
        "  fallback_adapter_keys: array of adapter keys to try in order if "
        "the chosen adapter fails.\n"
        "  decision_reason: short string explaining the choice.\n"
        "  candidate_choice: optional candidate_id when candidate-review "
        "policy was active (rare — leave null otherwise).\n"
        "When the package already carries a template_profile_id and the "
        "tenant has only one registered variant for that output_kind, the "
        "decision is deterministic (primary_dispatch with that template). "
        "When multiple variants exist, choose by content fit + attestation "
        "signal."
    ),
}

TIER_2_OUTPUT_SCHEMA_BASE = """
You must respond with a strict JSON object. You have TWO modes — pick
exactly one per response by setting `decision_kind`:

decision_kind="tool_call" — when you need runtime data (recent work
orders, work-order counts, runtime health, search results, etc.) before
you can compose the final deliverable. The runtime executes the tool,
feeds the result back in your next turn, then you compose the final
content_envelope. NEVER fabricate runtime data. NEVER claim you "looked
up" or "checked" anything — call the tool, then answer.

decision_kind="content_envelope" — DEFAULT. When you have everything you
need to produce the deliverable.

Schema:

{
  "decision_kind": "content_envelope" | "tool_call",
  "content_envelope": {
    "content_markdown": "the deliverable, as markdown",
    "summary": "one-line summary of what you produced",
    "output_kind": "gamma_pptx | gamma_pdf | generic",
    "metadata": { ... sub-agent specific fields ... }
  },
  "tool_call": {
    "tool_name": "<one of the tools assigned to you>",
    "args": { ... }
  }
}

Only include the subobject matching `decision_kind`. Output JSON ONLY,
no commentary, no markdown fences.
"""


TIER_2_OUTPUT_SCHEMA_NO_TOOL_CALL = """
You must respond with a strict JSON object of the form:

{
  "decision_kind": "content_envelope",
  "content_envelope": {
    "content_markdown": "the deliverable, as markdown",
    "summary": "one-line summary of what you produced",
    "output_kind": "gamma_pptx | gamma_pdf | generic",
    "metadata": { ... sub-agent specific fields ... }
  }
}

You have already exhausted your tool-call budget for this work order;
do NOT request another tool. Compose the final deliverable using
whatever runtime data you have already gathered. Output JSON ONLY,
no commentary, no fences.
"""

# Back-compat: legacy callers / docs may still reference the original
# constant name. Resolves to the dual-mode schema (tool_call enabled).
TIER_2_OUTPUT_SCHEMA = TIER_2_OUTPUT_SCHEMA_BASE


@dataclass(frozen=True)
class Tier2OutputEnvelope:
    content_markdown: str
    summary: str
    output_kind: str
    metadata: dict


@dataclass(frozen=True)
class Tier2ToolCall:
    """Loop Eta — a Tier 2 sub-agent requests one tool execution before
    composing its final content_envelope. The runtime executes the tool
    against the tenant-scoped connection and re-invokes the sub-agent
    with the tool result injected into intake_text. Cap of
    MAX_TIER_2_TOOL_CALLS round-trips per Tier 2 invocation."""

    tool_name: str
    args: dict


# Discriminated-union return shape for the single-round-trip helper.
# `invoke_tier_2` (the public API) loops over this until it gets an
# envelope or hits the tool cap.
Tier2Decision = Union[Tier2OutputEnvelope, Tier2ToolCall]


@dataclass(frozen=True)
class Tier2InvocationResult:
    role: str
    output_envelope: Tier2OutputEnvelope
    output_package_id: Optional[str]
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Tier2Error(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class Tier2RoleUnknown(Tier2Error):
    def __init__(self, role: str) -> None:
        super().__init__("role_unknown", f"role={role!r}")


class Tier2NoConfig(Tier2Error):
    def __init__(self, role: str) -> None:
        super().__init__(
            "no_llm_configured", f"no enabled LLM config for {role}"
        )


class Tier2OutputMalformed(Tier2Error):
    def __init__(self, detail: str) -> None:
        super().__init__("output_malformed", detail)


def normalize_tier_2_role(role: str) -> str:
    norm = NORMALIZE_TIER_2.get(role)
    if norm is None:
        raise Tier2RoleUnknown(role)
    return norm


def _parse_decision(raw_text: str) -> Tier2Decision:
    """Parse a Tier 2 LLM response into either a Tier2OutputEnvelope
    (final deliverable) or a Tier2ToolCall (intermediate runtime lookup).

    Accepts three shapes for backward compatibility with the pre-Loop-Eta
    contract:
      1. {"decision_kind": "content_envelope", "content_envelope": {...}}
      2. {"decision_kind": "tool_call", "tool_call": {...}}
      3. Legacy bare envelope: {"content_markdown": ..., "summary": ...,
         "output_kind": ..., "metadata": ...}  (no decision_kind wrapper)
    """
    body = raw_text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        body = "\n".join(lines)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise Tier2OutputMalformed(
            f"json decode failed: {exc}; first 200 chars: {body[:200]!r}"
        )

    kind = data.get("decision_kind")

    # Loop Eta — discriminated-union shape.
    if kind == "tool_call":
        sub = data.get("tool_call")
        if not isinstance(sub, dict):
            raise Tier2OutputMalformed(
                "decision_kind=tool_call but tool_call subobject missing"
            )
        tn = sub.get("tool_name")
        if not isinstance(tn, str) or not tn.strip():
            raise Tier2OutputMalformed("tool_call.tool_name missing or empty")
        ta = sub.get("args", {})
        if not isinstance(ta, dict):
            ta = {}
        return Tier2ToolCall(tool_name=tn.strip(), args=ta)

    if kind == "content_envelope":
        sub = data.get("content_envelope")
        if not isinstance(sub, dict):
            raise Tier2OutputMalformed(
                "decision_kind=content_envelope but content_envelope subobject missing"
            )
        return _parse_envelope_subobject(sub)

    # Legacy bare-envelope shape (pre-Loop-Eta): the body itself is the
    # envelope. Preserves compatibility with existing tests + any
    # operator system_prompt that hasn't been re-rendered.
    return _parse_envelope_subobject(data)


def _parse_envelope_subobject(data: dict) -> Tier2OutputEnvelope:
    md = data.get("content_markdown")
    if not isinstance(md, str) or not md.strip():
        raise Tier2OutputMalformed("content_markdown missing or empty")
    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = ""
    output_kind = data.get("output_kind") or "generic"
    if output_kind not in {
        "gamma_pptx", "gamma_pdf", "sandbox_pptx", "sandbox_pdf",
        "email_campaign", "drive_upload", "crm_mutation",
        "figma_handoff", "stitch_handoff", "designlab_handoff",
        "generic",
    }:
        output_kind = "generic"
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return Tier2OutputEnvelope(
        content_markdown=md,
        summary=summary,
        output_kind=output_kind,
        metadata=metadata,
    )


# Back-compat alias for any external import. New code should use
# `_parse_decision`.
def _parse_envelope(raw_text: str) -> Tier2OutputEnvelope:
    decision = _parse_decision(raw_text)
    if isinstance(decision, Tier2ToolCall):
        raise Tier2OutputMalformed(
            "expected content_envelope but got tool_call decision"
        )
    return decision


async def _emit_tier2_invoked(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: EffectiveLlmConfig,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    role: str,
    output_kind: str,
    output_package_id: Optional[str],
    decision_kind: str = "content_envelope",
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.invoked",
        target_type="output_package" if output_package_id else "work_order",
        target_id=output_package_id or work_order_id or cfg.config_id,
        metadata={
            "provider": cfg.provider,
            "model": cfg.model,
            "agentRole": role,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": prompt_tokens + completion_tokens,
            "latencyMs": latency_ms,
            "workOrderId": work_order_id,
            "decisionKind": decision_kind,
            "outputKind": output_kind,
            "outputPackageId": output_package_id,
            "contractVersion": TIER_2_CONTRACT_VERSION,
        },
    )


async def _emit_tier2_failed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: Optional[EffectiveLlmConfig],
    role: str,
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
            "agentRole": role,
            "workOrderId": work_order_id,
            "contractVersion": TIER_2_CONTRACT_VERSION,
        },
    )


async def _invoke_tier_2_once(
    conn: asyncpg.Connection,
    *,
    cfg: EffectiveLlmConfig,
    api_key: str,
    norm_role: str,
    intake_text: str,
    content_blocks: dict,
    work_order_id: Optional[str],
    client_id: str,
    actor_user_id: Optional[str],
    disable_tool_call: bool,
    memory_block: str = "",
    transport=None,
) -> Tier2Decision:
    """Single Tier 2 round-trip. Returns either an envelope (final
    deliverable) or a tool_call (intermediate). The looping wrapper
    `invoke_tier_2` calls this repeatedly until it gets an envelope or
    hits MAX_TIER_2_TOOL_CALLS.

    `disable_tool_call=True` swaps in the no-tool-call schema so the
    LLM is forced to compose a final envelope (used after the cap is
    reached)."""
    schema = (
        TIER_2_OUTPUT_SCHEMA_NO_TOOL_CALL
        if disable_tool_call
        else TIER_2_OUTPUT_SCHEMA_BASE
    )
    base_role_prompt = (
        cfg.system_prompt or DEFAULT_SYSTEM_PROMPTS.get(norm_role, "")
    )
    # Loop Lambda — prepend memory_block when the wrapper supplied
    # one. Memory context goes BEFORE the role prompt + schema so the
    # tenant-validated facts appear at the top of the system message.
    # Empty string is the safe default — Iota/Kappa Tier-2 behavior
    # preserved for callers that don't yet pass memory.
    if memory_block:
        system_prompt = memory_block + "\n\n" + base_role_prompt + schema
    else:
        system_prompt = base_role_prompt + schema

    user_msg = json.dumps(
        {"intake_text": intake_text, "content_blocks": content_blocks}
    )

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
            system_prompt=system_prompt,
            user_message=user_msg,
            options=options,
            transport=transport,
        )
    except LlmProviderError as exc:
        await _emit_tier2_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            role=norm_role,
            kind=exc.kind,
            detail=str(exc),
            http_status=exc.http_status,
        )
        raise Tier2Error(exc.kind, str(exc))

    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        decision = _parse_decision(result.text)
    except Tier2OutputMalformed as exc:
        await _emit_tier2_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            role=norm_role,
            kind="malformed_output",
            detail=str(exc),
        )
        raise

    raw = result.raw or {}
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if isinstance(usage, dict):
        prompt_t = int(usage.get("prompt_tokens") or 0)
        completion_t = int(usage.get("completion_tokens") or 0)
    else:
        prompt_t = result.prompt_chars // 4
        completion_t = result.completion_chars // 4

    decision_kind_label = (
        "tool_call" if isinstance(decision, Tier2ToolCall)
        else "content_envelope"
    )
    output_kind_label = (
        decision.output_kind
        if isinstance(decision, Tier2OutputEnvelope)
        else "tool_call"
    )
    await _emit_tier2_invoked(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        work_order_id=work_order_id,
        cfg=cfg,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        latency_ms=latency_ms,
        role=norm_role,
        output_kind=output_kind_label,
        output_package_id=None,
        decision_kind=decision_kind_label,
    )

    return decision


async def invoke_tier_2(
    conn: asyncpg.Connection,
    *,
    role: str,
    intake_text: str,
    content_blocks: dict,
    work_order_id: Optional[str],
    client_id: str,
    actor_user_id: Optional[str],
    memory_block: str = "",
    transport=None,
) -> Tier2OutputEnvelope:
    """Run a Tier 2 sub-agent end-to-end, including up to
    MAX_TIER_2_TOOL_CALLS tool round-trips before composing the final
    envelope.

    Each tool round-trip:
      1. Pre-execution authz via `check_sub_agent_tool_assignment`.
         Unauthorized → `sub_agent.tool_unauthorized` audit + the
         denial message is appended to intake for the next turn.
      2. Authorized → `execute_tool(event_prefix='sub_agent', ...)`
         which writes `sub_agent.tool_called` (or `sub_agent.tool_failed`)
         and returns the tool result.
      3. Tool result is appended to intake for the next turn.

    After cap reached: writes `sub_agent.tool_cap_reached`, re-invokes
    once with the no-tool-call schema, and returns whatever envelope the
    LLM composes.

    Does NOT persist output_package on its own — `produce_output_package`
    is the wrapper that persists. Used by both the WO direct path and the
    workflow_step_run advancement path.

    Returns the parsed envelope. Raises Tier2Error subclass on failure.
    """
    norm_role = normalize_tier_2_role(role)
    cfg = await resolve_llm_config(
        conn, client_id=client_id, agent_role=norm_role
    )
    if cfg is None or not cfg.enabled:
        raise Tier2NoConfig(norm_role)

    estimate = max(
        128,
        min(
            resolve_max_tokens(cfg.options),
            (len(intake_text) + len(json.dumps(content_blocks))) // 4,
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
        await _emit_tier2_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            role=norm_role,
            kind="credential_missing",
            detail=str(exc),
        )
        raise Tier2Error("credential_missing", str(exc))

    # Loop Eta — tool-call → execute → re-invoke loop. Local imports
    # avoid runtime → aiden_tools import cycle at module-load time.
    from runtime.aiden_tools import (  # noqa: PLC0415
        ToolExecutionError,
        ToolNotFoundError,
        check_sub_agent_tool_assignment,
        execute_tool,
    )

    current_intake = intake_text
    calls_made = 0

    while True:
        disable_tool_call = calls_made >= MAX_TIER_2_TOOL_CALLS
        decision = await _invoke_tier_2_once(
            conn,
            cfg=cfg,
            api_key=api_key,
            norm_role=norm_role,
            intake_text=current_intake,
            content_blocks=content_blocks,
            work_order_id=work_order_id,
            client_id=client_id,
            actor_user_id=actor_user_id,
            disable_tool_call=disable_tool_call,
            memory_block=memory_block,
            transport=transport,
        )

        if isinstance(decision, Tier2OutputEnvelope):
            return decision

        # decision is a Tier2ToolCall here.
        tool_call = decision

        if calls_made >= MAX_TIER_2_TOOL_CALLS:
            # Reached the cap and the LLM ignored the no-tool-call schema.
            # Force a final-envelope turn by injecting a hard hint and
            # re-invoking with the same disabled schema.
            current_intake = (
                f"{current_intake}\n\n"
                "[TOOL CAP REACHED — compose final envelope using what "
                "you have]"
            )
            continue

        # We're below the cap — try to execute the tool.
        calls_made += 1

        # Cap-reached audit fires PROACTIVELY when this round consumed
        # the last allowed slot, so operators see the cap event exactly
        # once per WO regardless of whether the LLM complies.
        if calls_made >= MAX_TIER_2_TOOL_CALLS:
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor_user_id,
                event="sub_agent.tool_cap_reached",
                target_type="llm_config",
                target_id=cfg.config_id,
                metadata={
                    "agent_role": norm_role,
                    "llm_config_id": cfg.config_id,
                    "work_order_id": work_order_id,
                    "calls_made": calls_made,
                    "contractVersion": TIER_2_CONTRACT_VERSION,
                },
            )

        # Pre-execution authz.
        try:
            authorized = await check_sub_agent_tool_assignment(
                conn,
                llm_config_id=cfg.config_id,
                tool_key=tool_call.tool_name,
            )
            authz_failure_detail = None
        except Exception as exc:  # noqa: BLE001 — defensive: schema not migrated, etc.
            authorized = False
            authz_failure_detail = f"authz_check_failed: {exc!s}"

        if not authorized:
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor_user_id,
                event="sub_agent.tool_unauthorized",
                target_type="aiden_tool",
                target_id=tool_call.tool_name,
                metadata={
                    "tool_name": tool_call.tool_name,
                    "args": tool_call.args,
                    "agent_role": norm_role,
                    "llm_config_id": cfg.config_id,
                    "work_order_id": work_order_id,
                    "iteration_index": calls_made,
                    "detail": authz_failure_detail,
                    "contractVersion": TIER_2_CONTRACT_VERSION,
                },
            )
            current_intake = (
                f"{current_intake}\n\n"
                f"[TOOL DENIED — {tool_call.tool_name} not assigned to "
                f"this agent. Compose your final content_envelope without "
                f"calling that tool.]"
            )
            continue

        try:
            tool_result = await execute_tool(
                conn,
                tool_name=tool_call.tool_name,
                args=tool_call.args,
                client_id=client_id,
                actor_user_id=actor_user_id or "",
                work_order_id=work_order_id,
                event_prefix="sub_agent",
                agent_role=norm_role,
                llm_config_id=cfg.config_id,
                iteration_index=calls_made,
            )
            tool_result_str = json.dumps(tool_result, default=str, indent=2)
        except ToolNotFoundError as exc:
            # `execute_tool` does NOT write an audit row on
            # ToolNotFoundError (it raises before the handler). Emit
            # `sub_agent.tool_failed` here so audit forensics capture
            # every refused round-trip.
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor_user_id,
                event="sub_agent.tool_failed",
                target_type="aiden_tool",
                target_id=tool_call.tool_name,
                metadata={
                    "tool_name": tool_call.tool_name,
                    "args": tool_call.args,
                    "agent_role": norm_role,
                    "llm_config_id": cfg.config_id,
                    "work_order_id": work_order_id,
                    "iteration_index": calls_made,
                    "kind": "ToolNotFoundError",
                    "detail": str(exc)[:500],
                    "contractVersion": TIER_2_CONTRACT_VERSION,
                },
            )
            tool_result_str = (
                f"[TOOL FAILED — {tool_call.tool_name}: not found in registry]"
            )
        except ToolExecutionError as exc:
            # `execute_tool` already wrote `sub_agent.tool_failed` for
            # this branch. Just inject the failure into intake.
            tool_result_str = (
                f"[TOOL FAILED — {tool_call.tool_name}: "
                f"{exc.kind}: {exc.detail}]"
            )

        current_intake = (
            f"{current_intake}\n\n"
            f"[TOOL RESULT — {tool_call.tool_name}]\n"
            f"{tool_result_str}\n"
            f"[END TOOL RESULT]"
        )


async def produce_output_package(
    conn: asyncpg.Connection,
    *,
    envelope: Tier2OutputEnvelope,
    title: str,
    work_order_id: Optional[str],
    workflow_execution_id: Optional[str],
    template_profile_id: Optional[str],
    client_id: str,
    actor_user_id: Optional[str],
    correlation_id: Optional[str] = None,
) -> str:
    """Persist a Tier 2 envelope as an `output_packages` row. Returns
    the package id. Caller decides whether to dispatch (Gamma etc)."""
    pkg_id = str(uuid.uuid4())
    content_blocks = {
        "content_markdown": envelope.content_markdown,
        "summary": envelope.summary,
        "metadata": envelope.metadata,
        # Convenience for adapters that want a `prompt` field.
        "prompt": envelope.content_markdown,
    }
    await conn.execute(
        """
        INSERT INTO output_packages
          (id, client_id, work_order_id, workflow_execution_id,
           output_kind, title, summary, content_blocks,
           template_profile_id, created_by_user_id, correlation_id,
           provenance)
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid,
                $5::output_package_kind, $6, $7, $8::jsonb,
                $9::uuid, $10::uuid, $11, $12::jsonb)
        """,
        pkg_id,
        client_id,
        work_order_id,
        workflow_execution_id,
        envelope.output_kind,
        title[:512],
        (envelope.summary or "")[:2000],
        json.dumps(content_blocks),
        template_profile_id,
        actor_user_id,
        correlation_id,
        json.dumps({"producedBy": "tier_2_subagents", "contractVersion": TIER_2_CONTRACT_VERSION}),
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="output_package.created",
        target_type="output_package",
        target_id=pkg_id,
        metadata={
            "outputKind": envelope.output_kind,
            "workOrderId": work_order_id,
            "workflowExecutionId": workflow_execution_id,
            "title": title,
        },
    )

    # Pre-Beta Loop δ.3 — auto-route the produced output into the
    # tenant's `Outputs/` workspace folder per architect decision (D).
    # Failure here is non-fatal: the output package is already
    # persisted, and the operator can save it manually from the
    # Output Packages surface. We log and continue.
    try:
        outputs_folder_id = await conn.fetchval(
            """
            SELECT root_outputs.id::text
              FROM workspace_folders root
              JOIN workspace_folders root_outputs
                ON root_outputs.parent_folder_id = root.id
               AND root_outputs.deleted_at IS NULL
               AND root_outputs.name = 'Outputs'
             WHERE root.client_id = $1::uuid
               AND root.parent_folder_id IS NULL
               AND root.name = '/'
               AND root.deleted_at IS NULL
            """,
            client_id,
        )
        if outputs_folder_id:
            artifact_id = await conn.fetchval(
                """
                INSERT INTO artifacts
                  (client_id, source_type, content_class, mime_type,
                   filename, storage_ref, extracted_text,
                   workspace_folder_id, metadata, created_by_user_id)
                VALUES ($1::uuid, 'generated'::artifact_source_type,
                        'c1'::artifact_content_class, $2, $3, $4, $5,
                        $6::uuid, $7::jsonb, $8::uuid)
                RETURNING id::text
                """,
                client_id,
                _mime_for_output_kind(envelope.output_kind),
                _filename_for_output(title, envelope.output_kind),
                f"output_package://{pkg_id}",
                envelope.content_markdown[:200_000],
                outputs_folder_id,
                json.dumps({
                    "outputPackageId": pkg_id,
                    "outputKind": envelope.output_kind,
                    "summary": envelope.summary,
                }),
                actor_user_id,
            )
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor_user_id,
                event="file.saved_from_output",
                target_type="artifact",
                target_id=artifact_id,
                metadata={
                    "outputPackageId": pkg_id,
                    "workspaceFolderId": outputs_folder_id,
                    "outputKind": envelope.output_kind,
                    "title": title,
                },
            )
    except Exception as exc:  # noqa: BLE001 — auto-routing is best-effort
        # Caller still gets pkg_id; operator can manually save later.
        import logging
        logging.getLogger("iwo3.tier_2").warning(
            "auto-route to workspace failed for pkg=%s tenant=%s: %s",
            pkg_id, client_id, exc,
        )

    return pkg_id


def _mime_for_output_kind(output_kind: str) -> str:
    """Map output_package_kind → mime hint. Plaintext fallback so
    workspace previews always render something readable."""
    return {
        "gamma_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "sandbox_pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "gamma_pdf": "application/pdf",
        "sandbox_pdf": "application/pdf",
        "email_campaign": "text/markdown",
        "drive_upload": "text/markdown",
        "crm_mutation": "application/json",
        "figma_handoff": "text/markdown",
        "stitch_handoff": "text/markdown",
        "designlab_handoff": "text/markdown",
        "generic": "text/markdown",
    }.get(output_kind, "text/markdown")


def _filename_for_output(title: str, output_kind: str) -> str:
    base = (title or "output")[:200].strip().replace("/", "_")
    ext = {
        "gamma_pptx": ".pptx",
        "sandbox_pptx": ".pptx",
        "gamma_pdf": ".pdf",
        "sandbox_pdf": ".pdf",
        "crm_mutation": ".json",
    }.get(output_kind, ".md")
    return f"{base}{ext}"


async def execute_step_run(
    conn: asyncpg.Connection,
    *,
    step_run_id: str,
    client_id: str,
    actor_user_id: Optional[str],
    intake_context: Optional[str] = None,
    memory_block: str = "",
    transport=None,
) -> Tier2InvocationResult:
    """Advance one workflow_step_run through Tier 2.

    Loads the step_run + its template_step (for assigned_sub_agent_key
    + display_name + prompt_ref). Marks step_run as `running`, calls
    the role's LLM, persists output, marks step_run `completed` (or
    `failed` on error)."""
    row = await conn.fetchrow(
        """
        SELECT sr.id::text                          AS id,
               sr.execution_id::text                AS execution_id,
               sr.step_key,
               sr.step_order,
               sr.status::text                      AS status,
               sr.input,
               we.work_order_id::text               AS work_order_id,
               we.client_id::text                   AS exec_client_id,
               wts.assigned_sub_agent_key,
               wts.display_name
          FROM workflow_step_runs sr
          JOIN workflow_executions we ON we.id = sr.execution_id
          JOIN workflow_template_steps wts
            ON wts.template_id = we.template_id
           AND wts.step_key = sr.step_key
         WHERE sr.id = $1::uuid AND we.client_id = $2::uuid
        """,
        step_run_id,
        client_id,
    )
    if row is None:
        raise Tier2Error("step_run_not_found", f"id={step_run_id}")

    if row["status"] not in ("pending",):
        raise Tier2Error(
            "step_run_not_pending",
            f"step_run={step_run_id} status={row['status']}",
        )

    role_raw = row["assigned_sub_agent_key"] or "mark"
    role = normalize_tier_2_role(role_raw)
    input_payload = row["input"]
    if isinstance(input_payload, str):
        try:
            input_payload = json.loads(input_payload)
        except Exception:
            input_payload = {"raw": input_payload}
    if not isinstance(input_payload, dict):
        input_payload = {}

    intake_text = intake_context or row["display_name"] or row["step_key"]

    # Mark step_run running.
    # lint:bypass-rls-explain="workflow_step_runs has no client_id column; tenant scoping enforced by parent workflow_executions RLS policy (Loop 4 Phase 4.3 nested-parent pattern)"
    await conn.execute(
        """
        UPDATE workflow_step_runs
           SET status = 'running'::workflow_step_run_status,
               started_at = now(),
               updated_at = now()
         WHERE id = $1::uuid
        """,
        step_run_id,
    )

    # Loop CAP-F wire-up — special-case branded-chain step kinds.
    # `brand_qa` step → call Darla helper (CAP-D Φ.6) against the prior
    #                   step's output_package; persist BrandAttestation
    # `deliver` step  → call Paul helper (CAP-D Φ.5) against the prior
    #                   render step's output_package; use Paul's decision
    #                   to dispatch via the unified router (CAP-F Φ.9);
    #                   persist PaulDecision + DispatchResult
    # Other step kinds fall through to the generic invoke_tier_2 path.
    if row["step_key"] in ("brand_qa", "deliver"):
        return await _execute_branded_chain_step(
            conn,
            step_run_id=step_run_id,
            execution_id=row["execution_id"],
            step_key=row["step_key"],
            step_order=row["step_order"],
            work_order_id=row["work_order_id"],
            display_name=row["display_name"],
            assigned_role=role,
            client_id=client_id,
            actor_user_id=actor_user_id,
            intake_text=intake_text,
            input_payload=input_payload,
            memory_block=memory_block,
        )

    try:
        envelope = await invoke_tier_2(
            conn,
            role=role,
            intake_text=intake_text,
            content_blocks=input_payload,
            work_order_id=row["work_order_id"],
            client_id=client_id,
            actor_user_id=actor_user_id,
            memory_block=memory_block,
            transport=transport,
        )
    except Exception as exc:
        # lint:bypass-rls-explain="workflow_step_runs nested-parent RLS via execution_id; failure path mirror of the running-mark above"
        await conn.execute(
            """
            UPDATE workflow_step_runs
               SET status = 'failed'::workflow_step_run_status,
                   output = $2::jsonb,
                   completed_at = now(),
                   updated_at = now()
             WHERE id = $1::uuid
            """,
            step_run_id,
            json.dumps({"error": str(exc), "kind": getattr(exc, "kind", "unknown")}),
        )
        raise

    # Beta-2 phase 0.2 — propagate operator-supplied template choice
    # from the parent WO's requested_outputs into the step's package row
    # so the adapter dispatcher can target the right Gamma template
    # without falling back to inference.
    requested_template_id: Optional[str] = None
    if row["work_order_id"]:
        # lint:bypass-rls-explain="execute_step_run runs under tenant-scoped conn; work_orders RLS filters by app.current_client_id transparently"
        wo_ro_row = await conn.fetchrow(
            "SELECT requested_outputs::text AS ro FROM work_orders WHERE id = $1::uuid",
            row["work_order_id"],
        )
        if wo_ro_row is not None and wo_ro_row["ro"]:
            try:
                ro = json.loads(wo_ro_row["ro"])
                tpl = ro.get("template_profile_id")
                if isinstance(tpl, str) and tpl:
                    requested_template_id = tpl
            except (json.JSONDecodeError, AttributeError):
                pass

    # Persist output_package + mark completed.
    pkg_id = await produce_output_package(
        conn,
        envelope=envelope,
        title=f"{row['display_name']} ({row['step_key']})",
        work_order_id=row["work_order_id"],
        workflow_execution_id=row["execution_id"],
        template_profile_id=requested_template_id,
        client_id=client_id,
        actor_user_id=actor_user_id,
        correlation_id=None,
    )
    # lint:bypass-rls-explain="workflow_step_runs nested-parent RLS via execution_id; completed-mark mirror of the running-mark above"
    await conn.execute(
        """
        UPDATE workflow_step_runs
           SET status = 'completed'::workflow_step_run_status,
               output = $2::jsonb,
               completed_at = now(),
               updated_at = now()
         WHERE id = $1::uuid
        """,
        step_run_id,
        json.dumps(
            {
                "outputPackageId": pkg_id,
                "summary": envelope.summary,
                "outputKind": envelope.output_kind,
            }
        ),
    )

    # Beta-2 phase 0.2 — auto-dispatch to Gamma when this step's
    # output is gamma_*-kinded. Mirrors the β.3 single-step path's
    # auto-dispatch hook so workflow steps close the loop too.
    if envelope.output_kind.startswith("gamma_"):
        try:
            # Local import avoids the runtime → adapter circular-import
            # hazard at module-load time.
            from adapter.dispatch import (  # noqa: PLC0415
                DispatchError as _DispErr,
                dispatch_gamma_for_package,
            )

            await dispatch_gamma_for_package(
                conn,
                output_package_id=pkg_id,
                client_id=client_id,
                actor_user_id=actor_user_id,
            )
        except _DispErr as exc:
            await write_audit_row(
                conn,
                client_id=client_id,
                actor_user_id=actor_user_id,
                event="adapter_dispatch.failed",
                target_type="output_package",
                target_id=pkg_id,
                metadata={
                    "kind": exc.kind,
                    "detail": exc.detail,
                    "stage": "auto_dispatch_post_step_run",
                },
            )

    return Tier2InvocationResult(
        role=role,
        output_envelope=envelope,
        output_package_id=pkg_id,
        provider="",
        model="",
        latency_ms=0,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
    )


# ── Loop CAP-F wire-up ───────────────────────────────────────────


async def _find_prior_step_output_package_id(
    conn: asyncpg.Connection,
    *,
    execution_id: str,
    step_order: int,
) -> Optional[str]:
    """Find the most recent prior step_run's output_package_id within
    the same workflow_execution. Branded chains produce a package at
    the render step (order 2); brand_qa (order 3) and deliver
    (order 4) both consume it."""
    return await conn.fetchval(
        """
        SELECT sr.output_package_id::text
          FROM workflow_step_runs sr
         WHERE sr.execution_id = $1::uuid
           AND sr.step_order < $2::int
           AND sr.output_package_id IS NOT NULL
         ORDER BY sr.step_order DESC
         LIMIT 1
        """,
        execution_id,
        step_order,
    )


async def _persist_branded_step_completion(
    conn: asyncpg.Connection,
    *,
    step_run_id: str,
    output_package_id: Optional[str],
    output_json: dict,
) -> None:
    # lint:bypass-rls-explain="workflow_step_runs has no client_id column; tenant scoping enforced by parent workflow_executions RLS policy (Loop 4 Phase 4.3 nested-parent pattern)"
    await conn.execute(
        """
        UPDATE workflow_step_runs
           SET status = 'completed'::workflow_step_run_status,
               output = $2::jsonb,
               output_package_id = $3::uuid,
               completed_at = now(),
               updated_at = now()
         WHERE id = $1::uuid
        """,
        step_run_id,
        json.dumps(output_json),
        output_package_id,
    )


async def _persist_branded_step_failure(
    conn: asyncpg.Connection,
    *,
    step_run_id: str,
    error_json: dict,
) -> None:
    # lint:bypass-rls-explain="workflow_step_runs has no client_id column; nested-parent RLS via execution_id"
    await conn.execute(
        """
        UPDATE workflow_step_runs
           SET status = 'failed'::workflow_step_run_status,
               output = $2::jsonb,
               completed_at = now(),
               updated_at = now()
         WHERE id = $1::uuid
        """,
        step_run_id,
        json.dumps(error_json),
    )


def _synthetic_branded_step_result(
    *,
    role: str,
    output_package_id: Optional[str],
) -> Tier2InvocationResult:
    """For brand_qa / deliver step kinds, the helpers (Darla / Paul)
    don't produce a `Tier2OutputEnvelope` in the standard sense.
    Return a synthetic invocation result so the existing run_next_step
    caller can read `.output_package_id` without special-casing."""
    return Tier2InvocationResult(
        role=role,
        output_envelope=Tier2OutputEnvelope(
            content_markdown="",
            summary="",
            output_kind="",
            metadata={"branded_chain_step": True},
        ),
        output_package_id=output_package_id,
        provider="",
        model="",
        latency_ms=0,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
    )


async def _execute_branded_chain_step(
    conn: asyncpg.Connection,
    *,
    step_run_id: str,
    execution_id: str,
    step_key: str,
    step_order: int,
    work_order_id: Optional[str],
    display_name: str,
    assigned_role: str,
    client_id: str,
    actor_user_id: Optional[str],
    intake_text: str,
    input_payload: dict,
    memory_block: str,
) -> Tier2InvocationResult:
    """Loop CAP-F wire-up — dispatch brand_qa + deliver step kinds
    through the CAP-D helpers (Darla, Paul) and the CAP-F adapter
    router. Other step kinds go through the generic invoke_tier_2
    path at the caller site."""
    # Lazy imports to avoid circular import (paul_delivery + darla_qa
    # import from this module).
    from .darla_qa import invoke_darla_qa
    from .paul_delivery import invoke_paul_delivery
    from adapter.dispatch import DispatchError, dispatch_for_adapter

    prior_pkg_id = await _find_prior_step_output_package_id(
        conn, execution_id=execution_id, step_order=step_order
    )
    if prior_pkg_id is None:
        await _persist_branded_step_failure(
            conn,
            step_run_id=step_run_id,
            error_json={
                "kind": "no_prior_package",
                "step_key": step_key,
                "step_order": step_order,
                "execution_id": execution_id,
            },
        )
        raise Tier2Error(
            "no_prior_package",
            f"branded chain {step_key} step has no prior output_package in execution {execution_id}",
        )

    if step_key == "brand_qa":
        try:
            attestation = await invoke_darla_qa(
                conn,
                output_package_id=prior_pkg_id,
                client_id=client_id,
                actor_user_id=actor_user_id,
                work_order_id=work_order_id,
                intake_text=intake_text,
                memory_block=memory_block,
            )
        except Exception as exc:
            await _persist_branded_step_failure(
                conn,
                step_run_id=step_run_id,
                error_json={
                    "kind": getattr(exc, "kind", "unknown"),
                    "error": str(exc),
                    "step_key": step_key,
                },
            )
            raise

        await _persist_branded_step_completion(
            conn,
            step_run_id=step_run_id,
            output_package_id=prior_pkg_id,
            output_json={
                "step_kind": "brand_qa",
                "verdict": attestation.overall,
                "palette_pass": attestation.palette_pass,
                "fonts_pass": attestation.fonts_pass,
                "voice_pass": attestation.voice_pass,
                "asset_pass": attestation.asset_pass,
                "notes": list(attestation.notes),
                "scored_package_id": prior_pkg_id,
            },
        )
        return _synthetic_branded_step_result(
            role=assigned_role, output_package_id=prior_pkg_id
        )

    # step_key == "deliver"
    # Resolve primary + fallback adapter chain from the input_payload
    # (populated by CAP-E Φ.8 dispatch routing when the workflow_brief
    # decision was instantiated).
    primary_adapter_key = (
        input_payload.get("primary_adapter_key") or "gamma"
    )
    fallback_adapter_keys = list(
        input_payload.get("fallback_adapter_keys") or []
    )
    output_kind = input_payload.get("detected_output_kind") or "pptx"

    try:
        paul_decision = await invoke_paul_delivery(
            conn,
            output_package_id=prior_pkg_id,
            client_id=client_id,
            actor_user_id=actor_user_id,
            output_kind=output_kind,
            primary_adapter_key=primary_adapter_key,
            fallback_adapter_keys=fallback_adapter_keys,
            work_order_id=work_order_id,
            intake_text=intake_text,
            memory_block=memory_block,
        )
    except Exception as exc:
        await _persist_branded_step_failure(
            conn,
            step_run_id=step_run_id,
            error_json={
                "kind": getattr(exc, "kind", "unknown"),
                "error": str(exc),
                "step_key": step_key,
                "phase": "paul_decision",
            },
        )
        raise

    if paul_decision.outcome == "blocked":
        await _persist_branded_step_completion(
            conn,
            step_run_id=step_run_id,
            output_package_id=prior_pkg_id,
            output_json={
                "step_kind": "deliver",
                "outcome": "blocked",
                "decision_reason": paul_decision.decision_reason,
                "adapter_key": paul_decision.adapter_key,
            },
        )
        return _synthetic_branded_step_result(
            role=assigned_role, output_package_id=prior_pkg_id
        )

    # Dispatch via the router; honors Paul's adapter_key + falls back
    # through fallback_adapter_keys on adapter_unavailable.
    try:
        dispatch_result = await dispatch_for_adapter(
            conn,
            adapter_key=paul_decision.adapter_key,
            output_package_id=prior_pkg_id,
            client_id=client_id,
            actor_user_id=actor_user_id,
            fallback_adapter_keys=list(paul_decision.fallback_adapter_keys),
        )
    except DispatchError as exc:
        await _persist_branded_step_failure(
            conn,
            step_run_id=step_run_id,
            error_json={
                "kind": exc.kind,
                "error": exc.detail,
                "step_key": step_key,
                "phase": "adapter_dispatch",
                "paul_outcome": paul_decision.outcome,
                "primary_adapter_key": paul_decision.adapter_key,
            },
        )
        raise

    await _persist_branded_step_completion(
        conn,
        step_run_id=step_run_id,
        output_package_id=prior_pkg_id,
        output_json={
            "step_kind": "deliver",
            "outcome": paul_decision.outcome,
            "decision_reason": paul_decision.decision_reason,
            "adapter_key": paul_decision.adapter_key,
            "fallback_adapter_keys": list(paul_decision.fallback_adapter_keys),
            "template_profile_id": paul_decision.template_profile_id,
            "dispatched_adapter_key": dispatch_result.adapter_key,
            "handoff_id": dispatch_result.handoff_id,
            "external_reference": dispatch_result.external_reference,
        },
    )
    return _synthetic_branded_step_result(
        role=assigned_role, output_package_id=prior_pkg_id
    )

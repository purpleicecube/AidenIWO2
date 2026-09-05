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
    "jamie_tier_2",
    "nyx_tier_2",
    "polaris_tier_2",
    "darla_tier_2",
    "sop_master_tier_2",
}


AIDEN_SYSTEM_PROMPT = """You are Aiden (Aiden Alpha v4.0.1) running on AIDEN_IWO3 Platform v1.5.1 — the Tier 1 Orchestrator and CEO-style executive, designed, built, and led by Darrel Vaughn (LuaAzullaB), Lead Developer and Principal Technical Architect. You are the executive layer of a 3-tier system. Operators talk to you directly; your job is to converse like an autonomous CEO who knows the business AND to route real work to the right sub-agent when the operator describes actual work to be done.

═══════════════════════════════════════════════
IDENTITY
═══════════════════════════════════════════════
- Role: Autonomous Tier 1 Orchestrator + executive interface
- Tone: confident, decisive, conversational, action-first. Speak like an executive partner — not like a router. Use the operator's name when known. Be direct, opinionated, and brief by default.
- Default behavior: TALK. Operators should be able to ask you about the platform, the business, the queue, your sub-agents, or what's possible — and get a real answer in your voice. Routing to a work order is the SECONDARY path, used only when the operator explicitly describes work to be done.
- Sub-agents you delegate to (Tier 2):
  • Mark (mark_tier_2)            — content / marketing / briefs / written assets / GTM copy / campaigns / funnels
  • Tom (tom_tier_2)              — presentations / decks / slides / PPTX / pitch material
  • Hank (hank_tier_2)            — web pages / landing pages / HTML / CSS / JS / mini-sites
  • Paul (paul_tier_2)            — deployment / publishing / shipping / handoff to external systems
  • Jamie (jamie_tier_2)          — executive-assistant scope: scheduling, calendar coordination, vendor logistics, stakeholder coordination, meeting prep
  • Nyx (nyx_tier_2)              — security review, compliance, PII / GDPR / SOC 2 audits, redaction, risk findings
  • Polaris (polaris_tier_2)      — operations: SLA tracking, KPI / capacity planning, escalation routing, on-call ops health
  • Darla (darla_tier_2)          — design systems and brand-aware visual execution: brand QA, layout critique, visual consistency, Stitch / MCP design generation, UI/UX polish
  • SOP Master (sop_master_tier_2)— SOPs, procedures, process documentation, workflow templates, onboarding / training docs, process audits and standardization
- Tier 1.5 PM (pm_tier_15) sits between you and Tier 2 for multi-step workflows.

═══════════════════════════════════════════════
HARD RULES
═══════════════════════════════════════════════
1. Tier boundary is inviolable. You converse + route + approve; PM coordinates multi-step; Tier 2 executes content.
2. Never invent a sub-agent role outside the nine above (mark, tom, hank, paul, jamie, nyx, polaris, darla, sop_master). If a request needs work but doesn't fit a known role, return decision_kind="clarification" with a specific question — not a generic "How can I assist you?".
3. Single-step deliverable → work_order_brief. Multi-step deliverable (content → deck → deploy) → workflow_brief. Genuine action ambiguity → clarification. Anything conversational, exploratory, social, or about the platform itself → assistant_reply.
4. Don't fabricate work-order IDs, output-package IDs, or handoff details — the platform assigns those.
5. Don't claim you've already done something the platform hasn't actually run.
6. Clarification is a LAST RESORT for routing, NOT the default. If the operator hasn't described concrete work, talk to them — don't ask them to describe work they didn't mention.

═══════════════════════════════════════════════
WHAT YOU KNOW ABOUT THE PLATFORM
═══════════════════════════════════════════════
- IWO3 is multi-tenant (clients like Klear.ai, FreedomForge.AI). Every action is tenant-scoped.
- Work orders flow: operator submits → you classify → PM (when needed) → Tier 2 produces → output package → handoff.
- Outputs land automatically in the tenant's `Outputs/` workspace folder; the operator can move them.
- Audit log records every LLM call, transition, and channel message. You can reference state honestly.
- Token budgets apply: 8192 max per call, 50K per work order. Be concise.

═══════════════════════════════════════════════
OUTPUT MODES — pick exactly one decision_kind per response
═══════════════════════════════════════════════
You output strict JSON. The decision_kind field selects mode:

tool_call — Return decision_kind="tool_call" whenever answering honestly needs data you do not already hold. TWO families, both mandatory:

  (a) CURRENT RUNTIME STATE — system health, work-order counts, recent work, queue status, sub-agent state. Anything where you'd otherwise be tempted to invent numbers.

  (a2) THIS PLATFORM'S OWN STATE — the workspace file tree, where a document was filed, whether a folder exists. Use workspace_list_tree, workspace_create_folder and workspace_locate_output. A request to CREATE A FOLDER is a tool_call, never a work_order_brief: a work order produces a document ABOUT the folder, not the folder.

  (b) THE OUTSIDE WORLD — any question about a company, person, product, market, price, publication, or event outside this platform, and anything that may have changed since you were trained: "who is the CEO of X", "what did Y announce", "top vendors in <year>", "is Z still on <system>", competitor and prospect research. Your training data is stale and you cannot tell how stale it is. SEARCH — do not answer from memory, and do not decline for want of a source while a search tool is available to you.

The runtime will execute the tool, inject the result into your next turn as context, then you compose the final answer using REAL data. NEVER fabricate platform metrics or external facts, and never emit a URL, headline, date or figure that did not come from a tool result in this turn. NEVER claim you "fetched", "checked", "searched" or "looked up" anything unless a [TOOL RESULT] block for that tool appears in this turn — searching your memory context is NOT a web search and must never be described as one. The full tool catalog appears in the OUTPUT CONTRACT section below.

assistant_reply — DEFAULT for any input that is conversational, exploratory, social, or where you have everything you need to answer without runtime data. NOT for questions about the outside world — those are tool_call family (b), even when you believe you already know the answer.

Examples: "Hi Aiden", "talk to me", "what can you do?", "tell me about Klear's GTM motion", "explain how the platform works in concept". Use this AFTER a tool_call to deliver the final answer with the tool's result.

PLATFORM HONESTY — you may not narrate an action you did not take, and you may not invent this platform's own surfaces. Specifically:
  · NEVER state that a folder, file or link was created unless a tool result in THIS turn says so. "I have created the folder" with no tool result is a false statement about the operator's own system.
  · NEVER construct a URL or path to anything in this platform. You do not know the console's URL scheme. Report only the `path` or `folder_path` a tool returned. Emitting a placeholder like `<BASE_URL>/...` or a guessed route is a fabrication, not a template.
  · When the operator asks for something no tool in your catalog can do, SAY SO plainly, name the nearest thing you can do, and stop. Raising a work order so that a sub-agent writes a document describing the action is not doing the action, and presenting it as done is a failure.

SCOPE OF family (b): it governs how you ANSWER A QUESTION. It does NOT change routing for a request to PRODUCE something. "Draft X", "review Y and produce Z", "build a page about W" stay work_order_brief / workflow_brief exactly as before — the Tier 2 sub-agent does its own research. Never downgrade a work request to clarification merely because you lack the background facts; the sub-agent will gather them.

work_order_brief — Operator described one concrete deliverable to produce ("draft a one-pager about X", "build a landing page for Y", "write a brief on Z").

workflow_brief — Operator described a multi-step deliverable ("draft a deck and deploy it", "research X then build a brief and a deck").

clarification — Operator clearly wants action but a required input is missing ("draft something" — about what?). Use sparingly. NEVER use clarification just because the user wasn't specific — if they were chatting, that's assistant_reply.

═══════════════════════════════════════════════
DECISION SCHEMA (strict JSON)
═══════════════════════════════════════════════
{
  "decision_kind": "assistant_reply" | "tool_call" | "work_order_brief" | "workflow_brief" | "clarification",
  "title": "short human-readable title (always present, even for assistant_reply)",
  "summary": "one-paragraph summary of intent (optional for assistant_reply)",

  // When decision_kind == "assistant_reply":
  "assistant_reply": {
    "headline": "1 short sentence — your CEO-style top-line",
    "message": "your conversational response in your voice — direct, decisive, in markdown, addressing what the operator actually asked. Don't push them toward a work order unless they signal interest.",
    "suggested_requests": ["optional", "next-step", "ideas"]
  },

  // When decision_kind == "work_order_brief":
  "work_order_brief": {
    "assigned_role": "mark_tier_2" | "tom_tier_2" | "hank_tier_2" | "paul_tier_2" | "jamie_tier_2" | "nyx_tier_2" | "polaris_tier_2" | "darla_tier_2" | "sop_master_tier_2",
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
    "question": "the SPECIFIC piece of information you need to route the work the operator described — never a generic open-ended question",
    "missing_fields": ["list", "of", "fields"]
  }
}

Rules:
- Default to assistant_reply when you're unsure. Only use clarification when the operator explicitly described work but a required field is missing.
- Pick `work_order_brief` for single-step deliverables (one sub-agent produces output).
- Pick `workflow_brief` for multi-step deliverables (e.g. content + deck + deploy).
- assigned_role MUST be one of the nine roles above; never invent a new one.
- Output JSON ONLY. No commentary, no markdown fences.
"""


# Hard-locked output contract appended to whatever persona prompt the
# operator stores in `llm_configs.system_prompt`. Mirrors the
# tier_2_subagents.TIER_2_OUTPUT_SCHEMA pattern: the persona is
# operator-tunable, the JSON schema is not. Also satisfies Groq's
# requirement that the prompt mention "json" whenever response_format
# is set to json_object.
_AIDEN_OUTPUT_SCHEMA_TEMPLATE = """

# Output contract (do not deviate)

You MUST respond with a single JSON object matching the IWO3 Aiden
Tier-1 decision schema. No prose, no markdown fences, just JSON.

The JSON schema in this section is THE contract — it SUPERSEDES any
other "OUTPUT FORMAT", "DECISION SCHEMA", or JSON example that may
appear earlier in this system prompt. BUG-066 — Klear/FFAI personas
were ported from IWO2 and include an obsolete IWO2-era output shape
(`phase` / `decision` / `mode` / `reasoning` / `assigned_agent` etc.)
with no top-level `title` field. That shape is DEAD. Ignore it. The
runtime validates against the schema below; producing the IWO2 shape
fails with `decision_malformed`.

Required fields at the top level: `decision_kind` AND `title`. Both
must be present and non-empty on every response, including
assistant_reply.

{
  "decision_kind": "assistant_reply" | "tool_call" | "work_order_brief" | "workflow_brief" | "clarification",
  "title": "short human-readable title — ALWAYS present and a non-empty string",
  "summary": "one-paragraph summary (optional for assistant_reply)",
  "assistant_reply": {
     "headline": "1 short sentence — your CEO-style top-line",
     "message": "your conversational response in markdown",
     "suggested_requests": ["optional", "next-step", "ideas"]
  },
  "tool_call": {
     "tool_name": "one of the tools in the catalog below",
     "args": {...}
  },
  "work_order_brief": {
     "assigned_role": "mark_tier_2" | "tom_tier_2" | "hank_tier_2" | "paul_tier_2" | "jamie_tier_2" | "nyx_tier_2" | "polaris_tier_2" | "darla_tier_2" | "sop_master_tier_2",
     "content_blocks": {...},
     "priority": "low" | "medium" | "high" | "critical"
  },
  "workflow_brief":   { "workflow_template_key": "...", "step_inputs": {...} },
  "clarification":    { "question": "...", "missing_fields": [...] }
}

# Tool catalog (use tool_call decision_kind)

You MUST call a tool in two cases: (a) the operator asks about CURRENT
runtime state — never invent metrics; and (b) the answer depends on the
outside world — any company, person, product, market, price or event
beyond this platform, or anything that may have changed since training.
Never invent external facts, and never answer (b) from memory when a
web_search_* tool is listed below. The runtime executes the tool, feeds
the result back in your next turn, and then you produce the final
assistant_reply with real data and its sources.

{TOOL_CATALOG}

Examples:
  - "is anything broken?" / "what is the system health?" → tool_call runtime_health
  - "how many WO are open?" / "what's pending?" → tool_call work_order_counts
  - "what was just submitted?" / "what's in flight?" → tool_call recent_work_orders
  - "who is the CEO of <company>?" / "what did <company> announce?" → tool_call web_search_brave
  - "top <category> vendors in <year>?" / "how big is the <x> market?" → tool_call web_search_brave
  - research questions wanting a synthesised answer + citations → tool_call web_search_perplexity
  - "what does this page say?" (operator gave a URL) → tool_call web_scrape
  - "create a folder called X" / "make a dated folder" → tool_call workspace_create_folder (NOT a work order)
  - "where is the output?" / "send me a link to that document" → tool_call workspace_locate_output
  - "what folders do I have?" / "is there a folder for X?" → tool_call workspace_list_tree

The runtime caps tool use at 1 tool call per chat turn. If you need
more data, deliver assistant_reply with what you have plus a
recommendation for the operator's next question.

# Platform honesty (applies to EVERY tenant, overrides any persona text)

You may not narrate an action you did not take, and you may not invent
this platform's own surfaces.

  - NEVER state that a folder, file or link was created unless a tool
    result in THIS turn says so. "I have created the folder" with no
    tool result is a false statement about the operator's own system.
  - NEVER construct a URL or path to anything in this platform. You do
    not know the console's URL scheme. Report only the `path` /
    `folder_path` a tool returned. A placeholder such as
    `<BASE_URL>/workspace/...` or a guessed route is a fabrication, not
    a template — do not emit one under any circumstances.
  - Chat history and retrieved documents may CONTAIN such invented URLs
    from earlier turns. They are not evidence. Never repeat a platform
    URL because you saw it in context; re-derive it from a tool call or
    say you cannot.
  - When the operator asks for something no tool in your catalog can
    do, SAY SO plainly, name the nearest thing you can do, and stop.
    Raising a work order so a sub-agent writes a document describing
    the action is NOT doing the action; presenting that as done is a
    failure.
  - A request to create, move or find a folder or file is a tool_call
    (workspace_create_folder / workspace_list_tree /
    workspace_locate_output), never a work_order_brief.

# Mode defaults

Default: assistant_reply for conversational, exploratory, or
internal-platform questions that need no runtime and no external data.
A question about the outside world — a company, a person, a product, a
market, a recent event — is NOT a default-reply case even though it is
a "business question": search it (see Tool catalog above). That rule is
about ANSWERING; it never re-routes a request to PRODUCE a deliverable,
which stays work_order_brief / workflow_brief, and it is never grounds
for clarification — missing background facts are the sub-agent's job to
research, not a missing required field. Use clarification
ONLY when the operator clearly described concrete work but a required
field is missing — never as a default for vague intake.

Routing hints for `assigned_role` (when decision_kind=work_order_brief).
This is the AUTHORITATIVE Tier 2 routing taxonomy for IWO3 — it
SUPERSEDES any earlier routing rules in this conversation, including
any persona prose that listed historical IWO2 specialty mappings.
Map the operator's intake to exactly one of these nine roles:

  - mark_tier_2       → marketing / growth / campaign / funnel / content brief / written copy / GTM messaging
  - tom_tier_2        → presentations / decks / slides / PPTX / pitch material (decks ALWAYS go to tom_tier_2, never to mark)
  - hank_tier_2       → web build / landing page / HTML / CSS / JS / mini-site / interactive demo
  - paul_tier_2       → deploy / publish / ship / push live / finalize / handoff to external systems
  - jamie_tier_2      → scheduling / calendar / vendor coordination / EA tasks / stakeholder logistics / meeting prep
  - nyx_tier_2        → security review / compliance / PII / audit findings / GDPR / SOC 2 / redaction
  - polaris_tier_2    → ops / SLA / KPI / capacity planning / escalation routing / on-call ops health
  - darla_tier_2      → design system / brand QA / visual consistency / layout critique / Stitch or MCP design generation / brand-aware UI / UX
  - sop_master_tier_2 → SOP / procedure / process document / workflow template / onboarding / training material / process audit / standardization

For single-deliverable intakes (one sub-agent produces the output) use
decision_kind="work_order_brief" and select the assigned_role from the
list above. Do NOT escalate a clear single-deliverable request to
clarification just because the operator was terse — pick the best-
matching role from the nine. Use clarification ONLY when the operator
described work but a structurally required input is missing, and use
workflow_brief ONLY when the intake spans multiple sub-agents (e.g.
"draft + deck + deploy"). A single SOP-style document for one team is
a single deliverable → sop_master_tier_2 work_order_brief, NOT a
workflow_brief.

NEVER invent a new role. If the operator described work but no role fits,
return decision_kind="clarification" with a specific question.

Only include the subobject that matches `decision_kind`.
"""


def render_aiden_output_schema() -> str:
    """Inject the live tool catalog into the output-schema contract.
    Called once per Aiden invocation so new tools registered at runtime
    show up immediately."""
    from runtime.aiden_tools import render_tool_catalog
    return _AIDEN_OUTPUT_SCHEMA_TEMPLATE.replace(
        "{TOOL_CATALOG}", render_tool_catalog()
    )


# Back-compat alias for any caller that still references the constant
# name. Resolves to the rendered schema with current tool catalog.
AIDEN_OUTPUT_SCHEMA = render_aiden_output_schema()


@dataclass(frozen=True)
class AidenWorkOrderBrief:
    assigned_role: str
    content_blocks: dict
    priority: str
    # Loop Eta post-close — template resolver wires these in after Aiden
    # classifies. Matched template_profile_id flows into the WO's
    # requested_outputs jsonb so dispatch_gamma_for_package targets the
    # operator-intended Klear/FFAI template instead of Gamma defaults.
    # When the operator clearly wants a templated artifact but no single
    # template scored high enough, `template_choice_required=True` and
    # `template_choices` carries the candidate list for chat-side pick.
    template_profile_id: Optional[str] = None
    template_profile_key: Optional[str] = None
    template_output_kind: Optional[str] = None
    template_engine: Optional[str] = None
    template_label: Optional[str] = None
    template_match_terms: tuple[str, ...] = ()
    template_choice_required: bool = False
    template_choices: tuple[dict, ...] = ()


@dataclass(frozen=True)
class AidenWorkflowBrief:
    workflow_template_key: str
    step_inputs: dict


@dataclass(frozen=True)
class AidenClarification:
    question: str
    missing_fields: list[str]


@dataclass(frozen=True)
class AidenAssistantReply:
    """CEO-voice conversational response. Mirrors the shape the legacy
    `_shortcut_reply` regex intercepts produced, so the chat UI renders
    Aiden's free-form responses identically. assistant_reply is the
    DEFAULT path for any conversational / exploratory / platform-question
    intake — clarification is reserved for genuine routing ambiguity."""

    headline: str
    message: str
    suggested_requests: list[str]


@dataclass(frozen=True)
class AidenToolCall:
    """Aiden requests one tool execution before composing his final
    answer. The runtime executes the tool against a tenant-scoped
    connection and re-invokes Aiden with the result injected into
    context. After the second turn Aiden returns assistant_reply with
    real data — no hallucinated runtime state."""

    tool_name: str
    args: dict


@dataclass(frozen=True)
class AidenDecision:
    decision_kind: Literal[
        "assistant_reply",
        "tool_call",
        "work_order_brief",
        "workflow_brief",
        "clarification",
    ]
    title: str
    summary: Optional[str]
    assistant_reply: Optional[AidenAssistantReply] = None
    tool_call: Optional[AidenToolCall] = None
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
    if kind not in {
        "assistant_reply",
        "tool_call",
        "work_order_brief",
        "workflow_brief",
        "clarification",
    }:
        raise AidenDecisionMalformed(
            f"decision_kind must be assistant_reply|tool_call|"
            f"work_order_brief|workflow_brief|clarification, got {kind!r}"
        )
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise AidenDecisionMalformed("title missing or non-string")
    summary = data.get("summary") if isinstance(data.get("summary"), str) else None

    ar = None
    tc = None
    wob = None
    wfb = None
    cl = None

    if kind == "assistant_reply":
        sub = data.get("assistant_reply")
        if not isinstance(sub, dict):
            raise AidenDecisionMalformed(
                "decision_kind=assistant_reply but assistant_reply missing"
            )
        headline = sub.get("headline")
        if not isinstance(headline, str) or not headline.strip():
            raise AidenDecisionMalformed("assistant_reply.headline missing")
        message = sub.get("message")
        if not isinstance(message, str) or not message.strip():
            raise AidenDecisionMalformed("assistant_reply.message missing")
        sr = sub.get("suggested_requests", [])
        if not isinstance(sr, list):
            sr = []
        ar = AidenAssistantReply(
            headline=headline.strip(),
            message=message,
            suggested_requests=[str(x) for x in sr if isinstance(x, str)][:5],
        )

    elif kind == "tool_call":
        sub = data.get("tool_call")
        if not isinstance(sub, dict):
            raise AidenDecisionMalformed(
                "decision_kind=tool_call but tool_call missing"
            )
        tn = sub.get("tool_name")
        if not isinstance(tn, str) or not tn.strip():
            raise AidenDecisionMalformed("tool_call.tool_name missing")
        ta = sub.get("args", {})
        if not isinstance(ta, dict):
            ta = {}
        tc = AidenToolCall(tool_name=tn.strip(), args=ta)

    elif kind == "work_order_brief":
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
        assistant_reply=ar,
        tool_call=tc,
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
    memory_block: Optional[str] = None,
) -> AidenDecision:
    """Run Aiden Tier 1 against `intake_text`; return a parsed decision.

    Caller (Submit Order route, Telegram intake handler, Chat-with-
    Aiden route) is responsible for acting on the decision: creating
    the WO, instantiating the workflow_execution, or surfacing the
    clarification question.

    Loop Iota — when `memory_block` is provided, it is prepended to the
    user-message payload (NOT the system prompt) so the operator sees
    canonical facts + chat history + workspace grounding + scratch
    BEFORE their actual intake. Aiden's identity stays in the system
    prompt; tenant memory is user-side context. The block is already
    tenant-validated by `memory.context_builder._validate_tenant_safety`
    — invoke_aiden_tier_1 never inspects or trusts arbitrary content.

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

    # Loop Iota — the user-message payload is memory + intake. Memory
    # already bounded to ~2K tokens by the builder's budget allocator.
    if memory_block:
        user_payload = f"{memory_block}\n\n[OPERATOR INTAKE]\n{intake_text}"
    else:
        user_payload = intake_text

    # Pre-flight budget — uses naive token estimate (chars/4) as a
    # cheap gate; the real per-call usage is logged after the call
    # completes with the provider-reported counts.
    estimate = max(
        128,
        min(
            DEFAULT_PER_CALL_MAX_TOKENS,
            (len(AIDEN_SYSTEM_PROMPT) + len(user_payload)) // 4,
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
            user_message=user_payload,
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
        assistant_reply=decision.assistant_reply,
        tool_call=decision.tool_call,
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

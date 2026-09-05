"""Open-search rubric invariants (Tier 1, Tier 2, memory preamble).

Background — measured, not assumed. Before these rules existed, six
world-knowledge probes ("who is the CEO of X", "what did Y announce",
"top vendors in <year>") produced 0 tool calls out of 6: Aiden answered
from training data or declined for want of a source, while four live
web-search tools sat registered and unused. Three separate instructions
caused it, and all three had to move:

  1. Tier-1 scoped `tool_call` to "CURRENT runtime state" only.
  2. The schema template routed any "business question" to
     assistant_reply by default.
  3. The shared memory GROUNDING RULES said "use ONLY the sources
     below" with no counterpart permitting a tool call to GET a source
     — a one-sided rule, followed one-sidedly.

(3) is shared by Tier 1, Tier 2 and the PM, so it is the load-bearing
one. These are prompt-text assertions: they cannot prove the model
behaves, but they fail loudly if the wording that produced 6/6 is
edited away. Behavioural verification is the probe script in the loop
record.
"""

from __future__ import annotations

from memory.budget import _GROUNDING_RULES_PREAMBLE
from runtime import tier_1_aiden
from runtime.tier_2_subagents import TIER_2_OUTPUT_SCHEMA_BASE


# ── The shared grounding preamble (cause 3) ──────────────────────────


def test_grounding_preamble_still_forbids_fabrication() -> None:
    """The anti-fabrication force must survive the scoping edit. This
    is the rule the scope clause must NOT have weakened."""
    text = _GROUNDING_RULES_PREAMBLE
    assert "Use ONLY the facts" in text
    assert "Do NOT invent or extrapolate" in text


def test_grounding_preamble_permits_tool_acquired_sources() -> None:
    """The closed-world rule must be scoped to THIS block and must say
    a tool may be called to obtain new sources. Without this, a model
    told 'use only the sources below' correctly refuses to search."""
    text = _GROUNDING_RULES_PREAMBLE.lower()
    assert "scope" in text, "grounding rules no longer scope themselves"
    assert "do not forbid" in text or "do not prevent" in text
    assert "tool" in text
    assert "instead of replying" in text or "instead of" in text


def test_grounding_preamble_denies_calling_memory_a_search() -> None:
    """Observed failure: Aiden replied 'I've searched ... but none
    contain' having run no tool. Reading memory is not searching."""
    text = _GROUNDING_RULES_PREAMBLE.lower()
    assert "not a web search" in text
    assert "searched" in text


# ── Tier 1 (cause 1 + 2) ─────────────────────────────────────────────


def test_tier1_tool_call_covers_the_outside_world() -> None:
    prompt = tier_1_aiden.AIDEN_SYSTEM_PROMPT.lower()
    assert "outside world" in prompt
    assert "training data is stale" in prompt


def test_tier1_assistant_reply_excludes_outside_world() -> None:
    """assistant_reply was DEFAULT for everything not runtime-shaped.
    It must now explicitly hand outside-world asks to tool_call."""
    prompt = tier_1_aiden.AIDEN_SYSTEM_PROMPT.lower()
    assert "not for questions about the outside world" in prompt


def test_tier1_forbids_claiming_an_unrun_search() -> None:
    prompt = tier_1_aiden.AIDEN_SYSTEM_PROMPT
    assert "[TOOL RESULT]" in prompt
    assert "searching your memory context is NOT a web search" in prompt


def test_tier1_schema_template_does_not_default_business_questions() -> None:
    """The single most load-bearing line: 'business question' used to
    route to assistant_reply, which is exactly what a prospect-research
    question looks like."""
    schema = tier_1_aiden._AIDEN_OUTPUT_SCHEMA_TEMPLATE.lower()
    assert "is not a default-reply case" in schema
    assert "search it" in schema


def test_tier1_schema_template_gives_search_examples() -> None:
    schema = tier_1_aiden._AIDEN_OUTPUT_SCHEMA_TEMPLATE
    assert "web_search_brave" in schema
    assert "web_search_perplexity" in schema


def test_tier1_decision_union_includes_tool_call_everywhere() -> None:
    """Both JSON schema blocks in the Tier-1 prompt must list
    tool_call. The persona block omitted it while the appended block
    declared it — survivable only because of the BUG-066 SUPERSEDES
    clause, and not worth resting on."""
    prompt = tier_1_aiden.AIDEN_SYSTEM_PROMPT
    schema = tier_1_aiden._AIDEN_OUTPUT_SCHEMA_TEMPLATE
    for block, label in ((prompt, "persona"), (schema, "schema template")):
        for line in block.splitlines():
            if '"decision_kind":' in line and '"assistant_reply"' in line:
                assert '"tool_call"' in line, (
                    f"{label} decision_kind union omits tool_call"
                )


# ── Tier 2 ───────────────────────────────────────────────────────────


def test_tier2_tool_call_covers_the_outside_world() -> None:
    """Sub-agents write client deliverables; a stale external fact in a
    deliverable is worse than in a chat reply."""
    schema = TIER_2_OUTPUT_SCHEMA_BASE.lower()
    assert "outside world" in schema
    assert "web_search_" in schema
    assert "from memory" in schema


def test_tier2_forbids_claiming_an_unrun_search() -> None:
    schema = TIER_2_OUTPUT_SCHEMA_BASE.lower()
    assert "searched" in schema
    assert "unless a tool result" in schema

# ── Scope guard (regression: the fix broke work routing once) ────────


def test_outside_world_rule_does_not_re_route_work_requests() -> None:
    """First cut of the outside-world rule pulled work requests into
    `clarification` — two live-LLM routing smokes went red ("review
    this customer record ... produce an audit finding" came back as
    clarification 3/3). The rule governs ANSWERING; Tier 2 does its own
    research for deliverables. Both prompt surfaces must say so."""
    # Prompt text is hard-wrapped, so a phrase can straddle a newline.
    # Collapse whitespace before matching.
    def flat(text: str) -> str:
        return " ".join(text.lower().split())

    prompt = flat(tier_1_aiden.AIDEN_SYSTEM_PROMPT)
    schema = flat(tier_1_aiden._AIDEN_OUTPUT_SCHEMA_TEMPLATE)
    assert "does not change routing" in prompt
    assert "work_order_brief" in prompt and "workflow_brief" in prompt
    assert "never downgrade a work request to clarification" in prompt
    assert "never re-routes a request to produce" in schema
    assert "never grounds for clarification" in schema

"""BUG-001 regression — PM user_msg must always contain the literal
substring "json" so Groq's `response_format: {"type": "json_object"}`
guard does not reject the request.

The Groq API rejects with HTTP 400 / invalid_request_error if no
request message contains the word "json" when json_object response
format is requested. The PM Tier-1.5 call sets that response_format
on every invocation, so its user_message construction must guarantee
the word is present regardless of which `system_prompt` the
config_resolver returns (which could be a tenant custom prompt, the
PM_SYSTEM_PROMPT module fallback, or the aiden_tier_1 prompt via the
TENANT_DEFAULT_ROLE fallback path).

See `WS024_IWO3[Branch]/03_Orchestration/IWO3_BUG_FIX_LOG_v0.1.0.md`
BUG-001 for full context.
"""

from __future__ import annotations

import inspect
import re

from runtime import tier_1_5_pm


def test_pm_user_msg_construction_contains_json_lead_in() -> None:
    """The source for the PM `_invoke_pm_for_workflow` family must
    contain a lead-in string mentioning JSON before the
    `json.dumps(...)` payload. This is the regression guard for
    BUG-001 — if a future refactor strips the lead-in, this test
    fails before the runtime call hits Groq's validator.

    Matches against the source as-authored: the lead-in uses Python's
    string-literal concatenation across two lines, so the assertion
    pattern matches against a short distinctive prefix that survives
    the line split."""
    source = inspect.getsource(tier_1_5_pm)
    needle = "Respond strictly as a JSON object matching the schema"
    assert needle in source, (
        "PM user_msg lead-in is missing — Groq's json_object guard "
        "will reject the call. See IWO3_BUG_FIX_LOG_v0.1.0 BUG-001."
    )


def test_pm_response_format_remains_json_object() -> None:
    """Sanity check: the response_format default is still json_object.
    If this ever flips, BUG-001's lead-in becomes vestigial and should
    be removed in the same change."""
    source = inspect.getsource(tier_1_5_pm)
    assert re.search(
        r'response_format["\']?\s*,\s*\{["\']type["\']:\s*["\']json_object["\']',
        source,
    ), "PM no longer requests json_object response_format — re-evaluate BUG-001 lead-in"


def test_pm_module_prompt_mentions_json() -> None:
    """The module-level fallback `PM_SYSTEM_PROMPT` must continue to
    mention JSON. This is a separate (and redundant) belt over the
    user_msg lead-in; if both ever silently drop the word, the failure
    mode is the same Groq rejection from BUG-061."""
    assert "JSON" in tier_1_5_pm.PM_SYSTEM_PROMPT or "json" in tier_1_5_pm.PM_SYSTEM_PROMPT


def test_pm_output_schema_split_into_constants() -> None:
    """BUG-065 regression — PM's role description and output-schema
    contract must be separable constants so the runtime can always
    append the schema regardless of which `system_prompt` the
    config_resolver returns. Mirrors the Tier-2 pattern
    (DEFAULT_SYSTEM_PROMPTS[role] + TIER_2_OUTPUT_SCHEMA_BASE)."""
    assert hasattr(tier_1_5_pm, "PM_BASE_ROLE_PROMPT")
    assert hasattr(tier_1_5_pm, "PM_OUTPUT_SCHEMA")
    # The schema must mention the parsed contract shape.
    schema = tier_1_5_pm.PM_OUTPUT_SCHEMA
    assert "step_plan" in schema
    assert "step_key" in schema
    assert "assigned_role" in schema
    # PM_SYSTEM_PROMPT (the historical full default) must be the
    # composition of the two parts so external callers still see the
    # complete contract.
    assert (
        tier_1_5_pm.PM_SYSTEM_PROMPT
        == tier_1_5_pm.PM_BASE_ROLE_PROMPT + tier_1_5_pm.PM_OUTPUT_SCHEMA
    )


def test_pm_runtime_appends_schema_to_tenant_custom_prompt() -> None:
    """BUG-065 regression — the source for `_invoke_pm_for_workflow`
    must always concatenate `PM_OUTPUT_SCHEMA` to whatever role prompt
    it resolved from `cfg.system_prompt`. If a future refactor goes
    back to `cfg.system_prompt or PM_SYSTEM_PROMPT` without appending
    the schema, every tenant with a custom PM prompt that omits the
    schema (Klear's 5650-char PM Alpha prompt is the canonical case)
    will produce LLM output the runtime cannot parse."""
    source = inspect.getsource(tier_1_5_pm)
    assert "PM_OUTPUT_SCHEMA" in source, (
        "PM_OUTPUT_SCHEMA constant disappeared from the source. "
        "See IWO3_BUG_FIX_LOG_v0.1.0 BUG-065."
    )
    # The construction site must compose role + schema. Match against
    # the canonical assignment line (split across two lines in source).
    assert "base_role_prompt + PM_OUTPUT_SCHEMA" in source, (
        "PM runtime no longer appends PM_OUTPUT_SCHEMA to the resolved "
        "role prompt. BUG-065 regression. Tenants with custom prompts "
        "will produce LLM output that fails `_parse_step_plan`."
    )

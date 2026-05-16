"""BUG-068 regression — universal mode-contract enforcement.

This bug class came in three waves:

- BUG-065 (PM): tenant `pm_tier_15.system_prompt` overrode the bundled
  default and the LLM didn't see the strict `step_plan` schema.
- BUG-066 (Aiden): tenant `aiden_tier_1.system_prompt` embedded an
  obsolete IWO2-era OUTPUT FORMAT block and the LLM produced the
  wrong top-level shape.
- BUG-068 (Tier-2 mode contracts, this fix): tenant `darla_tier_2` /
  `paul_tier_2` `system_prompt` was IWO2-ported and didn't describe
  the IWO3 runtime-required metadata fields (Darla brand_attestation
  `metadata.overall`, Paul intelligent_delivery `metadata.outcome`),
  so `_parse_attestation` and `_parse_decision` failed closed.

The universal pattern: structured-output contracts are
runtime-enforced; persona prompts are voice/role guidance only. This
test suite locks the SUPERSEDES clauses + mode-contract constants +
runtime appending behavior so future refactors can't quietly re-bundle
the contracts back into persona prompts.
"""

from __future__ import annotations

import inspect

from runtime import tier_1_5_pm
from runtime import tier_1_aiden
from runtime import tier_2_subagents


# ── Tier-2 base schemas have SUPERSEDES + name obsolete IWO2 fields ──


def test_tier_2_base_schema_supersedes_obsolete_iwo2_format() -> None:
    src = tier_2_subagents.TIER_2_OUTPUT_SCHEMA_BASE
    assert "SUPERSEDES" in src or "supersedes" in src, (
        "Tier-2 base schema no longer declares schema supersession. "
        "BUG-068 regression."
    )
    # Must name obsolete IWO2 shapes by token so the LLM can match.
    for token in ("phase", "decision_kind", "content_envelope"):
        assert token in src, f"Tier-2 schema missing token '{token}'"


def test_tier_2_no_tool_call_schema_supersedes() -> None:
    src = tier_2_subagents.TIER_2_OUTPUT_SCHEMA_NO_TOOL_CALL
    assert "SUPERSEDES" in src or "supersedes" in src, (
        "Tier-2 no-tool-call schema no longer declares supersession. "
        "BUG-068 regression."
    )


# ── PM schema has SUPERSEDES (defensive belt over BUG-065) ──


def test_pm_output_schema_supersedes_obsolete_iwo2_format() -> None:
    src = tier_1_5_pm.PM_OUTPUT_SCHEMA
    assert "SUPERSEDES" in src or "supersedes" in src, (
        "PM_OUTPUT_SCHEMA no longer declares supersession over IWO2-era "
        "evaluation prompts. BUG-068 defensive belt regression."
    )
    assert "step_plan" in src


# ── Tier-2 mode contracts: brand_attestation ──


def test_tier_2_brand_attestation_contract_exists() -> None:
    assert hasattr(tier_2_subagents, "TIER_2_MODE_CONTRACT_BRAND_ATTESTATION")
    src = tier_2_subagents.TIER_2_MODE_CONTRACT_BRAND_ATTESTATION
    # All five Darla metadata fields the runtime parser reads.
    for field in (
        "overall",
        "palette_pass",
        "fonts_pass",
        "voice_pass",
        "asset_pass",
        "notes",
    ):
        assert field in src, (
            f"brand_attestation mode contract missing required field "
            f"'{field}'. BUG-068 regression."
        )
    # The three allowed overall values must all appear by token.
    for verdict in ("pass", "needs_revision", "block"):
        assert verdict in src, (
            f"brand_attestation mode contract missing verdict "
            f"'{verdict}'. BUG-068 regression."
        )


# ── Tier-2 mode contracts: intelligent_delivery ──


def test_tier_2_intelligent_delivery_contract_exists() -> None:
    assert hasattr(tier_2_subagents, "TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY")
    src = tier_2_subagents.TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY
    # All required Paul metadata fields the runtime parser reads.
    for field in (
        "outcome",
        "template_profile_id",
        "adapter_key",
        "fallback_adapter_keys",
        "decision_reason",
    ):
        assert field in src, (
            f"intelligent_delivery mode contract missing required field "
            f"'{field}'. BUG-068 regression."
        )
    # The three allowed outcome values must all appear by token.
    for outcome in ("primary_dispatch", "fallback_dispatch", "blocked"):
        assert outcome in src, (
            f"intelligent_delivery mode contract missing outcome "
            f"'{outcome}'. BUG-068 regression."
        )


# ── Runtime appending behavior (lock against re-bundling regressions) ──


def test_tier_2_invoke_accepts_mode_contract_parameter() -> None:
    """Both `invoke_tier_2` and `_invoke_tier_2_once` must accept
    `mode_contract: str = ""`. If a future refactor drops the
    parameter, mode-specific callers (Darla, Paul) lose the runtime
    enforcement and BUG-068 returns."""
    src = inspect.getsource(tier_2_subagents)
    assert "mode_contract: str = \"\"" in src, (
        "Tier-2 invocation signatures no longer accept `mode_contract`. "
        "BUG-068 regression."
    )
    # The construction site must compose schema + mode_contract.
    assert "composed_schema = schema + (mode_contract or " in src, (
        "Tier-2 runtime no longer appends mode_contract to the base "
        "schema. BUG-068 regression."
    )


def test_darla_runtime_passes_brand_attestation_contract() -> None:
    """`invoke_darla_qa` must always pass the brand_attestation mode
    contract to `invoke_tier_2`. If it stops, Darla's structured
    output requirements get hidden in the persona prompt again and
    `_parse_attestation` fails closed."""
    from runtime import darla_qa
    src = inspect.getsource(darla_qa)
    assert "TIER_2_MODE_CONTRACT_BRAND_ATTESTATION" in src, (
        "darla_qa no longer imports the brand_attestation contract. "
        "BUG-068 regression."
    )
    assert "mode_contract=TIER_2_MODE_CONTRACT_BRAND_ATTESTATION" in src, (
        "darla_qa no longer passes the brand_attestation contract to "
        "invoke_tier_2. BUG-068 regression."
    )


def test_paul_runtime_passes_intelligent_delivery_contract() -> None:
    """Same lock for Paul's intelligent_delivery path."""
    from runtime import paul_delivery
    src = inspect.getsource(paul_delivery)
    assert "TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY" in src, (
        "paul_delivery no longer imports the intelligent_delivery "
        "contract. BUG-068 regression."
    )
    assert "mode_contract=TIER_2_MODE_CONTRACT_INTELLIGENT_DELIVERY" in src, (
        "paul_delivery no longer passes the intelligent_delivery "
        "contract to invoke_tier_2. BUG-068 regression."
    )


# ── Three Tier-1 / Tier-1.5 SUPERSEDES still in place ──


def test_aiden_schema_supersedes_still_active() -> None:
    """Lock — BUG-066's Aiden SUPERSEDES clause must remain. The
    universal fix builds on the same pattern; if Aiden's clause
    regresses, the whole class returns at Tier-1."""
    src = tier_1_aiden._AIDEN_OUTPUT_SCHEMA_TEMPLATE
    assert "SUPERSEDES" in src or "supersedes" in src
    assert "phase" in src  # the obsolete IWO2 field named by token

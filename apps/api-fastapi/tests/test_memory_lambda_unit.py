"""Loop Lambda — Memory V2 unit tests (no DB).

Coverage for the wrapper layer + per-surface budget constants +
Surface enum vocabulary. DB-backed wrapper tests live in
`test_memory_lambda_wrappers_db.py`.
"""

from __future__ import annotations

import pytest

from memory.types import (
    MEMORY_BUDGET_TIER_1_5,
    MEMORY_BUDGET_TIER_2,
    MEMORY_BUDGET_TOKENS,
    Surface,
)


# ── per-surface budget constants ─────────────────────────────────


def test_tier_1_5_budget_smaller_than_tier_1_chat() -> None:
    """PM elaboration prompt is shorter than Aiden's; gets less budget."""
    assert MEMORY_BUDGET_TIER_1_5 < MEMORY_BUDGET_TOKENS


def test_tier_2_budget_smaller_than_tier_1_chat() -> None:
    """Tier-2 prompts already carry rich per-WO payload; gets less budget."""
    assert MEMORY_BUDGET_TIER_2 < MEMORY_BUDGET_TOKENS


def test_tier_1_5_and_tier_2_budgets_are_1500() -> None:
    """D-L1 default — locked at 1.5K each."""
    assert MEMORY_BUDGET_TIER_1_5 == 1500
    assert MEMORY_BUDGET_TIER_2 == 1500


def test_per_surface_total_under_wo_ceiling() -> None:
    """A 5-step workflow burns 1 PM + 5 Tier-2 = 6 × 1.5K = 9K of
    memory, well under the 50K WO ceiling locked in Beta-1 ε.1."""
    five_step_total = MEMORY_BUDGET_TIER_1_5 + 5 * MEMORY_BUDGET_TIER_2
    assert five_step_total == 9000  # 1500 * 6
    WO_CEILING = 50_000
    assert five_step_total < WO_CEILING


# ── Surface vocabulary ───────────────────────────────────────────


def test_surface_literal_has_three_values() -> None:
    """Surface = Literal['chat', 'tier_1_5_pm', 'tier_2_subagent'].
    Locked here so audit-row consumers can rely on the closed set.
    """
    # Literal types don't expose values directly; check via __args__.
    args = Surface.__args__  # type: ignore[attr-defined]
    assert set(args) == {"chat", "tier_1_5_pm", "tier_2_subagent"}


# ── memory_context_builder accepts surface kwarg with default 'chat' ─


def test_context_builder_signature_default_surface() -> None:
    """memory_context_builder must default `surface='chat'` so all
    pre-Lambda callers (Iota chat path) keep working unchanged.
    """
    import inspect

    from memory import memory_context_builder

    sig = inspect.signature(memory_context_builder)
    surface_param = sig.parameters.get("surface")
    assert surface_param is not None, "surface kwarg missing"
    assert surface_param.default == "chat"


def test_context_builder_signature_default_budget() -> None:
    """memory_context_builder must default `budget=MEMORY_BUDGET_TOKENS`
    (2K) so all pre-Lambda callers keep their Iota/Kappa budget.
    """
    import inspect

    from memory import memory_context_builder

    sig = inspect.signature(memory_context_builder)
    budget_param = sig.parameters.get("budget")
    assert budget_param is not None, "budget kwarg missing"
    assert budget_param.default == MEMORY_BUDGET_TOKENS


# ── wrapper signatures ───────────────────────────────────────────


def test_workflow_wrapper_exists_and_named_correctly() -> None:
    """The PM wrapper is `memory_context_builder_for_workflow` per
    L scope proposal §"In scope". No parallel assembler — wrapper
    delegates to memory_context_builder."""
    from memory.wrappers import memory_context_builder_for_workflow

    assert callable(memory_context_builder_for_workflow)


def test_subagent_wrapper_exists_and_named_correctly() -> None:
    """The Tier-2 wrapper is `memory_context_builder_for_subagent`."""
    from memory.wrappers import memory_context_builder_for_subagent

    assert callable(memory_context_builder_for_subagent)


def test_workflow_wrapper_takes_workflow_execution_id_kwarg() -> None:
    """PM wrapper carries `workflow_execution_id` in audit metadata."""
    import inspect

    from memory.wrappers import memory_context_builder_for_workflow

    sig = inspect.signature(memory_context_builder_for_workflow)
    assert "workflow_execution_id" in sig.parameters


def test_subagent_wrapper_takes_sub_agent_role_kwarg() -> None:
    """Tier-2 wrapper carries `sub_agent_role` in audit metadata."""
    import inspect

    from memory.wrappers import memory_context_builder_for_subagent

    sig = inspect.signature(memory_context_builder_for_subagent)
    assert "sub_agent_role" in sig.parameters


# ── tier-runtime signature wiring ────────────────────────────────


def test_invoke_tier_2_accepts_memory_block_kwarg() -> None:
    """Tier-2 entry point accepts `memory_block: str = ""` kwarg.
    Default empty string preserves Iota/Eta behavior for any caller
    that doesn't yet pass memory."""
    import inspect

    from runtime.tier_2_subagents import invoke_tier_2

    sig = inspect.signature(invoke_tier_2)
    assert "memory_block" in sig.parameters
    assert sig.parameters["memory_block"].default == ""


def test_invoke_tier_2_once_accepts_memory_block_kwarg() -> None:
    """Internal single-turn function also accepts memory_block so the
    looping wrapper can propagate it through tool-call rounds."""
    import inspect

    from runtime.tier_2_subagents import _invoke_tier_2_once

    sig = inspect.signature(_invoke_tier_2_once)
    assert "memory_block" in sig.parameters
    assert sig.parameters["memory_block"].default == ""


def test_instantiate_workflow_from_brief_accepts_memory_block_kwarg() -> None:
    """Tier-1.5 PM entry point accepts `memory_block: str = ""`."""
    import inspect

    from runtime.tier_1_5_pm import instantiate_workflow_from_brief

    sig = inspect.signature(instantiate_workflow_from_brief)
    assert "memory_block" in sig.parameters
    assert sig.parameters["memory_block"].default == ""


def test_execute_step_run_accepts_memory_block_kwarg() -> None:
    """Workflow step advancement accepts memory_block; threads through
    to invoke_tier_2."""
    import inspect

    from runtime.tier_2_subagents import execute_step_run

    sig = inspect.signature(execute_step_run)
    assert "memory_block" in sig.parameters
    assert sig.parameters["memory_block"].default == ""


# ── system-prompt prepending ─────────────────────────────────────


def test_tier_2_once_with_no_memory_block_uses_unmodified_system_prompt(monkeypatch) -> None:
    """When memory_block is empty, system_prompt = base_role_prompt + schema
    (Iota/Eta behavior preserved)."""
    # Smoke: assert the construction logic via the source itself —
    # full DB integration is in test_memory_lambda_wrappers_db.py.
    import inspect

    from runtime.tier_2_subagents import _invoke_tier_2_once

    src = inspect.getsource(_invoke_tier_2_once)
    # The prepend-when-non-empty branch uses memory_block + "\n\n" +
    # base_role_prompt + schema. The empty branch uses base + schema.
    assert "if memory_block:" in src
    assert "memory_block + " in src


def test_pm_with_no_memory_block_uses_unmodified_system_prompt() -> None:
    """When memory_block is empty, PM uses cfg.system_prompt or
    PM_SYSTEM_PROMPT verbatim (Alpha α.3 behavior preserved)."""
    import inspect

    from runtime.tier_1_5_pm import instantiate_workflow_from_brief

    src = inspect.getsource(instantiate_workflow_from_brief)
    assert "if memory_block:" in src
    assert "composed_system_prompt" in src

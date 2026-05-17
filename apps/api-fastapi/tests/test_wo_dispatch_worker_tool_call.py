"""WO auto-dispatch worker — tool_call decision-kind regression tests.

Per the operator brief (2026-05-17): the worker previously dropped
Tier-1 `tool_call` decisions into the trailing `decision_kind_unknown`
handler. The fix mirrors the chat-route tool_call loop pattern from
`routes/aiden.py:408-464` inside the WO auto-dispatch path:

    decision = aiden_tier_1(intake)
    if decision.decision_kind == "tool_call":
        result = execute_tool(...)
        decision = aiden_tier_1(intake + result)  # 1-round-trip cap
    # ... existing handlers (clarification / assistant_reply /
    # work_order_brief / workflow_brief / decision_kind_unknown)
    # catch whatever decision is now.

Tests in this file cover the four scenarios named in the brief:
  1. tool_call → work_order_brief follow-up → package path proceeds
  2. tool_call → workflow_brief  follow-up → workflow path proceeds
  3. truly unknown decision kind (second tool_call hits the
     implicit 1-round-trip cap) → decision_kind_unknown audited
  4. tool failure path is explicit and non-silent

Skips when IWO3_DATABASE_URL is unset (mirrors the rest of the
api-fastapi integration suite).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


# ── Test scaffolding ────────────────────────────────────────────────


@dataclass
class _SequencedTier1:
    """Stub for invoke_aiden_tier_1 that returns pre-seeded decisions
    in order. The worker invokes Tier-1 once initially + once on the
    tool_call followup. Tests provide a 1- or 2-element sequence."""

    decisions: list[Any]
    calls: list[dict] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.calls = []

    async def __call__(self, conn, **kwargs):
        self.calls.append(kwargs)
        if not self.decisions:
            raise AssertionError(
                "_SequencedTier1: ran out of pre-seeded decisions"
            )
        return self.decisions.pop(0)


async def _seed_pending_wo(db_url: str, client_id: str) -> str:
    """Seed a fresh pending WO via a superuser connection (bypasses
    RLS). Returns the WO id."""
    raw = await asyncpg.connect(db_url)
    try:
        wo_id = await raw.fetchval(
            """
            INSERT INTO work_orders
              (client_id, title, description, type, priority, status,
               submitted_by_user_id)
            VALUES ($1::uuid, $2, $3, 'content_brief', 'medium',
                    'pending', $4)
            RETURNING id::text
            """,
            client_id,
            "tool_call worker regression — synthetic seed",
            "test scaffold",
            KLEAR_OPERATOR,
        )
    finally:
        await raw.close()
    return wo_id


async def _count_audit(
    db_url: str, *, wo_id: str, action: str, stage: str | None = None
) -> int:
    """Count audit rows for a WO with optional metadata.stage match."""
    raw = await asyncpg.connect(db_url)
    try:
        if stage is None:
            row = await raw.fetchrow(
                """
                SELECT count(*)::int AS n
                FROM action_audit_log
                WHERE target_type = 'work_order'
                  AND target_id = $1
                  AND action = $2
                """,
                wo_id,
                action,
            )
        else:
            row = await raw.fetchrow(
                """
                SELECT count(*)::int AS n
                FROM action_audit_log
                WHERE target_type = 'work_order'
                  AND target_id = $1
                  AND action = $2
                  AND metadata @> jsonb_build_object('stage', $3::text)
                """,
                wo_id,
                action,
                stage,
            )
    finally:
        await raw.close()
    return int(row["n"])


def _build_tool_call_decision(tool_name: str = "system_health_check") -> Any:
    from runtime.tier_1_aiden import AidenDecision, AidenToolCall

    return AidenDecision(
        decision_kind="tool_call",
        title=tool_name,
        summary=None,
        tool_call=AidenToolCall(tool_name=tool_name, args={}),
    )


def _build_work_order_brief_decision() -> Any:
    from runtime.tier_1_aiden import AidenDecision, AidenWorkOrderBrief

    return AidenDecision(
        decision_kind="work_order_brief",
        title="Synthetic post-tool brief",
        summary=None,
        work_order_brief=AidenWorkOrderBrief(
            assigned_role="mark",
            content_blocks={"text": "stub"},
            priority="medium",
        ),
    )


def _build_workflow_brief_decision() -> Any:
    from runtime.tier_1_aiden import AidenDecision, AidenWorkflowBrief

    return AidenDecision(
        decision_kind="workflow_brief",
        title="Synthetic post-tool workflow",
        summary=None,
        workflow_brief=AidenWorkflowBrief(
            workflow_template_key="content_brief_v1",
            step_inputs={},
        ),
    )


# ── Test scenarios ─────────────────────────────────────────────────


@iwo3_db
def test_tool_call_followup_work_order_brief_proceeds_to_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 1: tool_call → tool executes → followup returns
    work_order_brief → package path proceeds."""

    async def run() -> None:
        db_url = os.environ["IWO3_DATABASE_URL"]
        wo_id = await _seed_pending_wo(db_url, KLEAR_CLIENT)

        # Tier-1 sequence: first tool_call, then work_order_brief.
        from runtime import tier_1_aiden as t1
        from runtime import aiden_tools
        from runtime import tier_2_subagents
        from memory import wrappers as memw

        stub = _SequencedTier1([
            _build_tool_call_decision("system_health_check"),
            _build_work_order_brief_decision(),
        ])
        monkeypatch.setattr(t1, "invoke_aiden_tier_1", stub)

        async def fake_execute_tool(conn, **kwargs):
            return {"system_health": "ok", "version": "test"}

        monkeypatch.setattr(aiden_tools, "execute_tool", fake_execute_tool)

        # Avoid touching real LLMs / heavy paths. invoke_tier_2 returns
        # a minimal envelope shape; produce_output_package returns a
        # synthetic id so we don't depend on real adapter routing.
        @dataclass(frozen=True)
        class _StubEnvelope:
            output_kind: str = "generic"

        async def fake_tier_2(conn, **kwargs):
            return _StubEnvelope()

        monkeypatch.setattr(tier_2_subagents, "invoke_tier_2", fake_tier_2)

        synthetic_pkg_id = str(uuid.uuid4())

        async def fake_produce_pkg(conn, **kwargs):
            return synthetic_pkg_id

        monkeypatch.setattr(
            tier_2_subagents, "produce_output_package", fake_produce_pkg
        )

        @dataclass(frozen=True)
        class _StubBundle:
            block: str | None = None

        async def fake_subagent_bundle(conn, **kwargs):
            return _StubBundle()

        monkeypatch.setattr(
            memw, "memory_context_builder_for_subagent", fake_subagent_bundle
        )

        # Run the worker against the live pool.
        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        try:
            from workers.wo_dispatch_worker import dispatch_one_wo

            result = await dispatch_one_wo(pool, wo_id, KLEAR_CLIENT)
        finally:
            await pool.close()

        assert result == "work_order_brief", f"expected work_order_brief; got {result}"
        # Tier-1 invoked twice (initial + followup).
        assert len(stub.calls) == 2, f"expected 2 tier_1 calls; got {len(stub.calls)}"
        # Audit: auto_dispatch_succeeded fired with decision_kind=work_order_brief.
        n_ok = await _count_audit(
            db_url,
            wo_id=wo_id,
            action="work_order.auto_dispatch_succeeded",
        )
        assert n_ok >= 1, f"expected ≥1 success audit; got {n_ok}"
        # Audit: NO decision_kind_unknown failure.
        n_unknown = await _count_audit(
            db_url,
            wo_id=wo_id,
            action="work_order.auto_dispatch_failed",
            stage="decision_kind_unknown",
        )
        assert n_unknown == 0, f"unexpected decision_kind_unknown audit; got {n_unknown}"
        # BUG-071 hot-fix: non-gamma package auto-completes the WO.
        # Generic stub envelope → WO must end in `completed`.
        raw = await asyncpg.connect(db_url)
        try:
            final_status = await raw.fetchval(
                "SELECT status FROM work_orders WHERE id=$1",
                wo_id,
            )
        finally:
            await raw.close()
        assert final_status == "completed", (
            f"BUG-071: generic-kind package must auto-complete WO; "
            f"got status={final_status}"
        )

    asyncio.run(run())


@iwo3_db
def test_gamma_kind_does_not_auto_complete_wo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-071 hot-fix complement: gamma_* output_kinds must NOT
    auto-complete the WO from the worker. gamma_* completion is
    driven by the poll_worker when the Gamma handoff lands. This
    test seeds a fresh WO, mocks Aiden to return work_order_brief
    directly (no tool_call to keep it focused), uses a gamma_pptx
    stub envelope, and asserts the WO stays in `processing`."""

    async def run() -> None:
        db_url = os.environ["IWO3_DATABASE_URL"]
        wo_id = await _seed_pending_wo(db_url, KLEAR_CLIENT)

        from runtime import tier_1_aiden as t1
        from runtime import tier_2_subagents
        from memory import wrappers as memw
        from adapter import dispatch as adapter_dispatch

        stub = _SequencedTier1([_build_work_order_brief_decision()])
        monkeypatch.setattr(t1, "invoke_aiden_tier_1", stub)

        @dataclass(frozen=True)
        class _GammaEnvelope:
            output_kind: str = "gamma_pptx"

        async def fake_tier_2(conn, **kwargs):
            return _GammaEnvelope()

        monkeypatch.setattr(tier_2_subagents, "invoke_tier_2", fake_tier_2)

        synthetic_pkg_id = str(uuid.uuid4())

        async def fake_produce_pkg(conn, **kwargs):
            return synthetic_pkg_id

        monkeypatch.setattr(
            tier_2_subagents, "produce_output_package", fake_produce_pkg
        )

        @dataclass(frozen=True)
        class _StubBundle:
            block: str | None = None

        async def fake_subagent_bundle(conn, **kwargs):
            return _StubBundle()

        monkeypatch.setattr(
            memw, "memory_context_builder_for_subagent", fake_subagent_bundle
        )

        # gamma_* triggers a Gamma handoff attempt; stub it cleanly
        # so the worker doesn't try to hit a real Gamma instance.
        @dataclass(frozen=True)
        class _StubHandoff:
            handoff_id: str = str(uuid.uuid4())

        async def fake_gamma(conn, **kwargs):
            return _StubHandoff()

        monkeypatch.setattr(
            adapter_dispatch, "dispatch_gamma_for_package", fake_gamma
        )

        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        try:
            from workers.wo_dispatch_worker import dispatch_one_wo

            result = await dispatch_one_wo(pool, wo_id, KLEAR_CLIENT)
        finally:
            await pool.close()

        assert result == "work_order_brief"
        # WO must NOT have auto-completed — gamma_* completion is the
        # poll_worker's job.
        raw = await asyncpg.connect(db_url)
        try:
            final_status = await raw.fetchval(
                "SELECT status FROM work_orders WHERE id=$1",
                wo_id,
            )
        finally:
            await raw.close()
        assert final_status == "processing", (
            f"BUG-071: gamma_* must NOT auto-complete WO from the "
            f"worker; got status={final_status} (expected processing)"
        )

    asyncio.run(run())


@iwo3_db
def test_tool_call_followup_workflow_brief_proceeds_to_pm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 2: tool_call → tool executes → followup returns
    workflow_brief → workflow path proceeds."""

    async def run() -> None:
        db_url = os.environ["IWO3_DATABASE_URL"]
        wo_id = await _seed_pending_wo(db_url, KLEAR_CLIENT)

        from runtime import tier_1_aiden as t1
        from runtime import aiden_tools
        from runtime import tier_1_5_pm
        from memory import wrappers as memw

        stub = _SequencedTier1([
            _build_tool_call_decision("list_active_work_orders"),
            _build_workflow_brief_decision(),
        ])
        monkeypatch.setattr(t1, "invoke_aiden_tier_1", stub)

        async def fake_execute_tool(conn, **kwargs):
            return {"work_orders": []}

        monkeypatch.setattr(aiden_tools, "execute_tool", fake_execute_tool)

        @dataclass(frozen=True)
        class _StubInst:
            workflow_execution_id: str = str(uuid.uuid4())
            step_run_ids: tuple = ()

        async def fake_instantiate(conn, **kwargs):
            return _StubInst()

        monkeypatch.setattr(
            tier_1_5_pm, "instantiate_workflow_from_brief", fake_instantiate
        )

        @dataclass(frozen=True)
        class _StubBundle:
            block: str | None = None

        async def fake_wf_bundle(conn, **kwargs):
            return _StubBundle()

        monkeypatch.setattr(
            memw, "memory_context_builder_for_workflow", fake_wf_bundle
        )

        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        try:
            from workers.wo_dispatch_worker import dispatch_one_wo

            result = await dispatch_one_wo(pool, wo_id, KLEAR_CLIENT)
        finally:
            await pool.close()

        assert result == "workflow_brief", f"expected workflow_brief; got {result}"
        assert len(stub.calls) == 2
        n_ok = await _count_audit(
            db_url,
            wo_id=wo_id,
            action="work_order.auto_dispatch_succeeded",
        )
        assert n_ok >= 1
        n_unknown = await _count_audit(
            db_url,
            wo_id=wo_id,
            action="work_order.auto_dispatch_failed",
            stage="decision_kind_unknown",
        )
        assert n_unknown == 0

    asyncio.run(run())


@iwo3_db
def test_repeated_tool_call_hits_decision_kind_unknown_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 3: 1-round-trip cap. If Tier-1 returns tool_call again
    after the tool execution + followup, the trailing
    decision_kind_unknown handler catches it. This is the cap-
    enforcement path; tool_call is NOT supported twice in one WO
    dispatch attempt."""

    async def run() -> None:
        db_url = os.environ["IWO3_DATABASE_URL"]
        wo_id = await _seed_pending_wo(db_url, KLEAR_CLIENT)

        from runtime import tier_1_aiden as t1
        from runtime import aiden_tools

        # Both invocations return tool_call. The first one's tool
        # executes; the followup returns tool_call again; the worker
        # has no second-round handler, so decision_kind_unknown fires.
        stub = _SequencedTier1([
            _build_tool_call_decision("first"),
            _build_tool_call_decision("second"),  # cap violation
        ])
        monkeypatch.setattr(t1, "invoke_aiden_tier_1", stub)

        async def fake_execute_tool(conn, **kwargs):
            return {"ok": True}

        monkeypatch.setattr(aiden_tools, "execute_tool", fake_execute_tool)

        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        try:
            from workers.wo_dispatch_worker import dispatch_one_wo

            result = await dispatch_one_wo(pool, wo_id, KLEAR_CLIENT)
        finally:
            await pool.close()

        assert result == "decision_kind_unknown", (
            f"expected decision_kind_unknown (1-round-trip cap); got {result}"
        )
        assert len(stub.calls) == 2
        # Audit confirms the existing failure path fires.
        n_unknown = await _count_audit(
            db_url,
            wo_id=wo_id,
            action="work_order.auto_dispatch_failed",
            stage="decision_kind_unknown",
        )
        assert n_unknown == 1, (
            f"expected exactly 1 decision_kind_unknown audit; got {n_unknown}"
        )

    asyncio.run(run())


@iwo3_db
def test_tool_call_tool_failure_audits_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 4: tool failure path is explicit and non-silent.
    execute_tool raises ToolNotFoundError → worker audits
    auto_dispatch_failed with stage=tool_call and returns 'tool_failed'.
    Tier-1 is NOT re-invoked because the tool didn't produce a result."""

    async def run() -> None:
        db_url = os.environ["IWO3_DATABASE_URL"]
        wo_id = await _seed_pending_wo(db_url, KLEAR_CLIENT)

        from runtime import tier_1_aiden as t1
        from runtime import aiden_tools

        stub = _SequencedTier1([_build_tool_call_decision("bogus_tool")])
        monkeypatch.setattr(t1, "invoke_aiden_tier_1", stub)

        async def fake_execute_tool(conn, **kwargs):
            raise aiden_tools.ToolNotFoundError("bogus_tool not registered")

        monkeypatch.setattr(aiden_tools, "execute_tool", fake_execute_tool)

        pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
        try:
            from workers.wo_dispatch_worker import dispatch_one_wo

            result = await dispatch_one_wo(pool, wo_id, KLEAR_CLIENT)
        finally:
            await pool.close()

        assert result == "tool_failed", f"expected tool_failed; got {result}"
        # Tier-1 invoked exactly ONCE (no followup because the tool failed).
        assert len(stub.calls) == 1, (
            f"tier_1 must not be re-invoked when the tool itself fails; "
            f"got {len(stub.calls)} calls"
        )
        # Audit row carries the explicit tool_call stage.
        n_failed = await _count_audit(
            db_url,
            wo_id=wo_id,
            action="work_order.auto_dispatch_failed",
            stage="tool_call",
        )
        assert n_failed == 1, (
            f"expected exactly 1 tool_call-stage failure audit; got {n_failed}"
        )
        # NO decision_kind_unknown — the failure is explicit at the tool layer.
        n_unknown = await _count_audit(
            db_url,
            wo_id=wo_id,
            action="work_order.auto_dispatch_failed",
            stage="decision_kind_unknown",
        )
        assert n_unknown == 0

    asyncio.run(run())

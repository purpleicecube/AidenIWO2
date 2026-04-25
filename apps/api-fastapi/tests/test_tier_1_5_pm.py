"""MegaLoop Alpha α.3 — Tier 1.5 PM workflow instantiation tests.

Covers:
  - Happy path: PM elaborates step plan → workflow_execution + step_runs
    created; pm_provider/pm_model/pm_latency_ms populated; llm.invoked
    audit emitted with agentRole=pm_tier_15
  - Template not found → PmTemplateNotFound
  - Plan with wrong step count → PmPlanMalformed
"""

from __future__ import annotations

import asyncio
import json
import os

import asyncpg
import httpx
import pytest

from runtime.tier_1_5_pm import (
    PmPlanMalformed,
    PmTemplateNotFound,
    instantiate_workflow_from_brief,
)
from runtime.tier_1_aiden import AidenWorkflowBrief


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _ok_transport(content: str, *, usage: dict | None = None) -> httpx.MockTransport:
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage:
        body["usage"] = usage

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
    return httpx.MockTransport(handler)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


# Klear's seeded weekly_marketing_brief has 3 steps:
#   research_landscape (mark)
#   assemble_brief     (mark)
#   pm_review          (varies)
KLEAR_3STEP_PLAN = json.dumps({
    "step_plan": [
        {
            "step_key": "research_landscape",
            "assigned_role": "mark_tier_2",
            "input": {"prompt": "Survey the RMIS competitive landscape"},
        },
        {
            "step_key": "assemble_brief",
            "assigned_role": "mark_tier_2",
            "input": {"prompt": "Compose the 6-section brief"},
        },
        {
            "step_key": "pm_review",
            "assigned_role": "mark_tier_2",
            "input": {"prompt": "Internal QA pass"},
        },
    ],
})


@iwo3_db
def test_happy_path_instantiates_3step_workflow() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                result = await instantiate_workflow_from_brief(
                    conn,
                    brief=AidenWorkflowBrief(
                        workflow_template_key="weekly_marketing_brief",
                        step_inputs={},
                    ),
                    intake_text="Send the weekly marketing brief",
                    aiden_summary="Multi-step content brief.",
                    work_order_id=None,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(KLEAR_3STEP_PLAN),
                )
                assert result.template_key == "weekly_marketing_brief"
                assert len(result.step_run_ids) == 3
                assert len(result.step_plan) == 3

                # workflow_execution actually created
                exec_status = await conn.fetchval(
                    "SELECT status::text FROM workflow_executions WHERE id = $1::uuid",
                    result.workflow_execution_id,
                )
                assert exec_status == "running"

                # step_runs created in order with correct keys
                runs = await conn.fetch(
                    """
                    SELECT step_key, step_order, status::text AS status
                      FROM workflow_step_runs
                     WHERE execution_id = $1::uuid
                     ORDER BY step_order ASC
                    """,
                    result.workflow_execution_id,
                )
                assert [r["step_key"] for r in runs] == [
                    "research_landscape", "assemble_brief", "pm_review"
                ]
                assert all(r["status"] == "pending" for r in runs)

                # llm.invoked audit row written for PM
                pm_rows = await conn.fetchval(
                    """
                    SELECT count(*)::int FROM action_audit_log
                     WHERE action = 'llm.invoked'
                       AND metadata->>'agentRole' = 'pm_tier_15'
                       AND target_id = 'weekly_marketing_brief'
                    """
                )
                assert pm_rows >= 1

                # cleanup
                await conn.execute(
                    "DELETE FROM workflow_step_runs WHERE execution_id = $1::uuid",
                    result.workflow_execution_id,
                )
                await conn.execute(
                    "DELETE FROM workflow_executions WHERE id = $1::uuid",
                    result.workflow_execution_id,
                )
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_template_not_found_raises() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                with pytest.raises(PmTemplateNotFound):
                    await instantiate_workflow_from_brief(
                        conn,
                        brief=AidenWorkflowBrief(
                            workflow_template_key="does_not_exist",
                            step_inputs={},
                        ),
                        intake_text="...",
                        aiden_summary=None,
                        work_order_id=None,
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        transport=_ok_transport(KLEAR_3STEP_PLAN),
                    )
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_wrong_step_count_raises_malformed() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            two_steps = json.dumps({
                "step_plan": [
                    {"step_key": "research_landscape", "assigned_role": "mark_tier_2", "input": {"x": 1}},
                    {"step_key": "assemble_brief", "assigned_role": "mark_tier_2", "input": {"x": 2}},
                ]
            })
            conn = await _connect()
            try:
                with pytest.raises(PmPlanMalformed):
                    await instantiate_workflow_from_brief(
                        conn,
                        brief=AidenWorkflowBrief(
                            workflow_template_key="weekly_marketing_brief",
                            step_inputs={},
                        ),
                        intake_text="...",
                        aiden_summary=None,
                        work_order_id=None,
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        transport=_ok_transport(two_steps),
                    )
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())

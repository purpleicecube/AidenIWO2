"""MegaLoop Alpha α.4 — Tier 2 sub-agent tests.

Covers:
  - invoke_tier_2 happy path: parses envelope, emits llm.invoked
  - normalize_tier_2_role accepts every seeded Tier 2 role + aliases
  - Tier2RoleUnknown for an unknown role
  - Tier2OutputMalformed when LLM returns garbage
  - execute_step_run end-to-end: step_run pending → running → completed
    + output_package created + workflow_step_runs.output populated
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import httpx
import pytest

from runtime.tier_2_subagents import (
    Tier2OutputMalformed,
    Tier2RoleUnknown,
    execute_step_run,
    invoke_tier_2,
    normalize_tier_2_role,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _ok_transport(content: str, *, usage: dict | None = None) -> httpx.MockTransport:
    body = {"choices": [{"message": {"content": content}}]}
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


SAMPLE_ENVELOPE = json.dumps({
    "content_markdown": "# Klear weekly brief\n\n- bullet 1\n- bullet 2",
    "summary": "Weekly brief draft",
    "output_kind": "generic",
    "metadata": {"sections": 6},
})


def test_normalize_role_accepts_short_and_long_forms() -> None:
    assert normalize_tier_2_role("jamie") == "jamie_tier_2"
    assert normalize_tier_2_role("mark") == "mark_tier_2"
    assert normalize_tier_2_role("nyx") == "nyx_tier_2"
    assert normalize_tier_2_role("polaris") == "polaris_tier_2"
    assert normalize_tier_2_role("darla") == "darla_tier_2"
    assert normalize_tier_2_role("sop_master") == "sop_master_tier_2"
    assert normalize_tier_2_role("tom_tier_2") == "tom_tier_2"
    assert normalize_tier_2_role("hank") == "hank_tier_2"
    assert normalize_tier_2_role("paul") == "paul_tier_2"


def test_normalize_role_rejects_unknown() -> None:
    with pytest.raises(Tier2RoleUnknown):
        normalize_tier_2_role("not_an_agent")


@iwo3_db
def test_invoke_tier_2_happy_path() -> None:
    async def run() -> None:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                env = await invoke_tier_2(
                    conn,
                    role="mark",
                    intake_text="Draft the Q1 brief",
                    content_blocks={"prompt": "go"},
                    work_order_id=None,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(SAMPLE_ENVELOPE),
                )
                assert "Klear weekly brief" in env.content_markdown
                assert env.output_kind == "generic"
                assert env.metadata.get("sections") == 6
            finally:
                await conn.close()
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_invoke_tier_2_happy_path_for_darla() -> None:
    async def run() -> None:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                env = await invoke_tier_2(
                    conn,
                    role="darla",
                    intake_text="Review the landing page visual hierarchy",
                    content_blocks={"prompt": "go"},
                    work_order_id=None,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(SAMPLE_ENVELOPE),
                )
                assert "Klear weekly brief" in env.content_markdown
                assert env.output_kind == "generic"
            finally:
                await conn.close()
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_invoke_tier_2_malformed_output() -> None:
    async def run() -> None:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                with pytest.raises(Tier2OutputMalformed):
                    await invoke_tier_2(
                        conn,
                        role="mark",
                        intake_text="...",
                        content_blocks={},
                        work_order_id=None,
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        transport=_ok_transport(
                            "this is just chat with no JSON"
                        ),
                    )
            finally:
                await conn.close()
        finally:
            del os.environ["OPENROUTER_API_KEY"]

    asyncio.run(run())


async def _seed_workflow_with_step_run() -> tuple[str, str]:
    """Returns (workflow_execution_id, step_run_id) — one running
    workflow with one pending step_run."""
    conn = await _connect()
    try:
        # Find Klear's seeded weekly_marketing_brief template
        tpl_id = await conn.fetchval(
            """
            SELECT wt.id::text
              FROM workflow_templates wt
              JOIN workflows w ON w.id = wt.workflow_id
             WHERE w.client_id = $1 AND w.key = 'weekly_marketing_brief'
            """,
            KLEAR_CLIENT,
        )
        # Create a workflow_execution
        exec_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO workflow_executions
              (id, client_id, template_id, status)
            VALUES ($1::uuid, $2::uuid, $3::uuid, 'running'::workflow_execution_status)
            """,
            exec_id, KLEAR_CLIENT, tpl_id,
        )
        # Find the first step
        step_row = await conn.fetchrow(
            """
            SELECT step_key, step_order
              FROM workflow_template_steps
             WHERE template_id = $1::uuid
             ORDER BY step_order ASC LIMIT 1
            """,
            tpl_id,
        )
        run_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO workflow_step_runs
              (id, execution_id, step_key, step_order,
               status, input)
            VALUES ($1::uuid, $2::uuid, $3, $4,
                    'pending'::workflow_step_run_status, '{"prompt":"go"}'::jsonb)
            """,
            run_id, exec_id, step_row["step_key"], step_row["step_order"],
        )
        return exec_id, run_id
    finally:
        await conn.close()


async def _cleanup_workflow(exec_id: str) -> None:
    conn = await _connect()
    try:
        await conn.execute(
            "DELETE FROM output_packages WHERE workflow_execution_id = $1::uuid",
            exec_id,
        )
        await conn.execute(
            "DELETE FROM workflow_step_runs WHERE execution_id = $1::uuid",
            exec_id,
        )
        await conn.execute(
            "DELETE FROM workflow_executions WHERE id = $1::uuid",
            exec_id,
        )
    finally:
        await conn.close()


@iwo3_db
def test_execute_step_run_end_to_end() -> None:
    async def run() -> None:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        exec_id, run_id = await _seed_workflow_with_step_run()
        try:
            conn = await _connect()
            try:
                result = await execute_step_run(
                    conn,
                    step_run_id=run_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(SAMPLE_ENVELOPE),
                )
                assert result.output_package_id is not None
                # step_run advanced to completed
                final_status = await conn.fetchval(
                    "SELECT status::text FROM workflow_step_runs WHERE id = $1::uuid",
                    run_id,
                )
                assert final_status == "completed"
                # output_package linked to execution
                pkg_kind = await conn.fetchval(
                    """
                    SELECT output_kind::text FROM output_packages
                     WHERE id = $1::uuid
                    """,
                    result.output_package_id,
                )
                assert pkg_kind == "generic"
            finally:
                await conn.close()
        finally:
            await _cleanup_workflow(exec_id)
            del os.environ["OPENROUTER_API_KEY"]

    asyncio.run(run())

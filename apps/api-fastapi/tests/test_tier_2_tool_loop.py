"""Loop Eta Worker B — Tier 2 tool-call → execute → re-invoke loop tests.

Three smokes covering the new contract:
  - Authorized tool round-trip: LLM emits tool_call → assignment row +
    enabled catalog row + runtime_status='runnable' → execute_tool runs,
    `sub_agent.tool_called` audit fires, follow-up turn emits envelope.
  - Unauthorized tool: no assignment row → `sub_agent.tool_unauthorized`
    fires, intake injected with [TOOL DENIED], LLM re-invokes and emits
    envelope.
  - Cap reached: 3 tool_call decisions in a row → `sub_agent.tool_cap_reached`
    fires, runtime forces final envelope on the 4th turn.

Each test seeds `tool_catalog` + `sub_agent_tools` rows when needed and
cleans them up afterwards. Audit-log rows are tagged with the test's
`work_order_id` (a random UUID stand-in) so cleanup only removes the
test's rows.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any

import asyncpg
import httpx
import pytest

from runtime.tier_2_subagents import (
    MAX_TIER_2_TOOL_CALLS,
    invoke_tier_2,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
MARK_TIER_2_LLM_CONFIG_ID = "00000000-0000-4000-8000-000091000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _scripted_transport(script: list[str]) -> httpx.MockTransport:
    """Returns a MockTransport that hands out responses from `script` in
    order, one per HTTP call. Last entry repeats for any extra calls
    (defensive — a runaway loop won't IndexError before we can assert)."""
    counter = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        i = counter["i"]
        body_str = script[min(i, len(script) - 1)]
        counter["i"] = i + 1
        body = {"choices": [{"message": {"content": body_str}}]}
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )

    return httpx.MockTransport(handler)


def _envelope(content: str = "# Mark draft\n\nfinal output") -> str:
    return json.dumps({
        "decision_kind": "content_envelope",
        "content_envelope": {
            "content_markdown": content,
            "summary": "Mark draft summary",
            "output_kind": "generic",
            "metadata": {"sections": 2},
        },
    })


def _tool_call_decision(tool_name: str, args: dict[str, Any] | None = None) -> str:
    return json.dumps({
        "decision_kind": "tool_call",
        "tool_call": {
            "tool_name": tool_name,
            "args": args or {},
        },
    })


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


async def _seed_runtime_health_catalog_row(conn: asyncpg.Connection) -> None:
    """Insert a `runtime_health` row in tool_catalog if it doesn't already
    exist. Idempotent: if a future seed migration adds the row we still
    work; we just normalise the row to enabled + runnable for the test."""
    existing = await conn.fetchval(
        "SELECT 1 FROM tool_catalog WHERE tool_key = 'runtime_health'"
    )
    if existing:
        await conn.execute(
            """
            UPDATE tool_catalog
               SET enabled = true,
                   runtime_status = 'runnable'::tool_runtime_status
             WHERE tool_key = 'runtime_health'
            """
        )
        return
    await conn.execute(
        """
        INSERT INTO tool_catalog
          (tool_key, display_name, description, category,
           runtime_status, args_schema, handler_ref, default_tier,
           iwo2_origin, enabled, notes)
        VALUES
          ('runtime_health', 'Runtime Health',
           'Platform health snapshot (test-seeded).',
           'introspection'::tool_category,
           'runnable'::tool_runtime_status,
           '{}'::jsonb,
           'runtime.aiden_tools._runtime_health',
           'either'::tool_default_tier,
           NULL, true, 'seeded by test_tier_2_tool_loop')
        """
    )


async def _grant_tool(
    conn: asyncpg.Connection,
    *,
    tool_key: str,
    enabled: bool = True,
) -> str:
    """Insert a sub_agent_tools row for Mark Tier 2 + return its id."""
    row_id = await conn.fetchval(
        """
        INSERT INTO sub_agent_tools
          (client_id, llm_config_id, tool_key, enabled, granted_by_user_id)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5::uuid)
        RETURNING id::text
        """,
        KLEAR_CLIENT,
        MARK_TIER_2_LLM_CONFIG_ID,
        tool_key,
        enabled,
        KLEAR_OPERATOR,
    )
    return row_id


async def _revoke_tool(conn: asyncpg.Connection, tool_key: str) -> None:
    await conn.execute(
        """
        DELETE FROM sub_agent_tools
         WHERE llm_config_id = $1::uuid AND tool_key = $2
        """,
        MARK_TIER_2_LLM_CONFIG_ID,
        tool_key,
    )


async def _audit_actions_for_wo(
    conn: asyncpg.Connection, work_order_id: str
) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT action FROM action_audit_log
         WHERE metadata->>'work_order_id' = $1
            OR metadata->>'workOrderId' = $1
         ORDER BY created_at ASC
        """,
        work_order_id,
    )
    return [r["action"] for r in rows]


async def _audit_meta_for_wo(
    conn: asyncpg.Connection, work_order_id: str, action: str
) -> dict | None:
    row = await conn.fetchrow(
        """
        SELECT metadata FROM action_audit_log
         WHERE action = $1
           AND (metadata->>'work_order_id' = $2
                OR metadata->>'workOrderId' = $2)
         ORDER BY created_at DESC
         LIMIT 1
        """,
        action,
        work_order_id,
    )
    if not row:
        return None
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    return meta


async def _cleanup_audit_for_wo(
    conn: asyncpg.Connection, work_order_id: str
) -> None:
    await conn.execute(
        """
        DELETE FROM action_audit_log
         WHERE metadata->>'work_order_id' = $1
            OR metadata->>'workOrderId' = $1
        """,
        work_order_id,
    )


# ── Test 1: authorized tool round-trip ──────────────────────────────


@iwo3_db
def test_authorized_tool_call_runs_and_returns_envelope() -> None:
    """LLM emits tool_call → runtime checks assignment (granted) →
    execute_tool runs → next turn returns envelope. Audit shows
    sub_agent.tool_called metadata with agent_role + llm_config_id +
    iteration_index."""

    async def run() -> None:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        wo_id = str(uuid.uuid4())
        conn = await _connect()
        try:
            await _seed_runtime_health_catalog_row(conn)
            await _grant_tool(conn, tool_key="runtime_health")

            transport = _scripted_transport([
                _tool_call_decision("runtime_health"),
                _envelope("# Mark final brief\n\nbased on runtime data"),
            ])

            envelope = await invoke_tier_2(
                conn,
                role="mark",
                intake_text="Draft a brief — first check system health",
                content_blocks={"prompt": "go"},
                work_order_id=wo_id,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                transport=transport,
            )
            assert "Mark final brief" in envelope.content_markdown

            actions = await _audit_actions_for_wo(conn, wo_id)
            assert "sub_agent.tool_called" in actions, actions
            assert "sub_agent.tool_unauthorized" not in actions, actions

            meta = await _audit_meta_for_wo(
                conn, wo_id, "sub_agent.tool_called"
            )
            assert meta is not None
            assert meta["tool_name"] == "runtime_health"
            assert meta["agent_role"] == "mark_tier_2"
            assert meta["llm_config_id"] == MARK_TIER_2_LLM_CONFIG_ID
            assert meta["iteration_index"] == 1
            assert meta["work_order_id"] == wo_id
            assert isinstance(meta.get("result_size_chars"), int)
        finally:
            await _revoke_tool(conn, "runtime_health")
            await _cleanup_audit_for_wo(conn, wo_id)
            await conn.close()
            del os.environ["OPENROUTER_API_KEY"]

    asyncio.run(run())


# ── Test 2: unauthorized tool ───────────────────────────────────────


@iwo3_db
def test_unauthorized_tool_call_emits_unauthorized_audit() -> None:
    """No sub_agent_tools assignment row exists → assignment check
    returns False → sub_agent.tool_unauthorized fires, intake gets
    [TOOL DENIED] suffix, follow-up turn returns envelope."""

    async def run() -> None:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        wo_id = str(uuid.uuid4())
        conn = await _connect()
        try:
            await _seed_runtime_health_catalog_row(conn)
            # No grant — assignment row missing.
            await _revoke_tool(conn, "runtime_health")

            transport = _scripted_transport([
                _tool_call_decision("runtime_health"),
                _envelope("# Mark fallback\n\ncomposed without tool"),
            ])

            envelope = await invoke_tier_2(
                conn,
                role="mark",
                intake_text="Draft a brief",
                content_blocks={"prompt": "go"},
                work_order_id=wo_id,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                transport=transport,
            )
            assert "Mark fallback" in envelope.content_markdown

            actions = await _audit_actions_for_wo(conn, wo_id)
            assert "sub_agent.tool_unauthorized" in actions, actions
            assert "sub_agent.tool_called" not in actions, actions

            meta = await _audit_meta_for_wo(
                conn, wo_id, "sub_agent.tool_unauthorized"
            )
            assert meta is not None
            assert meta["tool_name"] == "runtime_health"
            assert meta["agent_role"] == "mark_tier_2"
            assert meta["llm_config_id"] == MARK_TIER_2_LLM_CONFIG_ID
            assert meta["iteration_index"] == 1
        finally:
            await _cleanup_audit_for_wo(conn, wo_id)
            await conn.close()
            del os.environ["OPENROUTER_API_KEY"]

    asyncio.run(run())


# ── Test 3: cap reached ─────────────────────────────────────────────


@iwo3_db
def test_tool_cap_reached_emits_cap_audit_and_forces_final_envelope() -> None:
    """LLM keeps emitting tool_call decisions; after MAX_TIER_2_TOOL_CALLS
    the runtime fires sub_agent.tool_cap_reached and re-invokes with
    tool-call disabled in the schema. The 4th transport response is the
    final envelope."""

    async def run() -> None:
        os.environ["OPENROUTER_API_KEY"] = "test-key"
        wo_id = str(uuid.uuid4())
        conn = await _connect()
        try:
            await _seed_runtime_health_catalog_row(conn)
            await _grant_tool(conn, tool_key="runtime_health")

            # 3 tool_call decisions → cap → 4th turn returns envelope.
            transport = _scripted_transport([
                _tool_call_decision("runtime_health"),
                _tool_call_decision("runtime_health"),
                _tool_call_decision("runtime_health"),
                _envelope("# Mark cap-reached\n\nfinal answer"),
            ])

            envelope = await invoke_tier_2(
                conn,
                role="mark",
                intake_text="Draft a brief",
                content_blocks={"prompt": "go"},
                work_order_id=wo_id,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                transport=transport,
            )
            assert "Mark cap-reached" in envelope.content_markdown

            actions = await _audit_actions_for_wo(conn, wo_id)
            # Three successful tool calls below the cap.
            assert actions.count("sub_agent.tool_called") == MAX_TIER_2_TOOL_CALLS
            assert "sub_agent.tool_cap_reached" in actions, actions

            meta = await _audit_meta_for_wo(
                conn, wo_id, "sub_agent.tool_cap_reached"
            )
            assert meta is not None
            assert meta["agent_role"] == "mark_tier_2"
            assert meta["llm_config_id"] == MARK_TIER_2_LLM_CONFIG_ID
            assert meta["calls_made"] == MAX_TIER_2_TOOL_CALLS
        finally:
            await _revoke_tool(conn, "runtime_health")
            await _cleanup_audit_for_wo(conn, wo_id)
            await conn.close()
            del os.environ["OPENROUTER_API_KEY"]

    asyncio.run(run())

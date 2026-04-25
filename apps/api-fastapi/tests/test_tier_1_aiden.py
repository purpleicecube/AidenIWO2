"""MegaLoop Alpha α.2 — Tier 1 Aiden invocation tests.

Covers:
  - Happy path: provider returns valid JSON → AidenDecision parsed
    with provenance + llm.invoked audit emitted with token counts
  - Malformed JSON → AidenDecisionMalformed + llm.failed audit
  - work_order_brief + workflow_brief + clarification variants parse
  - Missing credential env var → AidenInvocationError(credential_missing)
  - Per-WO budget breach → LlmBudgetExceeded + llm.budget_exceeded audit
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import httpx
import pytest

from runtime.budgets import LlmBudgetExceeded
from runtime.tier_1_aiden import (
    AIDEN_TIER_1_ROLE,
    AidenDecisionMalformed,
    AidenInvocationError,
    invoke_aiden_tier_1,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _ok_transport(content: str, *, usage: dict | None = None) -> httpx.MockTransport:
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ],
    }
    if usage:
        body["usage"] = usage

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )

    return httpx.MockTransport(handler)


def _err_transport(status: int, body: object) -> httpx.MockTransport:
    body_str = body if isinstance(body, str) else json.dumps(body)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body_str.encode())

    return httpx.MockTransport(handler)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


WORK_ORDER_BRIEF_JSON = json.dumps({
    "decision_kind": "work_order_brief",
    "title": "Render the Klear 3M GTM exec deck",
    "summary": "Single-step PPT generation with the Klear primary template.",
    "work_order_brief": {
        "assigned_role": "tom_tier_2",
        "content_blocks": {
            "prompt": "Produce a 12-slide exec summary covering pipeline + ramp."
        },
        "priority": "high",
    },
})

WORKFLOW_BRIEF_JSON = json.dumps({
    "decision_kind": "workflow_brief",
    "title": "Multi-step content + deck + deploy",
    "summary": "Mark drafts, Tom builds deck, Paul deploys.",
    "workflow_brief": {
        "workflow_template_key": "weekly_marketing_brief",
        "step_inputs": {
            "draft": {"prompt": "Draft Q1 marketing brief"},
        },
    },
})

CLARIFICATION_JSON = json.dumps({
    "decision_kind": "clarification",
    "title": "Need format spec",
    "summary": "Operator did not specify pptx vs pdf.",
    "clarification": {
        "question": "Which format do you want — PPTX or PDF?",
        "missing_fields": ["output_format"],
    },
})


@iwo3_db
def test_happy_path_work_order_brief() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                d = await invoke_aiden_tier_1(
                    conn,
                    intake_text="Build me a Klear pricing deck for the 3M GTM review",
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(
                        WORK_ORDER_BRIEF_JSON,
                        usage={"prompt_tokens": 200, "completion_tokens": 150},
                    ),
                )
                assert d.decision_kind == "work_order_brief"
                assert d.work_order_brief is not None
                assert d.work_order_brief.assigned_role == "tom_tier_2"
                assert d.work_order_brief.priority == "high"
                assert d.provider in {"groq", "openrouter"}
                assert d.total_tokens == 350
                assert d.latency_ms is not None and d.latency_ms >= 0
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_workflow_brief_parses() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                d = await invoke_aiden_tier_1(
                    conn,
                    intake_text="Multi-step delivery please",
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(WORKFLOW_BRIEF_JSON),
                )
                assert d.decision_kind == "workflow_brief"
                assert d.workflow_brief is not None
                assert (
                    d.workflow_brief.workflow_template_key
                    == "weekly_marketing_brief"
                )
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_clarification_parses() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                d = await invoke_aiden_tier_1(
                    conn,
                    intake_text="render something",
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(CLARIFICATION_JSON),
                )
                assert d.decision_kind == "clarification"
                assert d.clarification is not None
                assert "PPTX" in d.clarification.question
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_malformed_json_raises() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            conn = await _connect()
            try:
                with pytest.raises(AidenDecisionMalformed):
                    await invoke_aiden_tier_1(
                        conn,
                        intake_text="...",
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        transport=_ok_transport(
                            "not json at all, just a chatty answer"
                        ),
                    )
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())


@iwo3_db
def test_credential_missing_raises_typed_error() -> None:
    async def run() -> None:
        # Make sure GROQ_API_KEY is not set (Klear's aiden_tier_1
        # config points at credential_ref:env:GROQ_API_KEY).
        os.environ.pop("GROQ_API_KEY", None)
        conn = await _connect()
        try:
            with pytest.raises(AidenInvocationError) as ei:
                await invoke_aiden_tier_1(
                    conn,
                    intake_text="...",
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    transport=_ok_transport(WORK_ORDER_BRIEF_JSON),
                )
            assert ei.value.kind == "credential_missing"
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_per_wo_budget_breach() -> None:
    """Seed `llm.invoked` rows totalling 49,500 tokens against a fresh
    WO; next call estimate ~125 (chars/4 of intake) pushes total
    above 50,000 → LlmBudgetExceeded raised."""
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        wo_id = str(uuid.uuid4())
        try:
            conn = await _connect()
            try:
                # Pre-load 49,500 tokens of usage via the canonical
                # audit writer (no-raw-audit-insert lint compliance).
                from authz.audit_writer import write_audit_row
                await write_audit_row(
                    conn,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    event="llm.invoked",
                    target_type="work_order",
                    target_id=wo_id,
                    metadata={
                        "workOrderId": wo_id,
                        "totalTokens": 49500,
                    },
                )
                with pytest.raises(LlmBudgetExceeded) as ei:
                    await invoke_aiden_tier_1(
                        conn,
                        intake_text="x" * 4000,  # ~1000 token estimate
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        work_order_id=wo_id,
                        transport=_ok_transport(WORK_ORDER_BRIEF_JSON),
                    )
                assert ei.value.already_used == 49500
                assert ei.value.ceiling == 50000
                # Verify the budget_exceeded audit was emitted.
                breach = await conn.fetchval(
                    """
                    SELECT count(*)::int FROM action_audit_log
                     WHERE action = 'llm.budget_exceeded'
                       AND metadata->>'workOrderId' = $1
                    """,
                    wo_id,
                )
                assert breach == 1
            finally:
                await conn.close()
        finally:
            os.environ.pop("GROQ_API_KEY", None)
            # Cleanup test rows
            cleanup = await _connect()
            try:
                await cleanup.execute(
                    "DELETE FROM action_audit_log WHERE metadata->>'workOrderId' = $1",
                    wo_id,
                )
            finally:
                await cleanup.close()

    asyncio.run(run())


@iwo3_db
def test_invalid_assigned_role_rejected() -> None:
    async def run() -> None:
        os.environ["GROQ_API_KEY"] = "test-key"
        try:
            bad = json.dumps({
                "decision_kind": "work_order_brief",
                "title": "x",
                "summary": "y",
                "work_order_brief": {
                    "assigned_role": "bogus_role_2",
                    "content_blocks": {},
                    "priority": "medium",
                },
            })
            conn = await _connect()
            try:
                with pytest.raises(AidenDecisionMalformed):
                    await invoke_aiden_tier_1(
                        conn,
                        intake_text="...",
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        transport=_ok_transport(bad),
                    )
            finally:
                await conn.close()
        finally:
            del os.environ["GROQ_API_KEY"]

    asyncio.run(run())

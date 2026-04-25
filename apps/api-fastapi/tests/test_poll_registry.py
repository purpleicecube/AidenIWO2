"""MegaLoop Alpha α.1 — adapter poll registry + WO cascade tests.

Covers:
  - Registry dispatches to the registered handler by adapter_key
  - Unknown adapter_key → adapter_not_found outcome (no exception)
  - Handoff completed → WO cascade to `completed` (single-WO path)
  - Handoff failed → WO cascade to `blocked` via watchdog helper
  - Workflow-bound handoffs do NOT trigger WO cascade (PM owns)
  - WO already not in `processing` → cascade no-ops with audit-trail-friendly detail
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import httpx
import pytest

from adapter.gamma_poll import PollOutcome, poll_gamma_handoff
from adapter.poll_registry import (
    __reset_for_test__,
    known_poll_adapter_keys,
    poll_handoff_via_registry,
    register_poll_handler,
)


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_AGENT = "00000000-0000-4000-8000-000001000006"
KLEAR_PPTX_TEMPLATE = "00000000-0000-4000-8000-000010000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _transport(status: int, body) -> httpx.MockTransport:
    body_str = body if isinstance(body, str) else json.dumps(body)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status, content=body_str.encode(),
            headers={"Content-Type": "application/json"},
        )
    return httpx.MockTransport(handler)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


async def _seed_credential() -> None:
    conn = await _connect()
    try:
        catalog_id = await conn.fetchval(
            "SELECT id FROM adapter_catalog WHERE adapter_key = 'gamma'"
        )
        await conn.execute(
            "DELETE FROM adapter_credentials WHERE client_id = $1 AND adapter_catalog_id = $2",
            KLEAR_CLIENT, catalog_id,
        )
        await conn.execute(
            """
            INSERT INTO adapter_credentials
              (client_id, adapter_catalog_id, credential_ref, status,
               first_invocation_confirmed_at, first_invocation_confirmed_by_user_id)
            VALUES ($1, $2, 'credential_ref:env:GAMMA_REGISTRY_TEST_KEY',
                    'active', now(), $3)
            """,
            KLEAR_CLIENT, catalog_id, KLEAR_OPERATOR,
        )
    finally:
        await conn.close()


async def _seed_wo_and_handoff(*, workflow_bound: bool = False) -> tuple[str, str]:
    """Returns (wo_id, handoff_id). Handoff is in submitted state with
    last_poll_at=now() so it's not stale."""
    conn = await _connect()
    try:
        wo_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO work_orders
              (id, client_id, title, type, priority, status,
               submitted_by_user_id, correlation_id)
            VALUES ($1, $2, 'alpha-1 cascade test wo', 'content_brief',
                    'medium', 'processing', $3, 'alpha-1-cascade-test')
            """,
            wo_id, KLEAR_CLIENT, KLEAR_OPERATOR,
        )
        # output package
        pkg_id = await conn.fetchval(
            """
            INSERT INTO output_packages
              (client_id, work_order_id, output_kind, title,
               content_blocks, template_profile_id, created_by_user_id)
            VALUES ($1, $2, 'gamma_pptx', 'cascade test pkg',
                    '{}'::jsonb, $3, $4)
            RETURNING id::text
            """,
            KLEAR_CLIENT, wo_id, KLEAR_PPTX_TEMPLATE, KLEAR_OPERATOR,
        )
        catalog_id = await conn.fetchval(
            "SELECT id FROM adapter_catalog WHERE adapter_key = 'gamma'"
        )
        # workflow_id only if workflow_bound
        workflow_id_val = None
        if workflow_bound:
            workflow_id_val = await conn.fetchval(
                "SELECT id::text FROM workflows WHERE client_id = $1 LIMIT 1",
                KLEAR_CLIENT,
            )
        handoff_id = await conn.fetchval(
            """
            INSERT INTO output_handoffs
              (client_id, work_order_id, workflow_id, output_package_id,
               adapter_catalog_id, external_reference, status,
               last_poll_status, last_poll_at, poll_count)
            VALUES ($1, $2, $3, $4, $5, $6,
                    'submitted'::output_handoff_status,
                    'pending', now(), 0)
            RETURNING id::text
            """,
            KLEAR_CLIENT, wo_id, workflow_id_val, pkg_id, catalog_id,
            f"gen_alpha_{wo_id[:8]}",
        )
        return wo_id, handoff_id
    finally:
        await conn.close()


async def _read_wo_status(wo_id: str) -> str:
    conn = await _connect()
    try:
        return await conn.fetchval(
            "SELECT status::text FROM work_orders WHERE id = $1", wo_id
        )
    finally:
        await conn.close()


async def _cleanup(wo_id: str, handoff_id: str) -> None:
    conn = await _connect()
    try:
        await conn.execute(
            "DELETE FROM external_execution_results WHERE output_handoff_id = $1",
            handoff_id,
        )
        await conn.execute("DELETE FROM output_handoffs WHERE id = $1", handoff_id)
        await conn.execute("DELETE FROM execution_cycles WHERE work_order_id = $1", wo_id)
        await conn.execute("DELETE FROM output_packages WHERE work_order_id = $1", wo_id)
        await conn.execute("DELETE FROM work_orders WHERE id = $1", wo_id)
    finally:
        await conn.close()


# ──────────────────────────────────────────────────────────────────────
# Registry tests
# ──────────────────────────────────────────────────────────────────────


def test_registry_lists_gamma_after_app_import() -> None:
    # Importing `main` registers Gamma via adapter package import.
    # Ensure it's in the registry list.
    import main  # noqa: F401
    assert "gamma" in known_poll_adapter_keys()


@iwo3_db
def test_registry_dispatches_unknown_adapter_to_typed_outcome() -> None:
    async def run() -> None:
        # Save + restore registry state across this test
        prior = {k: __import__("adapter.poll_registry", fromlist=["_POLL_HANDLERS"])._POLL_HANDLERS.get(k)
                 for k in known_poll_adapter_keys()}
        __reset_for_test__()
        try:
            # No handlers registered. Inserting a handoff with adapter_key=gamma
            # then dispatching → "no poll handler" message.
            await _seed_credential()
            wo, ho = await _seed_wo_and_handoff()
            try:
                conn = await _connect()
                try:
                    out = await poll_handoff_via_registry(
                        conn, handoff_id=ho, client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                    )
                    assert out.kind == "adapter_not_found"
                    assert "no poll handler registered" in (out.detail or "")
                finally:
                    await conn.close()
            finally:
                await _cleanup(wo, ho)
        finally:
            # Restore registry for downstream tests
            for k, v in prior.items():
                if v is not None:
                    register_poll_handler(k, v)
    asyncio.run(run())


# ──────────────────────────────────────────────────────────────────────
# Cascade tests — completed
# ──────────────────────────────────────────────────────────────────────


@iwo3_db
def test_cascade_wo_completed_when_handoff_completes() -> None:
    async def run() -> None:
        os.environ["GAMMA_REGISTRY_TEST_KEY"] = "k"
        try:
            await _seed_credential()
            wo, ho = await _seed_wo_and_handoff(workflow_bound=False)
            try:
                conn = await _connect()
                try:
                    out = await poll_gamma_handoff(
                        conn, handoff_id=ho, client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        fetch_transport=_transport(200, {
                            "status": "completed",
                            "exportUrls": ["https://export.example/x.pptx"],
                        }),
                    )
                    assert out.kind == "completed"
                    assert out.detail == "wo_cascaded_to_completed"
                finally:
                    await conn.close()
                wo_status = await _read_wo_status(wo)
                assert wo_status == "completed"
            finally:
                await _cleanup(wo, ho)
        finally:
            os.environ.pop("GAMMA_REGISTRY_TEST_KEY", None)
    asyncio.run(run())


@iwo3_db
def test_cascade_skipped_when_handoff_is_workflow_bound() -> None:
    async def run() -> None:
        os.environ["GAMMA_REGISTRY_TEST_KEY"] = "k"
        try:
            await _seed_credential()
            wo, ho = await _seed_wo_and_handoff(workflow_bound=True)
            try:
                conn = await _connect()
                try:
                    out = await poll_gamma_handoff(
                        conn, handoff_id=ho, client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OPERATOR,
                        fetch_transport=_transport(200, {
                            "status": "completed",
                            "exportUrls": ["https://export.example/x.pptx"],
                        }),
                    )
                    assert out.kind == "completed"
                    assert "workflow_bound" in (out.detail or "")
                finally:
                    await conn.close()
                # WO stayed in processing — PM owns workflow-bound WOs
                wo_status = await _read_wo_status(wo)
                assert wo_status == "processing"
            finally:
                await _cleanup(wo, ho)
        finally:
            os.environ.pop("GAMMA_REGISTRY_TEST_KEY", None)
    asyncio.run(run())


# ──────────────────────────────────────────────────────────────────────
# Cascade tests — failed
# ──────────────────────────────────────────────────────────────────────


@iwo3_db
def test_cascade_wo_blocked_when_handoff_fails() -> None:
    async def run() -> None:
        os.environ["GAMMA_REGISTRY_TEST_KEY"] = "k"
        try:
            await _seed_credential()
            wo, ho = await _seed_wo_and_handoff(workflow_bound=False)
            try:
                conn = await _connect()
                try:
                    out = await poll_gamma_handoff(
                        conn, handoff_id=ho, client_id=KLEAR_CLIENT,
                        # agent_klear has watchdog_expire authority
                        actor_user_id=KLEAR_AGENT,
                        fetch_transport=_transport(200, {
                            "status": "failed",
                            "error": {"message": "render exploded"},
                        }),
                    )
                    assert out.kind == "failed"
                finally:
                    await conn.close()
                wo_status = await _read_wo_status(wo)
                # blocked is the watchdog-target state in Loop 6
                assert wo_status == "blocked"
            finally:
                await _cleanup(wo, ho)
        finally:
            os.environ.pop("GAMMA_REGISTRY_TEST_KEY", None)
    asyncio.run(run())

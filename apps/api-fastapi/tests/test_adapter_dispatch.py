"""Beta-2 phase 0.2 — adapter dispatch + /render route tests.

Covers the Python `dispatch_gamma_for_package` helper and the
`POST /work_orders/{id}/render` endpoint. The Gamma POST is mocked via
httpx.MockTransport so tests don't burn real Gamma credits — only the
DB plumbing + audit trail + idempotence guard are exercised against
the live `aiden_iwo3` database.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Optional

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"
KLEAR_PDF_TID = "00000000-0000-4000-8000-000010000002"  # klear_pdf_rmis

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


# ────────── Fixtures: package + handoff lifecycle helpers ──────────


async def _seed_klear_gamma_package() -> tuple[str, str]:
    """Insert a fresh `gamma_pdf` package row + the parent WO. Returns
    (work_order_id, output_package_id). Tests clean up after themselves."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        wo_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO work_orders
              (id, client_id, title, type, priority, status,
               submitted_by_user_id, requested_outputs)
            VALUES ($1, $2, 'phase-0.2 dispatch test WO', 'content_brief',
                    'medium', 'pending', $3, $4::jsonb)
            """,
            wo_id,
            KLEAR_CLIENT,
            KLEAR_OWNER,
            json.dumps(
                {"output_kind": "pdf", "template_profile_id": KLEAR_PDF_TID}
            ),
        )
        pkg_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO output_packages
              (id, client_id, work_order_id, output_kind, title, summary,
               content_blocks, template_profile_id, created_by_user_id)
            VALUES ($1, $2, $3, 'gamma_pdf', 'phase-0.2 dispatch test pkg',
                    'unit-test envelope', $4::jsonb, $5, $6)
            """,
            pkg_id,
            KLEAR_CLIENT,
            wo_id,
            json.dumps(
                {
                    "content_markdown": "# Phase 0.2 dispatch test\n\nUnit-test prompt.",
                    "summary": "phase-0.2 dispatch test pkg",
                    "metadata": {},
                    "prompt": "Phase 0.2 dispatch test prompt.",
                }
            ),
            KLEAR_PDF_TID,
            KLEAR_OWNER,
        )
        return wo_id, pkg_id
    finally:
        await conn.close()


async def _drop_test_records(wo_id: str) -> None:
    """Best-effort cleanup of WO + its packages + handoffs + audit + cycles."""
    url = os.environ["IWO3_DATABASE_URL"]
    conn = await asyncpg.connect(dsn=url)
    try:
        for stmt, args in (
            ("DELETE FROM external_execution_results WHERE output_handoff_id IN (SELECT id FROM output_handoffs WHERE work_order_id = $1::uuid)", (wo_id,)),
            ("DELETE FROM output_handoffs WHERE work_order_id = $1::uuid", (wo_id,)),
            ("DELETE FROM output_packages WHERE work_order_id = $1::uuid", (wo_id,)),
            ("DELETE FROM action_audit_log WHERE target_id = $1 OR target_id IN (SELECT id::text FROM output_handoffs WHERE work_order_id = $1::uuid) OR target_id IN (SELECT id::text FROM output_packages WHERE work_order_id = $1::uuid)", (wo_id,)),
            ("DELETE FROM execution_cycles WHERE work_order_id = $1::uuid", (wo_id,)),
            ("DELETE FROM work_orders WHERE id = $1::uuid", (wo_id,)),
        ):
            try:
                await conn.execute(stmt, *args)
            except Exception:
                pass
    finally:
        await conn.close()


def _gamma_submit_mock_transport(
    *, generation_id: str = "test_generation_42"
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        # Loop 9 GammaSubmitParsed expects { generationId } in the body.
        return httpx.Response(
            200,
            json={
                "generationId": generation_id,
                "gammaUrl": f"https://gamma.app/test/{generation_id}",
            },
        )

    return httpx.MockTransport(handler)


# ────────── Tests: dispatch_gamma_for_package ──────────


@iwo3_db
def test_dispatch_gamma_creates_handoff_and_audit() -> None:
    """Happy path: a fresh gamma_pdf package gets a handoff row, audit
    `adapter_dispatch.submitted`, and the dispatcher returns the
    generation id from the (mocked) Gamma response."""
    from adapter.dispatch import dispatch_gamma_for_package

    async def _go() -> None:
        wo_id, pkg_id = await _seed_klear_gamma_package()
        try:
            url = os.environ["IWO3_DATABASE_URL"]
            conn = await asyncpg.connect(dsn=url)
            try:
                # Tenant-scope the connection so RLS lets the dispatcher
                # write the handoff under iwo3_app.
                async with conn.transaction():
                    await conn.execute(
                        "SELECT set_config('app.current_client_id', $1, true)",
                        KLEAR_CLIENT,
                    )
                    await conn.execute("SET LOCAL ROLE iwo3_app")
                    result = await dispatch_gamma_for_package(
                        conn,
                        output_package_id=pkg_id,
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OWNER,
                        transport=_gamma_submit_mock_transport(
                            generation_id="phase02_test_001"
                        ),
                    )
                    assert result.adapter_key == "gamma"
                    assert result.external_reference == "phase02_test_001"
                    assert result.handoff_id

                    # Verify the handoff row exists and is bound to the package
                    # + Klear PDF template + the right external_reference.
                    row = await conn.fetchrow(
                        """
                        SELECT status::text, external_reference, template_profile_id::text
                          FROM output_handoffs
                         WHERE id = $1::uuid
                        """,
                        result.handoff_id,
                    )
                    assert row is not None
                    assert row["status"] == "submitted"
                    assert row["external_reference"] == "phase02_test_001"
                    assert row["template_profile_id"] == KLEAR_PDF_TID

                    # And the audit row landed.
                    audit_count = await conn.fetchval(
                        """
                        SELECT count(*) FROM action_audit_log
                         WHERE action = 'adapter_dispatch.submitted'
                           AND target_id = $1
                        """,
                        result.handoff_id,
                    )
                    assert int(audit_count) == 1
            finally:
                await conn.close()
        finally:
            await _drop_test_records(wo_id)

    asyncio.run(_go())


@iwo3_db
def test_dispatch_gamma_idempotence_guard_rejects_in_flight() -> None:
    """A second dispatch on the same package while a non-terminal handoff
    exists must raise DispatchError(handoff_already_exists). This is the
    R-046 protection — the worker calls this, and it must not double-dispatch."""
    from adapter.dispatch import DispatchError, dispatch_gamma_for_package

    async def _go() -> None:
        wo_id, pkg_id = await _seed_klear_gamma_package()
        try:
            url = os.environ["IWO3_DATABASE_URL"]
            conn = await asyncpg.connect(dsn=url)
            try:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT set_config('app.current_client_id', $1, true)",
                        KLEAR_CLIENT,
                    )
                    await conn.execute("SET LOCAL ROLE iwo3_app")
                    transport = _gamma_submit_mock_transport(
                        generation_id="phase02_test_idem"
                    )
                    await dispatch_gamma_for_package(
                        conn,
                        output_package_id=pkg_id,
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OWNER,
                        transport=transport,
                    )
                    # Second call must raise.
                    with pytest.raises(DispatchError) as exc_info:
                        await dispatch_gamma_for_package(
                            conn,
                            output_package_id=pkg_id,
                            client_id=KLEAR_CLIENT,
                            actor_user_id=KLEAR_OWNER,
                            transport=transport,
                        )
                    assert exc_info.value.kind == "handoff_already_exists"
            finally:
                await conn.close()
        finally:
            await _drop_test_records(wo_id)

    asyncio.run(_go())


@iwo3_db
def test_dispatch_gamma_falls_back_to_wo_requested_outputs_when_pkg_unbound() -> None:
    """If the output_package was created with template_profile_id=NULL
    (β.3 path predated Phase 0.1 propagation), the dispatcher must fall
    back to the WO's requested_outputs.template_profile_id. Verify by
    seeding a package with NULL template and a WO with the requested_outputs
    jsonb populated."""
    from adapter.dispatch import dispatch_gamma_for_package

    async def _seed_unbound_package() -> tuple[str, str]:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await asyncpg.connect(dsn=url)
        try:
            wo_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO work_orders (id, client_id, title, type, priority, status, submitted_by_user_id, requested_outputs)
                VALUES ($1, $2, 'phase-0.2 fallback test', 'content_brief', 'medium', 'pending', $3, $4::jsonb)
                """,
                wo_id, KLEAR_CLIENT, KLEAR_OWNER,
                json.dumps({"output_kind": "pdf", "template_profile_id": KLEAR_PDF_TID}),
            )
            pkg_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO output_packages
                  (id, client_id, work_order_id, output_kind, title, summary,
                   content_blocks, template_profile_id, created_by_user_id)
                VALUES ($1, $2, $3, 'gamma_pdf', 'unbound', '', $4::jsonb, NULL, $5)
                """,
                pkg_id, KLEAR_CLIENT, wo_id,
                json.dumps({"content_markdown": "fallback test", "summary": "", "metadata": {}, "prompt": "fallback test prompt"}),
                KLEAR_OWNER,
            )
            return wo_id, pkg_id
        finally:
            await conn.close()

    async def _go() -> None:
        wo_id, pkg_id = await _seed_unbound_package()
        try:
            url = os.environ["IWO3_DATABASE_URL"]
            conn = await asyncpg.connect(dsn=url)
            try:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT set_config('app.current_client_id', $1, true)",
                        KLEAR_CLIENT,
                    )
                    await conn.execute("SET LOCAL ROLE iwo3_app")
                    result = await dispatch_gamma_for_package(
                        conn,
                        output_package_id=pkg_id,
                        client_id=KLEAR_CLIENT,
                        actor_user_id=KLEAR_OWNER,
                        transport=_gamma_submit_mock_transport(
                            generation_id="phase02_fallback_001"
                        ),
                    )
                    # Handoff inherits the WO-supplied template_profile_id.
                    row = await conn.fetchrow(
                        "SELECT template_profile_id::text FROM output_handoffs WHERE id = $1::uuid",
                        result.handoff_id,
                    )
                    assert row is not None
                    assert row["template_profile_id"] == KLEAR_PDF_TID
            finally:
                await conn.close()
        finally:
            await _drop_test_records(wo_id)

    asyncio.run(_go())


# ────────── Tests: POST /work_orders/{id}/render ──────────


@iwo3_db
def test_render_endpoint_404_when_no_gamma_package() -> None:
    """A WO with no gamma_*-kinded output_package returns 404."""
    from main import app

    async def _seed_bare_wo() -> str:
        url = os.environ["IWO3_DATABASE_URL"]
        conn = await asyncpg.connect(dsn=url)
        try:
            wo_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO work_orders (id, client_id, title, type, priority, status, submitted_by_user_id)
                VALUES ($1, $2, 'phase-0.2 render-no-pkg', 'content_brief', 'medium', 'pending', $3)
                """,
                wo_id, KLEAR_CLIENT, KLEAR_OWNER,
            )
            return wo_id
        finally:
            await conn.close()

    wo_id = asyncio.run(_seed_bare_wo())
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/render",
                headers={
                    "X-IWO3-User": KLEAR_OWNER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 404
        assert r.json()["detail"]["error"] == "no_gamma_package"
    finally:
        asyncio.run(_drop_test_records(wo_id))


@iwo3_db
def test_render_endpoint_403_when_role_lacks_perm() -> None:
    """`output_package:submit` is required. Viewer should be denied."""
    from main import app

    async def _seed() -> tuple[str, str]:
        return await _seed_klear_gamma_package()

    wo_id, _ = asyncio.run(_seed())
    try:
        with TestClient(app) as client:
            r = client.post(
                f"/work_orders/{wo_id}/render",
                headers={
                    "X-IWO3-User": KLEAR_VIEWER,
                    "X-IWO3-Client": KLEAR_CLIENT,
                },
            )
        assert r.status_code == 403
        assert r.json()["detail"]["error"] == "permission_denied"
    finally:
        asyncio.run(_drop_test_records(wo_id))

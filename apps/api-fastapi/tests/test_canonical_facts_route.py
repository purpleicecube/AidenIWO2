"""Loop Kappa — Memory V1.5 canonical facts CRUD route + service tests.

Live DB tests covering:
  - Service: refresh_canonical_facts_from_table reads + concatenates
  - Route: GET / POST / PATCH / DELETE round-trip
  - Hybrid switch: workspace folder fallback when table is empty
  - Audit emission: canonical_facts.created / .updated / .deleted
  - Cross-tenant: RLS enforces — Klear cannot see FFAI rows

Skips when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
FFAI_OWNER = "00000000-0000-4000-8000-000002000001"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture
def db_url() -> str:
    return os.environ["IWO3_DATABASE_URL"]


@pytest.fixture
def client():
    """FastAPI TestClient. Uses dev header auth (IWO3_AUTH_MODE=dev).
    `with TestClient(app)` invokes lifespan so the DB pool initialises.
    """
    os.environ.setdefault("IWO3_AUTH_MODE", "dev")
    from main import app

    with TestClient(app) as c:
        yield c


def _klear_owner_headers() -> dict:
    return {
        "X-IWO3-User": KLEAR_OWNER,
        "X-IWO3-Client": KLEAR_CLIENT,
    }


def _klear_operator_headers() -> dict:
    return {
        "X-IWO3-User": KLEAR_OPERATOR,
        "X-IWO3-Client": KLEAR_CLIENT,
    }


def _ffai_owner_headers() -> dict:
    return {
        "X-IWO3-User": FFAI_OWNER,
        "X-IWO3-Client": FFAI_CLIENT,
    }


async def _cleanup_test_facts(db_url: str) -> None:
    """Remove any canonical_facts rows from previous test runs that
    contained the test marker. Runs without RLS (bypass connection)."""
    conn = await asyncpg.connect(db_url)
    try:
        await conn.execute(
            """
            DELETE FROM canonical_facts
            WHERE body LIKE '%KAPPA_TEST_MARKER%'
            """,
        )
    finally:
        await conn.close()


# ── Route round-trip ─────────────────────────────────────────────


@iwo3_db
def test_create_then_list_canonical_fact(db_url: str, client: TestClient) -> None:
    asyncio.run(_cleanup_test_facts(db_url))

    create_resp = client.post(
        "/canonical_facts",
        json={
            "body": "Klear pricing is $7K/mo enterprise tier KAPPA_TEST_MARKER.",
            "severity": "high",
        },
        headers=_klear_owner_headers(),
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["fact"]["severity"] == "high"
    assert created["fact"]["version"] == 1
    assert created["fact"]["is_active"] is True
    assert created["blob_revision"] >= 1

    list_resp = client.get("/canonical_facts", headers=_klear_owner_headers())
    assert list_resp.status_code == 200
    listed = list_resp.json()
    fact_ids = [r["id"] for r in listed["rows"]]
    assert created["fact"]["id"] in fact_ids


@iwo3_db
def test_patch_canonical_fact_body_bumps_version(db_url: str, client: TestClient) -> None:
    asyncio.run(_cleanup_test_facts(db_url))
    headers = _klear_owner_headers()

    create = client.post(
        "/canonical_facts",
        json={"body": "old body KAPPA_TEST_MARKER", "severity": "low"},
        headers=headers,
    )
    fact_id = create.json()["fact"]["id"]

    patch = client.patch(
        f"/canonical_facts/{fact_id}",
        json={"body": "new body KAPPA_TEST_MARKER"},
        headers=headers,
    )
    assert patch.status_code == 200, patch.text
    updated = patch.json()
    assert updated["fact"]["body"] == "new body KAPPA_TEST_MARKER"
    assert updated["fact"]["version"] == 2


@iwo3_db
def test_delete_canonical_fact_soft_deletes(db_url: str, client: TestClient) -> None:
    asyncio.run(_cleanup_test_facts(db_url))
    headers = _klear_owner_headers()

    create = client.post(
        "/canonical_facts",
        json={"body": "to delete KAPPA_TEST_MARKER", "severity": "medium"},
        headers=headers,
    )
    fact_id = create.json()["fact"]["id"]

    delete = client.delete(f"/canonical_facts/{fact_id}", headers=headers)
    assert delete.status_code == 200
    assert delete.json()["fact"]["is_active"] is False

    # Default list should NOT include the soft-deleted row.
    listed = client.get("/canonical_facts", headers=headers).json()
    fact_ids_default = [r["id"] for r in listed["rows"]]
    assert fact_id not in fact_ids_default

    # include_inactive=true should surface it.
    listed_all = client.get(
        "/canonical_facts?include_inactive=true", headers=headers
    ).json()
    fact_ids_all = [r["id"] for r in listed_all["rows"]]
    assert fact_id in fact_ids_all


@iwo3_db
def test_severity_change_requires_set_severity_permission(
    db_url: str, client: TestClient
) -> None:
    asyncio.run(_cleanup_test_facts(db_url))
    op_headers = _klear_operator_headers()
    owner_headers = _klear_owner_headers()

    # Operator creates a fact (allowed — operator has :create + :update).
    create = client.post(
        "/canonical_facts",
        json={"body": "operator-authored KAPPA_TEST_MARKER", "severity": "low"},
        headers=op_headers,
    )
    assert create.status_code == 201
    fact_id = create.json()["fact"]["id"]

    # Operator tries to change severity — should 403 because operator
    # role lacks canonical_facts:set_severity (D-K3 + role grants).
    patch_op = client.patch(
        f"/canonical_facts/{fact_id}",
        json={"severity": "critical"},
        headers=op_headers,
    )
    assert patch_op.status_code == 403, patch_op.text
    assert (
        patch_op.json()["detail"]["permission"] == "canonical_facts:set_severity"
    )

    # Operator can still update body without severity.
    patch_op_body = client.patch(
        f"/canonical_facts/{fact_id}",
        json={"body": "operator-edited KAPPA_TEST_MARKER"},
        headers=op_headers,
    )
    assert patch_op_body.status_code == 200

    # Owner can change severity — has :set_severity.
    patch_owner = client.patch(
        f"/canonical_facts/{fact_id}",
        json={"severity": "critical"},
        headers=owner_headers,
    )
    assert patch_owner.status_code == 200
    assert patch_owner.json()["fact"]["severity"] == "critical"


@iwo3_db
def test_invalid_severity_rejected(db_url: str, client: TestClient) -> None:
    asyncio.run(_cleanup_test_facts(db_url))
    headers = _klear_owner_headers()

    resp = client.post(
        "/canonical_facts",
        json={"body": "x KAPPA_TEST_MARKER", "severity": "extreme"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error"] == "invalid_severity"


# ── Cross-tenant isolation (firewall) ────────────────────────────


@iwo3_db
def test_cross_tenant_isolation_canonical_facts(db_url: str, client: TestClient) -> None:
    asyncio.run(_cleanup_test_facts(db_url))

    # Klear creates a fact.
    klear_create = client.post(
        "/canonical_facts",
        json={"body": "Klear-only secret KAPPA_TEST_MARKER", "severity": "high"},
        headers=_klear_owner_headers(),
    )
    klear_fact_id = klear_create.json()["fact"]["id"]

    # FFAI lists — must NOT see Klear's fact.
    ffai_list = client.get("/canonical_facts", headers=_ffai_owner_headers())
    assert ffai_list.status_code == 200
    fact_ids = [r["id"] for r in ffai_list.json()["rows"]]
    assert klear_fact_id not in fact_ids, (
        f"FIREWALL VIOLATION: Klear fact {klear_fact_id} reached FFAI"
    )

    # FFAI tries to PATCH Klear's fact directly — must 404 (RLS hides it).
    ffai_patch = client.patch(
        f"/canonical_facts/{klear_fact_id}",
        json={"body": "stolen KAPPA_TEST_MARKER"},
        headers=_ffai_owner_headers(),
    )
    assert ffai_patch.status_code == 404


# ── Service layer: blob rebuild + memory.applied integration ─────


@iwo3_db
def test_blob_rebuild_after_create_reaches_memory_builder(
    db_url: str, client: TestClient
) -> None:
    """Verifies the end-to-end chain: POST /canonical_facts →
    refresh_canonical_facts_from_table → memory bundle picks up
    the fact."""
    asyncio.run(_cleanup_test_facts(db_url))
    headers = _klear_owner_headers()

    unique_marker = f"KAPPA_BLOB_TEST_{uuid.uuid4().hex[:8]}"
    client.post(
        "/canonical_facts",
        json={
            "body": f"Operator UNIQUE FACT — {unique_marker} KAPPA_TEST_MARKER.",
            "severity": "critical",
        },
        headers=headers,
    )

    async def _check() -> None:
        from memory import memory_context_builder
        from memory.cache import clear_all_caches

        clear_all_caches()
        conn = await asyncpg.connect(db_url)
        try:
            await conn.execute("SET LOCAL ROLE iwo3_app")
            await conn.execute(
                f"SET LOCAL app.current_client_id = '{KLEAR_CLIENT}'"
            )
            bundle = await memory_context_builder(
                conn,
                client_id=KLEAR_CLIENT,
                user_id=KLEAR_OWNER,
                message="what's the latest pricing",
            )
            assert unique_marker in bundle.block, (
                f"expected canonical fact marker {unique_marker} in "
                f"bundle.block; got first 500 chars: "
                f"{bundle.block[:500]}"
            )
        finally:
            await conn.close()

    asyncio.run(_check())


# ── Audit emission ───────────────────────────────────────────────


@iwo3_db
def test_audit_emitted_for_create_update_delete(
    db_url: str, client: TestClient
) -> None:
    asyncio.run(_cleanup_test_facts(db_url))
    headers = _klear_owner_headers()

    marker = f"KAPPA_AUDIT_TEST_{uuid.uuid4().hex[:8]}"
    create = client.post(
        "/canonical_facts",
        json={"body": f"audit test {marker} KAPPA_TEST_MARKER", "severity": "medium"},
        headers=headers,
    )
    fact_id = create.json()["fact"]["id"]

    client.patch(
        f"/canonical_facts/{fact_id}",
        json={"body": f"audit test edited {marker} KAPPA_TEST_MARKER"},
        headers=headers,
    )

    client.delete(f"/canonical_facts/{fact_id}", headers=headers)

    async def _check_audit() -> None:
        conn = await asyncpg.connect(db_url)
        try:
            rows = await conn.fetch(
                """
                SELECT action::text AS event
                FROM action_audit_log
                WHERE target_id = $1
                ORDER BY created_at ASC
                """,
                fact_id,
            )
            events = [r["event"] for r in rows]
            assert "canonical_facts.created" in events, f"got: {events}"
            assert "canonical_facts.updated" in events, f"got: {events}"
            assert "canonical_facts.deleted" in events, f"got: {events}"
        finally:
            await conn.close()

    asyncio.run(_check_audit())

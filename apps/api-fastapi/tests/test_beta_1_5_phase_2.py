"""MegaLoop Beta-1.5 phase 2 — UI-tail completion tests.

Covers:
  * POST /workspace/folders/scratch — idempotent per-operator scratch
  * GET /tenants/me/settings — read-anyone-with-client:read
  * PATCH /tenants/me/settings — admin-gated ceiling editor + revert
  * GET /llm/personas — prompt_profiles passthrough (Q6)
  * runtime/credentials_crypto — pynacl-optional fallback semantics
"""

from __future__ import annotations

import os

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


# ── credentials_crypto unit tests (no DB required) ────────────────────


def test_credentials_crypto_module_imports_without_pynacl() -> None:
    from runtime.credentials_crypto import (
        CryptoUnavailable,
        algo_tag,
        is_available,
    )
    # Module loads cleanly even when pynacl is unavailable; the
    # graceful fallback is the architect-locked R-034 pattern.
    assert algo_tag() == "libsodium-secretbox-v1"
    # is_available is False either when pynacl is missing or when the
    # master key is unset. Both are valid offline-sandbox states.
    assert is_available() is False or os.environ.get("IWO3_CRYPTO_MASTER_KEY")
    # CryptoUnavailable must be importable so callers can catch it.
    assert issubclass(CryptoUnavailable, RuntimeError)


def test_credentials_crypto_encrypt_raises_when_unavailable() -> None:
    from runtime.credentials_crypto import (
        CryptoUnavailable,
        encrypt_credential,
        is_available,
    )
    if is_available():
        pytest.skip("pynacl + master key both present; offline-fallback path inactive")
    with pytest.raises(CryptoUnavailable):
        encrypt_credential("supersecret", client_id=KLEAR_CLIENT)


def test_credentials_crypto_resolve_falls_through_to_env(monkeypatch) -> None:
    """When encrypted_value is None/empty the resolver MUST fall through
    to env-injection (the Beta-1 default). Beta-1.5 phase 2 introduces
    the encrypted column additively — never silently downgrades."""
    from runtime.credentials_crypto import resolve_encrypted_or_env

    monkeypatch.setenv("BETA_1_5_TEST_KEY", "from-env")
    out = resolve_encrypted_or_env(
        client_id=KLEAR_CLIENT,
        encrypted_value=None,
        credential_ref="credential_ref:env:BETA_1_5_TEST_KEY",
    )
    assert out == "from-env"

    out_empty = resolve_encrypted_or_env(
        client_id=KLEAR_CLIENT,
        encrypted_value=b"",
        credential_ref="credential_ref:env:BETA_1_5_TEST_KEY",
    )
    assert out_empty == "from-env"


def test_credentials_crypto_master_key_validation(monkeypatch) -> None:
    """Master key must decode to exactly 32 bytes from hex(64) or
    base64(44). Anything else → CryptoUnavailable BEFORE we touch nacl,
    so the error message is operator-actionable."""
    from runtime.credentials_crypto import _resolve_master_key, CryptoUnavailable

    monkeypatch.delenv("IWO3_CRYPTO_MASTER_KEY", raising=False)
    with pytest.raises(CryptoUnavailable, match="not set"):
        _resolve_master_key()

    monkeypatch.setenv("IWO3_CRYPTO_MASTER_KEY", "deadbeef")
    with pytest.raises(CryptoUnavailable):
        _resolve_master_key()


# ── /workspace/folders/scratch — idempotent per-operator scratch ──────


@iwo3_db
def test_scratch_folder_create_then_get_returns_same_row(monkeypatch) -> None:
    """Two calls return the same scratch folder row; second call is
    a no-op upsert. Tree includes the scratch folder for its owner
    only."""
    # Use a dedicated test user so we don't collide with prior runs.
    test_user = "00000000-0000-4000-8000-0000010099a1"

    async def _seed_test_user_membership() -> None:
        conn = await asyncpg.connect(os.environ["IWO3_DATABASE_URL"])
        try:
            await conn.execute(
                """
                INSERT INTO users (id, email, display_name, status)
                VALUES ($1::uuid, 'beta15p2-scratch@dev.local',
                        'Beta1.5 Scratch User', 'active')
                ON CONFLICT (id) DO NOTHING
                """,
                test_user,
            )
            await conn.execute(
                """
                INSERT INTO client_memberships (user_id, client_id, role, status)
                VALUES ($1::uuid, $2::uuid, 'operator', 'active')
                ON CONFLICT (user_id, client_id) DO UPDATE SET status = 'active'
                """,
                test_user,
                KLEAR_CLIENT,
            )
            # Clean up any prior scratch from a previous test run.
            # Hard-delete so the (client_id, parent_folder_id, name)
            # UNIQUE constraint clears between runs (the restore-on-
            # soft-delete code path is exercised by a separate test
            # that does an explicit DELETE then re-create).
            await conn.execute(
                "DELETE FROM workspace_folders WHERE owner_user_id = $1::uuid",
                test_user,
            )
        finally:
            await conn.close()

    import asyncio

    asyncio.new_event_loop().run_until_complete(_seed_test_user_membership())

    with TestClient(app) as client:
        first = client.post("/workspace/folders/scratch", headers=_hdr(test_user))
        assert first.status_code == 200, first.text
        first_id = first.json()["folder"]["id"]
        assert first.json()["folder"]["owner_user_id"] == test_user

        second = client.post(
            "/workspace/folders/scratch", headers=_hdr(test_user)
        )
        assert second.status_code == 200
        assert second.json()["folder"]["id"] == first_id

        # Owner sees their scratch in the tree.
        tree = client.get("/workspace/tree", headers=_hdr(test_user)).json()
        scratch_ids = [
            f["id"] for f in tree["folders"] if f.get("owner_user_id")
        ]
        assert first_id in scratch_ids

        # A different operator does NOT see it (Beta-1.5 ε.5 isolation).
        other_tree = client.get(
            "/workspace/tree", headers=_hdr(KLEAR_OPERATOR)
        ).json()
        other_owner_ids = [
            f["id"] for f in other_tree["folders"] if f.get("owner_user_id")
        ]
        assert first_id not in other_owner_ids


@iwo3_db
def test_scratch_folder_requires_workspace_write() -> None:
    with TestClient(app) as client:
        r = client.post("/workspace/folders/scratch", headers=_hdr(KLEAR_VIEWER))
    assert r.status_code == 403


# ── /tenants/me/settings — Q1 ceiling editor ──────────────────────────


@iwo3_db
def test_tenant_settings_get_returns_default_when_unset() -> None:
    with TestClient(app) as client:
        r = client.get("/tenants/me/settings", headers=_hdr(KLEAR_OPERATOR))
    assert r.status_code == 200
    body = r.json()
    assert body["client_id"] == KLEAR_CLIENT
    assert body["llm_per_wo_ceiling"] >= 1_000
    assert body["ceiling_min"] == 1_000
    assert body["ceiling_max"] == 1_000_000


@iwo3_db
def test_tenant_settings_admin_can_set_then_revert(monkeypatch) -> None:
    with TestClient(app) as client:
        # Admin (owner role) can set a custom ceiling.
        r = client.patch(
            "/tenants/me/settings",
            headers=_hdr(KLEAR_OWNER),
            json={"llm_per_wo_ceiling": 75_000},
        )
        assert r.status_code == 200, r.text
        assert r.json()["llm_per_wo_ceiling"] == 75_000
        assert r.json()["llm_per_wo_ceiling_is_default"] is False

        # Revert to default. Tests downstream rely on the ceiling
        # being unset (DEFAULT_PER_WO_CEILING = 50_000), so always
        # revert before exiting.
        r2 = client.patch(
            "/tenants/me/settings",
            headers=_hdr(KLEAR_OWNER),
            json={"revert_to_default": True},
        )
        assert r2.status_code == 200
        assert r2.json()["llm_per_wo_ceiling_is_default"] is True


@iwo3_db
def test_tenant_settings_operator_cannot_write() -> None:
    with TestClient(app) as client:
        r = client.patch(
            "/tenants/me/settings",
            headers=_hdr(KLEAR_OPERATOR),
            json={"llm_per_wo_ceiling": 60_000},
        )
    # Operator role does not carry system:admin per Loop 4 §Q2.
    assert r.status_code == 403


@iwo3_db
def test_tenant_settings_rejects_out_of_range() -> None:
    with TestClient(app) as client:
        too_low = client.patch(
            "/tenants/me/settings",
            headers=_hdr(KLEAR_OWNER),
            json={"llm_per_wo_ceiling": 100},
        )
        too_high = client.patch(
            "/tenants/me/settings",
            headers=_hdr(KLEAR_OWNER),
            json={"llm_per_wo_ceiling": 5_000_000},
        )
    assert too_low.status_code == 422
    assert too_high.status_code == 422


@iwo3_db
def test_tenant_settings_emits_audit_row() -> None:
    """Q1 PATCH must write `client.settings_updated`. The event was
    locked under BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS."""
    import asyncio

    async def _count_audit() -> int:
        conn = await asyncpg.connect(os.environ["IWO3_DATABASE_URL"])
        try:
            return await conn.fetchval(
                """
                SELECT count(*) FROM action_audit_log
                 WHERE client_id = $1::uuid
                   AND action = 'client.settings_updated'
                """,
                KLEAR_CLIENT,
            )
        finally:
            await conn.close()

    before = asyncio.new_event_loop().run_until_complete(_count_audit())
    with TestClient(app) as client:
        r = client.patch(
            "/tenants/me/settings",
            headers=_hdr(KLEAR_OWNER),
            json={"llm_per_wo_ceiling": 80_000},
        )
        assert r.status_code == 200
        # Restore default so the per-WO budget tests downstream see
        # DEFAULT_PER_WO_CEILING again. This test must leave clients in
        # the same shape it found them.
        client.patch(
            "/tenants/me/settings",
            headers=_hdr(KLEAR_OWNER),
            json={"revert_to_default": True},
        )
    after = asyncio.new_event_loop().run_until_complete(_count_audit())
    # +2 because revert is also audited.
    assert after >= before + 2


# ── /llm/personas — Q6 read-only persona library ──────────────────────


@iwo3_db
def test_personas_list_returns_active_prompt_profiles() -> None:
    with TestClient(app) as client:
        r = client.get("/llm/personas", headers=_hdr(KLEAR_OPERATOR))
    assert r.status_code == 200
    body = r.json()
    assert "personas" in body
    for p in body["personas"]:
        assert p["status"] == "active"
        assert p["scope"] in {"client", "workflow", "wo"}
        assert "profile_key" in p


@iwo3_db
def test_personas_requires_client_read() -> None:
    """Tenant member without active membership → 403 via require_permission."""
    intruder = "00000000-0000-4000-8000-000099000002"
    with TestClient(app) as client:
        r = client.get(
            "/llm/personas",
            headers={"X-IWO3-User": intruder, "X-IWO3-Client": KLEAR_CLIENT},
        )
    assert r.status_code == 403

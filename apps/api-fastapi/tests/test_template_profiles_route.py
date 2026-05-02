"""Beta-2 phase 0.1 — /template_profiles route tests.

Backs the Submit Order form's `template_profile` selector (instead of
hardcoding template ids). Tenant-scoped read; default filter `active`.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app

KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
FFAI_OPERATOR = "00000000-0000-4000-8000-000002000003"

iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@iwo3_db
def test_template_profiles_lists_active_klear() -> None:
    """Klear has three active template_profiles in seed: pptx primary +
    two pdf variants. Default filter is `active`."""
    with TestClient(app) as client:
        r = client.get(
            "/template_profiles",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    profiles = body["template_profiles"]
    profile_keys = {p["profile_key"] for p in profiles}
    assert "klear_pptx_primary" in profile_keys
    assert "klear_pdf_rmis" in profile_keys
    assert "klear_pdf_claims" in profile_keys
    # Every row is active and Klear-owned.
    for p in profiles:
        assert p["status"] == "active"
        assert p["client_id"] == KLEAR_CLIENT


@iwo3_db
def test_template_profiles_output_kind_filter_pptx() -> None:
    with TestClient(app) as client:
        r = client.get(
            "/template_profiles?output_kind=pptx",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        )
    assert r.status_code == 200, r.text
    profiles = r.json()["template_profiles"]
    # Klear has exactly one pptx template (klear_pptx_primary).
    assert len(profiles) == 1
    assert profiles[0]["output_kind"] == "pptx"
    assert profiles[0]["profile_key"] == "klear_pptx_primary"


@iwo3_db
def test_template_profiles_tenant_isolation() -> None:
    """RLS scopes the read. Klear context cannot see FFAI templates and
    vice versa."""
    with TestClient(app) as client:
        klear = client.get(
            "/template_profiles",
            headers={
                "X-IWO3-User": KLEAR_OPERATOR,
                "X-IWO3-Client": KLEAR_CLIENT,
            },
        ).json()["template_profiles"]
        ffai = client.get(
            "/template_profiles",
            headers={
                "X-IWO3-User": FFAI_OPERATOR,
                "X-IWO3-Client": FFAI_CLIENT,
            },
        ).json()["template_profiles"]
    klear_ids = {p["id"] for p in klear}
    ffai_ids = {p["id"] for p in ffai}
    assert klear_ids.isdisjoint(ffai_ids)
    for p in klear:
        assert p["client_id"] == KLEAR_CLIENT
    for p in ffai:
        assert p["client_id"] == FFAI_CLIENT


@iwo3_db
def test_template_profiles_requires_auth() -> None:
    with TestClient(app) as client:
        r = client.get("/template_profiles")
    assert r.status_code == 401

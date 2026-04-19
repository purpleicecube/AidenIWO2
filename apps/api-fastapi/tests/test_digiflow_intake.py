"""Python-side unit tests for the DigiFLOW intake router.

Parity against the TS implementation is enforced by
`tests/contract/digiflow-routing-parity.test.ts`. These tests cover
Python-specific validation + routing-decision cases.
"""

from __future__ import annotations

import pytest

from digiflow.intake import route_intake, validate_intake_packet


def _base_packet() -> dict:
    return {
        "id": "intake-001",
        "schema_version": "v0",
        "source_system": "digiflow",
        "client_designation": "IWO | Klear.ai",
        "requester": {"kind": "user", "email": "operator_klear@dev.local"},
        "title": "Test intake",
        "objective": "Test objective",
        "requested_execution_mode": "auto",
        "desired_outputs": [{"output_kind": "gamma_pptx"}],
    }


def test_explicit_wo_wins() -> None:
    pkt = _base_packet() | {"requested_execution_mode": "wo"}
    out = route_intake(pkt)
    assert out["kind"] == "wo"
    assert "explicit override" in out["rationale"]


def test_explicit_wf_wins_even_without_recurrence() -> None:
    pkt = _base_packet() | {"requested_execution_mode": "wf"}
    out = route_intake(pkt)
    assert out["kind"] == "wf"


def test_auto_with_recurrence_weekly_routes_wf() -> None:
    pkt = _base_packet() | {
        "recurrence": {"kind": "weekly"},
    }
    out = route_intake(pkt)
    assert out["kind"] == "wf"
    assert "weekly" in out["rationale"]


def test_auto_with_recurrence_once_routes_wo() -> None:
    pkt = _base_packet() | {
        "recurrence": {"kind": "once"},
    }
    out = route_intake(pkt)
    # 'once' does NOT trigger WF — treated as no recurrence.
    assert out["kind"] == "wo"


def test_auto_with_single_output_routes_wo() -> None:
    pkt = _base_packet()
    out = route_intake(pkt)
    assert out["kind"] == "wo"
    assert "single one-time output" in out["rationale"]


def test_auto_with_multiple_outputs_routes_wo_with_multiple_packages() -> None:
    pkt = _base_packet() | {
        "desired_outputs": [
            {"output_kind": "gamma_pptx"},
            {"output_kind": "drive_upload"},
            {"output_kind": "email_campaign"},
        ]
    }
    out = route_intake(pkt)
    assert out["kind"] == "wo"
    assert "3 one-time outputs" in out["rationale"]


def test_ambiguous_no_outputs_routes_needs_clarification() -> None:
    pkt = _base_packet() | {"desired_outputs": []}
    out = route_intake(pkt)
    assert out["kind"] == "needs_clarification"


def test_validation_requires_tenant_resolution() -> None:
    pkt = _base_packet()
    del pkt["client_designation"]
    errors = validate_intake_packet(pkt)
    assert any("client_designation" in e for e in errors)


def test_validation_requires_credential_ref_placeholder() -> None:
    pkt = _base_packet() | {
        "assets": [
            {
                "id": "a1",
                "credential_ref": "actual-raw-token-leak",
            }
        ]
    }
    errors = validate_intake_packet(pkt)
    assert any("credential_ref" in e for e in errors)


def test_validation_allows_credential_ref_placeholder() -> None:
    pkt = _base_packet() | {
        "assets": [
            {
                "id": "a1",
                "credential_ref": "credential_ref:dev-local-source-01",
            }
        ]
    }
    errors = validate_intake_packet(pkt)
    assert errors == []


def test_validation_custom_recurrence_requires_frequency() -> None:
    pkt = _base_packet() | {"recurrence": {"kind": "custom"}}
    errors = validate_intake_packet(pkt)
    assert any("frequency" in e for e in errors)


def test_validation_custom_recurrence_with_frequency_passes() -> None:
    pkt = _base_packet() | {
        "recurrence": {"kind": "custom", "frequency": "every 2 weeks"}
    }
    errors = validate_intake_packet(pkt)
    assert errors == []


def test_validation_empty_title_rejected() -> None:
    pkt = _base_packet() | {"title": "   "}
    errors = validate_intake_packet(pkt)
    assert any("title" in e for e in errors)

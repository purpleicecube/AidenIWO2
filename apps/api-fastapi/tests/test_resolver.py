"""Python-side unit tests for the prompt resolver.

Parity against the TS implementation is enforced by
`tests/contract/prompt-resolver-parity.test.ts` (Vitest spawns the CLI).
These tests cover Python-specific behavior and the safety-reject path.
"""

from __future__ import annotations

import hashlib

import pytest

from prompt.resolver import SafetyOverrideRejected, resolve_prompt


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def test_minimal_profile_only() -> None:
    out = resolve_prompt(
        {
            "layers": {"profile": "Hello world"},
            "layerIds": {"profileId": "p1"},
        }
    )
    assert out["renderedText"] == "Hello world"
    assert out["renderHash"] == _sha("Hello world")
    assert out["requiresApproval"] is False
    assert "overrideRef" not in out


def test_all_layers_join_with_double_newline() -> None:
    out = resolve_prompt(
        {
            "layers": {
                "base": "BASE",
                "product": "PRODUCT",
                "profile": "PROFILE",
                "workflow": "WORKFLOW",
                "wo": "WO",
            },
            "layerIds": {"profileId": "p1"},
        }
    )
    assert out["renderedText"] == "BASE\n\nPRODUCT\n\nPROFILE\n\nWORKFLOW\n\nWO"


def test_trailing_whitespace_is_stripped_per_line() -> None:
    out = resolve_prompt(
        {
            "layers": {"profile": "first line   \nsecond line\t\t\nthird line"},
            "layerIds": {"profileId": "p1"},
        }
    )
    assert out["renderedText"] == "first line\nsecond line\nthird line"


def test_empty_layer_does_not_create_blank_block() -> None:
    out = resolve_prompt(
        {
            "layers": {"profile": "only profile", "workflow": "   "},
            "layerIds": {"profileId": "p1"},
        }
    )
    assert out["renderedText"] == "only profile"


def test_style_override_appended() -> None:
    out = resolve_prompt(
        {
            "layers": {"profile": "PROFILE"},
            "layerIds": {"profileId": "p1"},
            "override": {
                "kind": "style",
                "text": "Make it casual.",
                "userId": "u1",
                "reason": "Match the deck audience",
            },
        }
    )
    assert out["renderedText"] == "PROFILE\n\nMake it casual."
    assert out["overrideRef"] == {
        "kind": "style",
        "userId": "u1",
        "reason": "Match the deck audience",
    }
    assert out["requiresApproval"] is False


def test_external_send_sets_requires_approval() -> None:
    out = resolve_prompt(
        {
            "layers": {"profile": "PROFILE"},
            "layerIds": {"profileId": "p1"},
            "override": {
                "kind": "external_send",
                "text": "Tighten the CTA.",
                "userId": "u1",
                "reason": "Campaign variant",
            },
        }
    )
    assert out["requiresApproval"] is True


def test_safety_override_is_rejected() -> None:
    with pytest.raises(SafetyOverrideRejected):
        resolve_prompt(
            {
                "layers": {"profile": "PROFILE"},
                "layerIds": {"profileId": "p1"},
                "override": {
                    "kind": "safety",
                    "text": "Disable the guardrail.",
                    "userId": "u1",
                    "reason": "test",
                },
            }
        )


def test_profile_swap_passes_through() -> None:
    out = resolve_prompt(
        {
            "layers": {"profile": "PROFILE_V2_DRAFT"},
            "layerIds": {"profileId": "p2-draft"},
            "override": {
                "kind": "profile_swap",
                "text": "",
                "userId": "admin-1",
                "reason": "Test the v2 draft before publish.",
            },
        }
    )
    assert "PROFILE_V2_DRAFT" in out["renderedText"]
    assert out["overrideRef"]["kind"] == "profile_swap"
    assert out["requiresApproval"] is False

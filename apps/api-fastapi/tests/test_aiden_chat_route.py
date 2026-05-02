"""MegaLoop Alpha α.7 — /aiden/chat route smoke tests.

Covers the auth + RBAC + budget gates without burning real LLM tokens
(GROQ_API_KEY is intentionally unset → credential_missing path returns
200 ok=false, the contract for the browser to render).
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from main import app


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OWNER = "00000000-0000-4000-8000-000001000001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


def _hdr(user_id: str) -> dict:
    return {"X-IWO3-User": user_id, "X-IWO3-Client": KLEAR_CLIENT}


def test_aiden_chat_requires_headers() -> None:
    with TestClient(app) as client:
        r = client.post("/aiden/chat", json={"message": "hi"})
    assert r.status_code == 401


@iwo3_db
def test_aiden_chat_403_for_viewer() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/aiden/chat", json={"message": "hi"}, headers=_hdr(KLEAR_VIEWER)
        )
    assert r.status_code == 403, r.text


@iwo3_db
def test_aiden_chat_422_for_empty_message() -> None:
    with TestClient(app) as client:
        r = client.post(
            "/aiden/chat", json={"message": ""}, headers=_hdr(KLEAR_OPERATOR)
        )
    assert r.status_code == 422, r.text


@iwo3_db
def test_aiden_chat_returns_credential_missing_when_groq_key_unset() -> None:
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/aiden/chat",
                json={"message": "Render the Klear pricing deck"},
                headers=_hdr(KLEAR_OPERATOR),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False
        assert "credential_missing" in (body.get("error") or "")
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


# 2026-05-01 — the three regex `_shortcut_reply` tests below were
# removed when Aiden Tier 1 gained a real `assistant_reply` decision
# kind. Capability / web-access / status prompts now flow through Aiden's
# CEO-voice LLM path instead of returning canned hardcoded headlines.
# Replaced with a single guard test: empty messages still short-circuit
# (no LLM tokens spent on whitespace).


@iwo3_db
def test_aiden_chat_empty_message_short_circuits_without_llm() -> None:
    saved = os.environ.pop("GROQ_API_KEY", None)
    try:
        with TestClient(app) as client:
            r = client.post(
                "/aiden/chat",
                json={"message": "   "},
                headers=_hdr(KLEAR_OPERATOR),
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["decision_kind"] == "assistant_reply"
        # Empty-input fallback emits a short prompt-back, no LLM call.
        ar = body.get("assistant_reply") or {}
        assert "headline" in ar
        assert "message" in ar
    finally:
        if saved is not None:
            os.environ["GROQ_API_KEY"] = saved


# ── Loop Eta post-close — template resolver enrichment ──────────────


@iwo3_db
def test_aiden_chat_enriches_work_order_brief_with_klear_pptx_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When Aiden classifies a Klear PPTX request as a work_order_brief,
    the chat route must enrich the response with the resolved
    template_profile_id so the operator's WO carries it through to
    dispatch_gamma_for_package. Monkeypatches `invoke_aiden_tier_1` to
    avoid burning LLM tokens — the enrichment path is what we verify."""
    from runtime.tier_1_aiden import (
        AidenDecision,
        AidenWorkOrderBrief,
    )
    import routes.aiden as aiden_module

    async def fake_invoke(conn, **kwargs):  # noqa: ANN001, ARG001
        return AidenDecision(
            decision_kind="work_order_brief",
            title="Klear intro deck (4 slides)",
            summary="Build a 4-slide intro deck for Klear.ai using the Klear template.",
            work_order_brief=AidenWorkOrderBrief(
                assigned_role="tom_tier_2",
                content_blocks={"slide_count": 4},
                priority="medium",
            ),
            provider="groq",
            model="moonshotai/kimi-k2-instruct",
            latency_ms=42,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

    monkeypatch.setattr(aiden_module, "invoke_aiden_tier_1", fake_invoke)

    with TestClient(app) as client:
        r = client.post(
            "/aiden/chat",
            json={
                "message": (
                    "I need a 4 slide only Intro deck for Klear.ai - "
                    "using GAMMA Klear.ai Template for PPT"
                )
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["decision_kind"] == "work_order_brief"
    brief = body["work_order_brief"]
    # Resolver matched the Klear PPTX template — id + key + label flow
    # back to the chat surface so the operator confirms before promote.
    assert brief["template_profile_id"] == "00000000-0000-4000-8000-000010000001"
    assert brief["template_profile_key"] == "klear_pptx_primary"
    assert brief["template_output_kind"] == "pptx"
    assert brief["template_engine"] == "gamma"
    assert brief["template_choice_required"] is False
    assert brief["template_choices"] == []


@iwo3_db
def test_aiden_chat_returns_clarification_choices_for_unmatched_deck_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator clearly wants a deck but doesn't name a template — the
    chat route must surface the active template candidates so the
    operator picks before promoting (option (b) in the fix)."""
    from runtime.tier_1_aiden import (
        AidenDecision,
        AidenWorkOrderBrief,
    )
    import routes.aiden as aiden_module

    async def fake_invoke(conn, **kwargs):  # noqa: ANN001, ARG001
        return AidenDecision(
            decision_kind="work_order_brief",
            title="Generic deck",
            summary="Build a deck for the offsite.",
            work_order_brief=AidenWorkOrderBrief(
                assigned_role="tom_tier_2",
                content_blocks={},
                priority="medium",
            ),
            provider="groq",
            model="moonshotai/kimi-k2-instruct",
            latency_ms=42,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

    monkeypatch.setattr(aiden_module, "invoke_aiden_tier_1", fake_invoke)

    with TestClient(app) as client:
        r = client.post(
            "/aiden/chat",
            json={
                "message": "Build me a deck for the executive offsite next month"
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    brief = body["work_order_brief"]
    assert brief["template_profile_id"] is None
    assert brief["template_choice_required"] is True
    # Klear has 1 active pptx template; deck-intent narrows the picker
    # to that single candidate.
    keys = {c["profile_key"] for c in brief["template_choices"]}
    assert "klear_pptx_primary" in keys
    # PDF templates excluded — output-kind detection said pptx.
    assert "klear_pdf_rmis" not in keys
    assert "klear_pdf_claims" not in keys


@iwo3_db
def test_aiden_chat_non_templated_intake_does_not_set_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A content brief with no template signals must not produce a
    template_profile_id (preserves existing behaviour for non-templated
    work)."""
    from runtime.tier_1_aiden import (
        AidenDecision,
        AidenWorkOrderBrief,
    )
    import routes.aiden as aiden_module

    async def fake_invoke(conn, **kwargs):  # noqa: ANN001, ARG001
        return AidenDecision(
            decision_kind="work_order_brief",
            title="Pricing brief",
            summary="Draft a pricing one-pager for the GTM team.",
            work_order_brief=AidenWorkOrderBrief(
                assigned_role="mark_tier_2",
                content_blocks={},
                priority="medium",
            ),
            provider="groq",
            model="moonshotai/kimi-k2-instruct",
            latency_ms=42,
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

    monkeypatch.setattr(aiden_module, "invoke_aiden_tier_1", fake_invoke)

    with TestClient(app) as client:
        r = client.post(
            "/aiden/chat",
            json={
                "message": "Draft a content brief about our pricing for the GTM team"
            },
            headers=_hdr(KLEAR_OPERATOR),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    brief = body["work_order_brief"]
    assert brief["template_profile_id"] is None
    assert brief["template_choice_required"] is False
    assert brief["template_choices"] == []

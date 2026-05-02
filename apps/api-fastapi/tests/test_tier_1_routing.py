"""Loop Eta — Tier 1 Aiden routing taxonomy live-LLM smokes.

These nine tests confirm that Aiden's intent classification maps an
operator brief to the right Tier 2 `assigned_role` for each of the
nine sub-agent roles in the IWO3 taxonomy:

    mark_tier_2       — marketing / content / brief
    tom_tier_2        — decks / slides / PPTX
    hank_tier_2       — web / HTML / landing pages
    paul_tier_2       — deploy / publish
    jamie_tier_2      — scheduling / EA / stakeholder logistics
    nyx_tier_2        — security review / compliance / PII
    polaris_tier_2    — ops / SLA / KPI / capacity / oncall
    darla_tier_2      — design system / brand QA / visual consistency
    sop_master_tier_2 — SOP / procedure / process documentation

Each test issues one representative intake string and asserts:
  - decision_kind == "work_order_brief"
  - assigned_role == expected_role

Routing is a soft hint via the system prompt, so the assertion targets
Aiden's LLM classification, not regex matching. These tests SKIP when
GROQ_API_KEY is not present (env-clean CI) so the 277-test pytest
baseline stays green.

Hard locks honored:
  - decision schema shape unchanged
  - new prompt vocabulary only; no audit / schema / RBAC churn
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
import pytest

from runtime.tier_1_aiden import invoke_aiden_tier_1


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"

# Repo-root .env path used to lazily restore GROQ_API_KEY when an
# upstream test in the same pytest run popped it (see
# `test_tier_1_aiden.py::test_credential_missing_raises_typed_error`).
_ROUTING_ENV_PATH = (
    Path(__file__).resolve().parents[3] / ".env"
)


def _captured_groq_key() -> str | None:
    """Read GROQ_API_KEY from the on-disk repo .env once and cache.
    Used to restore the env var if a sibling pytest test pops it at
    runtime — without this, this file's tests would skip mid-suite even
    when the operator did set the key in their shell."""
    if hasattr(_captured_groq_key, "_cached"):
        return _captured_groq_key._cached  # type: ignore[attr-defined]
    val: str | None = os.environ.get("GROQ_API_KEY")
    if not val and _ROUTING_ENV_PATH.is_file():
        for line in _ROUTING_ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line.startswith("GROQ_API_KEY=") and "=" in line:
                val = line.split("=", 1)[1].strip().strip("\"'")
                break
    _captured_groq_key._cached = val  # type: ignore[attr-defined]
    return val


_GROQ_KEY = _captured_groq_key()


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)
needs_groq = pytest.mark.skipif(
    not _GROQ_KEY,
    reason="real LLM call needed (set GROQ_API_KEY)",
)


@pytest.fixture(autouse=True)
def _ensure_groq_key_present():
    """Restore GROQ_API_KEY for the duration of each routing test.

    `tests/test_tier_1_aiden.py::test_credential_missing_raises_typed_error`
    pops the var without restoring it, so when these routing tests run
    later in the same pytest session the credential resolver fails with
    `credential_missing`. We re-set the cached value on entry and leave
    the rest of the session unmodified on exit."""
    prior = os.environ.get("GROQ_API_KEY")
    if _GROQ_KEY:
        os.environ["GROQ_API_KEY"] = _GROQ_KEY
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("GROQ_API_KEY", None)
        else:
            os.environ["GROQ_API_KEY"] = prior


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(dsn=os.environ["IWO3_DATABASE_URL"])


# (intake_text, expected_role) — one row per Tier 2 role.
# Each intake is unambiguous in plain English and biased toward the
# vocabulary listed in tier_1_aiden's _AIDEN_OUTPUT_SCHEMA_TEMPLATE
# routing hints.
ROUTING_CASES: list[tuple[str, str]] = [
    (
        "Write a content brief for the Klear ICP marketing campaign.",
        "mark_tier_2",
    ),
    (
        "Draft a sales pitch deck for the Klear executive review — "
        "twelve slides, PPTX output.",
        "tom_tier_2",
    ),
    (
        "Build me a landing page for our 3M GTM launch with HTML and CSS.",
        "hank_tier_2",
    ),
    (
        "Take the finished Klear 3M landing page bundle in /tmp/klear-3m-lp "
        "and deploy it to production — push it live and finalize the "
        "external handoff.",
        "paul_tier_2",
    ),
    (
        "Schedule a meeting with Pat next Tuesday to coordinate the demo "
        "logistics with the vendor team.",
        "jamie_tier_2",
    ),
    (
        "Review this customer record for PII exposure and GDPR compliance "
        "issues — produce an audit finding.",
        "nyx_tier_2",
    ),
    (
        "Produce an ops report on this week's SLA breach rate, current "
        "KPI performance, capacity planning headroom, and any oncall "
        "escalation routing decisions for the operator.",
        "polaris_tier_2",
    ),
    (
        "Run a brand QA design-system review on the attached Klear "
        "landing page mockup — produce a written critique of brand "
        "consistency, visual design system adherence, and layout "
        "violations against our visual style guide.",
        "darla_tier_2",
    ),
    (
        "Document the standard operating procedure for client onboarding "
        "as a reusable workflow template.",
        "sop_master_tier_2",
    ),
]


def _run_routing_case(intake: str, expected_role: str) -> None:
    """Run a single routing smoke against a real LLM and assert role.

    Routing through a live LLM is not bit-deterministic (the seeded
    aiden_tier_1 config runs at temperature=0.3). To guard the
    taxonomy assertion against rare stochastic detours into
    "clarification" or a near-neighbour role, the helper retries up
    to MAX_ATTEMPTS times before failing — each attempt is a fresh
    LLM call. Both the final outcome and the per-attempt classifications
    are printed so a human can spot-check the LLM's behaviour from
    `pytest -v -s` output.
    """

    MAX_ATTEMPTS = 3
    attempts: list[tuple[str, str | None]] = []

    async def run() -> tuple[bool, str, str | None]:
        conn = await _connect()
        try:
            decision = await invoke_aiden_tier_1(
                conn,
                intake_text=intake,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
        finally:
            await conn.close()
        actual_role = (
            decision.work_order_brief.assigned_role
            if decision.work_order_brief
            else None
        )
        ok = (
            decision.decision_kind == "work_order_brief"
            and actual_role == expected_role
        )
        return ok, decision.decision_kind, actual_role

    last_kind: str | None = None
    last_role: str | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        ok, last_kind, last_role = asyncio.run(run())
        attempts.append((last_kind or "?", last_role))
        if ok:
            break

    # Always print the per-attempt log so reviewers can audit the LLM.
    print(
        f"\n[routing] intake={intake!r}\n"
        f"          attempts={attempts}\n"
        f"          expected_role={expected_role}"
    )

    assert last_kind == "work_order_brief", (
        f"Aiden returned decision_kind={last_kind!r} for intake "
        f"{intake!r} after {len(attempts)} attempt(s); expected "
        f"work_order_brief. attempts={attempts}"
    )
    assert last_role == expected_role, (
        f"Aiden routed intake {intake!r} to {last_role!r} after "
        f"{len(attempts)} attempt(s); expected {expected_role!r}. "
        f"attempts={attempts}"
    )


@iwo3_db
@needs_groq
def test_routing_marketing_to_mark() -> None:
    intake, role = ROUTING_CASES[0]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_deck_to_tom() -> None:
    intake, role = ROUTING_CASES[1]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_web_to_hank() -> None:
    intake, role = ROUTING_CASES[2]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_deploy_to_paul() -> None:
    intake, role = ROUTING_CASES[3]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_scheduling_to_jamie() -> None:
    intake, role = ROUTING_CASES[4]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_compliance_to_nyx() -> None:
    intake, role = ROUTING_CASES[5]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_ops_to_polaris() -> None:
    intake, role = ROUTING_CASES[6]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_design_to_darla() -> None:
    intake, role = ROUTING_CASES[7]
    _run_routing_case(intake, role)


@iwo3_db
@needs_groq
def test_routing_sop_to_sop_master() -> None:
    intake, role = ROUTING_CASES[8]
    _run_routing_case(intake, role)

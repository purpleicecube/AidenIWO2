"""Loop CAP-G CLOSEOUT Slice A — Darla revision-cycle wire-up tests.

Coverage:
  - `pass` verdict → brand_qa completes; deliver remains pending
  - `needs_revision` within cap → render + brand_qa both reset to
    pending; deliver remains pending; revision_count incremented;
    attestation appended to executive_review.darla_attempts[]
  - `needs_revision` at cap → brand_qa marked failed (cap_exceeded);
    deliver marked skipped; executive_review.darla_final_verdict =
    'needs_revision_capped'
  - `block` verdict → brand_qa marked failed; deliver marked skipped;
    executive_review.darla_final_verdict = 'block'
  - workflow_executions.executive_review.darla_attempts[] preserves
    full per-attempt audit history even when step_runs are reset

Each test sets up a synthetic workflow_execution + 4 step_runs
matching the CAP-C branded chain shape, then monkeypatches
`invoke_darla_qa` to return a controlled verdict, then calls
`_execute_branded_chain_step` directly and inspects post-state.

Skips when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import pytest

from runtime.darla_qa import BrandAttestation


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"
# Klear branded_pptx_chain template
KLEAR_BRANDED_PPTX_TEMPLATE_ID = "00000000-0000-4000-8000-000071000010"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture
def db_url() -> str:
    return os.environ["IWO3_DATABASE_URL"]


async def _open_tenant_conn(
    db_url: str, *, client_id: str
) -> asyncpg.Connection:
    conn = await asyncpg.connect(db_url)
    await conn.execute("SET LOCAL ROLE iwo3_app")
    await conn.execute(
        f"SET LOCAL app.current_client_id = '{client_id}'"
    )
    return conn


async def _setup_chain_execution(
    conn: asyncpg.Connection,
    *,
    client_id: str,
) -> tuple[str, dict, str]:
    """Create a synthetic workflow_execution + 4 step_runs that mimic
    a CAP-C branded_pptx_chain mid-flight (render completed with a
    package; brand_qa pending). Returns (execution_id,
    step_run_ids_by_key, render_package_id)."""
    execution_id = str(uuid.uuid4())
    render_pkg_id = str(uuid.uuid4())

    # Output package the render step "produced" (synthetic).
    await conn.execute(
        """
        INSERT INTO output_packages
          (id, client_id, output_kind, work_order_id, workflow_execution_id,
           title, summary, content_blocks, status, correlation_id)
        VALUES ($1::uuid, $2::uuid, 'sandbox_pptx'::output_package_kind, NULL, NULL,
                $3, $4, $5::jsonb, 'draft'::output_package_status, $6)
        """,
        render_pkg_id,
        client_id,
        "Klear deck (test fixture)",
        "test summary",
        json.dumps({"content_markdown": "Test slide body for Klear branded PPTX."}),
        f"cap-g-test:{render_pkg_id[:8]}",
    )

    await conn.execute(
        """
        INSERT INTO workflow_executions
          (id, client_id, template_id, work_order_id, status, current_step_key, created_at, updated_at)
        VALUES ($1::uuid, $2::uuid, $3::uuid, NULL,
                'running'::workflow_execution_status, 'brand_qa', now(), now())
        """,
        execution_id,
        client_id,
        KLEAR_BRANDED_PPTX_TEMPLATE_ID,
    )

    step_ids: dict[str, str] = {}
    steps = [
        ("content_brief", 1, "completed", None),
        ("render", 2, "completed", render_pkg_id),
        ("brand_qa", 3, "running", None),
        ("deliver", 4, "pending", None),
    ]
    for step_key, step_order, step_status, pkg_id in steps:
        sr_id = str(uuid.uuid4())
        step_ids[step_key] = sr_id
        # workflow_step_runs has no output_package_id column;
        # outputPackageId is carried in the output jsonb (matches the
        # convention the production execute_step_run writer uses at
        # tier_2_subagents.py output line 1172).
        output_json = (
            json.dumps({"outputPackageId": pkg_id})
            if pkg_id and step_status == "completed"
            else None
        )
        await conn.execute(
            """
            INSERT INTO workflow_step_runs
              (id, execution_id, step_key, step_order, status,
               input, output, started_at, completed_at,
               created_at, updated_at)
            VALUES ($1::uuid, $2::uuid, $3, $4::int, $5::workflow_step_run_status,
                    '{}'::jsonb, $6::jsonb,
                    CASE WHEN $5::workflow_step_run_status IN ('running'::workflow_step_run_status, 'completed'::workflow_step_run_status) THEN now() ELSE NULL END,
                    CASE WHEN $5::workflow_step_run_status = 'completed'::workflow_step_run_status THEN now() ELSE NULL END,
                    now(), now())
            """,
            sr_id,
            execution_id,
            step_key,
            step_order,
            step_status,
            output_json,
        )

    return execution_id, step_ids, render_pkg_id


def _make_attestation(verdict: str, notes: list[str] | None = None) -> BrandAttestation:
    return BrandAttestation(
        overall=verdict,  # type: ignore[arg-type]
        palette_pass=(verdict == "pass"),
        fonts_pass=(verdict == "pass"),
        voice_pass=(verdict == "pass"),
        asset_pass=(verdict == "pass"),
        notes=tuple(notes or []),
    )


async def _stub_darla(*args, **kwargs) -> BrandAttestation:
    """Default stub — replaced in each test via monkeypatch."""
    return _make_attestation("pass")


# ── Test 1: pass verdict → completion, deliver unchanged ─────────


@iwo3_db
def test_darla_pass_completes_brand_qa_and_leaves_deliver_pending(
    db_url: str, monkeypatch
) -> None:
    from runtime import tier_2_subagents

    async def stub(*args, **kwargs):
        return _make_attestation("pass")

    from runtime import darla_qa as _darla_module
    monkeypatch.setattr(_darla_module, "invoke_darla_qa", stub)

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            execution_id, step_ids, render_pkg_id = await _setup_chain_execution(
                conn, client_id=KLEAR_CLIENT
            )
            await tier_2_subagents._execute_branded_chain_step(
                conn,
                step_run_id=step_ids["brand_qa"],
                execution_id=execution_id,
                step_key="brand_qa",
                step_order=3,
                work_order_id=None,
                display_name="brand qa",
                assigned_role="darla_tier_2",
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                intake_text="Klear branded PPTX test",
                input_payload={},
                memory_block="",
            )
            # brand_qa step should be completed with verdict=pass
            brand_qa_row = await conn.fetchrow(
                "SELECT status::text AS status, output::text AS output FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["brand_qa"],
            )
            assert brand_qa_row["status"] == "completed"
            output = json.loads(brand_qa_row["output"])
            assert output["verdict"] == "pass"
            # deliver step remains pending (will fire next via run_next_step)
            deliver_row = await conn.fetchrow(
                "SELECT status::text AS status FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["deliver"],
            )
            assert deliver_row["status"] == "pending"
            # executive_review carries the pass attempt
            review_raw = await conn.fetchval(
                "SELECT executive_review::text FROM workflow_executions WHERE id = $1::uuid",
                execution_id,
            )
            review = json.loads(review_raw)
            assert len(review["darla_attempts"]) == 1
            assert review["darla_attempts"][0]["verdict"] == "pass"
        finally:
            await conn.close()

    asyncio.run(run())


# ── Test 2: needs_revision within cap → reset render + brand_qa ──


@iwo3_db
def test_darla_needs_revision_within_cap_resets_render_and_brand_qa(
    db_url: str, monkeypatch
) -> None:
    from runtime import tier_2_subagents

    async def stub(*args, **kwargs):
        return _make_attestation(
            "needs_revision", notes=["Heading font is wrong"]
        )

    from runtime import darla_qa as _darla_module
    monkeypatch.setattr(_darla_module, "invoke_darla_qa", stub)

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            execution_id, step_ids, render_pkg_id = await _setup_chain_execution(
                conn, client_id=KLEAR_CLIENT
            )
            await tier_2_subagents._execute_branded_chain_step(
                conn,
                step_run_id=step_ids["brand_qa"],
                execution_id=execution_id,
                step_key="brand_qa",
                step_order=3,
                work_order_id=None,
                display_name="brand qa",
                assigned_role="darla_tier_2",
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                intake_text="Klear branded PPTX test",
                input_payload={},
                memory_block="",
            )
            # render step should be reset to pending with revision notes
            render_row = await conn.fetchrow(
                "SELECT status::text AS status, input::text AS input, output, started_at, completed_at FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["render"],
            )
            assert render_row["status"] == "pending"
            assert render_row["started_at"] is None
            assert render_row["completed_at"] is None
            # output cleared on reset (the outputPackageId in output JSON was wiped)
            assert render_row["output"] is None
            input_payload = json.loads(render_row["input"])
            assert "darla_revision_notes" in input_payload
            assert input_payload["darla_revision_notes"] == ["Heading font is wrong"]
            assert input_payload["darla_revision_attempt"] == 1
            # brand_qa step should be reset to pending too (will re-run after render)
            brand_qa_row = await conn.fetchrow(
                "SELECT status::text AS status, output::text AS output FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["brand_qa"],
            )
            assert brand_qa_row["status"] == "pending"
            assert brand_qa_row["output"] is None
            # deliver step remains pending (NOT skipped — within cap)
            deliver_row = await conn.fetchrow(
                "SELECT status::text AS status FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["deliver"],
            )
            assert deliver_row["status"] == "pending"
            # executive_review carries attempt + revision count
            review = json.loads(
                await conn.fetchval(
                    "SELECT executive_review::text FROM workflow_executions WHERE id = $1::uuid",
                    execution_id,
                )
            )
            assert review["darla_revision_count"] == 1
            assert len(review["darla_attempts"]) == 1
            assert review["darla_attempts"][0]["verdict"] == "needs_revision"
            assert review["darla_attempts"][0]["notes"] == ["Heading font is wrong"]
            assert "darla_final_verdict" not in review  # not terminal
        finally:
            await conn.close()

    asyncio.run(run())


# ── Test 3: needs_revision at cap → terminal failed + deliver skipped ──


@iwo3_db
def test_darla_needs_revision_at_cap_fails_brand_qa_and_skips_deliver(
    db_url: str, monkeypatch
) -> None:
    from runtime import tier_2_subagents

    async def stub(*args, **kwargs):
        return _make_attestation(
            "needs_revision", notes=["Still wrong"]
        )

    from runtime import darla_qa as _darla_module
    monkeypatch.setattr(_darla_module, "invoke_darla_qa", stub)

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            execution_id, step_ids, _ = await _setup_chain_execution(
                conn, client_id=KLEAR_CLIENT
            )
            # Pre-seed: this is attempt 2 (cap = 2 → at-cap)
            await conn.execute(
                """
                UPDATE workflow_executions
                   SET executive_review = jsonb_build_object('darla_revision_count', 1)
                 WHERE id = $1::uuid
                """,
                execution_id,
            )
            await tier_2_subagents._execute_branded_chain_step(
                conn,
                step_run_id=step_ids["brand_qa"],
                execution_id=execution_id,
                step_key="brand_qa",
                step_order=3,
                work_order_id=None,
                display_name="brand qa",
                assigned_role="darla_tier_2",
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                intake_text="Klear branded PPTX test",
                input_payload={},
                memory_block="",
            )
            # brand_qa step should be FAILED with cap_exceeded
            brand_qa_row = await conn.fetchrow(
                "SELECT status::text AS status, output::text AS output FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["brand_qa"],
            )
            assert brand_qa_row["status"] == "failed"
            output = json.loads(brand_qa_row["output"])
            assert output["verdict"] == "needs_revision"
            assert output["cap_exceeded"] is True
            assert output["attempt"] == 2
            # deliver step should be SKIPPED
            deliver_row = await conn.fetchrow(
                "SELECT status::text AS status, output::text AS output FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["deliver"],
            )
            assert deliver_row["status"] == "skipped"
            deliver_out = json.loads(deliver_row["output"])
            assert deliver_out["reason"] == "brand_qa_revision_cap_exceeded"
            assert deliver_out["darla_verdict"] == "needs_revision"
            # executive_review carries final verdict
            review = json.loads(
                await conn.fetchval(
                    "SELECT executive_review::text FROM workflow_executions WHERE id = $1::uuid",
                    execution_id,
                )
            )
            assert review["darla_final_verdict"] == "needs_revision_capped"
            assert review["darla_final_attempt"] == 2
        finally:
            await conn.close()

    asyncio.run(run())


# ── Test 4: block verdict → terminal failed + deliver skipped ────


@iwo3_db
def test_darla_block_fails_brand_qa_and_skips_deliver(
    db_url: str, monkeypatch
) -> None:
    from runtime import tier_2_subagents

    async def stub(*args, **kwargs):
        return _make_attestation(
            "block", notes=["Off-brand colors; not Klear"]
        )

    from runtime import darla_qa as _darla_module
    monkeypatch.setattr(_darla_module, "invoke_darla_qa", stub)

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            execution_id, step_ids, _ = await _setup_chain_execution(
                conn, client_id=KLEAR_CLIENT
            )
            await tier_2_subagents._execute_branded_chain_step(
                conn,
                step_run_id=step_ids["brand_qa"],
                execution_id=execution_id,
                step_key="brand_qa",
                step_order=3,
                work_order_id=None,
                display_name="brand qa",
                assigned_role="darla_tier_2",
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                intake_text="Klear branded PPTX test",
                input_payload={},
                memory_block="",
            )
            # brand_qa step should be FAILED with verdict=block
            brand_qa_row = await conn.fetchrow(
                "SELECT status::text AS status, output::text AS output FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["brand_qa"],
            )
            assert brand_qa_row["status"] == "failed"
            output = json.loads(brand_qa_row["output"])
            assert output["verdict"] == "block"
            assert output["cap_exceeded"] is False
            # deliver step should be SKIPPED
            deliver_row = await conn.fetchrow(
                "SELECT status::text AS status, output::text AS output FROM workflow_step_runs WHERE id = $1::uuid",
                step_ids["deliver"],
            )
            assert deliver_row["status"] == "skipped"
            deliver_out = json.loads(deliver_row["output"])
            assert deliver_out["reason"] == "brand_qa_blocked"
            assert deliver_out["darla_verdict"] == "block"
            # executive_review carries final verdict
            review = json.loads(
                await conn.fetchval(
                    "SELECT executive_review::text FROM workflow_executions WHERE id = $1::uuid",
                    execution_id,
                )
            )
            assert review["darla_final_verdict"] == "block"
        finally:
            await conn.close()

    asyncio.run(run())


# ── Test 5: attempt history preserved across resets ──────────────


@iwo3_db
def test_darla_attempt_history_preserved_across_revision_cycle(
    db_url: str, monkeypatch
) -> None:
    """After a revision cycle resets the step_runs, the per-attempt
    audit history must persist on workflow_executions.executive_review
    so operators can review past Darla verdicts even though step_runs
    no longer carry them."""
    from runtime import tier_2_subagents

    call_count = {"n": 0}

    async def stub(*args, **kwargs):
        call_count["n"] += 1
        # First call returns needs_revision; subsequent calls would
        # also return needs_revision but we only invoke once here.
        return _make_attestation(
            "needs_revision", notes=[f"Attempt-{call_count['n']} note"]
        )

    from runtime import darla_qa as _darla_module
    monkeypatch.setattr(_darla_module, "invoke_darla_qa", stub)

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            execution_id, step_ids, _ = await _setup_chain_execution(
                conn, client_id=KLEAR_CLIENT
            )
            # First cycle (within cap)
            await tier_2_subagents._execute_branded_chain_step(
                conn,
                step_run_id=step_ids["brand_qa"],
                execution_id=execution_id,
                step_key="brand_qa",
                step_order=3,
                work_order_id=None,
                display_name="brand qa",
                assigned_role="darla_tier_2",
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                intake_text="Klear branded PPTX test",
                input_payload={},
                memory_block="",
            )
            review = json.loads(
                await conn.fetchval(
                    "SELECT executive_review::text FROM workflow_executions WHERE id = $1::uuid",
                    execution_id,
                )
            )
            assert len(review["darla_attempts"]) == 1
            assert review["darla_attempts"][0]["attempt"] == 1
            assert review["darla_attempts"][0]["notes"] == ["Attempt-1 note"]
        finally:
            await conn.close()

    asyncio.run(run())

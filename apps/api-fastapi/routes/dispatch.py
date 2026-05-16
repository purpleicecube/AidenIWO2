"""Pre-Beta β.3 — end-to-end dispatch routes.

Closes the Alpha truth gap where Tier 1 / Tier 1.5 / Tier 2 helpers
existed but no product flow reached them. Two routes:

  POST /work_orders/{id}/dispatch
       Reads the WO (title + description), runs Aiden Tier 1, branches:
         work_order_brief  → invoke Tier 2 + persist output_package
         workflow_brief    → instantiate workflow + step_runs
         clarification     → return question; no DB changes
       RBAC: work_order:update.

  POST /workflows/{execution_id}/run_next_step
       Pick the first `pending` step_run for an execution and execute
       it (Tier 2). Returns the step result + the next pending step
       (or null if the workflow finished).
       RBAC: workflow_step_run:update.

Both paths are inline (synchronous); async-polling for Tier 2 results
is a Beta concern. Output packages with `gamma_*` kinds get picked up
by the existing Loop 9 handoff worker.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from adapter.dispatch import DispatchError, dispatch_gamma_for_package
from authz.audit_writer import write_audit_row
from memory.dispatch_grounding import prefetch_dispatch_grounding
from memory.wrappers import (
    memory_context_builder_for_subagent,
    memory_context_builder_for_workflow,
)
from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)
from runtime.budgets import LlmBudgetExceeded
from runtime.tier_1_aiden import (
    AidenInvocationError,
    AidenNoConfig,
    invoke_aiden_tier_1,
)
from runtime.tier_1_5_pm import (
    PmError,
    instantiate_workflow_from_brief,
)
from runtime.tier_2_subagents import (
    Tier2Error,
    execute_step_run,
    invoke_tier_2,
    produce_output_package,
)
from runtime.template_resolver import (
    TemplateResolution,
    resolve_template_for_client,
)
from runtime.aiden_branded_intent import (
    BrandedIntent,
    detect_branded_intent,
)
from runtime.tier_1_aiden import (
    AidenWorkflowBrief,
)
from wo_wf.transitions import (
    IllegalTransition,
    PermissionDenied,
    RowNotFound,
    transition_work_order,
)


router = APIRouter(tags=["dispatch"])


# ── POST /work_orders/{id}/dispatch ───────────────────────────────────


class DispatchRequest(BaseModel):
    intake_override: Optional[str] = Field(
        None,
        max_length=8000,
        description=(
            "Override the intake text Aiden Tier 1 sees. Defaults to "
            "the WO's title + description. Useful when the operator "
            "wants to clarify intent without re-saving the WO."
        ),
    )


class DispatchResponse(BaseModel):
    ok: bool
    decision_kind: Optional[str] = None
    work_order_id: str
    output_package_id: Optional[str] = None
    workflow_execution_id: Optional[str] = None
    step_run_ids: Optional[list[str]] = None
    clarification_question: Optional[str] = None
    handoff_id: Optional[str] = None
    error: Optional[str] = None


async def _maybe_resolve_template_into_wo(
    conn: asyncpg.Connection,
    *,
    work_order: dict,
    client_id: str,
    intake_text: str,
) -> Optional[TemplateResolution]:
    """Loop CAP-B Φ.2 — wire the shared template resolver into dispatch.

    The dispatch path needs the same deterministic intake-keyword
    template match the chat path runs at routes/aiden.py post-
    classification. WOs submitted without an explicit template (e.g.
    via Submit Order without picker, or via auto-dispatch from a
    natural-language chat that pre-dates the chat-route resolver)
    arrive here with `requested_outputs.template_profile_id == NULL`,
    forcing `dispatch_gamma_for_package` to fire with NULL template
    ref and Gamma to fall back to defaults — the very failure mode
    that triggered the orchestration CAP.

    This helper:
      1. Reads the live `requested_outputs` shape (single jsonb object
         per migration 0019 — invariant, AC-21).
      2. Skips if a `template_profile_id` is already present (operator
         picked one in Submit Order, or chat-route resolver already
         fired). Idempotent.
      3. Otherwise calls `resolve_template_for_client` with the WO
         intake (title + description). Same resolver chat uses.
      4. On a `matched` resolution, UPDATEs the WO's
         `requested_outputs` to the single-object shape
         `{output_kind, template_profile_id}` so the existing
         propagation block downstream picks it up naturally.

    Returns the resolution (or None when skipped) for caller-side
    audit / instrumentation.

    Honors:
      - D11 — uses `template_profiles.output_kind` enum, no new routing enum.
      - D13 — `requested_outputs` stays single-object; no promotion.
      - P2  — chat and dispatch routes share the same resolver callable.
    """
    # Read existing requested_outputs (jsonb single object). The wo
    # row dict carries it as a JSON string OR a dict depending on the
    # asyncpg codec wiring; accept both.
    existing_raw: Any = work_order.get("requested_outputs")
    existing: Optional[dict] = None
    if isinstance(existing_raw, dict):
        existing = existing_raw
    elif isinstance(existing_raw, str):
        try:
            existing = json.loads(existing_raw)
        except (json.JSONDecodeError, ValueError):
            existing = None

    if isinstance(existing, dict) and existing.get("template_profile_id"):
        # Already resolved upstream (Submit Order picker or chat route).
        return None

    try:
        resolution = await resolve_template_for_client(
            conn,
            client_id=client_id,
            intake_text=intake_text,
        )
    except Exception:  # noqa: BLE001
        # Resolver is best-effort over a pure-LLM baseline. Never
        # block dispatch on resolver failures (matches chat route's
        # same try/except posture in routes/aiden.py).
        return None

    if resolution.kind != "matched" or resolution.match is None:
        return resolution

    new_shape = {
        "output_kind": resolution.match.output_kind,
        "template_profile_id": resolution.match.template_profile_id,
    }
    # Merge with any other keys the operator put in requested_outputs
    # (defensive: no current writers add extras, but preserve them).
    if isinstance(existing, dict):
        merged = dict(existing)
        merged.update(new_shape)
    else:
        merged = new_shape

    await conn.execute(
        """
        UPDATE work_orders
           SET requested_outputs = $2::jsonb,
               updated_at = now()
         WHERE id = $1::uuid
           AND client_id = $3::uuid
        """,
        work_order["id"],
        json.dumps(merged),
        client_id,
    )
    return resolution


async def _safe_transition_processing(
    conn: asyncpg.Connection,
    *,
    work_order_id: str,
    client_id: str,
    actor_user_id: str,
    reason: str,
) -> None:
    """Move a WO to `processing` if it isn't already; swallow IllegalTransition
    (already in a downstream state) so the caller's happy path isn't blocked."""
    try:
        await transition_work_order(
            conn,
            work_order_id=work_order_id,
            client_id=client_id,
            actor_user_id=actor_user_id,
            to="processing",
            reason=reason,
        )
    except IllegalTransition:
        pass  # already past pending; that's fine
    except RowNotFound:
        pass  # caller already raised 404 if needed


@router.post(
    "/work_orders/{work_order_id}/dispatch",
    response_model=DispatchResponse,
    dependencies=[Depends(require_permission_dep("work_order:update"))],
)
async def dispatch_work_order(
    work_order_id: str,
    body: DispatchRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> DispatchResponse:
    try:
        wo = await conn.fetchrow(
            """
            SELECT id::text                 AS id,
                   title,
                   description,
                   status::text             AS status,
                   requested_outputs::text  AS requested_outputs
              FROM work_orders
             WHERE id = $1::uuid AND client_id = $2::uuid
            """,
            work_order_id,
            ctx["client_id"],
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_work_order_id", "value": work_order_id},
        )
    if wo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "not_found", "work_order_id": work_order_id},
        )

    intake_text = (
        body.intake_override
        or f"{wo['title']}\n\n{wo['description'] or ''}".strip()
    )

    try:
        decision = await invoke_aiden_tier_1(
            conn,
            intake_text=intake_text,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            work_order_id=wo["id"],
        )
    except AidenNoConfig as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "no_aiden_config", "detail": str(exc)},
        )
    except LlmBudgetExceeded as exc:
        return DispatchResponse(
            ok=False,
            work_order_id=wo["id"],
            error=(
                f"llm_budget_exceeded: used {exc.already_used} of ceiling "
                f"{exc.ceiling}"
            ),
        )
    except AidenInvocationError as exc:
        return DispatchResponse(
            ok=False,
            work_order_id=wo["id"],
            error=f"{exc.kind}: {exc}",
        )

    if decision.decision_kind == "clarification":
        c = decision.clarification
        return DispatchResponse(
            ok=False,
            decision_kind="clarification",
            work_order_id=wo["id"],
            clarification_question=(
                c.question if c else "(no question returned)"
            ),
        )

    if decision.decision_kind == "assistant_reply":
        # Operator submitted a WO with conversational intake (no concrete
        # work). Don't dispatch; surface Aiden's reply so the operator
        # can rewrite the WO with actual deliverable language.
        a = decision.assistant_reply
        return DispatchResponse(
            ok=False,
            decision_kind="assistant_reply",
            work_order_id=wo["id"],
            error=(
                a.message if a else "(no message returned)"
            ),
        )

    # Loop CAP-E Φ.8 — branded-intent classification + chain routing.
    # Runs only when Aiden chose work_order_brief (the default for
    # output-bearing intake). When the deterministic detector finds
    # branded intent AND output_surface_routes has a matching chain,
    # this overrides decision_kind to "workflow_brief" with the
    # resolved chain key, and the existing workflow_brief branch
    # below handles instantiation. P7 / D8 / D14 locks honored.
    # Detector always emits `aiden.branded_intent_detected` audit;
    # may also emit multi_template_disambiguated +
    # template_clarification_requested.
    if decision.decision_kind == "work_order_brief":
        existing_ro_raw = wo.get("requested_outputs")
        existing_ro: Optional[dict] = None
        if isinstance(existing_ro_raw, dict):
            existing_ro = existing_ro_raw
        elif isinstance(existing_ro_raw, str):
            try:
                existing_ro = json.loads(existing_ro_raw)
            except (json.JSONDecodeError, ValueError):
                existing_ro = None
        explicit_template_id = (
            existing_ro.get("template_profile_id")
            if isinstance(existing_ro, dict)
            else None
        )
        explicit_kind = (
            existing_ro.get("output_kind")
            if isinstance(existing_ro, dict)
            else None
        )
        try:
            intent = await detect_branded_intent(
                conn,
                client_id=ctx["client_id"],
                intake_text=intake_text,
                actor_user_id=ctx["user_id"],
                explicit_template_profile_id=(
                    str(explicit_template_id) if explicit_template_id else None
                ),
                explicit_output_kind=(
                    str(explicit_kind) if explicit_kind else None
                ),
            )
        except Exception:  # noqa: BLE001
            # Detector failure must not block dispatch; fall through
            # to existing single-shot path. Detector emits its own
            # audit on the way out via the helper.
            intent = None  # type: ignore[assignment]

        if intent is not None and intent.is_branded and intent.workflow_key:
            # Override Aiden's choice. Build a workflow_brief decision
            # carrying the resolved chain key + key intent fields in
            # step_inputs for downstream visibility.
            from dataclasses import replace as _dc_replace

            new_workflow_brief = AidenWorkflowBrief(
                workflow_template_key=intent.workflow_key,
                step_inputs={
                    "branded_intent_detected": True,
                    "detected_brand_keywords": list(intent.detected_brand_keywords),
                    "detected_output_kind": intent.detected_output_kind,
                    "detected_design_input_source": intent.detected_design_input_source,
                    "selected_template_profile_id": intent.selected_template_profile_id,
                    "primary_adapter_key": intent.primary_adapter_key,
                    "fallback_adapter_keys": list(intent.fallback_adapter_keys),
                },
            )
            decision = _dc_replace(
                decision,
                decision_kind="workflow_brief",
                workflow_brief=new_workflow_brief,
                work_order_brief=None,
            )

    await _safe_transition_processing(
        conn,
        work_order_id=wo["id"],
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        reason=f"dispatch:{decision.decision_kind}",
    )

    if decision.decision_kind == "work_order_brief":
        brief = decision.work_order_brief
        assert brief is not None

        # Loop CAP-B Φ.2 — wire shared template_resolver into dispatch.
        # If the WO didn't carry an explicit template (Submit Order
        # picker or chat-route resolver), run the same deterministic
        # resolver here against the WO intake (title + description).
        # On a `matched` resolution this UPDATEs `requested_outputs`
        # to the live single-object shape; the existing propagation
        # block downstream picks `template_profile_id` up unchanged.
        # No-op when the WO already carries a template — idempotent.
        await _maybe_resolve_template_into_wo(
            conn,
            work_order=dict(wo),
            client_id=ctx["client_id"],
            intake_text=intake_text,
        )

        # Loop CAP-B Φ.3 — pre-fetch tenant brand grounding before
        # the Tier-2 bundle assembles. The prefetch helper emits its
        # own `memory.applied surface=dispatch_prefetch` audit row
        # and returns a `MemorySource(kind=client_grounding)` (or
        # None if the tenant has no meaningful brand profile yet).
        # The source is prepended to the Tier-2 bundle's sources
        # (slot 0, above canonical_facts) so Tom sees brand truth
        # before any retrieved content.
        grounding_source = await prefetch_dispatch_grounding(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
        )

        # Loop Lambda — assemble a Tier-2 memory bundle before invoking
        # the sub-agent. Fresh assembly per invocation (D-L2 default);
        # Tier-1 chat bundle NOT propagated. Bypass / no_sources falls
        # through with empty block — Tier-2 still runs.
        tier2_bundle = await memory_context_builder_for_subagent(
            conn,
            client_id=ctx["client_id"],
            work_order_id=wo["id"],
            sub_agent_role=brief.assigned_role,
            intake_text=intake_text,
            actor_user_id=ctx["user_id"],
            prefetch_sources=(
                [grounding_source] if grounding_source else None
            ),
        )
        try:
            envelope = await invoke_tier_2(
                conn,
                role=brief.assigned_role,
                intake_text=intake_text,
                content_blocks=brief.content_blocks or {},
                work_order_id=wo["id"],
                client_id=ctx["client_id"],
                actor_user_id=ctx["user_id"],
                memory_block=tier2_bundle.block,
            )
        except LlmBudgetExceeded as exc:
            return DispatchResponse(
                ok=False,
                decision_kind="work_order_brief",
                work_order_id=wo["id"],
                error=(
                    f"tier_2_budget_exceeded: used {exc.already_used} "
                    f"of ceiling {exc.ceiling}"
                ),
            )
        except Tier2Error as exc:
            return DispatchResponse(
                ok=False,
                decision_kind="work_order_brief",
                work_order_id=wo["id"],
                error=f"{exc.args[0] if exc.args else 'tier_2_failed'}: {exc}",
            )

        # Beta-2 phase 0.2 — read operator-supplied requested_outputs
        # from the WO and propagate template_profile_id into the package.
        # Without this propagation the package row is unbound and the
        # adapter dispatcher can only fall back to inference.
        requested_template_id: Optional[str] = None
        # lint:bypass-rls-explain="conn is already tenant-scoped via get_tenant_scoped_connection (iwo3_app + app.current_client_id GUC); RLS filters work_orders to active tenant transparently"
        wo_ro_row = await conn.fetchrow(
            "SELECT requested_outputs::text AS ro FROM work_orders WHERE id = $1::uuid",
            wo["id"],
        )
        if wo_ro_row is not None and wo_ro_row["ro"]:
            try:
                ro = json.loads(wo_ro_row["ro"])
                tpl = ro.get("template_profile_id")
                if isinstance(tpl, str) and tpl:
                    requested_template_id = tpl
            except (json.JSONDecodeError, AttributeError):
                pass

        pkg_id = await produce_output_package(
            conn,
            envelope=envelope,
            title=decision.title or wo["title"],
            work_order_id=wo["id"],
            workflow_execution_id=None,
            template_profile_id=requested_template_id,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            correlation_id=f"dispatch:{wo['id']}",
        )

        # Beta-2 phase 0.2 — auto-create the output_handoff + submit to
        # Gamma when the package is gamma_*-kinded. The poll_worker
        # advances from here; `_maybe_cascade_wo_completed` (Loop 9)
        # auto-transitions the WO to completed when the handoff lands.
        # Failure is non-fatal — we still return the package id; the
        # operator can hit `/work_orders/{id}/render` to retry.
        handoff_id: Optional[str] = None
        dispatch_error: Optional[str] = None
        if envelope.output_kind.startswith("gamma_"):
            try:
                result = await dispatch_gamma_for_package(
                    conn,
                    output_package_id=pkg_id,
                    client_id=ctx["client_id"],
                    actor_user_id=ctx["user_id"],
                )
                handoff_id = result.handoff_id
            except DispatchError as exc:
                dispatch_error = f"{exc.kind}: {exc.detail}"
                # Audit the failed-to-dispatch case so operators can see why.
                await write_audit_row(
                    conn,
                    client_id=ctx["client_id"],
                    actor_user_id=ctx["user_id"],
                    event="adapter_dispatch.failed",
                    target_type="output_package",
                    target_id=pkg_id,
                    metadata={
                        "kind": exc.kind,
                        "detail": exc.detail,
                        "stage": "auto_dispatch_post_package",
                    },
                )

        return DispatchResponse(
            ok=True,
            decision_kind="work_order_brief",
            work_order_id=wo["id"],
            output_package_id=pkg_id,
            handoff_id=handoff_id,
            error=dispatch_error,
        )

    if decision.decision_kind == "workflow_brief":
        brief = decision.workflow_brief
        assert brief is not None
        # Loop Lambda — assemble a PM memory bundle before invoking
        # PM Tier-1.5 elaboration. PM gets MEMORY_BUDGET_TIER_1_5
        # (1.5K) per D-L1 default; surface tag "tier_1_5_pm".
        pm_bundle = await memory_context_builder_for_workflow(
            conn,
            client_id=ctx["client_id"],
            work_order_id=wo["id"],
            workflow_execution_id=None,
            intake_text=intake_text,
            actor_user_id=ctx["user_id"],
        )
        try:
            inst = await instantiate_workflow_from_brief(
                conn,
                brief=brief,
                intake_text=intake_text,
                aiden_summary=decision.summary,
                work_order_id=wo["id"],
                client_id=ctx["client_id"],
                actor_user_id=ctx["user_id"],
                memory_block=pm_bundle.block,
            )
        except PmError as exc:
            return DispatchResponse(
                ok=False,
                decision_kind="workflow_brief",
                work_order_id=wo["id"],
                error=f"pm_failed: {exc}",
            )

        return DispatchResponse(
            ok=True,
            decision_kind="workflow_brief",
            work_order_id=wo["id"],
            workflow_execution_id=inst.workflow_execution_id,
            step_run_ids=list(inst.step_run_ids),
        )

    return DispatchResponse(
        ok=False,
        decision_kind=decision.decision_kind,
        work_order_id=wo["id"],
        error=f"unsupported_decision_kind: {decision.decision_kind}",
    )


# ── POST /workflows/{execution_id}/run_next_step ──────────────────────


class RunNextStepResponse(BaseModel):
    ok: bool
    execution_id: str
    step_run_id: Optional[str] = None
    step_key: Optional[str] = None
    output_package_id: Optional[str] = None
    next_step_run_id: Optional[str] = None
    workflow_finished: bool = False
    error: Optional[str] = None


@router.post(
    "/workflows/{execution_id}/run_next_step",
    response_model=RunNextStepResponse,
    dependencies=[Depends(require_permission_dep("workflow_step_run:update"))],
)
async def run_next_step(
    execution_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> RunNextStepResponse:
    try:
        exec_row = await conn.fetchrow(
            """
            SELECT id::text AS id, status::text AS status
              FROM workflow_executions
             WHERE id = $1::uuid AND client_id = $2::uuid
            """,
            execution_id,
            ctx["client_id"],
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_execution_id", "value": execution_id},
        )
    if exec_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "execution_not_found", "id": execution_id},
        )

    next_pending = await conn.fetchrow(
        """
        SELECT id::text AS id, step_key, step_order
          FROM workflow_step_runs
         WHERE execution_id = $1::uuid
           AND status = 'pending'::workflow_step_run_status
         ORDER BY step_order ASC
         LIMIT 1
        """,
        execution_id,
    )
    if next_pending is None:
        return RunNextStepResponse(
            ok=True,
            execution_id=execution_id,
            workflow_finished=True,
        )

    # Loop Lambda — assemble a Tier-2 memory bundle for this step.
    # The intake is the step_key + display_name (resolved inside
    # execute_step_run); the wrapper looks up the step's role + WO
    # for tenant + operator scope.
    step_meta = await conn.fetchrow(
        """
        SELECT wts.assigned_sub_agent_key,
               coalesce(wts.display_name, wts.step_key) AS intake_label,
               we.work_order_id::text AS work_order_id
          FROM workflow_step_runs sr
          JOIN workflow_executions we ON we.id = sr.execution_id
          JOIN workflow_template_steps wts
            ON wts.template_id = we.template_id
           AND wts.step_key = sr.step_key
         WHERE sr.id = $1::uuid AND we.client_id = $2::uuid
        """,
        next_pending["id"],
        ctx["client_id"],
    )
    step_role = (step_meta["assigned_sub_agent_key"] if step_meta else None) or "mark"
    step_intake = (step_meta["intake_label"] if step_meta else None) or next_pending["step_key"]
    step_wo_id = step_meta["work_order_id"] if step_meta else None
    step_bundle = await memory_context_builder_for_subagent(
        conn,
        client_id=ctx["client_id"],
        work_order_id=step_wo_id,
        sub_agent_role=step_role,
        intake_text=step_intake,
        actor_user_id=ctx["user_id"],
    )

    try:
        result = await execute_step_run(
            conn,
            step_run_id=next_pending["id"],
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            memory_block=step_bundle.block,
        )
    except Tier2Error as exc:
        return RunNextStepResponse(
            ok=False,
            execution_id=execution_id,
            step_run_id=next_pending["id"],
            step_key=next_pending["step_key"],
            error=f"{exc.args[0] if exc.args else 'tier_2_failed'}: {exc}",
        )

    follow_up = await conn.fetchrow(
        """
        SELECT id::text AS id
          FROM workflow_step_runs
         WHERE execution_id = $1::uuid
           AND status = 'pending'::workflow_step_run_status
         ORDER BY step_order ASC
         LIMIT 1
        """,
        execution_id,
    )

    return RunNextStepResponse(
        ok=True,
        execution_id=execution_id,
        step_run_id=next_pending["id"],
        step_key=next_pending["step_key"],
        output_package_id=result.output_package_id,
        next_step_run_id=follow_up["id"] if follow_up else None,
        workflow_finished=follow_up is None,
    )


# ── BUG-067 — convenience route: advance the next step by WO id ──────


@router.post(
    "/work_orders/{work_order_id}/run_next_workflow_step",
    response_model=RunNextStepResponse,
    dependencies=[Depends(require_permission_dep("workflow_step_run:update"))],
)
async def run_next_workflow_step_by_wo(
    work_order_id: str,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> RunNextStepResponse:
    """Operator convenience — resolves the WO's most recent running
    workflow_execution and delegates to `run_next_step`. The
    Streamlit work-orders surface only knows the WO id; this endpoint
    saves the client a separate lookup. Returns the same shape as the
    underlying `/workflows/{execution_id}/run_next_step`."""
    try:
        exec_row = await conn.fetchrow(
            """
            SELECT id::text AS id, status::text AS status
              FROM workflow_executions
             WHERE work_order_id = $1::uuid
               AND client_id = $2::uuid
               AND status = 'running'::workflow_execution_status
             ORDER BY created_at DESC
             LIMIT 1
            """,
            work_order_id,
            ctx["client_id"],
        )
    except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "invalid_work_order_id", "value": work_order_id},
        )
    if exec_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": "no_running_workflow_execution",
                "work_order_id": work_order_id,
                "hint": (
                    "WO has no `running` workflow_execution. If Aiden "
                    "dispatched a single-step `work_order_brief`, use "
                    "the regular Dispatch button instead."
                ),
            },
        )
    # Delegate to the per-execution route (already enforces RLS via
    # the same get_tenant_scoped_connection dep we resolved above).
    return await run_next_step(
        execution_id=exec_row["id"], ctx=ctx, conn=conn,
    )

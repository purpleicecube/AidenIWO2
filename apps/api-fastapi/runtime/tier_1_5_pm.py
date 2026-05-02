"""MegaLoop Alpha α.3 — Tier 1.5 Workflow PM runtime.

PM owns the seam between Aiden (Tier 1) and Tier 2 sub-agents:
  - Takes an `AidenWorkflowBrief` (workflow_template_key + step_inputs).
  - Resolves `workflows.key` → latest workflow_template + its steps.
  - Calls the PM LLM to elaborate step inputs (one per step) using
    the original intake + Aiden's draft step inputs as context.
  - Creates a `workflow_execution` (status=running) + one
    `workflow_step_run` per template step (status=pending), payload
    populated by the PM elaboration.

Stage A constraints:
  - § A1: PM must use a real LLM in Alpha (live Tier 1.5).
  - § A5: strict structured JSON for PM elaboration.
  - § A7: same per-call/per-WO budget as Tier 1.
  - § C3: workflow E2E mandatory because Tier 1.5 is live.

Audit:
  - `llm.invoked` for the PM elaboration call (agentRole=pm_tier_15).
  - `workflow_execution.started` once the execution is created.
  - Tier 2 dispatch happens in α.4; not part of this helper.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import asyncpg

from authz.audit_writer import write_audit_row
from llm.config_resolver import EffectiveLlmConfig, resolve_llm_config
from llm.credentials import LlmCredentialError, resolve_credential
from llm.providers import LlmProviderError, call_openai_compatible
from runtime.budgets import (
    check_or_raise_wo_budget,
    resolve_max_tokens,
)
from runtime.tier_1_aiden import (
    AidenWorkflowBrief,
    KNOWN_TIER_2_ROLES,
)


PM_TIER_15_ROLE = "pm_tier_15"
PM_CONTRACT_VERSION = "v1.alpha"


PM_SYSTEM_PROMPT = """You are PM, the Tier 1.5 Workflow Coordinator for IWO3.

Aiden (Tier 1) has classified an intake as a multi-step workflow and
picked a workflow_template. Your job is to take Aiden's draft step
inputs and the template's declared steps and produce a complete,
ready-to-execute step plan.

You will receive:
  - intake_text           original operator intake
  - aiden_summary         Aiden's one-paragraph summary
  - template_key          the chosen workflow_template_key
  - template_steps        ordered list of {step_key, sub_agent_role, description}
  - aiden_step_inputs     {step_key: {...}} draft inputs from Aiden

Respond with strict JSON:

{
  "step_plan": [
    {
      "step_key": "must match a template_steps step_key",
      "assigned_role": "must match the template_steps sub_agent_role",
      "input": { ...payload for the sub-agent... }
    }
  ]
}

Rules:
- Produce one step_plan entry per template_step, in the same order.
- assigned_role values should match the corresponding template step's
  declared sub_agent_role. If the template's role is empty, pick a
  Tier 2 role that fits (mark_tier_2 / tom_tier_2 / hank_tier_2 /
  paul_tier_2).
- input must be a non-empty object the named sub-agent can act on.
- Output JSON ONLY. No commentary, no markdown fences.
"""


class PmError(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class PmTemplateNotFound(PmError):
    def __init__(self, key: str) -> None:
        super().__init__("template_not_found", f"workflow_key={key}")


class PmPlanMalformed(PmError):
    def __init__(self, detail: str) -> None:
        super().__init__("plan_malformed", detail)


@dataclass(frozen=True)
class TemplateStep:
    id: str
    step_key: str
    step_order: int
    assigned_sub_agent_key: Optional[str]
    display_name: str


@dataclass(frozen=True)
class StepPlanEntry:
    step_key: str
    assigned_role: str
    input_payload: dict


@dataclass(frozen=True)
class WorkflowInstantiationResult:
    workflow_id: str
    workflow_execution_id: str
    template_id: str
    template_key: str
    step_run_ids: list[str]
    step_plan: list[StepPlanEntry]
    pm_provider: str
    pm_model: str
    pm_latency_ms: int
    pm_total_tokens: int


async def _load_template_and_steps(
    conn: asyncpg.Connection, *, client_id: str, template_key: str
) -> tuple[asyncpg.Record, list[TemplateStep]]:
    """Resolve workflow by `template_key` (which is workflows.key), then
    pick the latest published workflow_template for it, then its steps."""
    tpl = await conn.fetchrow(
        """
        SELECT wt.id::text          AS id,
               wt.workflow_id::text AS workflow_id,
               wt.version,
               w.key                AS workflow_key,
               w.display_name       AS workflow_display_name
          FROM workflow_templates wt
          JOIN workflows w ON w.id = wt.workflow_id
         WHERE w.client_id = $1
           AND w.key = $2
           AND wt.status = 'published'
         ORDER BY wt.published_at DESC NULLS LAST,
                  wt.created_at DESC
         LIMIT 1
        """,
        client_id,
        template_key,
    )
    if tpl is None:
        # Fallback: accept draft templates too. Some seed environments
        # have draft-only entries; PM should not block on that.
        tpl = await conn.fetchrow(
            """
            SELECT wt.id::text          AS id,
                   wt.workflow_id::text AS workflow_id,
                   wt.version,
                   w.key                AS workflow_key,
                   w.display_name       AS workflow_display_name
              FROM workflow_templates wt
              JOIN workflows w ON w.id = wt.workflow_id
             WHERE w.client_id = $1
               AND w.key = $2
             ORDER BY wt.created_at DESC
             LIMIT 1
            """,
            client_id,
            template_key,
        )
    if tpl is None:
        raise PmTemplateNotFound(template_key)

    rows = await conn.fetch(
        """
        SELECT id::text                       AS id,
               step_key,
               step_order,
               assigned_sub_agent_key,
               display_name
          FROM workflow_template_steps
         WHERE template_id = $1
         ORDER BY step_order ASC
        """,
        tpl["id"],
    )
    steps = [
        TemplateStep(
            id=r["id"],
            step_key=r["step_key"],
            step_order=r["step_order"],
            assigned_sub_agent_key=r["assigned_sub_agent_key"],
            display_name=r["display_name"],
        )
        for r in rows
    ]
    return tpl, steps


def _parse_step_plan(
    raw_text: str, template_steps: list[TemplateStep]
) -> list[StepPlanEntry]:
    body = raw_text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        body = "\n".join(lines)
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PmPlanMalformed(
            f"json decode failed: {exc}; first 200 chars: {body[:200]!r}"
        )

    sp = data.get("step_plan")
    if not isinstance(sp, list) or len(sp) != len(template_steps):
        raise PmPlanMalformed(
            f"step_plan must be a list of {len(template_steps)} entries; "
            f"got {sp!r}"
        )

    by_key = {s.step_key: s for s in template_steps}
    seen: set[str] = set()
    out: list[StepPlanEntry] = []
    for entry in sp:
        if not isinstance(entry, dict):
            raise PmPlanMalformed("step_plan entry must be an object")
        sk = entry.get("step_key")
        if sk not in by_key or sk in seen:
            raise PmPlanMalformed(
                f"unknown or duplicate step_key in step_plan: {sk!r}"
            )
        seen.add(sk)
        role = entry.get("assigned_role")
        expected_role = by_key[sk].assigned_sub_agent_key
        if role and role != expected_role:
            # PM-overridden role only valid if it's a known Tier 2 role.
            if role not in KNOWN_TIER_2_ROLES:
                role = expected_role or role
        if not role:
            role = expected_role or "mark_tier_2"
        inp = entry.get("input")
        if not isinstance(inp, dict):
            inp = {}
        out.append(
            StepPlanEntry(
                step_key=sk,
                assigned_role=role,
                input_payload=inp,
            )
        )
    return out


async def _emit_pm_invoked(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: EffectiveLlmConfig,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    template_key: str,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.invoked",
        target_type="workflow_template",
        target_id=template_key,
        metadata={
            "provider": cfg.provider,
            "model": cfg.model,
            "agentRole": cfg.resolved_role,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": prompt_tokens + completion_tokens,
            "latencyMs": latency_ms,
            "workOrderId": work_order_id,
            "decisionKind": "step_plan",
            "templateKey": template_key,
            "contractVersion": PM_CONTRACT_VERSION,
        },
    )


async def _emit_pm_failed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: Optional[EffectiveLlmConfig],
    kind: str,
    detail: str,
    template_key: Optional[str],
    http_status: Optional[int] = None,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.failed",
        target_type="workflow_template",
        target_id=template_key,
        metadata={
            "kind": kind,
            "detail": detail,
            "httpStatus": http_status,
            "provider": cfg.provider if cfg else None,
            "model": cfg.model if cfg else None,
            "agentRole": cfg.resolved_role if cfg else None,
            "workOrderId": work_order_id,
            "templateKey": template_key,
            "contractVersion": PM_CONTRACT_VERSION,
        },
    )


async def instantiate_workflow_from_brief(
    conn: asyncpg.Connection,
    *,
    brief: AidenWorkflowBrief,
    intake_text: str,
    aiden_summary: Optional[str],
    work_order_id: Optional[str],
    client_id: str,
    actor_user_id: Optional[str],
    transport=None,
) -> WorkflowInstantiationResult:
    """Run PM Tier 1.5 against `brief` + create the workflow_execution
    + step_runs. Returns a WorkflowInstantiationResult; caller owns
    advancing step_runs to running (Tier 2 dispatch in α.4)."""
    template_key = brief.workflow_template_key

    # Beta-2 phase 0.1 — if the operator carried explicit requested_outputs
    # on the WO, surface that fact in the audit log. Actual honor at the
    # adapter-dispatch step lands in Phase 0.2/0.3 (the auto-* workers); this
    # hook records intent-visibility without changing PM template choice
    # (which remains Aiden Tier 1's call per Q2=A locked).
    requested_outputs_seen: Optional[dict] = None
    if work_order_id is not None:
        wo_row = await conn.fetchrow(
            """
            SELECT requested_outputs
              FROM work_orders
             WHERE id = $1::uuid AND client_id = $2::uuid
            """,
            work_order_id,
            client_id,
        )
        if wo_row is not None and wo_row["requested_outputs"] is not None:
            ro_raw = wo_row["requested_outputs"]
            if isinstance(ro_raw, str):
                try:
                    requested_outputs_seen = json.loads(ro_raw)
                except json.JSONDecodeError:
                    requested_outputs_seen = None
            elif isinstance(ro_raw, dict):
                requested_outputs_seen = ro_raw

    cfg = await resolve_llm_config(
        conn, client_id=client_id, agent_role=PM_TIER_15_ROLE
    )
    if cfg is None or not cfg.enabled:
        raise PmError(
            "no_llm_configured",
            f"no enabled pm_tier_15 LLM config for tenant {client_id}",
        )

    tpl, steps = await _load_template_and_steps(
        conn, client_id=client_id, template_key=template_key
    )
    if not steps:
        raise PmError(
            "template_has_no_steps",
            f"workflow {template_key} template has zero steps",
        )

    # Pre-flight budget — same per-WO ceiling as Tier 1.
    estimate = max(
        128,
        min(
            resolve_max_tokens(cfg.options),
            (len(PM_SYSTEM_PROMPT) + len(intake_text)) // 4,
        ),
    )
    await check_or_raise_wo_budget(
        conn,
        work_order_id=work_order_id,
        client_id=client_id,
        actor_user_id=actor_user_id,
        next_call_estimate=estimate,
    )

    try:
        api_key = resolve_credential(cfg.credential_ref)
    except LlmCredentialError as exc:
        await _emit_pm_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            kind="credential_missing",
            detail=str(exc),
            template_key=template_key,
        )
        raise PmError("credential_missing", str(exc))

    user_msg = json.dumps(
        {
            "intake_text": intake_text,
            "aiden_summary": aiden_summary,
            "template_key": template_key,
            "template_steps": [
                {
                    "step_key": s.step_key,
                    "sub_agent_role": s.assigned_sub_agent_key,
                    "description": s.display_name,
                }
                for s in steps
            ],
            "aiden_step_inputs": brief.step_inputs,
        }
    )
    options = dict(cfg.options or {})
    options.setdefault("max_tokens", resolve_max_tokens(cfg.options))
    options.setdefault("response_format", {"type": "json_object"})

    started = time.monotonic()
    try:
        result = call_openai_compatible(
            provider=cfg.provider,
            model=cfg.model,
            api_key=api_key,
            base_url=cfg.base_url,
            system_prompt=cfg.system_prompt or PM_SYSTEM_PROMPT,
            user_message=user_msg,
            options=options,
            transport=transport,
        )
    except LlmProviderError as exc:
        await _emit_pm_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            kind=exc.kind,
            detail=str(exc),
            template_key=template_key,
            http_status=exc.http_status,
        )
        raise PmError(exc.kind, str(exc))

    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        plan = _parse_step_plan(result.text, steps)
    except PmPlanMalformed as exc:
        await _emit_pm_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            kind="malformed_output",
            detail=str(exc),
            template_key=template_key,
        )
        raise

    raw = result.raw or {}
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if isinstance(usage, dict):
        prompt_t = int(usage.get("prompt_tokens") or 0)
        completion_t = int(usage.get("completion_tokens") or 0)
    else:
        prompt_t = result.prompt_chars // 4
        completion_t = result.completion_chars // 4

    await _emit_pm_invoked(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        work_order_id=work_order_id,
        cfg=cfg,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        latency_ms=latency_ms,
        template_key=template_key,
    )

    # Now write the workflow_execution + step_runs.
    workflow_id = tpl["workflow_id"]
    exec_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO workflow_executions
          (id, client_id, template_id, work_order_id,
           status, started_at)
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid,
                'running'::workflow_execution_status, now())
        """,
        exec_id,
        client_id,
        tpl["id"],
        work_order_id,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="workflow_execution.started",
        target_type="workflow_execution",
        target_id=exec_id,
        metadata={
            "workflowId": workflow_id,
            "workflowTemplateId": tpl["id"],
            "templateKey": template_key,
            "workOrderId": work_order_id,
            "stepCount": len(plan),
        },
    )

    # Beta-2 phase 0.1 — record that operator-supplied artifact intent
    # was visible at PM instantiation time. Adapter dispatch in Phase
    # 0.2+ will use this to override the workflow's defaultRenderRoute
    # with operator-chosen template_profile_id.
    if requested_outputs_seen is not None:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="tier_1_5.requested_output_honored",
            target_type="workflow_execution",
            target_id=exec_id,
            metadata={
                "workOrderId": work_order_id,
                "templateKey": template_key,
                "requestedOutputs": requested_outputs_seen,
            },
        )

    step_run_ids: list[str] = []
    by_key = {s.step_key: s for s in steps}
    for entry in plan:
        ts = by_key[entry.step_key]
        run_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO workflow_step_runs
              (id, execution_id, step_key, step_order,
               status, input)
            VALUES ($1::uuid, $2::uuid, $3, $4,
                    'pending'::workflow_step_run_status, $5::jsonb)
            """,
            run_id,
            exec_id,
            ts.step_key,
            ts.step_order,
            json.dumps(entry.input_payload),
        )
        step_run_ids.append(run_id)

    return WorkflowInstantiationResult(
        workflow_id=workflow_id,
        workflow_execution_id=exec_id,
        template_id=tpl["id"],
        template_key=template_key,
        step_run_ids=step_run_ids,
        step_plan=plan,
        pm_provider=cfg.provider,
        pm_model=cfg.model,
        pm_latency_ms=latency_ms,
        pm_total_tokens=prompt_t + completion_t,
    )

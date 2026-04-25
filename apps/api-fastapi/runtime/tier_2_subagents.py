"""MegaLoop Alpha α.4 — Tier 2 sub-agent runtime.

One execution path used by both:
  - Aiden's direct `work_order_brief` route (single-step delivery)
  - PM's `workflow_step_run` advancement (multi-step delivery)

Each Tier 2 sub-agent has its own LLM config (mark_tier_2,
tom_tier_2, hank_tier_2, paul_tier_2) and produces:
  - markdown content (the actual deliverable)
  - structured JSON metadata (output_kind + summary + sub-agent-specific)

The runtime parses the response, writes an `output_packages` row,
emits `output_package.created` audit, and returns the package id +
provenance. Dispatch (handoff via Gamma or other adapter) is the
caller's responsibility — keeping content production and adapter
dispatch as separable surfaces.

Stage A constraints:
  - § A1: Tier 2 must use a real LLM (live).
  - § A5: Tier 2 returns JSON envelope wrapping markdown content +
    metadata so callers can mechanically build the output_package.
  - § A7: same per-call/per-WO budget enforcement as Tier 1 / 1.5.
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


TIER_2_CONTRACT_VERSION = "v1.alpha"


# Roles that are always known to be Tier 2 in IWO3. Legacy
# template seeds may use the un-suffixed forms ("mark", "tom", ...);
# normalisation happens at the dispatch boundary.
NORMALIZE_TIER_2 = {
    "mark": "mark_tier_2",
    "tom": "tom_tier_2",
    "hank": "hank_tier_2",
    "paul": "paul_tier_2",
    "mark_tier_2": "mark_tier_2",
    "tom_tier_2": "tom_tier_2",
    "hank_tier_2": "hank_tier_2",
    "paul_tier_2": "paul_tier_2",
}


# Default per-role system prompts. Used when the resolved llm_configs
# row has no system_prompt of its own. Tier 2 sub-agents are
# producers; they output a strict JSON envelope.
DEFAULT_SYSTEM_PROMPTS = {
    "mark_tier_2": (
        "You are Mark, the Tier 2 marketing/content sub-agent for IWO3. "
        "Produce content briefs and marketing copy. Respond with strict "
        "JSON wrapping a markdown content block."
    ),
    "tom_tier_2": (
        "You are Tom, the Tier 2 deck-builder sub-agent for IWO3. "
        "Produce structured presentation content blocks for Gamma. "
        "Respond with strict JSON wrapping a markdown content block."
    ),
    "hank_tier_2": (
        "You are Hank, the Tier 2 web-builder sub-agent for IWO3. "
        "Produce HTML / landing page snippets. Respond with strict "
        "JSON wrapping a markdown content block."
    ),
    "paul_tier_2": (
        "You are Paul, the Tier 2 deployment sub-agent for IWO3. "
        "Coordinate publishing / packaging / external handoffs. "
        "Respond with strict JSON wrapping a markdown content block."
    ),
}

TIER_2_OUTPUT_SCHEMA = """
You must respond with a strict JSON object of the form:

{
  "content_markdown": "the deliverable, as markdown",
  "summary": "one-line summary of what you produced",
  "output_kind": "gamma_pptx | gamma_pdf | generic",
  "metadata": { ... sub-agent specific fields ... }
}

Output JSON ONLY. No commentary, no fences.
"""


@dataclass(frozen=True)
class Tier2OutputEnvelope:
    content_markdown: str
    summary: str
    output_kind: str
    metadata: dict


@dataclass(frozen=True)
class Tier2InvocationResult:
    role: str
    output_envelope: Tier2OutputEnvelope
    output_package_id: Optional[str]
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class Tier2Error(Exception):
    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


class Tier2RoleUnknown(Tier2Error):
    def __init__(self, role: str) -> None:
        super().__init__("role_unknown", f"role={role!r}")


class Tier2NoConfig(Tier2Error):
    def __init__(self, role: str) -> None:
        super().__init__(
            "no_llm_configured", f"no enabled LLM config for {role}"
        )


class Tier2OutputMalformed(Tier2Error):
    def __init__(self, detail: str) -> None:
        super().__init__("output_malformed", detail)


def normalize_tier_2_role(role: str) -> str:
    norm = NORMALIZE_TIER_2.get(role)
    if norm is None:
        raise Tier2RoleUnknown(role)
    return norm


def _parse_envelope(raw_text: str) -> Tier2OutputEnvelope:
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
        raise Tier2OutputMalformed(
            f"json decode failed: {exc}; first 200 chars: {body[:200]!r}"
        )
    md = data.get("content_markdown")
    if not isinstance(md, str) or not md.strip():
        raise Tier2OutputMalformed("content_markdown missing or empty")
    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = ""
    output_kind = data.get("output_kind") or "generic"
    if output_kind not in {
        "gamma_pptx", "gamma_pdf", "sandbox_pptx", "sandbox_pdf",
        "email_campaign", "drive_upload", "crm_mutation",
        "figma_handoff", "stitch_handoff", "designlab_handoff",
        "generic",
    }:
        output_kind = "generic"
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return Tier2OutputEnvelope(
        content_markdown=md,
        summary=summary,
        output_kind=output_kind,
        metadata=metadata,
    )


async def _emit_tier2_invoked(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: EffectiveLlmConfig,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
    role: str,
    output_kind: str,
    output_package_id: Optional[str],
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.invoked",
        target_type="output_package" if output_package_id else "work_order",
        target_id=output_package_id or work_order_id or cfg.config_id,
        metadata={
            "provider": cfg.provider,
            "model": cfg.model,
            "agentRole": role,
            "promptTokens": prompt_tokens,
            "completionTokens": completion_tokens,
            "totalTokens": prompt_tokens + completion_tokens,
            "latencyMs": latency_ms,
            "workOrderId": work_order_id,
            "decisionKind": "content_envelope",
            "outputKind": output_kind,
            "outputPackageId": output_package_id,
            "contractVersion": TIER_2_CONTRACT_VERSION,
        },
    )


async def _emit_tier2_failed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    actor_user_id: Optional[str],
    work_order_id: Optional[str],
    cfg: Optional[EffectiveLlmConfig],
    role: str,
    kind: str,
    detail: str,
    http_status: Optional[int] = None,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.failed",
        target_type="work_order" if work_order_id else "llm_config",
        target_id=work_order_id or (cfg.config_id if cfg else None),
        metadata={
            "kind": kind,
            "detail": detail,
            "httpStatus": http_status,
            "provider": cfg.provider if cfg else None,
            "model": cfg.model if cfg else None,
            "agentRole": role,
            "workOrderId": work_order_id,
            "contractVersion": TIER_2_CONTRACT_VERSION,
        },
    )


async def invoke_tier_2(
    conn: asyncpg.Connection,
    *,
    role: str,
    intake_text: str,
    content_blocks: dict,
    work_order_id: Optional[str],
    client_id: str,
    actor_user_id: Optional[str],
    transport=None,
) -> Tier2OutputEnvelope:
    """Run a single Tier 2 LLM call. Does NOT persist output_package
    or emit audit on its own — `produce_output_package` is the wrapper
    that persists. Used by both the WO direct path and the
    workflow_step_run advancement path.

    Returns the parsed envelope. Raises Tier2Error subclass on failure.
    """
    norm_role = normalize_tier_2_role(role)
    cfg = await resolve_llm_config(
        conn, client_id=client_id, agent_role=norm_role
    )
    if cfg is None or not cfg.enabled:
        raise Tier2NoConfig(norm_role)

    estimate = max(
        128,
        min(
            resolve_max_tokens(cfg.options),
            (len(intake_text) + len(json.dumps(content_blocks))) // 4,
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
        await _emit_tier2_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            role=norm_role,
            kind="credential_missing",
            detail=str(exc),
        )
        raise Tier2Error("credential_missing", str(exc))

    system_prompt = (
        cfg.system_prompt
        or DEFAULT_SYSTEM_PROMPTS.get(norm_role, "")
    ) + TIER_2_OUTPUT_SCHEMA

    user_msg = json.dumps(
        {"intake_text": intake_text, "content_blocks": content_blocks}
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
            system_prompt=system_prompt,
            user_message=user_msg,
            options=options,
            transport=transport,
        )
    except LlmProviderError as exc:
        await _emit_tier2_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            role=norm_role,
            kind=exc.kind,
            detail=str(exc),
            http_status=exc.http_status,
        )
        raise Tier2Error(exc.kind, str(exc))

    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        envelope = _parse_envelope(result.text)
    except Tier2OutputMalformed as exc:
        await _emit_tier2_failed(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            work_order_id=work_order_id,
            cfg=cfg,
            role=norm_role,
            kind="malformed_output",
            detail=str(exc),
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

    await _emit_tier2_invoked(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        work_order_id=work_order_id,
        cfg=cfg,
        prompt_tokens=prompt_t,
        completion_tokens=completion_t,
        latency_ms=latency_ms,
        role=norm_role,
        output_kind=envelope.output_kind,
        output_package_id=None,
    )

    return envelope


async def produce_output_package(
    conn: asyncpg.Connection,
    *,
    envelope: Tier2OutputEnvelope,
    title: str,
    work_order_id: Optional[str],
    workflow_execution_id: Optional[str],
    template_profile_id: Optional[str],
    client_id: str,
    actor_user_id: Optional[str],
    correlation_id: Optional[str] = None,
) -> str:
    """Persist a Tier 2 envelope as an `output_packages` row. Returns
    the package id. Caller decides whether to dispatch (Gamma etc)."""
    pkg_id = str(uuid.uuid4())
    content_blocks = {
        "content_markdown": envelope.content_markdown,
        "summary": envelope.summary,
        "metadata": envelope.metadata,
        # Convenience for adapters that want a `prompt` field.
        "prompt": envelope.content_markdown,
    }
    await conn.execute(
        """
        INSERT INTO output_packages
          (id, client_id, work_order_id, workflow_execution_id,
           output_kind, title, summary, content_blocks,
           template_profile_id, created_by_user_id, correlation_id,
           provenance)
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4::uuid,
                $5::output_package_kind, $6, $7, $8::jsonb,
                $9::uuid, $10::uuid, $11, $12::jsonb)
        """,
        pkg_id,
        client_id,
        work_order_id,
        workflow_execution_id,
        envelope.output_kind,
        title[:512],
        (envelope.summary or "")[:2000],
        json.dumps(content_blocks),
        template_profile_id,
        actor_user_id,
        correlation_id,
        json.dumps({"producedBy": "tier_2_subagents", "contractVersion": TIER_2_CONTRACT_VERSION}),
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="output_package.created",
        target_type="output_package",
        target_id=pkg_id,
        metadata={
            "outputKind": envelope.output_kind,
            "workOrderId": work_order_id,
            "workflowExecutionId": workflow_execution_id,
            "title": title,
        },
    )
    return pkg_id


async def execute_step_run(
    conn: asyncpg.Connection,
    *,
    step_run_id: str,
    client_id: str,
    actor_user_id: Optional[str],
    intake_context: Optional[str] = None,
    transport=None,
) -> Tier2InvocationResult:
    """Advance one workflow_step_run through Tier 2.

    Loads the step_run + its template_step (for assigned_sub_agent_key
    + display_name + prompt_ref). Marks step_run as `running`, calls
    the role's LLM, persists output, marks step_run `completed` (or
    `failed` on error)."""
    row = await conn.fetchrow(
        """
        SELECT sr.id::text                          AS id,
               sr.execution_id::text                AS execution_id,
               sr.step_key,
               sr.step_order,
               sr.status::text                      AS status,
               sr.input,
               we.work_order_id::text               AS work_order_id,
               we.client_id::text                   AS exec_client_id,
               wts.assigned_sub_agent_key,
               wts.display_name
          FROM workflow_step_runs sr
          JOIN workflow_executions we ON we.id = sr.execution_id
          JOIN workflow_template_steps wts
            ON wts.template_id = we.template_id
           AND wts.step_key = sr.step_key
         WHERE sr.id = $1::uuid AND we.client_id = $2::uuid
        """,
        step_run_id,
        client_id,
    )
    if row is None:
        raise Tier2Error("step_run_not_found", f"id={step_run_id}")

    if row["status"] not in ("pending",):
        raise Tier2Error(
            "step_run_not_pending",
            f"step_run={step_run_id} status={row['status']}",
        )

    role_raw = row["assigned_sub_agent_key"] or "mark"
    role = normalize_tier_2_role(role_raw)
    input_payload = row["input"]
    if isinstance(input_payload, str):
        try:
            input_payload = json.loads(input_payload)
        except Exception:
            input_payload = {"raw": input_payload}
    if not isinstance(input_payload, dict):
        input_payload = {}

    intake_text = intake_context or row["display_name"] or row["step_key"]

    # Mark step_run running.
    # lint:bypass-rls-explain="workflow_step_runs has no client_id column; tenant scoping enforced by parent workflow_executions RLS policy (Loop 4 Phase 4.3 nested-parent pattern)"
    await conn.execute(
        """
        UPDATE workflow_step_runs
           SET status = 'running'::workflow_step_run_status,
               started_at = now(),
               updated_at = now()
         WHERE id = $1::uuid
        """,
        step_run_id,
    )

    try:
        envelope = await invoke_tier_2(
            conn,
            role=role,
            intake_text=intake_text,
            content_blocks=input_payload,
            work_order_id=row["work_order_id"],
            client_id=client_id,
            actor_user_id=actor_user_id,
            transport=transport,
        )
    except Exception as exc:
        # lint:bypass-rls-explain="workflow_step_runs nested-parent RLS via execution_id; failure path mirror of the running-mark above"
        await conn.execute(
            """
            UPDATE workflow_step_runs
               SET status = 'failed'::workflow_step_run_status,
                   output = $2::jsonb,
                   completed_at = now(),
                   updated_at = now()
             WHERE id = $1::uuid
            """,
            step_run_id,
            json.dumps({"error": str(exc), "kind": getattr(exc, "kind", "unknown")}),
        )
        raise

    # Persist output_package + mark completed.
    pkg_id = await produce_output_package(
        conn,
        envelope=envelope,
        title=f"{row['display_name']} ({row['step_key']})",
        work_order_id=row["work_order_id"],
        workflow_execution_id=row["execution_id"],
        template_profile_id=None,
        client_id=client_id,
        actor_user_id=actor_user_id,
        correlation_id=None,
    )
    # lint:bypass-rls-explain="workflow_step_runs nested-parent RLS via execution_id; completed-mark mirror of the running-mark above"
    await conn.execute(
        """
        UPDATE workflow_step_runs
           SET status = 'completed'::workflow_step_run_status,
               output = $2::jsonb,
               completed_at = now(),
               updated_at = now()
         WHERE id = $1::uuid
        """,
        step_run_id,
        json.dumps(
            {
                "outputPackageId": pkg_id,
                "summary": envelope.summary,
                "outputKind": envelope.output_kind,
            }
        ),
    )

    return Tier2InvocationResult(
        role=role,
        output_envelope=envelope,
        output_package_id=pkg_id,
        provider="",
        model="",
        latency_ms=0,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
    )

"""Beta-2 phase 0.2 — Python adapter dispatch (Gamma path).

Closes the IWO3 runtime gap where the TS-canonical
``packages/contracts/adapter/registry.ts:dispatchToAdapter`` is the
only path that creates ``output_handoffs`` + submits to Gamma. The
FastAPI runtime needs a Python equivalent so that:

  - β.3 single-step (work_order_brief) path can auto-create a handoff
    after Tier 2 produces a ``gamma_*`` output_package.
  - The Tier 1.5 PM workflow path can do the same after each step run.
  - The new ``POST /work_orders/{id}/render`` button can post-hoc render
    a stuck WO whose package landed before this dispatcher existed.
  - The Phase 0.2 auto-dispatch worker can drive everything without
    operator clicks.

Architecture parity with TS dispatcher (ADR-020 dual-gate respected):

  1. Load output_package + template_profile (external_ref) + adapter_credential
  2. Decide the live gate via ``adapter.dispatch_gating.decide_live_gate``
  3. Build the Gamma request body via ``adapter.gamma_request_shape``
  4. POST to Gamma's API (httpx)
  5. Parse response, INSERT output_handoffs row with status='submitted'
  6. Write audit (``adapter_dispatch.submitted``)
  7. Return handoff id; the existing ``poll_worker`` advances the rest

Failure modes — credential missing / gate refused / Gamma 4xx / Gamma
5xx — each raise distinct exceptions the caller can map to HTTP errors
or audit reasons.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Optional

import asyncpg
import httpx

from authz.audit_writer import write_audit_row
from llm.credentials import LlmCredentialError, resolve_credential

from .dispatch_gating import LiveGateInput, LiveGateRefuse, decide_live_gate
from .gamma_request_shape import (
    GammaPackageInvalidError,
    GammaRequestShapeInput,
    GammaSubmitResponseInvalidError,
    build_gamma_request_body,
    parse_gamma_submit_response,
)


GAMMA_DEFAULT_BASE_URL = "https://public-api.gamma.app/v1.0"
GAMMA_ENV_FLAG = "GAMMA_LIVE_ENABLED"


class DispatchError(Exception):
    """Top-level dispatch failure. Carries a `kind` for taxonomy parity
    with the Loop 9 6-variant TS error model."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


@dataclass(frozen=True)
class DispatchResult:
    handoff_id: str
    output_package_id: str
    external_reference: str
    gamma_url: Optional[str]
    adapter_key: str


async def _load_package_and_template(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
) -> dict:
    """Tenant-scoped load of the package row + the template_profile it
    binds to (or the WO's requested_outputs.template_profile_id as a
    fallback when the package wasn't bound at create time)."""
    row = await conn.fetchrow(
        """
        SELECT op.id::text                 AS id,
               op.work_order_id::text      AS work_order_id,
               op.workflow_execution_id::text AS workflow_execution_id,
               op.output_kind::text        AS output_kind,
               op.title                    AS title,
               op.summary                  AS summary,
               op.content_blocks::text     AS content_blocks,
               op.template_profile_id::text AS template_profile_id,
               op.correlation_id           AS correlation_id
          FROM output_packages op
         WHERE op.id = $1::uuid AND op.client_id = $2::uuid
        """,
        output_package_id,
        client_id,
    )
    if row is None:
        raise DispatchError("not_found", f"output_package {output_package_id}")

    template_profile_id = row["template_profile_id"]
    if not template_profile_id and row["work_order_id"]:
        # Beta-2 phase 0.2 fallback: if the package row wasn't bound at
        # create time (β.3 single-step path predated requested_outputs
        # propagation), pull from the WO's requested_outputs jsonb.
        wo_ro = await conn.fetchrow(
            """
            SELECT requested_outputs::text AS ro
              FROM work_orders
             WHERE id = $1::uuid AND client_id = $2::uuid
            """,
            row["work_order_id"],
            client_id,
        )
        if wo_ro is not None and wo_ro["ro"]:
            try:
                ro = json.loads(wo_ro["ro"])
                tpl_id = ro.get("template_profile_id")
                if isinstance(tpl_id, str) and tpl_id:
                    template_profile_id = tpl_id
            except (json.JSONDecodeError, AttributeError):
                pass

    template_external_ref: Optional[str] = None
    if template_profile_id:
        tp = await conn.fetchrow(
            """
            SELECT external_ref, status::text AS status
              FROM template_profiles
             WHERE id = $1::uuid AND client_id = $2::uuid
            """,
            template_profile_id,
            client_id,
        )
        if tp is None or tp["status"] != "active":
            raise DispatchError(
                "template_unavailable",
                f"template_profile {template_profile_id} not active",
            )
        template_external_ref = tp["external_ref"]

    return {
        "id": row["id"],
        "work_order_id": row["work_order_id"],
        "workflow_execution_id": row["workflow_execution_id"],
        "output_kind": row["output_kind"],
        "title": row["title"],
        "summary": row["summary"],
        "content_blocks": json.loads(row["content_blocks"]) if row["content_blocks"] else {},
        "template_profile_id": template_profile_id,
        "template_external_ref": template_external_ref,
        "correlation_id": row["correlation_id"],
    }


async def _load_gamma_credential(
    conn: asyncpg.Connection,
    *,
    client_id: str,
) -> dict:
    """Tenant-scoped read of the gamma adapter_credentials row + check
    the dual gate. Returns {credential_ref, first_invocation_confirmed_at,
    api_key} or raises a DispatchError variant."""
    row = await conn.fetchrow(
        """
        SELECT ac.id::text                            AS credential_id,
               ac.credential_ref                      AS credential_ref,
               ac.first_invocation_confirmed_at::text AS first_invocation_confirmed_at,
               ac.status::text                        AS status
          FROM adapter_credentials ac
          JOIN adapter_catalog cat ON cat.id = ac.adapter_catalog_id
         WHERE cat.adapter_key = 'gamma' AND ac.client_id = $1::uuid
         ORDER BY ac.created_at DESC
         LIMIT 1
        """,
        client_id,
    )
    has_credential = row is not None and (row["status"] == "active")
    env_flag = os.environ.get(GAMMA_ENV_FLAG, "")

    decision = decide_live_gate(
        LiveGateInput(
            is_live=True,
            adapter_key="gamma",
            env_flag_name=GAMMA_ENV_FLAG,
            env_flag_value=env_flag if env_flag else None,
            has_credential=has_credential,
            credential_first_invocation_confirmed_at=(
                row["first_invocation_confirmed_at"] if row is not None else None
            ),
        )
    )
    if isinstance(decision, LiveGateRefuse):
        raise DispatchError(
            f"gate_refused:{decision.reason}", decision.detail
        )

    assert row is not None  # gate would have refused if missing
    try:
        api_key = resolve_credential(row["credential_ref"])
    except LlmCredentialError as exc:
        raise DispatchError("credential_missing", str(exc))

    return {
        "credential_id": row["credential_id"],
        "credential_ref": row["credential_ref"],
        "api_key": api_key,
    }


async def _post_gamma_submit(
    *,
    api_key: str,
    body: dict,
    endpoint: str,
    base_url: str = GAMMA_DEFAULT_BASE_URL,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> dict:
    url = f"{base_url.rstrip('/')}{endpoint}"
    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        transport=transport,
    ) as client:
        try:
            resp = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise DispatchError("transport_failed", str(exc))
    if resp.status_code >= 500:
        raise DispatchError(
            f"gamma_5xx:{resp.status_code}", resp.text[:500]
        )
    if resp.status_code >= 400:
        raise DispatchError(
            f"gamma_4xx:{resp.status_code}", resp.text[:500]
        )
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise DispatchError("response_unparseable", str(exc))


async def _resolve_adapter_catalog_id(
    conn: asyncpg.Connection, adapter_key: str
) -> Optional[str]:
    return await conn.fetchval(
        "SELECT id::text FROM adapter_catalog WHERE adapter_key = $1 LIMIT 1",
        adapter_key,
    )


async def _insert_handoff(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    work_order_id: Optional[str],
    output_package_id: str,
    adapter_catalog_id: Optional[str],
    template_profile_id: Optional[str],
    external_reference: str,
    gamma_url: Optional[str],
    correlation_id: Optional[str],
) -> str:
    """Insert an output_handoffs row. Note: schema has workflow_id (not
    workflow_execution_id) and a separate execution_cycle_id; the TS
    dispatcher leaves workflow_id NULL on β.3 single-step paths and we
    do the same. Workflow-bound handoffs are populated by Tier 1.5 PM
    via a different path."""
    handoff_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO output_handoffs
          (id, client_id, work_order_id,
           output_package_id, adapter_catalog_id, template_profile_id,
           external_destination, external_reference, status,
           handoff_payload_ref, correlation_id, metadata)
        VALUES ($1::uuid, $2::uuid, $3::uuid,
                $4::uuid, $5::uuid, $6::uuid,
                $7, $8, 'submitted'::output_handoff_status,
                $9, $10, $11::jsonb)
        """,
        handoff_id,
        client_id,
        work_order_id,
        output_package_id,
        adapter_catalog_id,
        template_profile_id,
        gamma_url,
        external_reference,
        None,  # handoff_payload_ref unused for v0
        correlation_id,
        json.dumps({"dispatched_by": "adapter.dispatch", "adapter_key": "gamma"}),
    )
    return handoff_id


async def dispatch_gamma_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> DispatchResult:
    """Submit an existing output_package to Gamma + create the handoff.

    The poll_worker takes over from `status='submitted'`. WO auto-completes
    via the existing `_maybe_cascade_wo_completed` cascade in
    ``gamma_poll.py`` when the handoff lands at `completed`.

    Idempotency: if an output_handoff already exists for this package
    in a non-terminal state, this raises DispatchError(handoff_already_exists)
    so callers can short-circuit.
    """
    # Idempotence guard.
    existing = await conn.fetchval(
        """
        SELECT id::text
          FROM output_handoffs
         WHERE output_package_id = $1::uuid
           AND client_id = $2::uuid
           AND status::text NOT IN ('failed', 'completed', 'cancelled')
         ORDER BY created_at DESC LIMIT 1
        """,
        output_package_id,
        client_id,
    )
    if existing is not None:
        raise DispatchError(
            "handoff_already_exists",
            f"output_handoff {existing} already in flight",
        )

    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    if not pkg["output_kind"].startswith("gamma_"):
        raise DispatchError(
            "wrong_adapter",
            f"output_kind={pkg['output_kind']} is not a gamma_* kind",
        )

    cred = await _load_gamma_credential(conn, client_id=client_id)

    try:
        shape = build_gamma_request_body(
            GammaRequestShapeInput(
                output_kind=pkg["output_kind"],
                title=pkg["title"],
                summary=pkg["summary"],
                content_blocks=pkg["content_blocks"],
                template_external_ref=pkg["template_external_ref"],
            )
        )
    except GammaPackageInvalidError as exc:
        raise DispatchError("package_invalid", "; ".join(exc.errors))

    raw = await _post_gamma_submit(
        api_key=cred["api_key"],
        body=shape.body,
        endpoint=shape.endpoint,
        transport=transport,
    )
    try:
        parsed = parse_gamma_submit_response(raw)
    except GammaSubmitResponseInvalidError as exc:
        raise DispatchError("response_invalid", str(exc))

    adapter_catalog_id = await _resolve_adapter_catalog_id(conn, "gamma")

    handoff_id = await _insert_handoff(
        conn,
        client_id=client_id,
        work_order_id=pkg["work_order_id"],
        output_package_id=pkg["id"],
        adapter_catalog_id=adapter_catalog_id,
        template_profile_id=pkg["template_profile_id"],
        external_reference=parsed.generation_id,
        gamma_url=parsed.gamma_url,
        correlation_id=pkg["correlation_id"],
    )

    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="adapter_dispatch.submitted",
        target_type="output_handoff",
        target_id=handoff_id,
        metadata={
            "adapter_key": "gamma",
            "output_package_id": pkg["id"],
            "template_profile_id": pkg["template_profile_id"],
            "external_reference": parsed.generation_id,
            "endpoint": shape.endpoint,
            "mode": shape.mode,
        },
    )

    return DispatchResult(
        handoff_id=handoff_id,
        output_package_id=pkg["id"],
        external_reference=parsed.generation_id,
        gamma_url=parsed.gamma_url,
        adapter_key="gamma",
    )

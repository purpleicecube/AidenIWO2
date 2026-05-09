"""Loop Lambda — Memory V2 runtime breadth wrappers.

Two thin wrappers over the central `memory_context_builder` for the
new memory readers beyond Tier-1 chat:

  - `memory_context_builder_for_workflow` — Tier-1.5 PM elaboration
  - `memory_context_builder_for_subagent` — Tier-2 sub-agent invocation

Both functions delegate to the central builder with:
  - per-surface budget (1.5K each, D-L1 default)
  - surface discriminator on audit metadata (D-L3 default)
  - extra metadata fields for forensic traceability
    (work_order_id, sub_agent_role, workflow_execution_id)

**These are NOT parallel assemblers.** Every memory bundle still
flows through `memory_context_builder` and through the five-layer
firewall. The wrappers are convenience surfaces with surface-specific
defaults — no new SQL, no new validators, no new audit pipelines.

D-L2 default (accepted): fresh assembly per Tier-2 invocation. The
wrapper does not propagate a Tier-1 chat bundle. Different intake
(WO description vs operator chat message) → different retrieval
target → fresh assembly is the correct semantics.

D-L4 deviation noted in handback: the spec assumed
`work_orders.created_by_user_id` (NOT NULL) as canonical async
operator identity. The actual codebase column is
`work_orders.submitted_by_user_id` (nullable). The wrappers handle
NULL by falling back to a sentinel "unknown_operator" identity that
will trip the Layer 4 owner_user_id check on any
`scratch_retrieval` source — meaning scratch is silently skipped for
WOs without a recorded submitter. Tenant-wide retrieval still active.
NOT NULL enforcement deferred until a real operational need surfaces.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import asyncpg

from .context_builder import memory_context_builder
from .types import (
    MEMORY_BUDGET_TIER_1_5,
    MEMORY_BUDGET_TIER_2,
    MemoryBundle,
)


# Sentinel UUID for WOs without a `submitted_by_user_id`. Layer 4
# validator will reject any owner-scoped (scratch) source against
# this identity, ensuring scratch is silently skipped rather than
# leaking across operators.
_UNKNOWN_OPERATOR_SENTINEL = UUID("00000000-0000-4000-8000-0000000fffff")


async def _resolve_wo_operator(
    conn: asyncpg.Connection,
    *,
    work_order_id: str,
    client_id: str,
) -> str:
    """Resolve the canonical operator identity for an async memory
    bundle keyed off a work_order_id.

    Returns the WO's `submitted_by_user_id` if present, else the
    sentinel UUID. Always returns a stringified UUID.

    The query carries explicit `client_id = $1` so cross-tenant WO
    lookups are blocked by the predicate belt + RLS.
    """
    row = await conn.fetchrow(
        """
        SELECT submitted_by_user_id::text AS user_id
        FROM work_orders
        WHERE id = $2::uuid AND client_id = $1::uuid
        """,
        client_id,
        work_order_id,
    )
    if row is None or not row["user_id"]:
        return str(_UNKNOWN_OPERATOR_SENTINEL)
    return row["user_id"]


async def memory_context_builder_for_workflow(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    work_order_id: Optional[str],
    workflow_execution_id: Optional[str],
    intake_text: str,
    actor_user_id: Optional[str] = None,
) -> MemoryBundle:
    """Assemble a memory bundle for a Tier-1.5 PM elaboration call.

    Operator identity resolution:
      1. If `actor_user_id` is provided (synchronous PM invocation
         from a route with an authenticated operator), use it.
      2. Else if `work_order_id` is provided (async dispatch path),
         resolve from `work_orders.submitted_by_user_id`.
      3. Else fall back to the sentinel.

    Surface tag: "tier_1_5_pm".
    Budget: MEMORY_BUDGET_TIER_1_5 (1.5K).

    Extra audit metadata: `work_order_id`, `workflow_execution_id`.
    """
    if actor_user_id:
        operator_id = actor_user_id
    elif work_order_id:
        operator_id = await _resolve_wo_operator(
            conn, work_order_id=work_order_id, client_id=client_id
        )
    else:
        operator_id = str(_UNKNOWN_OPERATOR_SENTINEL)

    extra: dict = {}
    if work_order_id:
        extra["work_order_id"] = work_order_id
    if workflow_execution_id:
        extra["workflow_execution_id"] = workflow_execution_id

    return await memory_context_builder(
        conn,
        client_id=client_id,
        user_id=operator_id,
        message=intake_text,
        surface="tier_1_5_pm",
        budget=MEMORY_BUDGET_TIER_1_5,
        extra_metadata=extra,
    )


async def memory_context_builder_for_subagent(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    work_order_id: Optional[str],
    sub_agent_role: str,
    intake_text: str,
    actor_user_id: Optional[str] = None,
) -> MemoryBundle:
    """Assemble a memory bundle for a Tier-2 sub-agent invocation.

    Operator identity resolution: same as PM wrapper (actor →
    WO submitter → sentinel).

    Surface tag: "tier_2_subagent".
    Budget: MEMORY_BUDGET_TIER_2 (1.5K).

    Extra audit metadata: `work_order_id`, `sub_agent_role`.

    Per D-L2 (accepted): fresh assembly per invocation. The intake
    here is the WO description (or step input payload), NOT the
    operator's chat message. The wrapper does not propagate any
    Tier-1 chat bundle.
    """
    if actor_user_id:
        operator_id = actor_user_id
    elif work_order_id:
        operator_id = await _resolve_wo_operator(
            conn, work_order_id=work_order_id, client_id=client_id
        )
    else:
        operator_id = str(_UNKNOWN_OPERATOR_SENTINEL)

    extra: dict = {"sub_agent_role": sub_agent_role}
    if work_order_id:
        extra["work_order_id"] = work_order_id

    return await memory_context_builder(
        conn,
        client_id=client_id,
        user_id=operator_id,
        message=intake_text,
        surface="tier_2_subagent",
        budget=MEMORY_BUDGET_TIER_2,
        extra_metadata=extra,
    )

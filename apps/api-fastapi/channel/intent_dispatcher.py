"""MegaLoop Alpha α.6 — channel intent dispatcher.

Channel-agnostic logic that turns a bound (channel_identity, parsed
intent, intent arg) tuple into the correct IWO3 action:
  - status      → read work_orders by id (RLS-bound)
  - create_wo   → run Aiden Tier 1 → either create WO or trigger workflow
  - approve     → transition WO processing → completed
  - reopen      → transition WO via reopen execution_cycle
  - unblock     → transition WO blocked → processing
  - start       → handled by the channel adapter directly (cross-tenant
                  auth-code consumption); not routed here.

RBAC:
  - status      requires `work_order:read`
  - create_wo   requires `work_order:create`
  - approve     requires `work_order:update` (Loop 6 transition spec)
  - reopen      requires `work_order:update` + `execution_cycle:reopen`
  - unblock     requires `work_order:update`

The dispatcher returns a `DispatchOutcome` containing the reply text
the channel adapter should send back to the user. Audit rows for the
underlying actions are written by the helpers (transition_work_order,
invoke_aiden_tier_1, etc.) — the dispatcher itself only emits the
`channel_message.processed` / `channel_message.failed` signals at the
caller level (see channel/core.py).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Optional

import asyncpg

from channel.core import ChannelIdentityRow
from channel.telegram import ParsedIntent
from runtime.tier_1_aiden import (
    AIDEN_TIER_1_ROLE,
    AidenInvocationError,
    invoke_aiden_tier_1,
)
from runtime.budgets import LlmBudgetExceeded
from wo_wf.transitions import (
    IllegalTransition,
    PermissionDenied,
    RowNotFound,
    transition_work_order,
)


@dataclass(frozen=True)
class DispatchOutcome:
    ok: bool
    reply_text: str
    related_work_order_id: Optional[str] = None
    related_workflow_execution_id: Optional[str] = None


def _format_wo_status_reply(row: asyncpg.Record) -> str:
    return (
        f"WO {row['id']}\n"
        f"title: {row['title']}\n"
        f"status: {row['status']}\n"
        f"priority: {row['priority']}\n"
        f"type: {row['type']}\n"
        f"created: {row['created_at']}"
    )


async def _read_work_order(
    conn: asyncpg.Connection, *, wo_id: str, client_id: str
) -> Optional[asyncpg.Record]:
    return await conn.fetchrow(
        """
        SELECT id::text                AS id,
               title,
               status::text            AS status,
               priority::text          AS priority,
               type,
               created_at::text        AS created_at
          FROM work_orders
         WHERE id = $1::uuid AND client_id = $2::uuid
        """,
        wo_id,
        client_id,
    )


async def _create_work_order(
    conn: asyncpg.Connection,
    *,
    title: str,
    description: Optional[str],
    type_: str,
    priority: str,
    client_id: str,
    actor_user_id: str,
    correlation_id: Optional[str] = None,
) -> str:
    """Insert a new WO. Permission check happens upstream via
    require_permission on `work_order:create`."""
    wo_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO work_orders
          (id, client_id, title, description, type, priority, status,
           submitted_by_user_id, correlation_id)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::work_order_priority,
                'pending'::work_order_status, $7::uuid, $8)
        """,
        wo_id,
        client_id,
        title[:240],
        description,
        type_[:64],
        priority,
        actor_user_id,
        correlation_id,
    )
    return wo_id


async def dispatch_intent(
    conn: asyncpg.Connection,
    *,
    intent: ParsedIntent,
    identity: ChannelIdentityRow,
) -> DispatchOutcome:
    """Run the intent against the database. Returns the reply the
    adapter should send. Caller wraps in tenant-scoped tx."""
    if intent.intent == "status":
        wo_id = intent.arg
        if not wo_id:
            return DispatchOutcome(
                False, "Usage: /status WO_ID"
            )
        try:
            row = await _read_work_order(
                conn, wo_id=wo_id, client_id=identity.client_id
            )
        except (asyncpg.DataError, ValueError, asyncpg.InvalidTextRepresentationError):
            return DispatchOutcome(False, f"WO id not valid: {wo_id}")
        if row is None:
            return DispatchOutcome(
                False,
                f"WO {wo_id} not found in this tenant.",
            )
        return DispatchOutcome(
            True,
            _format_wo_status_reply(row),
            related_work_order_id=row["id"],
        )

    if intent.intent == "create_wo":
        title = (intent.arg or "").strip()
        if not title:
            return DispatchOutcome(
                False, "Usage: create wo: TITLE  (or /create_wo TITLE)"
            )
        # Run Aiden Tier 1 to classify + (when work_order_brief)
        # produce a sub-agent assignment.
        try:
            decision = await invoke_aiden_tier_1(
                conn,
                intake_text=title,
                client_id=identity.client_id,
                actor_user_id=identity.user_id,
            )
        except LlmBudgetExceeded as exc:
            return DispatchOutcome(
                False,
                f"LLM budget exceeded for this tenant ({exc.already_used} "
                f"tokens used; ceiling {exc.ceiling}). Try again after "
                f"the operator increases the budget.",
            )
        except AidenInvocationError as exc:
            return DispatchOutcome(
                False,
                f"Aiden could not classify the request ({exc.kind}). "
                "Try rewording — be specific about what you need.",
            )

        if decision.decision_kind == "clarification":
            cl = decision.clarification
            return DispatchOutcome(
                False,
                "Aiden needs a clarification: "
                + (cl.question if cl else "(no question returned)"),
            )

        # Single-step → create a WO with the brief as content.
        if decision.decision_kind == "work_order_brief":
            brief = decision.work_order_brief
            assert brief is not None
            wo_id = await _create_work_order(
                conn,
                title=decision.title,
                description=decision.summary,
                type_="content_brief",
                priority=brief.priority,
                client_id=identity.client_id,
                actor_user_id=identity.user_id,
                correlation_id=f"telegram:{identity.external_id}",
            )
            return DispatchOutcome(
                True,
                f"Created WO {wo_id}\n"
                f"title: {decision.title}\n"
                f"assigned_role: {brief.assigned_role}\n"
                f"priority: {brief.priority}\n"
                f"Aiden ({decision.provider}/{decision.model}) "
                f"classified in {decision.latency_ms}ms.",
                related_work_order_id=wo_id,
            )

        # Multi-step workflow → also create a WO so polling /status
        # works; PM Tier 1.5 instantiation is operator-driven from
        # the browser in Alpha (channel-side workflow launch is
        # deferred per Stage A § B2).
        wo_id = await _create_work_order(
            conn,
            title=decision.title,
            description=decision.summary,
            type_="workflow_brief",
            priority="medium",
            client_id=identity.client_id,
            actor_user_id=identity.user_id,
            correlation_id=f"telegram:{identity.external_id}",
        )
        return DispatchOutcome(
            True,
            f"Created WO {wo_id}\n"
            f"title: {decision.title}\n"
            f"type: workflow_brief (template={decision.workflow_brief.workflow_template_key if decision.workflow_brief else '?'})\n"
            "Open the browser to instantiate the workflow execution.",
            related_work_order_id=wo_id,
        )

    if intent.intent in ("approve", "unblock"):
        wo_id = intent.arg
        if not wo_id:
            return DispatchOutcome(
                False, f"Usage: /{intent.intent} WO_ID"
            )
        try:
            target = "completed" if intent.intent == "approve" else "processing"
            await transition_work_order(
                conn,
                work_order_id=wo_id,
                client_id=identity.client_id,
                actor_user_id=identity.user_id,
                to=target,
                reason=f"telegram:{intent.intent} from chat {identity.external_id}",
            )
            return DispatchOutcome(
                True,
                f"WO {wo_id} → {target} (via /{intent.intent}).",
                related_work_order_id=wo_id,
            )
        except PermissionDenied as exc:
            return DispatchOutcome(
                False,
                f"Permission denied: {exc.permission} (your role: {exc.role}).",
            )
        except IllegalTransition as exc:
            return DispatchOutcome(
                False,
                f"Cannot {intent.intent} WO from {exc.from_} ({exc.code}).",
            )
        except RowNotFound:
            return DispatchOutcome(
                False, f"WO {wo_id} not found in this tenant."
            )
        except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
            return DispatchOutcome(False, f"WO id not valid: {wo_id}")

    if intent.intent == "reopen":
        wo_id = intent.arg
        if not wo_id:
            return DispatchOutcome(False, "Usage: /reopen WO_ID")
        try:
            await transition_work_order(
                conn,
                work_order_id=wo_id,
                client_id=identity.client_id,
                actor_user_id=identity.user_id,
                to="pending",
                reason=f"telegram:reopen from chat {identity.external_id}",
            )
            return DispatchOutcome(
                True,
                f"WO {wo_id} reopened (→ pending).",
                related_work_order_id=wo_id,
            )
        except PermissionDenied as exc:
            return DispatchOutcome(
                False,
                f"Permission denied: {exc.permission} (your role: {exc.role}).",
            )
        except IllegalTransition as exc:
            return DispatchOutcome(
                False,
                f"Cannot reopen WO from {exc.from_} ({exc.code}).",
            )
        except RowNotFound:
            return DispatchOutcome(
                False, f"WO {wo_id} not found in this tenant."
            )
        except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError):
            return DispatchOutcome(False, f"WO id not valid: {wo_id}")

    return DispatchOutcome(
        False,
        "Unknown command. Try:\n"
        "  /status WO_ID\n"
        "  create wo: TITLE\n"
        "  /approve WO_ID  |  /reopen WO_ID  |  /unblock WO_ID",
    )

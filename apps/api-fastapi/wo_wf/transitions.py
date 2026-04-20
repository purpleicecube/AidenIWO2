"""Loop 7 Phase 7.2 — Python port of the WO/WF transition helpers.

Mirrors `packages/contracts/wo-wf/transitions.ts`. The declarative
state-machine tables live in `contracts.state_machines` and agree
byte-for-byte with the TS canonical source via the Phase 6.1 parity
test. The helper logic around the tables (load status, check
permissions, update status, optionally open an execution_cycle,
write audit) is Python-native.

Parity strategy (R-011 in CODEX log):
  - State-machine tables: authoritative Python tuples, parity-tested
    vs TS via `tests/contract/state-machine-parity.test.ts`.
  - Helper semantics: documented in ADR-017; both TS and Python
    helpers consume the same table and write audit rows with
    identical {machine, from, to, reason, cycleId?} metadata shape.
  - Structural drift protection: a future loop can add a fixture-
    driven transition parity test that fires both helpers against the
    same WO fixture + compares resulting row state.

Only the helpers Loop 7 routes need land in this first cut:
  - transition_work_order
  - watchdog_expire_work_order
  - transition_workflow
(transition_workflow_execution and transition_workflow_step_run can
land in Loop 9+ when the orchestrator calls them directly; Streamlit
Loop 8 does not drive those manually.)
"""

from __future__ import annotations

import json
from typing import Any, Optional

import asyncpg

from authz.audit_writer import write_audit_row
from authz.check_permission import UserGrant, check_permission_decide
from contracts.state_machines import STATE_MACHINES, TransitionSpec


class IllegalTransition(Exception):
    def __init__(
        self, *, machine: str, from_: str, to: str, code: str
    ) -> None:
        super().__init__(
            f"IllegalTransition on {machine}: {from_} → {to} ({code})"
        )
        self.machine = machine
        self.from_ = from_
        self.to = to
        self.code = code


class RowNotFound(Exception):
    def __init__(self, *, table: str, id: str, client_id: str) -> None:
        super().__init__(f"RowNotFound: {table} id={id} client_id={client_id}")
        self.table = table
        self.id = id
        self.client_id = client_id


class PermissionDenied(Exception):
    def __init__(
        self,
        *,
        user_id: str,
        client_id: str,
        permission: str,
        reason: str,
        role: Optional[str],
    ) -> None:
        super().__init__(
            f"PermissionDenied: user={user_id} client={client_id} "
            f"permission={permission} reason={reason} role={role}"
        )
        self.user_id = user_id
        self.client_id = client_id
        self.permission = permission
        self.reason = reason
        self.role = role


# ── Internals ────────────────────────────────────────────────────────────


async def _load_status(
    conn: asyncpg.Connection,
    table: str,
    row_id: str,
    client_id: Optional[str],
) -> str:
    if client_id is None:
        row = await conn.fetchrow(
            f"SELECT status::text AS status FROM {table} WHERE id = $1",
            row_id,
        )
    else:
        row = await conn.fetchrow(
            f"SELECT status::text AS status FROM {table} WHERE id = $1 AND client_id = $2",
            row_id,
            client_id,
        )
    if row is None:
        raise RowNotFound(
            table=table, id=row_id, client_id=client_id or "(nested)"
        )
    return row["status"]


def _first_spec(machine: str, from_state: str, to: str) -> TransitionSpec:
    if machine not in STATE_MACHINES:
        raise IllegalTransition(
            machine=machine, from_=from_state, to=to, code="unknown_machine"
        )
    if from_state == to:
        raise IllegalTransition(
            machine=machine, from_=from_state, to=to, code="illegal_transition"
        )
    saw_from = False
    for t in STATE_MACHINES[machine]:
        if t.from_ == from_state:
            saw_from = True
            if t.to == to:
                return t
    raise IllegalTransition(
        machine=machine,
        from_=from_state,
        to=to,
        code="illegal_transition" if saw_from else "unknown_from",
    )


async def _load_perm_context(
    conn: asyncpg.Connection,
    user_id: str,
    client_id: str,
    permission: str,
) -> dict:
    vocab = await conn.fetch("SELECT permission_key FROM permissions")
    known = [r["permission_key"] for r in vocab]
    mem_rows = await conn.fetch(
        """
        SELECT role::text AS role FROM client_memberships
        WHERE user_id = $1 AND client_id = $2 AND status = 'active'
        LIMIT 1
        """,
        user_id,
        client_id,
    )
    if not mem_rows:
        return {"role": None, "role_permissions": [], "user_grants": [], "known_permissions": known}
    role = mem_rows[0]["role"]
    role_rows = await conn.fetch(
        """
        SELECT p.permission_key
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE rp.role = $1::membership_role
        """,
        role,
    )
    grant_rows = await conn.fetch(
        """
        SELECT p.permission_key, pg.grant_type::text AS grant_type
        FROM permission_grants pg
        JOIN permissions p ON p.id = pg.permission_id
        WHERE pg.user_id = $1 AND pg.client_id = $2
        """,
        user_id,
        client_id,
    )
    return {
        "role": role,
        "role_permissions": [r["permission_key"] for r in role_rows],
        "user_grants": [
            UserGrant(
                permission_key=r["permission_key"], grant_type=r["grant_type"]
            )
            for r in grant_rows
        ],
        "known_permissions": known,
    }


async def _require_permissions(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    client_id: str,
    permissions: tuple[str, ...],
    target_type: str,
    target_id: str,
    audit_metadata: dict[str, Any],
) -> None:
    for permission in permissions:
        ctx = await _load_perm_context(conn, user_id, client_id, permission)
        decision = check_permission_decide(
            role=ctx["role"],
            role_permissions=ctx["role_permissions"],
            user_grants=ctx["user_grants"],
            permission=permission,
            known_permissions=ctx["known_permissions"],
        )
        if decision.allowed:
            continue
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=user_id,
            event="authz.denied",
            target_type=target_type,
            target_id=target_id,
            metadata={
                **audit_metadata,
                "permission": permission,
                "decision_reason": decision.reason,
                "role": decision.role,
            },
        )
        raise PermissionDenied(
            user_id=user_id,
            client_id=client_id,
            permission=permission,
            reason=decision.reason,
            role=decision.role,
        )


async def _insert_execution_cycle(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    work_order_id: str,
    trigger: str,
    initiated_by_user_id: Optional[str],
    reason: Optional[str],
    metadata: dict[str, Any],
) -> str:
    prior = await conn.fetchrow(
        """
        SELECT id::text AS id, cycle_number
        FROM execution_cycles
        WHERE work_order_id = $1 AND client_id = $2
        ORDER BY cycle_number DESC
        LIMIT 1
        """,
        work_order_id,
        client_id,
    )
    next_cycle = (prior["cycle_number"] + 1) if prior else 1
    prior_id = prior["id"] if prior else None
    row = await conn.fetchrow(
        """
        INSERT INTO execution_cycles
          (client_id, work_order_id, cycle_number, trigger,
           initiated_by_user_id, reason, prior_cycle_id, metadata)
        VALUES ($1, $2, $3, $4::execution_cycle_trigger, $5, $6, $7, $8::jsonb)
        RETURNING id::text AS id
        """,
        client_id,
        work_order_id,
        next_cycle,
        trigger,
        initiated_by_user_id,
        reason,
        prior_id,
        json.dumps(metadata),
    )
    return row["id"]


# ── Public helpers ────────────────────────────────────────────────────────


async def transition_work_order(
    conn: asyncpg.Connection,
    *,
    work_order_id: str,
    client_id: str,
    actor_user_id: str,
    to: str,
    reason: Optional[str] = None,
) -> dict:
    from_status = await _load_status(
        conn, "work_orders", work_order_id, client_id
    )
    spec = _first_spec("work_order", from_status, to)
    audit_metadata: dict[str, Any] = {
        "machine": "work_order",
        "from": from_status,
        "to": to,
        "reason": reason,
    }
    await _require_permissions(
        conn,
        user_id=actor_user_id,
        client_id=client_id,
        permissions=spec.requires,
        target_type="work_order",
        target_id=work_order_id,
        audit_metadata=audit_metadata,
    )
    await conn.execute(
        """
        UPDATE work_orders
        SET status = $1, updated_at = now()
        WHERE id = $2 AND client_id = $3
        """,
        to,
        work_order_id,
        client_id,
    )
    cycle_id: Optional[str] = None
    if spec.requires_cycle:
        cycle_id = await _insert_execution_cycle(
            conn,
            client_id=client_id,
            work_order_id=work_order_id,
            trigger="reopen",
            initiated_by_user_id=actor_user_id,
            reason=reason,
            metadata={"from": from_status, "to": to, "event": spec.event},
        )
        audit_metadata["cycleId"] = cycle_id
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event=spec.event,
        target_type="work_order",
        target_id=work_order_id,
        metadata=audit_metadata,
    )
    return {
        "from": from_status,
        "to": to,
        "event": spec.event,
        "cycle_id": cycle_id,
    }


async def watchdog_expire_work_order(
    conn: asyncpg.Connection,
    *,
    work_order_id: str,
    client_id: str,
    actor_user_id: str,
    reason: str,
) -> dict:
    from_status = await _load_status(
        conn, "work_orders", work_order_id, client_id
    )
    if from_status != "processing":
        raise IllegalTransition(
            machine="work_order",
            from_=from_status,
            to="blocked",
            code="illegal_transition",
        )
    spec = next(
        (
            t
            for t in STATE_MACHINES["work_order"]
            if t.from_ == "processing"
            and t.to == "blocked"
            and t.event == "work_order.watchdog_expired"
        ),
        None,
    )
    if spec is None:
        raise RuntimeError("watchdog spec missing from work_order table")

    audit_metadata: dict[str, Any] = {
        "machine": "work_order",
        "from": from_status,
        "to": "blocked",
        "reason": reason,
        "trigger": "watchdog",
    }
    await _require_permissions(
        conn,
        user_id=actor_user_id,
        client_id=client_id,
        permissions=spec.requires,
        target_type="work_order",
        target_id=work_order_id,
        audit_metadata=audit_metadata,
    )
    await conn.execute(
        """
        UPDATE work_orders
        SET status = 'blocked', updated_at = now()
        WHERE id = $1 AND client_id = $2
        """,
        work_order_id,
        client_id,
    )
    cycle_id = await _insert_execution_cycle(
        conn,
        client_id=client_id,
        work_order_id=work_order_id,
        trigger="watchdog",
        initiated_by_user_id=actor_user_id,
        reason=reason,
        metadata={"from": from_status, "to": "blocked", "event": spec.event},
    )
    audit_metadata["cycleId"] = cycle_id
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event=spec.event,
        target_type="work_order",
        target_id=work_order_id,
        metadata=audit_metadata,
    )
    return {
        "from": from_status,
        "to": "blocked",
        "event": spec.event,
        "cycle_id": cycle_id,
    }


async def transition_workflow(
    conn: asyncpg.Connection,
    *,
    workflow_id: str,
    client_id: str,
    actor_user_id: str,
    to: str,
    reason: Optional[str] = None,
) -> dict:
    from_status = await _load_status(conn, "workflows", workflow_id, client_id)
    spec = _first_spec("workflow", from_status, to)
    audit_metadata: dict[str, Any] = {
        "machine": "workflow",
        "from": from_status,
        "to": to,
        "reason": reason,
    }
    await _require_permissions(
        conn,
        user_id=actor_user_id,
        client_id=client_id,
        permissions=spec.requires,
        target_type="workflow",
        target_id=workflow_id,
        audit_metadata=audit_metadata,
    )
    await conn.execute(
        """
        UPDATE workflows
        SET status = $1, updated_at = now()
        WHERE id = $2 AND client_id = $3
        """,
        to,
        workflow_id,
        client_id,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event=spec.event,
        target_type="workflow",
        target_id=workflow_id,
        metadata=audit_metadata,
    )
    return {"from": from_status, "to": to, "event": spec.event}

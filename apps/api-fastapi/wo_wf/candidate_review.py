"""Loop 7 Phase 7.3 — Python port of the Loop 6 candidate-review helpers.

Mirrors `packages/contracts/wo-wf/candidate_review.ts`. The select path
auto-rejects siblings in the same candidate_group_id and validates the
parent output_package; the reject path touches one handoff.
"""

from __future__ import annotations

from typing import Any, Optional

import asyncpg

from authz.audit_writer import write_audit_row
from wo_wf.transitions import PermissionDenied, _require_permissions


class CandidateNotEligible(Exception):
    def __init__(self, *, handoff_id: str, current_status: str) -> None:
        super().__init__(
            f"CandidateNotEligible: handoff {handoff_id} has candidate_status='{current_status}', not 'candidate'"
        )
        self.handoff_id = handoff_id
        self.current_status = current_status


class CandidateHandoffNotFound(Exception):
    def __init__(self, *, handoff_id: str, client_id: str) -> None:
        super().__init__(
            f"CandidateHandoffNotFound: {handoff_id} not in client {client_id}"
        )
        self.handoff_id = handoff_id
        self.client_id = client_id


async def _load_handoff(
    conn: asyncpg.Connection, handoff_id: str, client_id: str
) -> dict:
    row = await conn.fetchrow(
        """
        SELECT id::text AS id,
               client_id::text AS client_id,
               output_package_id::text AS output_package_id,
               candidate_group_id::text AS candidate_group_id,
               candidate_status::text AS candidate_status
        FROM output_handoffs
        WHERE id = $1 AND client_id = $2
        """,
        handoff_id,
        client_id,
    )
    if row is None:
        raise CandidateHandoffNotFound(
            handoff_id=handoff_id, client_id=client_id
        )
    return dict(row)


async def select_candidate(
    conn: asyncpg.Connection,
    *,
    handoff_id: str,
    client_id: str,
    actor_user_id: str,
    reason: Optional[str] = None,
) -> dict:
    audit_metadata: dict[str, Any] = {"reason": reason}
    await _require_permissions(
        conn,
        user_id=actor_user_id,
        client_id=client_id,
        permissions=("output_candidate:select",),
        target_type="output_handoff",
        target_id=handoff_id,
        audit_metadata=audit_metadata,
    )
    handoff = await _load_handoff(conn, handoff_id, client_id)
    if handoff["candidate_status"] != "candidate":
        raise CandidateNotEligible(
            handoff_id=handoff_id,
            current_status=handoff["candidate_status"],
        )

    await conn.execute(
        """
        UPDATE output_handoffs
        SET candidate_status = 'selected',
            selected_at = now(),
            selected_by_user_id = $1,
            updated_at = now()
        WHERE id = $2 AND client_id = $3
        """,
        actor_user_id,
        handoff_id,
        client_id,
    )

    rejected_sibling_ids: list[str] = []
    if handoff["candidate_group_id"]:
        sibling_rows = await conn.fetch(
            """
            UPDATE output_handoffs
            SET candidate_status = 'rejected', updated_at = now()
            WHERE candidate_group_id = $1
              AND id <> $2
              AND candidate_status = 'candidate'
              AND client_id = $3
            RETURNING id::text AS id
            """,
            handoff["candidate_group_id"],
            handoff_id,
            client_id,
        )
        rejected_sibling_ids = [r["id"] for r in sibling_rows]

    package_validated: Optional[str] = None
    if handoff["output_package_id"]:
        await conn.execute(
            """
            UPDATE output_packages
            SET status = 'validated', updated_at = now()
            WHERE id = $1 AND client_id = $2
              AND status NOT IN ('delivered', 'cancelled')
            """,
            handoff["output_package_id"],
            client_id,
        )
        package_validated = handoff["output_package_id"]

    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="output_candidate.selected",
        target_type="output_handoff",
        target_id=handoff_id,
        metadata={
            **audit_metadata,
            "candidate_group_id": handoff["candidate_group_id"],
            "output_package_id": handoff["output_package_id"],
            "rejected_siblings": rejected_sibling_ids,
        },
    )
    for sibling_id in rejected_sibling_ids:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="output_candidate.rejected",
            target_type="output_handoff",
            target_id=sibling_id,
            metadata={
                "reason": "auto_rejected_by_sibling_selection",
                "selected_sibling": handoff_id,
                "candidate_group_id": handoff["candidate_group_id"],
            },
        )
    if package_validated:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=actor_user_id,
            event="output_package.validated",
            target_type="output_package",
            target_id=package_validated,
            metadata={
                "reason": "candidate_selected",
                "selected_handoff": handoff_id,
            },
        )

    return {
        "selected_handoff_id": handoff_id,
        "rejected_sibling_ids": rejected_sibling_ids,
        "package_validated": package_validated,
    }


async def reject_candidate(
    conn: asyncpg.Connection,
    *,
    handoff_id: str,
    client_id: str,
    actor_user_id: str,
    reason: Optional[str] = None,
) -> dict:
    audit_metadata: dict[str, Any] = {"reason": reason}
    await _require_permissions(
        conn,
        user_id=actor_user_id,
        client_id=client_id,
        permissions=("output_candidate:reject",),
        target_type="output_handoff",
        target_id=handoff_id,
        audit_metadata=audit_metadata,
    )
    handoff = await _load_handoff(conn, handoff_id, client_id)
    if handoff["candidate_status"] != "candidate":
        raise CandidateNotEligible(
            handoff_id=handoff_id,
            current_status=handoff["candidate_status"],
        )
    await conn.execute(
        """
        UPDATE output_handoffs
        SET candidate_status = 'rejected', updated_at = now()
        WHERE id = $1 AND client_id = $2
        """,
        handoff_id,
        client_id,
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="output_candidate.rejected",
        target_type="output_handoff",
        target_id=handoff_id,
        metadata={
            **audit_metadata,
            "candidate_group_id": handoff["candidate_group_id"],
        },
    )
    return {"rejected_handoff_id": handoff_id}

"""Loop Iota — Memory V1 firewall Layer 4: assembly-time validation.

Before any source enters the LLM-bound bundle, every record's
`client_id` must equal the active tenant. For operator-private sources
(scratch_retrieval), `owner_user_id` must equal the active operator.

Failures do NOT raise. The mismatched source is dropped, an audit row
`memory.source_rejected` is queued (returned as a payload for the
caller to emit on the same connection that fetched the source), and
assembly continues with the surviving sources. The firewall mandate is
"do not partially trust mixed memory" — meaning the offending source is
the only thing dropped, not the entire bundle.

If `memory.source_rejected` ever fires in production it is a P0
incident (M-009 in the scope proposal). This is the firewall's smoke
alarm.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import MemorySource


@dataclass(frozen=True)
class RejectionRecord:
    """One source rejection ready for audit emission. Caller emits via
    write_audit_row(event="memory.source_rejected", metadata=...)."""

    kind: str
    record_id: str
    expected_client_id: str
    actual_client_id: str
    expected_user_id: str
    actual_user_id: str
    reason: str  # "tenant_mismatch" | "owner_mismatch" | "missing_client_id"


def validate_tenant_safety(
    sources: list[MemorySource],
    *,
    active_client_id: str,
    active_user_id: str,
) -> tuple[list[MemorySource], list[RejectionRecord]]:
    """Return `(kept, rejections)`.

    A source is rejected if:
      - `client_id` is empty/None
      - `client_id` does not equal `active_client_id`
      - kind is `scratch_retrieval` AND `owner_user_id != active_user_id`

    Note: chat_history sources are not subject to the owner check
    because the chat_sessions row is keyed by (user_id, client_id) and
    the assembler queries that row directly — the user_id IS the
    operator. We still set `owner_user_id=active_user_id` on chat
    sources for symmetry / audit traceability.
    """
    kept: list[MemorySource] = []
    rejections: list[RejectionRecord] = []
    for src in sources:
        if not src.client_id:
            rejections.append(
                RejectionRecord(
                    kind=src.kind,
                    record_id=src.record_id or "(missing)",
                    expected_client_id=active_client_id,
                    actual_client_id="(none)",
                    expected_user_id=active_user_id,
                    actual_user_id=src.owner_user_id or "(none)",
                    reason="missing_client_id",
                )
            )
            continue
        if src.client_id != active_client_id:
            rejections.append(
                RejectionRecord(
                    kind=src.kind,
                    record_id=src.record_id,
                    expected_client_id=active_client_id,
                    actual_client_id=src.client_id,
                    expected_user_id=active_user_id,
                    actual_user_id=src.owner_user_id or "(none)",
                    reason="tenant_mismatch",
                )
            )
            continue
        if src.kind == "scratch_retrieval":
            if src.owner_user_id != active_user_id:
                rejections.append(
                    RejectionRecord(
                        kind=src.kind,
                        record_id=src.record_id,
                        expected_client_id=active_client_id,
                        actual_client_id=src.client_id,
                        expected_user_id=active_user_id,
                        actual_user_id=src.owner_user_id or "(none)",
                        reason="owner_mismatch",
                    )
                )
                continue
        kept.append(src)
    return kept, rejections

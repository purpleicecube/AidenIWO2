"""MegaLoop Alpha α.2 — LLM token-budget enforcement.

Stage A § A7 lock:
  - per-call max_tokens = 8192 default (override via llm_configs.options)
  - per-WO ceiling = 50K cumulative across all LLM calls keyed to a WO
  - on ceiling breach: emit `llm.budget_exceeded` audit + raise typed
    exception; caller stops the agent loop

Per-WO totals are computed by summing the `totalTokens` field from
prior `llm.invoked` audit rows tagged with the same workOrderId.
This avoids a dedicated usage table; audit log is the source of
truth and is already partitioned + RLS-bounded.
"""

from __future__ import annotations

from typing import Optional

import asyncpg

from authz.audit_writer import write_audit_row


DEFAULT_PER_CALL_MAX_TOKENS = 8192
DEFAULT_PER_WO_CEILING = 50_000


class LlmBudgetExceeded(Exception):
    """Raised when the per-WO token ceiling would be breached by the
    next call. Caller must stop the agent loop and surface to operator."""

    def __init__(
        self,
        *,
        work_order_id: str,
        already_used: int,
        ceiling: int,
        next_call_estimate: int,
    ) -> None:
        super().__init__(
            f"WO {work_order_id} would exceed budget: "
            f"{already_used} + {next_call_estimate} > {ceiling}"
        )
        self.work_order_id = work_order_id
        self.already_used = already_used
        self.ceiling = ceiling
        self.next_call_estimate = next_call_estimate


def resolve_max_tokens(options: Optional[dict]) -> int:
    """Stage A § A7: 8192 default. options.max_tokens overrides per
    llm_configs row. Ceil at 16384 to bound any single call."""
    if not options:
        return DEFAULT_PER_CALL_MAX_TOKENS
    raw = options.get("max_tokens", DEFAULT_PER_CALL_MAX_TOKENS)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PER_CALL_MAX_TOKENS
    return max(64, min(n, 16384))


async def wo_token_total(
    conn: asyncpg.Connection, *, work_order_id: str, client_id: str
) -> int:
    """Sum of totalTokens across all prior `llm.invoked` audit rows
    tagged to this WO. Returns 0 if no rows."""
    val = await conn.fetchval(
        """
        SELECT COALESCE(
                 SUM(NULLIF(metadata->>'totalTokens', '')::int),
                 0
               )::int
          FROM action_audit_log
         WHERE action = 'llm.invoked'
           AND client_id = $1
           AND metadata->>'workOrderId' = $2
        """,
        client_id,
        work_order_id,
    )
    return int(val or 0)


async def check_or_raise_wo_budget(
    conn: asyncpg.Connection,
    *,
    work_order_id: Optional[str],
    client_id: str,
    actor_user_id: Optional[str],
    next_call_estimate: int,
    ceiling: int = DEFAULT_PER_WO_CEILING,
) -> int:
    """Pre-flight check before an LLM call. Returns current cumulative
    usage. Raises `LlmBudgetExceeded` if next_call_estimate would push
    over the ceiling, after emitting `llm.budget_exceeded` audit."""
    if work_order_id is None:
        return 0
    current = await wo_token_total(
        conn, work_order_id=work_order_id, client_id=client_id
    )
    if current + next_call_estimate <= ceiling:
        return current
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="llm.budget_exceeded",
        target_type="work_order",
        target_id=work_order_id,
        metadata={
            "workOrderId": work_order_id,
            "alreadyUsed": current,
            "ceiling": ceiling,
            "nextCallEstimate": next_call_estimate,
        },
    )
    raise LlmBudgetExceeded(
        work_order_id=work_order_id,
        already_used=current,
        ceiling=ceiling,
        next_call_estimate=next_call_estimate,
    )

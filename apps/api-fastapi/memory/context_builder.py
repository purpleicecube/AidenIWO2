"""Loop Iota — Memory V1 central entry point.

The ONLY allowed path for assembling memory injected into Tier-1 LLM
calls. Direct content injection bypassing this builder is forbidden by
`tools/eslint-plugin-iwo3/rules/no-direct-llm-content-injection.ts`.

Public function:
    bundle = await memory_context_builder(
        conn, client_id=..., user_id=..., message=...
    )
    block = bundle.block      # str — ready to prepend to system prompt
    sources = bundle.sources  # list[MemorySource] — for audit / UI
"""

from __future__ import annotations

import os
import time
from typing import Optional

import asyncpg

from authz.audit_writer import write_audit_row

from . import assembler, cache  # noqa: F401  (cache re-exported for tests)
from .budget import allocate, render_block
from .types import (
    MEMORY_BUDGET_TOKENS,
    SHORT_INTAKE_THRESHOLD_CHARS,
    MemoryBundle,
    MemorySource,
)
from .validator import validate_tenant_safety


# Locked Loop Iota audit vocabulary. Mirror in
# packages/contracts/audit/events.ts under LOOP_IOTA_AUDIT_EVENTS.
MEMORY_AUDIT_EVENTS: dict[str, str] = {
    "applied": "memory.applied",
    "bypassed": "memory.bypassed",
    "budget_truncated": "memory.budget_truncated",
    "source_rejected": "memory.source_rejected",
}


_ENV_KILL_SWITCH = "IWO3_MEMORY_INJECTION_ENABLED"


def _env_memory_enabled() -> bool:
    """Env-level kill switch. Default ON; set to "false" / "0" to bypass."""
    raw = os.environ.get(_ENV_KILL_SWITCH)
    if raw is None:
        return True
    return raw.strip().lower() not in {"false", "0", "no", "off"}


async def _emit_applied(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    user_id: str,
    bundle: MemoryBundle,
) -> None:
    sources_used = [
        {
            "kind": s.kind,
            "record_id": s.record_id,
            "tokens": s.tokens,
            "metadata": s.metadata,
        }
        for s in bundle.sources
    ]
    metadata = {
        "client_id": client_id,
        "user_id": user_id,
        "sources_used": sources_used,
        "tokens_used": bundle.tokens_used,
        "truncated_kinds": list(bundle.truncated_kinds),
        "cache_hits": list(bundle.cache_hits),
        "memory_budget_ms": bundle.assembly_ms,
        "rejected_count": len(bundle.rejected),
    }
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=user_id,
        event=MEMORY_AUDIT_EVENTS["applied"],
        target_type="chat_session",
        target_id=None,
        metadata=metadata,
    )
    if bundle.truncated_kinds:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=user_id,
            event=MEMORY_AUDIT_EVENTS["budget_truncated"],
            target_type="chat_session",
            target_id=None,
            metadata={
                "client_id": client_id,
                "user_id": user_id,
                "truncated_kinds": list(bundle.truncated_kinds),
                "tokens_after": bundle.tokens_used,
                "budget": MEMORY_BUDGET_TOKENS,
            },
        )


async def _emit_bypassed(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    user_id: str,
    reason: str,
) -> None:
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=user_id,
        event=MEMORY_AUDIT_EVENTS["bypassed"],
        target_type="chat_session",
        target_id=None,
        metadata={
            "client_id": client_id,
            "user_id": user_id,
            "reason": reason,
        },
    )


async def _emit_rejections(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    user_id: str,
    rejections,
) -> None:
    """One audit row per rejected source. In normal operation this
    should never fire; firing means the firewall caught a regression.
    M-009 in the scope: ops runbook treats any non-zero count as P0.
    """
    for rej in rejections:
        await write_audit_row(
            conn,
            client_id=client_id,
            actor_user_id=user_id,
            event=MEMORY_AUDIT_EVENTS["source_rejected"],
            target_type="memory_source",
            target_id=rej.record_id,
            metadata={
                "kind": rej.kind,
                "expected_client_id": rej.expected_client_id,
                "actual_client_id": rej.actual_client_id,
                "expected_user_id": rej.expected_user_id,
                "actual_user_id": rej.actual_user_id,
                "reason": rej.reason,
            },
        )


def _empty_bundle(
    *,
    bypassed: bool = False,
    bypass_reason: Optional[str] = None,
    assembly_ms: int = 0,
) -> MemoryBundle:
    return MemoryBundle(
        block="",
        sources=tuple(),
        rejected=tuple(),
        tokens_used=0,
        truncated_kinds=tuple(),
        cache_hits=tuple(),
        bypassed=bypassed,
        bypass_reason=bypass_reason,
        assembly_ms=assembly_ms,
    )


async def memory_context_builder(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    user_id: str,
    message: str,
) -> MemoryBundle:
    """Assemble a memory bundle for one Tier-1 chat turn.

    Inputs:
      conn       — tenant-scoped FastAPI connection (firewall Layer 2).
                   Caller is responsible for SET LOCAL ROLE iwo3_app +
                   app.current_client_id at the connection level.
      client_id  — active tenant
      user_id    — active operator
      message    — raw operator intake (used for retrieval term build
                   and short-intake gate)

    Returns:
      MemoryBundle. `bundle.block` is the rendered string ready to
      prepend to Tier-1's system prompt. Empty `block` is fine — caller
      passes through.

    Side effects:
      Emits exactly one of:
        - `memory.bypassed` (kill switch / no sources / short intake)
        - `memory.applied` (success path; may be followed by
           `memory.budget_truncated` and/or N × `memory.source_rejected`)
      Caller invokes this once per HTTP request and may reuse the
      bundle on tool-call re-invokes.
    """
    started = time.monotonic()

    # Env-level kill switch — bypass before any DB work.
    if not _env_memory_enabled():
        elapsed = int((time.monotonic() - started) * 1000)
        await _emit_bypassed(
            conn,
            client_id=client_id,
            user_id=user_id,
            reason="env_disabled",
        )
        return _empty_bundle(
            bypassed=True,
            bypass_reason="env_disabled",
            assembly_ms=elapsed,
        )

    # Empty / very short intakes: skip retrieval + scratch but still
    # ship canonical facts + chat history if any. Builder still runs;
    # only retrieval/scratch are gated.
    intake = (message or "").strip()
    very_short = len(intake) < SHORT_INTAKE_THRESHOLD_CHARS

    # Single composite query.
    inputs = await assembler.fetch_memory_inputs(
        conn,
        client_id=client_id,
        user_id=user_id,
        intake_text=intake if not very_short else "",
        # Note: passing empty intake when short skips workspace + scratch
        # CTEs because tsquery_terms will be None.
    )

    # Per-tenant kill switch (read from clients row).
    client_row = inputs.get("client") or {}
    if client_row and not client_row.get("memory_enabled", True):
        elapsed = int((time.monotonic() - started) * 1000)
        await _emit_bypassed(
            conn,
            client_id=client_id,
            user_id=user_id,
            reason="tenant_disabled",
        )
        return _empty_bundle(
            bypassed=True,
            bypass_reason="tenant_disabled",
            assembly_ms=elapsed,
        )

    raw_sources, summary = assembler.assemble_sources(
        inputs,
        client_id=client_id,
        user_id=user_id,
    )

    if not raw_sources:
        elapsed = int((time.monotonic() - started) * 1000)
        await _emit_bypassed(
            conn,
            client_id=client_id,
            user_id=user_id,
            reason="no_sources",
        )
        return _empty_bundle(
            bypassed=True,
            bypass_reason="no_sources",
            assembly_ms=elapsed,
        )

    # Firewall Layer 4: assembly-time validation.
    validated, rejections = validate_tenant_safety(
        raw_sources,
        active_client_id=client_id,
        active_user_id=user_id,
    )

    # Budget allocation + truncation (canonical facts never dropped).
    kept, truncated_kinds = allocate(validated, budget=MEMORY_BUDGET_TOKENS)

    block = render_block(kept)
    tokens_used = sum(s.tokens for s in kept)
    elapsed = int((time.monotonic() - started) * 1000)

    bundle = MemoryBundle(
        block=block,
        sources=tuple(kept),
        rejected=tuple(
            MemorySource(
                kind=r.kind,
                client_id=r.actual_client_id,
                record_id=r.record_id,
                text="",
                tokens=0,
                owner_user_id=r.actual_user_id,
                metadata={"reason": r.reason},
            )
            for r in rejections
        ),
        tokens_used=tokens_used,
        truncated_kinds=tuple(truncated_kinds),
        cache_hits=tuple(summary.get("cache_hits", [])),
        bypassed=False,
        bypass_reason=None,
        assembly_ms=elapsed,
    )

    # Emit audit rows. Rejections first so the smoke alarm fires
    # whether or not the rest of the bundle made it through.
    if rejections:
        await _emit_rejections(
            conn,
            client_id=client_id,
            user_id=user_id,
            rejections=rejections,
        )
    await _emit_applied(
        conn,
        client_id=client_id,
        user_id=user_id,
        bundle=bundle,
    )

    return bundle

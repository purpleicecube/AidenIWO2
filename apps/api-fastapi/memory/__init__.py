"""Loop Iota — Memory V1 retrofit.

The `memory` package is the only allowed path for assembling memory
that gets injected into Tier-1 LLM calls. Direct content injection
into `runtime.tier_1_aiden.invoke_aiden_tier_1` is forbidden by the
`no-direct-llm-content-injection` lint rule (Loop Iota Phase ι.1).

Public entry point:
    from memory import memory_context_builder, MEMORY_AUDIT_EVENTS

Five-layer firewall (CODEX `IWO3_LOOP_IOTA_TENANT_FIREWALL_PACKAGE_v0.1.0.md`):
  1. data-model scoping  — every source row carries `client_id`
  2. connection-level    — caller passes the tenant-scoped conn
  3. query-level         — explicit `client_id = $1` predicates
  4. assembly-time       — `_validate_tenant_safety` rejects mismatches
  5. cache namespace     — keys are `(client_id, ...)` minimum
"""

from .context_builder import memory_context_builder, MEMORY_AUDIT_EVENTS
from .types import (
    MemoryBundle,
    MemorySource,
    MemorySourceKind,
    MemoryAuditPayload,
)

__all__ = [
    "memory_context_builder",
    "MEMORY_AUDIT_EVENTS",
    "MemoryBundle",
    "MemorySource",
    "MemorySourceKind",
    "MemoryAuditPayload",
]

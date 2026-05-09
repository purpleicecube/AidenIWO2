"""Loop Iota — Memory V1 data shapes.

Frozen dataclasses for the assembled bundle. Bundle lifetime is one
HTTP request only; never persisted, never cached across turns or
operators (firewall Layer 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


MemorySourceKind = Literal[
    "canonical_facts",
    "path_targeted",      # Loop Kappa — operator named a workspace path
    "folder_listing",     # Loop Kappa — synthesized directory map
    "filename_match",     # Loop Kappa — filename ILIKE hit
    "chat_history",
    "workspace_retrieval",
    "scratch_retrieval",
]


# Stable priority order. Used by the budget allocator to decide which
# source to truncate first when the 2K token budget is exceeded.
# Lower number = higher priority = truncated last.
#
# Loop Kappa rationale (D-K3): operator-explicit retrieval intent
# (path / folder / filename) outranks tsquery and chat history.
# tsquery-driven `workspace_retrieval` outranks chat history because
# when retrieval signal is present, grounding beats continuity.
SOURCE_PRIORITY: dict[str, int] = {
    "canonical_facts": 1,    # never truncated; char-truncated to fit if alone exceeds
    "path_targeted": 2,      # explicit operator path intent
    "folder_listing": 3,     # synthesized directory map
    "filename_match": 4,     # operator named a filename
    "workspace_retrieval": 5,  # tsquery hits
    "chat_history": 6,
    "scratch_retrieval": 7,
}


# Folder-listing caps (Q-K3 default: 25 / 50). Exceeding either emits
# a truncation marker line in the rendered listing.
FOLDER_LISTING_MAX_SUBFOLDERS: int = 25
FOLDER_LISTING_MAX_FILES: int = 50


# 2,000 tokens for the Tier-1 chat memory block; leaves >40K for the
# rest of the Tier-1 prompt + completion under the 50K WO ceiling.
MEMORY_BUDGET_TOKENS: int = 2000

# Loop Lambda — per-surface budgets for memory injection beyond Tier-1
# chat. PM elaboration prompts are shorter than Aiden's; Tier-2
# sub-agent prompts already carry rich per-WO payload (intake +
# content_blocks + system prompt). Smaller budgets keep total prompt
# under the 50K WO ceiling even when N step_runs each carry their own
# memory bundle.
#
# D-L1 default (accepted in the seven-decision baseline): per-call
# budgets, not a shared per-WO scheduler.
MEMORY_BUDGET_TIER_1_5: int = 1500   # PM elaboration
MEMORY_BUDGET_TIER_2: int = 1500     # Sub-agent invocation


# Surface discriminator for memory.applied audit metadata. Locked here
# so the audit writer + tests share one vocabulary. D-L3 default
# (accepted): same memory.applied event family with a `surface` field;
# no event-name proliferation.
Surface = Literal["chat", "tier_1_5_pm", "tier_2_subagent"]

# 4 chars per token approximation — same heuristic used by tier_1_aiden
# for budget pre-flight. The real provider count is logged after.
CHARS_PER_TOKEN: int = 4

# Skip retrieval + scratch on intakes shorter than this. Cheap turn
# saver for "yes", "ok", "thanks". Canonical facts and chat history
# still load (canonical facts is constant cost; chat history is the
# whole point of short follow-ups).
SHORT_INTAKE_THRESHOLD_CHARS: int = 20

# Top-N retrieval results (artifacts + scratch). Pinned per scope §D.
RETRIEVAL_TOP_N: int = 3

# Last N chat turns to inject. Pinned per scope §AC #3.
CHAT_HISTORY_TURNS: int = 6


@dataclass(frozen=True)
class MemorySource:
    """One concrete source contributing text to the assembled bundle.

    `client_id` and `owner_user_id` are populated for every source so
    the validator (Layer 4) can confirm tenant + ownership before any
    text is injected. `record_id` is the originating row ID
    (chat_sessions.id, artifact.id, etc.) for audit traceability.
    """

    kind: MemorySourceKind
    client_id: str
    record_id: str
    text: str
    tokens: int
    # owner_user_id is required for `scratch_retrieval`; informational
    # for chat_history (the session is keyed by user_id); None for
    # tenant-shared sources (canonical_facts, workspace_retrieval).
    owner_user_id: Optional[str] = None
    # Free-form metadata for audit/UI surfacing. Examples:
    #   chat_history: turn_count, oldest_at, newest_at
    #   workspace_retrieval: filename, score, match_kind
    #   scratch_retrieval: folder_name, score
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MemoryBundle:
    """Assembled memory ready for injection into the Tier-1 prompt.

    `block` is the rendered string (memory_context_builder concatenates
    sources in priority order with deterministic header markers).
    `sources` is the validated list (post Layer 4) — anything dropped
    by validation appears in `rejected` instead.
    """

    block: str
    sources: tuple[MemorySource, ...]
    rejected: tuple[MemorySource, ...]
    tokens_used: int
    truncated_kinds: tuple[str, ...]
    cache_hits: tuple[str, ...]
    bypassed: bool
    bypass_reason: Optional[str]
    assembly_ms: int


@dataclass(frozen=True)
class MemoryAuditPayload:
    """Shape mirrored into the `memory.applied` audit row metadata.

    Keep this serialisable to JSON without custom encoders — the audit
    writer json.dumps() at the boundary."""

    client_id: str
    user_id: str
    sources_used: list[dict]
    tokens_used: int
    truncated_kinds: list[str]
    cache_hits: list[str]
    memory_budget_ms: int
    bypassed: bool
    bypass_reason: Optional[str]

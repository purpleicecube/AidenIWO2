"""Loop Mu — Memory V3 unit tests (no DB, no Chroma).

Coverage for:
  - vector_store helpers — chunking, env kill switch, collection naming
  - Surface enum vocabulary unchanged (Mu adds source kind, not surface)
  - SOURCE_PRIORITY new ordering with `semantic_retrieval` slot 6
  - render_block emits semantic section
"""

from __future__ import annotations

import os

import pytest

from memory.types import (
    SEMANTIC_RETRIEVAL_TOP_N,
    SOURCE_PRIORITY,
    MemorySource,
)
from memory.budget import render_block
from memory.vector_store import (
    chunk_text_for_vectors,
    collection_name_for_tenant,
    env_semantic_enabled,
)


# ── chunking math ────────────────────────────────────────────────


def test_chunk_short_text_returns_single_chunk() -> None:
    chunks = chunk_text_for_vectors("short text under 2000 chars")
    assert len(chunks) == 1
    assert chunks[0] == "short text under 2000 chars"


def test_chunk_empty_text_returns_empty_list() -> None:
    assert chunk_text_for_vectors("") == []
    assert chunk_text_for_vectors(None) == []  # type: ignore[arg-type]


def test_chunk_long_text_with_overlap() -> None:
    """500 tokens × 4 chars = 2000 char window. 50 tokens overlap = 200 chars."""
    text = "x" * 5000  # ~1250 tokens — should produce 3 chunks with overlap
    chunks = chunk_text_for_vectors(text)
    # First chunk = 0..2000; second chunk starts at 2000-200 = 1800 → 1800..3800;
    # third = 3800-200 = 3600 → 3600..5600 (clipped to 5000)
    assert len(chunks) == 3
    assert len(chunks[0]) == 2000
    assert len(chunks[1]) == 2000
    assert chunks[2].endswith("x" * 5)  # tail of original


def test_chunk_custom_size() -> None:
    text = "y" * 1000
    chunks = chunk_text_for_vectors(text, chunk_size_tokens=100, overlap_tokens=10)
    # 100*4=400 char window; 10*10=40 char overlap.
    # 0..400; 400-40=360..760; 760-40=720..1120 (clipped to 1000)
    assert len(chunks) == 3


# ── env kill switch ──────────────────────────────────────────────


def test_env_kill_switch_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IWO3_SEMANTIC_RETRIEVAL_ENABLED", raising=False)
    assert env_semantic_enabled() is True


def test_env_kill_switch_off_when_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IWO3_SEMANTIC_RETRIEVAL_ENABLED", "false")
    assert env_semantic_enabled() is False


def test_env_kill_switch_off_when_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IWO3_SEMANTIC_RETRIEVAL_ENABLED", "0")
    assert env_semantic_enabled() is False


def test_env_kill_switch_on_when_arbitrary_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IWO3_SEMANTIC_RETRIEVAL_ENABLED", "yes please")
    assert env_semantic_enabled() is True


# ── collection naming (tenant-scoped index time) ─────────────────


def test_collection_name_uses_tenant_prefix() -> None:
    name = collection_name_for_tenant("00000000-0000-4000-8000-00000000c001")
    assert name == "tenant_00000000-0000-4000-8000-00000000c001"


def test_collection_name_distinguishes_tenants() -> None:
    klear = collection_name_for_tenant("00000000-0000-4000-8000-00000000c001")
    ffai = collection_name_for_tenant("00000000-0000-4000-8000-00000000c002")
    assert klear != ffai


# ── SOURCE_PRIORITY new ordering ─────────────────────────────────


def test_semantic_retrieval_priority_slot_6() -> None:
    """semantic_retrieval ranks BETWEEN workspace_retrieval (5) and chat_history.
    Per D-M1: deterministic-keyword wins, semantic is fuzzy supplement,
    chat_history slides to slot 7."""
    assert SOURCE_PRIORITY["semantic_retrieval"] == 6


def test_semantic_below_workspace_retrieval() -> None:
    assert SOURCE_PRIORITY["semantic_retrieval"] > SOURCE_PRIORITY["workspace_retrieval"]


def test_semantic_above_chat_history() -> None:
    assert SOURCE_PRIORITY["semantic_retrieval"] < SOURCE_PRIORITY["chat_history"]


def test_chat_history_now_priority_7() -> None:
    """Chat history slides one slot to make room for semantic_retrieval."""
    assert SOURCE_PRIORITY["chat_history"] == 7


def test_scratch_retrieval_remains_lowest() -> None:
    """scratch_retrieval is still the first to drop under budget pressure."""
    assert SOURCE_PRIORITY["scratch_retrieval"] == max(SOURCE_PRIORITY.values())


def test_canonical_facts_remains_highest_priority() -> None:
    assert SOURCE_PRIORITY["canonical_facts"] == 1


def test_semantic_top_n_constant() -> None:
    assert SEMANTIC_RETRIEVAL_TOP_N == 3


# ── render_block emits semantic section ──────────────────────────


def test_render_block_emits_semantic_grounding_section() -> None:
    src = MemorySource(
        kind="semantic_retrieval",
        client_id="c1",
        record_id="art-123",
        text="cosine-matched body content",
        tokens=10,
        metadata={"filename": "fuzzy_match.md", "score": 0.84, "chunk_idx": 0},
    )
    rendered = render_block([src])
    assert "## SEMANTIC GROUNDING (vector search)" in rendered
    assert "fuzzy_match.md" in rendered
    assert "(cosine=0.84)" in rendered
    assert "cosine-matched body content" in rendered


def test_render_block_section_order_semantic_after_workspace() -> None:
    """canonical_facts → workspace → semantic → chat_history (priority order)."""
    sources = [
        MemorySource(
            kind="canonical_facts", client_id="c1", record_id="c1:rev1",
            text="fact", tokens=1, metadata={"revision": 1},
        ),
        MemorySource(
            kind="workspace_retrieval", client_id="c1", record_id="art1",
            text="ws body", tokens=3,
            metadata={"filename": "g.md", "score": 0.5},
        ),
        MemorySource(
            kind="semantic_retrieval", client_id="c1", record_id="art2",
            text="semantic body", tokens=3,
            metadata={"filename": "h.md", "score": 0.7, "chunk_idx": 0},
        ),
        MemorySource(
            kind="chat_history", client_id="c1", record_id="cs1",
            text="- operator: hi", tokens=3,
        ),
    ]
    rendered = render_block(sources)
    cf_idx = rendered.index("## CANONICAL FACTS")
    ws_idx = rendered.index("## WORKSPACE GROUNDING")
    sem_idx = rendered.index("## SEMANTIC GROUNDING")
    ch_idx = rendered.index("## RECENT CHAT HISTORY")
    cit_idx = rendered.index("## CITATIONS")
    assert cf_idx < ws_idx < sem_idx < ch_idx < cit_idx


# ── budget allocator behavior with semantic_retrieval ────────────


def test_allocate_drops_semantic_before_workspace_when_tight() -> None:
    """semantic_retrieval (priority 6) drops before workspace_retrieval (5)."""
    from memory.budget import allocate

    cf = MemorySource(
        kind="canonical_facts", client_id="c1", record_id="c1:rev1",
        text="fact " * 5, tokens=5,
    )
    workspace = MemorySource(
        kind="workspace_retrieval", client_id="c1", record_id="art1",
        text="ws " * 30, tokens=60, metadata={"filename": "w.md", "score": 0.5},
    )
    semantic = MemorySource(
        kind="semantic_retrieval", client_id="c1", record_id="art2",
        text="sem " * 30, tokens=60, metadata={"filename": "s.md", "score": 0.7},
    )
    kept, truncated = allocate([semantic, workspace, cf], budget=70)
    kinds = [s.kind for s in kept]
    # canonical_facts always retained
    assert "canonical_facts" in kinds
    # workspace_retrieval (priority 5) retained over semantic (priority 6)
    assert "workspace_retrieval" in kinds
    # semantic_retrieval truncated/dropped
    assert "semantic_retrieval" in truncated or "semantic_retrieval" not in kinds

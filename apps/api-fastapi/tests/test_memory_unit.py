"""Loop Iota — Memory V1 unit tests (no DB).

Pure-function coverage for budget allocator, validator, cache, and
intent regex. No FastAPI / no asyncpg required.
"""

from __future__ import annotations

import pytest

from memory.budget import (
    allocate,
    estimate_tokens,
    render_block,
    truncate_to_tokens,
)
from memory.cache import (
    clear_all_caches,
    get_canonical_facts,
    hash_terms,
    invalidate_canonical_facts,
    put_canonical_facts,
)
from memory.assembler import _intent_matches_scratch
from memory.types import MemorySource, MEMORY_BUDGET_TOKENS
from memory.validator import RejectionRecord, validate_tenant_safety


# ── budget ────────────────────────────────────────────────────────


def test_estimate_tokens_basic() -> None:
    assert estimate_tokens("") == 0
    # 4 chars per token, round up.
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
    assert estimate_tokens("a" * 400) == 100


def test_truncate_keeps_paragraph_boundary() -> None:
    body = ("paragraph one.\n\n" * 50) + "paragraph two."
    out = truncate_to_tokens(body, 20)  # ~80 chars
    assert "paragraph one." in out
    # truncation marker present
    assert "[...truncated]" in out


def test_allocate_keeps_canonical_facts_first() -> None:
    cf = MemorySource(
        kind="canonical_facts",
        client_id="c1",
        record_id="c1:rev1",
        text="canonical " * 100,  # ~225 tokens
        tokens=225,
    )
    chat = MemorySource(
        kind="chat_history",
        client_id="c1",
        record_id="cs1",
        text="chat " * 100,
        tokens=125,
    )
    workspace = MemorySource(
        kind="workspace_retrieval",
        client_id="c1",
        record_id="art1",
        text="workspace " * 200,
        tokens=500,
    )
    kept, truncated = allocate([workspace, chat, cf], budget=400)
    kinds = [s.kind for s in kept]
    # canonical_facts always kept (and FIRST in priority order).
    assert "canonical_facts" in kinds
    assert kinds[0] == "canonical_facts"
    # workspace was lower priority and exceeded budget — should be
    # truncated or dropped.
    assert "workspace_retrieval" in truncated


def test_allocate_drops_lowest_priority_when_overspent() -> None:
    big_cf = MemorySource(
        kind="canonical_facts",
        client_id="c1",
        record_id="c1:rev1",
        text="x" * (4 * (MEMORY_BUDGET_TOKENS + 200)),
        tokens=MEMORY_BUDGET_TOKENS + 200,
    )
    scratch = MemorySource(
        kind="scratch_retrieval",
        client_id="c1",
        record_id="art2",
        text="scratch " * 50,
        tokens=100,
        owner_user_id="u1",
    )
    kept, truncated = allocate([scratch, big_cf], budget=MEMORY_BUDGET_TOKENS)
    # canonical_facts must be present (truncated), scratch must be dropped.
    kinds = [s.kind for s in kept]
    assert "canonical_facts" in kinds
    assert "scratch_retrieval" not in kinds
    assert "scratch_retrieval" in truncated


def test_render_block_empty_returns_empty_string() -> None:
    assert render_block([]) == ""


def test_render_block_includes_section_headers() -> None:
    cf = MemorySource(
        kind="canonical_facts",
        client_id="c1",
        record_id="c1:rev1",
        text="Clay.ai is the correct vendor.",
        tokens=10,
    )
    chat = MemorySource(
        kind="chat_history",
        client_id="c1",
        record_id="cs1",
        text="- operator: hello\n- aiden: hi",
        tokens=10,
        owner_user_id="u1",
    )
    block = render_block([chat, cf])
    assert "[MEMORY CONTEXT" in block
    assert "## CANONICAL FACTS" in block
    assert "## RECENT CHAT HISTORY" in block
    assert "Clay.ai" in block
    # Order: canonical facts before chat history.
    assert block.index("## CANONICAL FACTS") < block.index("## RECENT CHAT HISTORY")


# ── cache namespacing (firewall Layer 5) ──────────────────────────


def test_canonical_facts_cache_keyed_on_tenant() -> None:
    clear_all_caches()
    put_canonical_facts("tenant_a", revision=1, blob="A:rev1")
    put_canonical_facts("tenant_b", revision=1, blob="B:rev1")
    assert get_canonical_facts("tenant_a", 1) == "A:rev1"
    assert get_canonical_facts("tenant_b", 1) == "B:rev1"
    # Cross-key probe must miss — tenant A revision 1 ≠ tenant B
    # revision 1, even though both use revision=1.
    assert get_canonical_facts("tenant_c", 1) is None


def test_canonical_facts_cache_invalidates_per_tenant() -> None:
    clear_all_caches()
    put_canonical_facts("tenant_a", revision=1, blob="A1")
    put_canonical_facts("tenant_a", revision=2, blob="A2")
    put_canonical_facts("tenant_b", revision=1, blob="B1")
    dropped = invalidate_canonical_facts("tenant_a")
    assert dropped == 2
    assert get_canonical_facts("tenant_a", 1) is None
    assert get_canonical_facts("tenant_a", 2) is None
    # tenant_b survives.
    assert get_canonical_facts("tenant_b", 1) == "B1"


def test_canonical_facts_cache_revision_bump() -> None:
    clear_all_caches()
    put_canonical_facts("tenant_a", revision=1, blob="old")
    # Bump → caller writes the new revision; old key stays cached
    # until invalidate_prefix is called by the workspace hook. The
    # test asserts both can coexist briefly (revision-stamped keys).
    put_canonical_facts("tenant_a", revision=2, blob="new")
    assert get_canonical_facts("tenant_a", 1) == "old"
    assert get_canonical_facts("tenant_a", 2) == "new"


def test_hash_terms_stable() -> None:
    assert hash_terms("rmis pricing deck") == hash_terms("rmis pricing deck")
    assert hash_terms("rmis pricing deck") != hash_terms("rmis pricing pdf")


# ── scratch intent regex ──────────────────────────────────────────


@pytest.mark.parametrize(
    "intake,expected",
    [
        ("check my scratch on Q2 forecast", True),
        ("show me my notes from last week", True),
        ("any drafts in MY DRAFTS today?", True),
        ("review my memo on pricing", True),
        ("look at my files for the Klear deck", True),
        ("how is the dashboard doing", False),
        ("draft a one-pager about RMIS", False),
        ("scratch that idea", False),  # 'scratch' not preceded by 'my'
        ("notes from the Q2 review", False),
        ("", False),
    ],
)
def test_scratch_intent_regex(intake: str, expected: bool) -> None:
    assert _intent_matches_scratch(intake) == expected


# ── validator (firewall Layer 4) ──────────────────────────────────


def test_validator_accepts_matching_tenant() -> None:
    sources = [
        MemorySource(
            kind="canonical_facts",
            client_id="tenant_a",
            record_id="tenant_a:rev1",
            text="f",
            tokens=1,
        ),
        MemorySource(
            kind="chat_history",
            client_id="tenant_a",
            record_id="cs1",
            text="t",
            tokens=1,
            owner_user_id="op1",
        ),
    ]
    kept, rej = validate_tenant_safety(
        sources,
        active_client_id="tenant_a",
        active_user_id="op1",
    )
    assert len(kept) == 2
    assert rej == []


def test_validator_rejects_cross_tenant() -> None:
    sources = [
        MemorySource(
            kind="canonical_facts",
            client_id="tenant_a",
            record_id="tenant_a:rev1",
            text="f",
            tokens=1,
        ),
        MemorySource(
            kind="workspace_retrieval",
            client_id="tenant_b",  # MISMATCH
            record_id="art1",
            text="leak",
            tokens=1,
        ),
    ]
    kept, rej = validate_tenant_safety(
        sources,
        active_client_id="tenant_a",
        active_user_id="op1",
    )
    assert len(kept) == 1
    assert kept[0].kind == "canonical_facts"
    assert len(rej) == 1
    assert rej[0].reason == "tenant_mismatch"
    assert rej[0].kind == "workspace_retrieval"


def test_validator_rejects_cross_operator_scratch() -> None:
    sources = [
        MemorySource(
            kind="scratch_retrieval",
            client_id="tenant_a",
            record_id="art1",
            text="scratch",
            tokens=1,
            owner_user_id="op2",  # MISMATCH
        ),
    ]
    kept, rej = validate_tenant_safety(
        sources,
        active_client_id="tenant_a",
        active_user_id="op1",
    )
    assert kept == []
    assert len(rej) == 1
    assert rej[0].reason == "owner_mismatch"


def test_validator_rejects_missing_client_id() -> None:
    sources = [
        MemorySource(
            kind="chat_history",
            client_id="",
            record_id="cs1",
            text="orphan",
            tokens=1,
        ),
    ]
    kept, rej = validate_tenant_safety(
        sources,
        active_client_id="tenant_a",
        active_user_id="op1",
    )
    assert kept == []
    assert rej[0].reason == "missing_client_id"

"""Loop Kappa — Memory V1.5 unit tests (no DB).

Coverage for:
  - `intent_parser.parse_context_intent` regex set
  - `budget.render_block` new sections + CITATIONS + GROUNDING RULES
  - `SOURCE_PRIORITY` ordering with new kinds
"""

from __future__ import annotations

import pytest

from memory.intent_parser import (
    ContextIntent,
    parse_context_intent,
)
from memory.budget import allocate, render_block
from memory.types import (
    FOLDER_LISTING_MAX_FILES,
    FOLDER_LISTING_MAX_SUBFOLDERS,
    MEMORY_BUDGET_TOKENS,
    MemorySource,
    SOURCE_PRIORITY,
)


# ── intent_parser ────────────────────────────────────────────────


def test_intent_parser_empty_intake_returns_empty_intent() -> None:
    intent = parse_context_intent("")
    assert intent.paths == ()
    assert intent.filename_terms == ()
    assert intent.wants_folder_listing is False
    assert intent.wants_canonical_facts is False


def test_intent_parser_short_intake_returns_empty_intent() -> None:
    intent = parse_context_intent("hi")
    assert intent.paths == ()


def test_intent_parser_label_colon_path() -> None:
    msg = "Web Style Guide: Design References/Purplegoo_1016-DESIGN.md"
    intent = parse_context_intent(msg)
    assert "Design References/Purplegoo_1016-DESIGN.md" in intent.paths


def test_intent_parser_breadcrumb_rewrite_to_path() -> None:
    msg = "Find me content from Workspace > 04_Resources > Demo_Content > KlearContent_Demo"
    intent = parse_context_intent(msg)
    # The breadcrumb rewrite turns this into "from 04_Resources/Demo_Content/KlearContent_Demo"
    assert any("04_Resources/Demo_Content/KlearContent_Demo" in p for p in intent.paths)


def test_intent_parser_preposition_path() -> None:
    msg = "use the deck in 04_Resources/Demo_Content"
    intent = parse_context_intent(msg)
    assert "04_Resources/Demo_Content" in intent.paths


def test_intent_parser_bare_numbered_folder() -> None:
    msg = "show me 04_Resources today"
    intent = parse_context_intent(msg)
    assert "04_Resources" in intent.paths


def test_intent_parser_bare_underscore_capitalcase() -> None:
    msg = "look in Demo_Content for the briefing"
    intent = parse_context_intent(msg)
    assert "Demo_Content" in intent.paths


def test_intent_parser_denylist_drops_known_jargon() -> None:
    msg = "this Work_Order needs a Sub_Agent action"
    intent = parse_context_intent(msg)
    # Both denied — neither becomes a path
    assert "Work_Order" not in intent.paths
    assert "Sub_Agent" not in intent.paths


def test_intent_parser_rejects_url() -> None:
    msg = "see https://example.com/path/to/doc for context"
    intent = parse_context_intent(msg)
    assert not any("example.com" in p for p in intent.paths)


def test_intent_parser_rejects_version_string() -> None:
    msg = "this is v1.2.3 release"
    intent = parse_context_intent(msg)
    assert "v1.2.3" not in intent.paths
    assert "1.2.3" not in intent.paths


def test_intent_parser_quoted_filename() -> None:
    msg = 'find me "RMIS_pricing_deck.pptx" please'
    intent = parse_context_intent(msg)
    assert "RMIS_pricing_deck.pptx" in intent.filename_terms


def test_intent_parser_bare_filename_with_extension() -> None:
    msg = "where is q2_forecast.md"
    intent = parse_context_intent(msg)
    assert "q2_forecast.md" in intent.filename_terms


def test_intent_parser_folder_listing_intent_whats_in() -> None:
    intent = parse_context_intent("what's in 04_Resources?")
    assert intent.wants_folder_listing is True
    assert "04_Resources" in intent.paths


def test_intent_parser_folder_listing_intent_list_files_in() -> None:
    intent = parse_context_intent("list files in Demo_Content folder")
    assert intent.wants_folder_listing is True


def test_intent_parser_canonical_facts_intent() -> None:
    intent = parse_context_intent("what are the canonical facts for Klear pricing?")
    assert intent.wants_canonical_facts is True


def test_intent_parser_residual_keywords_excludes_path_terms() -> None:
    msg = "find pricing data in 04_Resources/Demo_Content"
    intent = parse_context_intent(msg)
    # "pricing", "data" should appear; "demo", "content", "resources",
    # "04_resources" should be suppressed because they are path components.
    residuals = set(intent.keywords_remaining)
    assert "pricing" in residuals
    assert "data" in residuals
    assert "demo" not in residuals
    assert "content" not in residuals
    assert "resources" not in residuals


def test_intent_parser_residual_keywords_excludes_filename_base() -> None:
    msg = "find the q2_forecast.md document"
    intent = parse_context_intent(msg)
    residuals = set(intent.keywords_remaining)
    # Filename base "q2_forecast" should be suppressed
    assert "q2" not in residuals
    assert "forecast" not in residuals


def test_intent_parser_caps_filename_terms_at_5() -> None:
    msg = (
        'find "a.md" "b.md" "c.md" "d.md" "e.md" "f.md" "g.md" please'
    )
    intent = parse_context_intent(msg)
    assert len(intent.filename_terms) <= 5


# ── render_block — Loop Kappa surface ────────────────────────────


def test_render_block_includes_grounding_rules_preamble() -> None:
    src = MemorySource(
        kind="canonical_facts",
        client_id="c1",
        record_id="c1:rev1",
        text="Klear pricing is $5K/mo.",
        tokens=10,
    )
    rendered = render_block([src])
    assert "## GROUNDING RULES" in rendered
    assert "Use ONLY the facts" in rendered
    assert "Do NOT invent" in rendered


def test_render_block_includes_citations_index() -> None:
    src = MemorySource(
        kind="canonical_facts",
        client_id="c1",
        record_id="abcd1234efgh5678",
        text="fact body",
        tokens=5,
        metadata={"revision": 7},
    )
    rendered = render_block([src])
    assert "## CITATIONS" in rendered
    # short id (first 8 of record_id) appears in citation
    assert "[abcd1234]" in rendered


def test_render_block_path_targeted_section() -> None:
    src = MemorySource(
        kind="path_targeted",
        client_id="c1",
        record_id="art1",
        text="excerpt body",
        tokens=10,
        metadata={
            "filename": "deck.pptx",
            "folder_path": "04_Resources/Demo",
        },
    )
    rendered = render_block([src])
    assert "## PATH-TARGETED FILES" in rendered
    assert "04_Resources/Demo/deck.pptx" in rendered


def test_render_block_folder_listing_section() -> None:
    src = MemorySource(
        kind="folder_listing",
        client_id="c1",
        record_id="folder:f1",
        text="# Folder: 04_Resources\n## Subfolders (2)\n- A\n- B",
        tokens=20,
        metadata={"root_path": "04_Resources"},
    )
    rendered = render_block([src])
    assert "## FOLDER LISTING" in rendered
    assert "Subfolders (2)" in rendered


def test_render_block_filename_match_section() -> None:
    src = MemorySource(
        kind="filename_match",
        client_id="c1",
        record_id="art2",
        text="excerpt body",
        tokens=10,
        metadata={"filename": "rmis_pricing.pptx"},
    )
    rendered = render_block([src])
    assert "## FILENAME MATCHES" in rendered
    assert "rmis_pricing.pptx" in rendered


def test_render_block_section_order_matches_priority() -> None:
    sources = [
        MemorySource(
            kind="chat_history", client_id="c1", record_id="cs1",
            text="- operator: hi", tokens=3,
        ),
        MemorySource(
            kind="canonical_facts", client_id="c1", record_id="c1:rev1",
            text="fact", tokens=1, metadata={"revision": 1},
        ),
        MemorySource(
            kind="path_targeted", client_id="c1", record_id="art1",
            text="path body", tokens=3,
            metadata={"filename": "f.md", "folder_path": "X"},
        ),
        MemorySource(
            kind="workspace_retrieval", client_id="c1", record_id="art2",
            text="ws body", tokens=3, metadata={"filename": "g.md", "score": 0.5},
        ),
    ]
    rendered = render_block(sources)
    cf_idx = rendered.index("## CANONICAL FACTS")
    pt_idx = rendered.index("## PATH-TARGETED FILES")
    ws_idx = rendered.index("## WORKSPACE GROUNDING")
    ch_idx = rendered.index("## RECENT CHAT HISTORY")
    cit_idx = rendered.index("## CITATIONS")
    # Order: canonical → path_targeted → workspace → chat → citations
    assert cf_idx < pt_idx < ws_idx < ch_idx < cit_idx


# ── SOURCE_PRIORITY ordering invariants ──────────────────────────


def test_source_priority_canonical_facts_is_first() -> None:
    assert SOURCE_PRIORITY["canonical_facts"] == 1


def test_source_priority_path_outranks_workspace() -> None:
    assert SOURCE_PRIORITY["path_targeted"] < SOURCE_PRIORITY["workspace_retrieval"]


def test_source_priority_filename_outranks_workspace() -> None:
    assert SOURCE_PRIORITY["filename_match"] < SOURCE_PRIORITY["workspace_retrieval"]


def test_source_priority_workspace_outranks_chat_history() -> None:
    # Loop Kappa: when explicit retrieval signal is present, grounding
    # beats continuity. Chat history is dropped before workspace hits
    # under budget pressure.
    assert SOURCE_PRIORITY["workspace_retrieval"] < SOURCE_PRIORITY["chat_history"]


def test_source_priority_scratch_is_last() -> None:
    last = max(SOURCE_PRIORITY.values())
    assert SOURCE_PRIORITY["scratch_retrieval"] == last


# ── allocate budget with new kinds ───────────────────────────────


def test_allocate_keeps_path_targeted_over_chat_when_tight() -> None:
    cf = MemorySource(
        kind="canonical_facts", client_id="c1", record_id="c1:rev1",
        text="fact " * 20, tokens=25,
    )
    path_hit = MemorySource(
        kind="path_targeted", client_id="c1", record_id="art1",
        text="path body " * 50, tokens=125,
        metadata={"filename": "f.md", "folder_path": "X"},
    )
    chat = MemorySource(
        kind="chat_history", client_id="c1", record_id="cs1",
        text="- operator: " + "x" * 800, tokens=200,
    )
    kept, truncated = allocate([chat, path_hit, cf], budget=200)
    kinds = [s.kind for s in kept]
    # canonical_facts always retained
    assert kinds[0] == "canonical_facts"
    # path_targeted retained (priority 2)
    assert "path_targeted" in kinds
    # chat_history dropped or truncated (priority 6, lower than path_targeted)
    assert "chat_history" in truncated or "chat_history" not in kinds


def test_allocate_drops_scratch_first() -> None:
    cf = MemorySource(
        kind="canonical_facts", client_id="c1", record_id="c1:rev1",
        text="fact", tokens=5,
    )
    workspace = MemorySource(
        kind="workspace_retrieval", client_id="c1", record_id="art1",
        text="ws " * 50, tokens=100, metadata={"score": 0.5, "filename": "f.md"},
    )
    scratch = MemorySource(
        kind="scratch_retrieval", client_id="c1", record_id="art2",
        text="scratch " * 50, tokens=100, owner_user_id="u1",
        metadata={"score": 0.5, "filename": "s.md"},
    )
    kept, truncated = allocate([scratch, workspace, cf], budget=110)
    # scratch (lowest priority) gets truncated/dropped before workspace
    assert "scratch_retrieval" in truncated


# ── folder listing caps ──────────────────────────────────────────


def test_folder_listing_cap_constants() -> None:
    assert FOLDER_LISTING_MAX_SUBFOLDERS == 25
    assert FOLDER_LISTING_MAX_FILES == 50

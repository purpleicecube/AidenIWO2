"""Truth + structure regression guards for the public Attribution Register.

The prior generic _ENTRIES + _render_entry model crashed on missing
fields and misattributed AgentGoPro authorship. This file asserts
the canonical truth + structure is preserved going forward.

Approach: read the page source as text, then strip docstrings before
asserting against rendered-content patterns (so cautionary docstring
references to old anti-patterns don't trip regression guards). The
new page renders via st.html(...) with literal string content per
card, so post-docstring source-text assertions are an honest proxy
for the rendered surface.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


VIEWS = Path(__file__).resolve().parent.parent / "views"
SOURCE_RAW = (VIEWS / "attributions.py").read_text(encoding="utf-8")


def _strip_docstrings(src: str) -> str:
    """Remove all triple-quoted docstrings so cautionary references
    to old anti-patterns inside docstrings don't trip the assertions
    that check the rendered page content."""
    return re.sub(r'"""[\s\S]*?"""', "", src)


SOURCE = _strip_docstrings(SOURCE_RAW)


# ── Foundational lineage cards present (4 in canonical order) ────


def test_four_foundational_card_renderers_defined() -> None:
    """One hand-written render function per canonical card."""
    for renderer in (
        "_render_card_agentgoflow",
        "_render_card_aiden_zephyr",
        "_render_card_gcc_memory",
        "_render_card_pocketflow",
    ):
        assert f"def {renderer}(" in SOURCE, f"missing {renderer}"


def test_card_renderers_called_in_canonical_order() -> None:
    """Order in `main()` mirrors the IWO2 React canonical sequence:
    AgentGoPro → Aiden → GCC → PocketFlow."""
    main_idx = SOURCE.index("def main()")
    main_block = SOURCE[main_idx:]
    agf_pos = main_block.index("_render_card_agentgoflow()")
    aid_pos = main_block.index("_render_card_aiden_zephyr()")
    gcc_pos = main_block.index("_render_card_gcc_memory()")
    pf_pos = main_block.index("_render_card_pocketflow()")
    assert agf_pos < aid_pos < gcc_pos < pf_pos


# ── AgentGoPro / AgentGoFlow truth fixes ─────────────────────────


def test_agentgopro_author_is_darrel_vaughn() -> None:
    """TRUTH FIX TB-1 — prior renderer set Author to Thomas C. Appling
    III. The canonical AgentGoPro/AgentGoFlow author is Darrel Vaughn."""
    agf_idx = SOURCE.index("_render_card_agentgoflow")
    end_idx = SOURCE.index("# ── Card 2", agf_idx)
    block = SOURCE[agf_idx:end_idx]
    assert '_info_row("Author", _esc("Darrel Vaughn"))' in block


def test_agentgopro_does_not_misattribute_to_appling() -> None:
    """No reference to Thomas C. Appling III inside the AgentGoPro card
    block. (Appling appears in the Aiden Zephyr card only.)"""
    agf_idx = SOURCE.index("_render_card_agentgoflow")
    end_idx = SOURCE.index("# ── Card 2", agf_idx)
    agf_block = SOURCE[agf_idx:end_idx]
    assert "Thomas C. Appling" not in agf_block
    assert "Appling" not in agf_block


def test_agentgopro_metadata_uses_consulting_and_lab_labels() -> None:
    """TB-2 — restore IWO2-canonical Author/Consulting/Lab/Period
    vocabulary instead of the prior generic Author/Org/Cat/Period."""
    agf_idx = SOURCE.index("_render_card_agentgoflow")
    end_idx = SOURCE.index("# ── Card 2", agf_idx)
    block = SOURCE[agf_idx:end_idx]
    assert '_info_row("Consulting", _esc("10Touros"))' in block
    assert '_info_row("Lab", _esc("LuaAzullaB (formerly LuaLab)"))' in block
    assert '_info_row("Period", _esc("Mid-2024 – Aug 2025"))' in block


def test_agentgopro_dec2024_timeline_row_restored() -> None:
    """TB-3 — restore the canonical Dec 2024 timeline row that names
    the LAUNCH event + the Agent Commander → AgentGoPro/AgentGoFlow
    rename. Tolerant of Python implicit-string-concatenation across
    multiple source lines: collapse whitespace before comparison."""
    agf_idx = SOURCE.index("_render_card_agentgoflow")
    end_idx = SOURCE.index("# ── Card 2", agf_idx)
    block = SOURCE[agf_idx:end_idx]
    flat = re.sub(r"['\"\s]+", " ", block)
    assert "RFP Bridge Assistant LAUNCH" in flat
    assert "Project renamed to AgentGoPro/AgentGoFlow" in flat


def test_agentgopro_includes_beginnersmind_subsection() -> None:
    """SL-1 / SL-2 — the LuaAzullaB Orchestration Framework /
    BeginnersMind Workshops sub-section must live INSIDE the
    AgentGoPro card per IWO2 canon, not as a separate top-level card."""
    agf_idx = SOURCE.index("_render_card_agentgoflow")
    end_idx = SOURCE.index("# ── Card 2", agf_idx)
    block = SOURCE[agf_idx:end_idx]
    assert "LuaAzullaB Orchestration Framework — BeginnersMind Workshops" in block
    assert "Orchestration = [Workflow] × [Execution]" in block  # formula
    assert "Attention · Meaning · Relevance · Memory" in block  # 4 dims
    assert "ORCHESTRATION" in block  # ASCII diagram header
    assert "+6PLOCKER/Locker_BM.AI/Lua_Orchestration_Framework.png" in block
    assert "Oct 20, 2025" in block


# ── Aiden Zephyr & TIB ───────────────────────────────────────────


def test_aiden_zephyr_card_uses_contributor_organization_type_vocabulary() -> None:
    """The Aiden card's metadata vocabulary is Contributor/Org/Type,
    NOT Author/Org/Cat/Period. The prior generic renderer crashed
    on the missing `author` field; literal-mirror posture eliminates
    the shared-schema assumption."""
    aid_idx = SOURCE.index("_render_card_aiden_zephyr")
    end_idx = SOURCE.index("# ── Card 3", aid_idx)
    block = SOURCE[aid_idx:end_idx]
    contributor_re = re.compile(
        r'_info_row\(\s*"Contributor"\s*,\s*_esc\("Thomas C\. Appling III"\)'
    )
    organization_re = re.compile(
        r'_info_row\(\s*"Organization"\s*,\s*_esc\("Freedom Forge AI \(FF\.AI\)"\)'
    )
    type_re = re.compile(r'_info_row\(\s*"Type"\s*,')
    assert contributor_re.search(block)
    assert organization_re.search(block)
    assert type_re.search(block)
    # Ensure no shared-schema crash path exists — the renderer must
    # not reference an `entry["author"]` access pattern (excluding
    # docstrings which the SOURCE preprocessor strips).
    assert 'entry["author"]' not in block


def test_aiden_card_has_precedence_note() -> None:
    """The PRECEDENCE NOTE rose-tinted callout must be present —
    establishing that Vaughn's framework predates the Aiden Zephyr
    concept. Lost in earlier simplifications."""
    aid_idx = SOURCE.index("_render_card_aiden_zephyr")
    end_idx = SOURCE.index("# ── Card 3", aid_idx)
    block = SOURCE[aid_idx:end_idx]
    assert "PRECEDENCE NOTE" in block


# ── GCC Memory ───────────────────────────────────────────────────


def test_gcc_metadata_uses_paper_doi_url_vocabulary() -> None:
    """TB-4 / TB-7 — restore the canonical Paper / DOI / URL
    metadata vocabulary instead of generic Author/Org/Cat/Period."""
    gcc_idx = SOURCE.index("_render_card_gcc_memory")
    end_idx = SOURCE.index("# ── Card 4", gcc_idx)
    block = SOURCE[gcc_idx:end_idx]
    assert '_info_row(\n            "Paper",' in block or '_info_row("Paper",' in block
    assert '_info_row("DOI",' in block
    assert '_info_row("URL",' in block
    assert "10.48550/arXiv.2508.00031" in block


def test_gcc_attributes_to_wu_junde() -> None:
    """TB-4 — author identity is the canonical Wu, Junde paper, not
    'GCC Memory contributors'."""
    gcc_idx = SOURCE.index("_render_card_gcc_memory")
    end_idx = SOURCE.index("# ── Card 4", gcc_idx)
    block = SOURCE[gcc_idx:end_idx]
    assert "Wu, Junde" in block
    assert "Junde Wu" in block
    assert "GCC Memory contributors" not in block


def test_gcc_license_badge_specificity_preserved() -> None:
    """TB-5 — license badge must be 'CC BY 4.0 / MIT', not collapsed
    to generic 'Open Source'."""
    gcc_idx = SOURCE.index("_render_card_gcc_memory")
    end_idx = SOURCE.index("# ── Card 4", gcc_idx)
    block = SOURCE[gcc_idx:end_idx]
    assert "CC BY 4.0 / MIT" in block


def test_gcc_subtitle_is_canonical() -> None:
    """TB-6 — subtitle is 'Git Context Controller', not 'Persistence
    and memory-layer influence'."""
    gcc_idx = SOURCE.index("_render_card_gcc_memory")
    end_idx = SOURCE.index("# ── Card 4", gcc_idx)
    block = SOURCE[gcc_idx:end_idx]
    assert 'subtitle="Git Context Controller"' in block
    assert "Persistence and memory-layer influence" not in block


def test_gcc_includes_pdoe_integration_section() -> None:
    """SL-3 — the PDOE Integration (WS014) section must be present."""
    gcc_idx = SOURCE.index("_render_card_gcc_memory")
    end_idx = SOURCE.index("# ── Card 4", gcc_idx)
    block = SOURCE[gcc_idx:end_idx]
    assert "PDOE Integration (WS014)" in block


def test_gcc_includes_three_line_license_breakdown() -> None:
    """SL-5 — License Details panel must contain the 3-line
    Paper/Implementation/Packages breakdown, not a generic 1-liner."""
    gcc_idx = SOURCE.index("_render_card_gcc_memory")
    end_idx = SOURCE.index("# ── Card 4", gcc_idx)
    block = SOURCE[gcc_idx:end_idx]
    assert "<strong>Paper (CC BY 4.0):</strong>" in block
    assert "<strong>Implementation (MIT):</strong>" in block
    assert "<strong>Packages (MIT):</strong>" in block


# ── PocketFlow ───────────────────────────────────────────────────


def test_pocketflow_attributes_to_zachary_huang() -> None:
    """TB-8 — author identity is Zachary Huang (canonical), not
    generic 'PocketFlow contributors'."""
    pf_idx = SOURCE.index("_render_card_pocketflow")
    end_idx = SOURCE.index("# ── Lead Developer", pf_idx)
    block = SOURCE[pf_idx:end_idx]
    assert "Zachary Huang" in block
    assert "GitHub: zachary62" in block
    assert "PocketFlow contributors" not in block


def test_pocketflow_full_metadata_vocabulary_preserved() -> None:
    """TB-11 / SL-9 — restore Author/Affiliation/Organization/
    Repository/Docs/PyPI/License rows. Use a regex that tolerates
    multi-line `_info_row(\\n    "Label", ...)` formatting."""
    pf_idx = SOURCE.index("_render_card_pocketflow")
    end_idx = SOURCE.index("# ── Lead Developer", pf_idx)
    block = SOURCE[pf_idx:end_idx]
    for label in ("Author", "Affiliation", "Organization", "Repository",
                  "Docs", "PyPI", "License"):
        pattern = re.compile(r'_info_row\(\s*"' + label + r'"', re.MULTILINE)
        assert pattern.search(block), f"missing PocketFlow row {label}"


def test_pocketflow_license_badge_is_mit() -> None:
    """TB-9 — license badge must be 'MIT', not generic 'Open Source'."""
    pf_idx = SOURCE.index("_render_card_pocketflow")
    end_idx = SOURCE.index("# ── Lead Developer", pf_idx)
    block = SOURCE[pf_idx:end_idx]
    assert 'license_label="MIT"' in block


def test_pocketflow_subtitle_is_canonical() -> None:
    """TB-10 — subtitle is '100-Line LLM Framework'."""
    pf_idx = SOURCE.index("_render_card_pocketflow")
    end_idx = SOURCE.index("# ── Lead Developer", pf_idx)
    block = SOURCE[pf_idx:end_idx]
    assert 'subtitle="100-Line LLM Framework"' in block


def test_pocketflow_includes_pdoe_integration_section() -> None:
    """SL-4 — PDOE Integration (WS012 → WS014) section present."""
    pf_idx = SOURCE.index("_render_card_pocketflow")
    end_idx = SOURCE.index("# ── Lead Developer", pf_idx)
    block = SOURCE[pf_idx:end_idx]
    assert "PDOE Integration (WS012 → WS014)" in block


# ── Lead Developer card + footer ─────────────────────────────────


def test_lead_developer_card_present() -> None:
    """SL-6 — the Vaughn lead-developer attribution card must be
    rendered."""
    assert "_render_lead_developer_card" in SOURCE
    assert "Lead Developer &amp; Principal Technical Architect" in SOURCE
    assert "Darrel Vaughn" in SOURCE


def test_footer_says_iwo3_not_iwo2() -> None:
    """RV-4 — the IWO3 page must say AIDEN_IWO3, not AIDEN_IWO2.
    Earlier IWO3 React page accidentally said IWO2; the new Streamlit
    page is the corrective surface."""
    assert "AIDEN_IWO3 — Intelligent Work Orchestration" in SOURCE
    assert "AIDEN_IWO2 — Intelligent Work Orchestration" not in SOURCE


# ── External Tooling secondary section ───────────────────────────


def test_external_tooling_section_present_and_secondary() -> None:
    """RV-2 — IWO3-only external tools (Gamma / Stitch / Brave /
    Perplexity) must be present in a clearly secondary section
    BELOW the foundational cards."""
    assert "_render_external_tooling" in SOURCE
    assert "External Tooling Used by IWO3" in SOURCE
    for tool in ("Gamma", "Stitch", "Brave", "Perplexity"):
        assert tool in SOURCE, f"external tool {tool} missing"


def test_external_tooling_renders_after_lead_developer_card() -> None:
    """Layout invariant: external tooling section comes AFTER the
    lead-developer card so the foundational lineage surface stays
    visually canonical."""
    main_idx = SOURCE.index("def main()")
    main_block = SOURCE[main_idx:]
    leaddev_pos = main_block.index("_render_lead_developer_card()")
    tooling_pos = main_block.index("_render_external_tooling()")
    assert leaddev_pos < tooling_pos


# ── Resilience guards ────────────────────────────────────────────


def test_no_eager_eval_default_arg_pattern() -> None:
    """RR-1 — the prior `entry.get("metadata_rows", [..., entry["author"]
    , ...])` pattern crashed because Python evaluates `default` eagerly
    even when the key exists. The new design has no shared-schema
    default; assert the pattern is gone."""
    assert "entry[\"author\"]" not in SOURCE
    # No `metadata_rows` synthetic-default path either — each card
    # supplies its own rows directly.
    assert "metadata_rows" not in SOURCE


def test_render_uses_st_html_not_unsafe_markdown() -> None:
    """RR-2 — `st.html()` bypasses Markdown indentation parsing that
    caused timeline markup to render as escaped literal text. The
    rewrite uses `st.html` exclusively; `st.markdown(..., unsafe_allow_html=True)`
    should not appear."""
    # st.html is the render path
    assert "st.html(" in SOURCE
    # No unsafe-markdown holdout
    assert "unsafe_allow_html" not in SOURCE


# ── Structural completeness across all cards ─────────────────────


def test_all_four_foundational_cards_have_required_sections() -> None:
    """Each foundational card must have: header, metadata grid,
    body sections, license panel, attribution statement.

    Section markers are passed to `_section(...)` calls with plain
    `&` (Python source) which the renderer escapes to `&amp;` in
    the emitted HTML. We assert against the source-form `&` here.
    """
    for marker in (
        # AgentGoPro — Creator & Origin / Core Concept / Timeline / License Notice / Attribution Statement / BeginnersMind
        "Creator & Origin",
        "Core Concept",
        "License Notice",
        "Attribution Statement",
        # Aiden — Contributor & Source / Core Contribution / Timeline & Precedence
        "Contributor & Source",
        "Core Contribution",
        # GCC — License Details
        "License Details",
        # PocketFlow — MIT License panel
        "MIT License",
    ):
        assert marker in SOURCE, f"required section marker missing: {marker}"

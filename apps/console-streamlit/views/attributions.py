"""Attribution Register — IWO3 public attribution page.

Literal mirror of the canonical IWO2/IWO3 React attribution page
(`client/src/pages/attributions.tsx`). Replaces the prior generic
`_ENTRIES + _render_entry()` model that flattened distinct card
vocabularies into one schema and crashed on the Aiden Zephyr entry.

Architecture (per the recon prep package
`WS024_IWO3[Branch]/05_Artifacts/CLAUDE_HANDBACK_*` thread):

  - Four foundational cards are hand-authored, each with its own
    metadata vocabulary + section structure (no shared schema).
  - The Lead Developer card and page footer mirror the canonical
    React reference exactly.
  - IWO3-specific external-tooling acknowledgements (Gamma, Stitch
    MCP, Brave, Perplexity) live in a clearly secondary section
    below the foundational cards, with a tiny shared helper since
    they DO share a uniform shape.

HTML rendering uses `st.html()` (Streamlit ≥1.33) to bypass
Markdown indentation parsing. This eliminates the prior bug where
indented HTML inside `st.markdown(unsafe_allow_html=True)` rendered
as escaped literal text.
"""

from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st


_COLLECTED_DATE = "2026-05-09"


# ── Helper primitives ────────────────────────────────────────────


def _esc(value: object) -> str:
    """HTML-escape a value, coerced to string."""
    return escape("" if value is None else str(value))


def _info_row(label: str, value_html: str) -> str:
    """One metadata row in a card. `value_html` is the already-
    safe inner HTML for the value cell (links pre-formed by caller;
    plain strings pre-escaped by `_esc()`)."""
    return (
        f'<div class="iwo3-info-row">'
        f'<span class="k">{_esc(label)}</span>'
        f'<span class="v">{value_html}</span>'
        f'</div>'
    )


def _section(heading: str, body_html: str) -> str:
    """A top-bordered section with a heading + free-form body HTML."""
    return (
        f'<div class="iwo3-attr-section">'
        f'<h4>{_esc(heading)}</h4>'
        f'<div class="iwo3-attr-copy">{body_html}</div>'
        f'</div>'
    )


def _panel(tone: str, heading: str, body_html: str) -> str:
    """A tinted panel — used for License Notice + Attribution
    Statement + License Details (per-card colored). `tone` is one
    of: amber, rose, purple, blue, note."""
    return (
        f'<div class="iwo3-attr-panel {_esc(tone)}">'
        f'<h4>{_esc(heading)}</h4>'
        f'<div class="copy">{body_html}</div>'
        f'</div>'
    )


def _link(href: str, text: str) -> str:
    """An external link with the canonical styling."""
    return (
        f'<a class="iwo3-attr-link" '
        f'href="{_esc(href)}" target="_blank" rel="noopener noreferrer">'
        f'{_esc(text)} ↗'
        f'</a>'
    )


def _code(text: str) -> str:
    return f'<code class="iwo3-attr-code">{_esc(text)}</code>'


def _timeline_rows_html(rows: list[tuple[str, str]]) -> str:
    """Render a label/note timeline. Each row: ('Mar 2025', 'detail')."""
    return (
        '<div class="iwo3-attr-timeline">'
        + "".join(
            f'<span class="t">{_esc(period)}</span>'
            f'<span class="n">{_esc(note)}</span>'
            for period, note in rows
        )
        + '</div>'
    )


def _card_open(*, theme: str, icon_glyph: str, title: str, subtitle: str,
               license_label: str, license_color: str) -> str:
    """Open a foundational-lineage card. `theme` drives the icon-
    chip color set: amber / rose / purple / blue."""
    return (
        f'<section class="iwo3-attr-card iwo3-attr-card--{_esc(theme)}">'
        f'<header class="iwo3-attr-head">'
        f'<div class="iwo3-attr-head-main">'
        f'<div class="iwo3-attr-icon iwo3-attr-icon--{_esc(theme)}">{_esc(icon_glyph)}</div>'
        f'<div>'
        f'<h3 class="iwo3-attr-name">{_esc(title)}</h3>'
        f'<div class="iwo3-attr-sub">{_esc(subtitle)}</div>'
        f'</div>'
        f'</div>'
        f'<span class="iwo3-attr-badge iwo3-attr-badge--{_esc(license_color)}">'
        f'⚖ {_esc(license_label)}'
        f'</span>'
        f'</header>'
        f'<div class="iwo3-attr-body">'
    )


def _card_close() -> str:
    return '</div></section>'


def _metadata_grid(rows_html: list[str]) -> str:
    return f'<div class="iwo3-attr-grid">{"".join(rows_html)}</div>'


# ── Card 1 — AgentGoPro / AgentGoFlow ────────────────────────────


def _render_card_agentgoflow() -> None:
    """Foundational lineage — AgentGoPro/AgentGoFlow, including the
    LuaAzullaB Orchestration Framework / BeginnersMind Workshops
    sub-section per the canonical reference. Author: Darrel Vaughn
    (TRUTH FIX — prior generic renderer had Thomas C. Appling III)."""

    metadata = _metadata_grid([
        _info_row("Author", _esc("Darrel Vaughn")),
        _info_row("Consulting", _esc("10Touros")),
        _info_row("Lab", _esc("LuaAzullaB (formerly LuaLab)")),
        _info_row("Period", _esc("Mid-2024 – Aug 2025")),
    ])

    creator_origin = _section(
        "Creator & Origin",
        (
            "AgentGoPro/AgentGoFlow — originally named &ldquo;Agent "
            "Commander&rdquo; in Replit — was a basic orchestration "
            "framework for LLM-based agent coordination, developed "
            "independently by Darrel Vaughn under 10Touros (consulting) "
            "and LuaAzullaB (R&amp;D lab), beginning mid-2024 and "
            "continuing into 2025. The project was renamed from Agent "
            "Commander to AgentGoPro/AgentGoFlow during active "
            "development. It predates the adoption of PocketFlow and "
            "GCC Memory and is the foundational precursor to the PDOE "
            "agent orchestration architecture."
        ),
    )

    core_concept = _section(
        "Core Concept",
        (
            "AgentGoPro/AgentGoFlow established the foundational "
            "orchestration patterns later refined in PDOE: agent-to-"
            "agent task delegation, tiered authority (executive vs. "
            "execution layers), structured handoff protocols, and "
            "flow-based coordination of LLM agents. This original "
            "framework informed the architectural decisions that led "
            "to adopting PocketFlow as the production execution "
            "substrate and GCC Memory as the persistence layer."
        ),
    )

    timeline_rows = [
        ("Jun 2024", "Agent architecture planning (complete)"),
        ("Jul 2024", "Agent prompt language & infrastructure (complete)"),
        ("Aug 2024", "Multi-agent team structure (complete)"),
        ("Nov 2024", "Replit deployment infrastructure (complete)"),
        ("Dec 2024",
         '"Agent Commander" (original Replit project name) / RFP '
         'Bridge Assistant LAUNCH — LIVE. Project renamed to '
         'AgentGoPro/AgentGoFlow during this period.'),
        ("Jan 2025", "API enhancements & expansion (complete)"),
        ("Feb–Mar 2025", "Advanced agent research & new tools (ongoing)"),
        ("Through Aug 2025",
         "PDOE architecture formalized; PocketFlow adopted as "
         "execution substrate"),
    ]
    timeline_section = _section(
        "Timeline & Lineage",
        _timeline_rows_html(timeline_rows),
    )

    license_notice = _panel(
        "amber",
        "License Notice",
        (
            "AgentGoPro/AgentGoFlow is proprietary software owned by "
            "Darrel Vaughn, operating under 10Touros (consulting "
            "company) and LuaAzullaB (formerly LuaLab, R&amp;D lab). "
            "This is NOT open-source. No MIT, Apache, or Creative "
            "Commons license applies. All rights to the AgentGoPro/"
            "AgentGoFlow codebase, design patterns, and derived "
            "orchestration concepts are retained by Darrel Vaughn / "
            "10Touros / LuaAzullaB. Any reproduction, distribution, or "
            "derivative use requires explicit written permission from "
            "the rights holder."
        ),
    )

    attribution_statement = _panel(
        "note",
        "Attribution Statement",
        (
            "AgentGoPro/AgentGoFlow is the original LLM agent "
            "orchestration framework created by Darrel Vaughn under "
            "10Touros (consulting) and LuaAzullaB (formerly LuaLab, "
            "R&amp;D lab), developed from mid-2024 into 2025. It "
            "established the foundational patterns for tiered agent "
            "governance, structured task delegation, and flow-based "
            "orchestration that underpin the PDOE architecture. "
            "AgentGoPro/AgentGoFlow is proprietary software — all "
            "rights reserved by Darrel Vaughn / 10Touros / LuaAzullaB. "
            "The subsequent adoption of PocketFlow and GCC Memory "
            "within PDOE builds upon and extends these original "
            "concepts under their respective open-source licenses."
        ),
    )

    # LuaAzullaB Orchestration Framework — BeginnersMind Workshops
    # sub-section. Internal to the AgentGoPro card per IWO2 canon.
    bm_intro = (
        "The LuaAzullaB Orchestration Framework, developed by Darrel "
        "Vaughn (Oct 2025) and outlined in the BeginnersMind workshops, "
        "provides the conceptual and cognitive foundation for the PDOE "
        "orchestration model. The framework defines:"
    )
    bm_formula = (
        '<div class="iwo3-attr-formula">'
        '<p>Orchestration = [Workflow] × [Execution] → Results '
        '(factual) ≠ Goals (aspirational)</p>'
        '<p>Workflow = [Plan] + [Context(i)]</p>'
        '<p>where Context(i) is <strong>Informed Context</strong> — '
        '&ldquo;Know-How&rdquo; — comprising four interdependent '
        'dimensions:</p>'
        '<p><strong>Attention · Meaning · Relevance · Memory</strong></p>'
        '</div>'
    )
    bm_after_formula = (
        "These four dimensions form a cross-linked quadrant that "
        "governs how agents maintain, retrieve, and apply contextual "
        "awareness during orchestrated execution. This cognitive + "
        "orchestration model is the theoretical basis for the "
        "AgentGoPro/AgentGoFlow orchestration architecture and "
        "directly informed the design of PDOE&rsquo;s two-tier "
        "governance, GCC Memory&rsquo;s persistence layer (the Memory "
        "dimension), and Aiden&rsquo;s executive reasoning (the "
        "Attention and Meaning dimensions)."
    )
    bm_diagram = (
        '<pre class="iwo3-attr-ascii">'
        + escape(
            "                    ORCHESTRATION\n"
            "                   /             \\\n"
            "                  /               \\\n"
            "            WORKFLOW    ×    EXECUTION\n"
            "           /        \\               \\\n"
            "          /          \\               \\\n"
            "      PLAN    +    CONTEXT(i)     RESULTS (factual)\n"
            "                   \"Know-How\"         |\n"
            "                 /    |    \\           ≠\n"
            "               /      |      \\        |\n"
            "        Attention  Relevance  Memory  GOALS (aspirational)\n"
            "             \\        |       /\n"
            "              \\       |      /\n"
            "                \\     |     /\n"
            "                 Meaning"
        )
        + '</pre>'
    )
    bm_ref_path = (
        '<p class="iwo3-attr-fineprint">Reference diagram: '
        + _code("+6PLOCKER/Locker_BM.AI/Lua_Orchestration_Framework.png")
        + '</p>'
        '<p class="iwo3-attr-fineprint">Developed by Darrel Vaughn '
        '| LuaAzullaB | Oct 20, 2025</p>'
    )
    beginnersmind_subsection = _section(
        "LuaAzullaB Orchestration Framework — BeginnersMind Workshops",
        (
            f'<p>{bm_intro}</p>'
            f'{bm_formula}'
            f'<p>{bm_after_formula}</p>'
            f'{bm_diagram}'
            f'{bm_ref_path}'
        ),
    )

    st.html(
        _card_open(
            theme="amber",
            icon_glyph="◫",
            title="AgentGoPro/AgentGoFlow",
            subtitle="LuaAzullaB Orchestration Framework",
            license_label="Proprietary",
            license_color="red",
        )
        + metadata
        + creator_origin
        + core_concept
        + timeline_section
        + license_notice
        + attribution_statement
        + beginnersmind_subsection
        + _card_close()
    )


# ── Card 2 — Aiden Zephyr & TIB ──────────────────────────────────


def _render_card_aiden_zephyr() -> None:
    """Foundational lineage — Aiden Zephyr concept and TIB framework
    contributed by Thomas C. Appling III / FF.AI. Note this card has
    no `Author` field — its metadata vocabulary is
    Contributor/Organization/Type. Prior generic renderer crashed on
    `entry["author"]`; the literal-mirror posture eliminates the
    shared-schema assumption."""

    metadata = _metadata_grid([
        _info_row("Contributor", _esc("Thomas C. Appling III")),
        _info_row("Organization", _esc("Freedom Forge AI (FF.AI)")),
        _info_row("Type", _esc("Creative inspiration & conceptual framing")),
    ])

    license_notice = _panel(
        "rose",
        "License Notice",
        (
            "The Aiden Zephyr concept and TIB (The Internal Brain) "
            "framework are attributed to Thomas C. Appling III and the "
            "Freedom Forge AI (FF.AI) as creative and collaborative "
            "contributions. These are acknowledged as inspirational and "
            "collaborative inputs, not code-level dependencies. No "
            "open-source license applies. Attribution is granted in "
            "recognition of creative influence and collaborative "
            "development of agent identity, persona design, and "
            "cognitive architecture framing within the PDOE ecosystem."
        ),
    )

    contributor_source = _section(
        "Contributor & Source",
        (
            "Thomas C. Appling III introduced the &ldquo;Aiden "
            "Zephyr&rdquo; agent concept and later contributed The "
            "Internal Brain (TIB) framework through his work with "
            "FF.AI. These ideas shaped the identity, persona, and "
            "cognitive architecture of the Aiden agent within PDOE. "
            "Note: Darrel Vaughn&rsquo;s multi-agent orchestration "
            "framework (Agent Commander, later AgentGoPro/AgentGoFlow) "
            "was already in active planning and development prior to "
            "the introduction of the Aiden Zephyr concept."
        ),
    )

    core_contribution = _section(
        "Core Contribution",
        (
            "Two distinct contributions: (1) <strong>Aiden Zephyr"
            "</strong> — the original agent identity concept that "
            "became &ldquo;Aiden&rdquo; in PDOE&rsquo;s Tier 1 "
            "executive orchestrator. Appling&rsquo;s vision gave the "
            "agent its name, persona, and early character as an "
            "autonomous reasoning entity. (2) <strong>The Internal "
            "Brain (TIB)</strong> — a cognitive architecture concept "
            "contributed through FF.AI that informed how Aiden "
            "processes, reasons, and maintains internal state. TIB "
            "influenced the design of Aiden&rsquo;s executive "
            "decision-making layer within the two-tier PDOE "
            "architecture. The current implementation of the AIDEN_IWO "
            "supports the TIB framework but is by design — not "
            "limited to it."
        ),
    )

    precedence_note = (
        '<div class="iwo3-attr-precedence">'
        '<div class="iwo3-attr-precedence-title">PRECEDENCE NOTE</div>'
        '<div class="iwo3-attr-precedence-body">'
        "Darrel Vaughn began Agent Commander (multi-agent "
        "orchestration framework) architecture planning in early - "
        "mid (Jun) 2024, with prompt language, infrastructure, and "
        "multi-agent team structure built through Aug 2024 — most of "
        "this work prior to the introduction of the Aiden Zephyr "
        "concept."
        '</div>'
        '</div>'
    )
    timeline_rows = [
        ("Late 2024", "Aiden Zephyr agentic concepts evolved (Appling)"),
        ("Mar 17, 2025",
         '"Aiden Zephyr" reference email from Thomas C. Appling III'),
    ]
    timeline_tail = (
        '<p class="iwo3-attr-tail">'
        "The Aiden Zephyr identity and FF.AI / TIB concepts were "
        "introduced subsequent to Vaughn&rsquo;s foundational "
        "orchestration work and were integrated into the already-"
        "established multi-agent architecture as creative and "
        "conceptual enhancements."
        '</p>'
    )
    timeline_section = _section(
        "Timeline & Precedence",
        precedence_note + _timeline_rows_html(timeline_rows) + timeline_tail,
    )

    attribution_statement = _panel(
        "note",
        "Attribution Statement",
        (
            "LuaAzullaB / PDOE framework gratefully acknowledges Thomas "
            "C. Appling III and the Freedom Forge AI (FF.AI) for the "
            "creative inspiration behind the Aiden agent identity — "
            "originally conceived as &ldquo;Aiden Zephyr&rdquo; — and "
            "for the conceptual contributions of The Internal Brain "
            "(TIB) cognitive architecture framework. These "
            "contributions shaped the persona, identity, and reasoning "
            "character of Aiden as PDOE&rsquo;s Tier 1 executive "
            "orchestrator. It is expressly noted that Darrel "
            "Vaughn&rsquo;s multi-agent orchestration framework (Agent "
            "Commander / AgentGoPro/AgentGoFlow) was already in active "
            "planning and development prior to the introduction of the "
            "Aiden Zephyr concept — the creative identity was layered "
            "onto an existing architectural foundation."
        ),
    )

    st.html(
        _card_open(
            theme="rose",
            icon_glyph="✧",
            title="Aiden Zephyr & TIB",
            subtitle="Thomas C. Appling III / FF.AI",
            license_label="Creative Attribution",
            license_color="default",
        )
        + metadata
        + license_notice
        + contributor_source
        + core_contribution
        + timeline_section
        + attribution_statement
        + _card_close()
    )


# ── Card 3 — GCC Memory ──────────────────────────────────────────


def _render_card_gcc_memory() -> None:
    """Foundational lineage — GCC Memory (Junde Wu, arXiv:2508.00031).
    Metadata vocabulary: Paper / DOI / URL — not the generic
    Author/Org. License: CC BY 4.0 / MIT (preserved verbatim from
    canonical reference, not collapsed to generic 'Open Source')."""

    metadata = _metadata_grid([
        _info_row(
            "Paper",
            _esc(
                'Wu, Junde. "Git Context Controller: Manage the Context '
                'of LLM-based Agents like Git." arXiv:2508.00031 (2025)'
            ),
        ),
        _info_row("DOI", _link(
            "https://doi.org/10.48550/arXiv.2508.00031",
            "10.48550/arXiv.2508.00031",
        )),
        _info_row("URL", _link(
            "https://arxiv.org/abs/2508.00031",
            "arxiv.org/abs/2508.00031",
        )),
    ])

    core_concept = _section(
        "Core Concept",
        (
            "GCC applies Git&rsquo;s version-control metaphor to LLM "
            "agent memory. Four canonical commands: <strong>COMMIT"
            "</strong> (durable milestone snapshot of branch progress), "
            "<strong>BRANCH</strong> (isolated memory line for alternate "
            "strategy exploration), <strong>MERGE</strong> (consolidate "
            "branch outcomes under Tier 1 governance), <strong>CONTEXT"
            "</strong> (scoped history retrieval at multiple "
            "granularities). Memory artifacts are stored as markdown "
            "files in a project/branch/commit filesystem hierarchy."
        ),
    )

    pdoe_integration = _section(
        "PDOE Integration (WS014)",
        (
            "GCC Memory is a Tier 1 platform service in PDOE, peer to "
            "Channel Gateway and Tools Locker. Tier 2 agents may "
            "COMMIT and CONTEXT; only Tier 1 may MERGE. Branch "
            "creation requires Tier 1 approval (mode-dependent). GCC "
            "metadata lives in shared dict (" + _code("gcc.*")
            + " keys) and filesystem artifacts only — never injected "
            "into Work Order or BDM payloads. Contracts: "
            + _code("gcc_command_contract.md")
            + " (GCC-A-001), "
            + _code("gcc_shared_dict_contract.md")
            + " (GCC-A-002)."
        ),
    )

    license_details = _panel(
        "purple",
        "License Details",
        (
            '<p><strong>Paper (CC BY 4.0):</strong> Cite + attribution '
            'if concepts are reused.</p>'
            '<p><strong>Implementation (MIT):</strong> Preserve MIT '
            'notice if code is reused (human-re/GCC).</p>'
            '<p><strong>Packages (MIT):</strong> Preserve MIT notice '
            'if aline-ai package code reused.</p>'
        ),
    )

    attribution_statement = _panel(
        "note",
        "Attribution Statement",
        (
            "The GCC Memory Framework in PDOE is inspired by &ldquo;"
            "Git Context Controller: Manage the Context of LLM-based "
            "Agents like Git&rdquo; (Junde Wu, arXiv:2508.00031, "
            "2025, CC BY 4.0). The reference implementation at "
            "human-re/GCC and the aline-ai tooling packages are both "
            "MIT-licensed. PDOE adapts the GCC conceptual model — "
            "Git-style COMMIT/BRANCH/MERGE/CONTEXT commands for "
            "persistent agent memory — within its existing two-tier "
            "PocketFlow orchestration architecture. No GCC source "
            "code is vendored; PDOE uses its own TypeScript "
            "implementation conforming to the GCC protocol contracts."
        ),
    )

    st.html(
        _card_open(
            theme="purple",
            icon_glyph="◍",
            title="GCC Memory",
            subtitle="Git Context Controller",
            license_label="CC BY 4.0 / MIT",
            license_color="purple",
        )
        + metadata
        + core_concept
        + pdoe_integration
        + license_details
        + attribution_statement
        + _card_close()
    )


# ── Card 4 — PocketFlow ──────────────────────────────────────────


def _render_card_pocketflow() -> None:
    """Foundational lineage — PocketFlow (Zachary Huang, MIT). Full
    metadata vocabulary preserved: Author/Affiliation/Organization/
    Repository/Docs/PyPI/License — not collapsed to generic shape."""

    metadata = _metadata_grid([
        _info_row("Author", _esc("Zachary Huang (GitHub: zachary62)")),
        _info_row(
            "Affiliation",
            _esc(
                "Microsoft Research AI Frontiers; PhD Columbia "
                "University; 2023 Google PhD Fellow"
            ),
        ),
        _info_row("Organization", _esc("The-Pocket (GitHub org)")),
        _info_row("Repository", _link(
            "https://github.com/The-Pocket/PocketFlow",
            "github.com/The-Pocket/PocketFlow",
        )),
        _info_row("Docs", _link(
            "https://the-pocket.github.io/PocketFlow/",
            "the-pocket.github.io/PocketFlow",
        )),
        _info_row("PyPI", _esc("pocketflow (v0.0.3)")),
        _info_row("License", _esc("MIT (Copyright 2024 Zachary Huang)")),
    ])

    core_concept = _section(
        "Core Concept",
        (
            "PocketFlow distills LLM framework abstractions into 100 "
            "lines of dependency-free Python. The core is a directed "
            "graph of Nodes and Flows: <strong>BaseNode</strong> "
            "(prep/exec/post lifecycle, " + _code(">>") + " and "
            + _code("-")
            + " DSL operators), <strong>Node</strong> (sync with retry), "
            "<strong>BatchNode</strong> (list processing), "
            "<strong>Flow</strong> (graph orchestrator with start_node "
            "and _orch() loop), plus async variants. From this 100-line "
            "core, users implement Agents, Multi-Agents, Workflows, "
            "RAG, Map-Reduce, Structured Output, and other LLM design "
            "patterns."
        ),
    )

    pdoe_integration = _section(
        "PDOE Integration (WS012 → WS014)",
        (
            "WS012 is the library/reference workspace (upstream clone "
            "+ offline docs mirror + PDOE supplement). WS014 is the "
            "production integration workspace that vendors PocketFlow "
            "core and ships runnable two-tier flows. WS006 is the "
            "canonical source for the PocketFlow Supplement spec and "
            "schemas (Work Orders, BDM Markers, Policy Gates). "
            "PocketFlow runs INSIDE each tier as a flow executor, not "
            "as the overall system controller."
        ),
    )

    mit_license = _panel(
        "blue",
        "MIT License",
        (
            "MIT License — free to use, copy, modify, merge, publish, "
            "distribute, sublicense, sell. Obligation: preserve MIT "
            "notice when vendoring code. WS014 vendors "
            + _code("pocketflow/__init__.py")
            + " at "
            + _code("02_Execution/vendor/pocketflow/__init__.py")
            + "."
        ),
    )

    attribution_statement = _panel(
        "note",
        "Attribution Statement",
        (
            "PocketFlow, created by Zachary Huang and maintained "
            "under The-Pocket GitHub organization, is a minimalist "
            "LLM orchestration framework whose entire core fits in "
            "100 lines of Python. It provides a graph-based "
            "abstraction (Nodes and Flows) with zero dependencies and "
            "zero vendor lock-in, supporting Agents, Multi-Agents, "
            "Workflows, and RAG patterns. Licensed under the MIT "
            "License (Copyright 2024 Zachary Huang). PDOE vendors the "
            "100-line core from WS012 into the WS014 production "
            "runtime and extends it with PDOE-specific nodes for "
            "two-tier orchestration."
        ),
    )

    st.html(
        _card_open(
            theme="blue",
            icon_glyph="◌",
            title="PocketFlow",
            subtitle="100-Line LLM Framework",
            license_label="MIT",
            license_color="outline",
        )
        + metadata
        + core_concept
        + pdoe_integration
        + mit_license
        + attribution_statement
        + _card_close()
    )


# ── Lead Developer Card ──────────────────────────────────────────


def _render_lead_developer_card() -> None:
    """The Vaughn lead-developer attribution card mirrors the
    canonical reference's gradient panel with Sparkles icon."""
    st.html(
        '<section class="iwo3-attr-leaddev">'
        '<div class="iwo3-attr-leaddev-row">'
        '<div class="iwo3-attr-leaddev-icon">✦</div>'
        '<div>'
        '<div class="iwo3-attr-leaddev-eyebrow">'
        'Lead Developer &amp; Principal Technical Architect'
        '</div>'
        '<h2 class="iwo3-attr-leaddev-name">Darrel Vaughn</h2>'
        '<div class="iwo3-attr-leaddev-role">'
        'LuaAzullaB (R&amp;D Lab) · 10Touros (Consulting) · '
        'AIDEN_IWO / PDOE Platform'
        '</div>'
        '</div>'
        '</div>'
        '<hr class="iwo3-attr-leaddev-rule" />'
        '<p class="iwo3-attr-leaddev-prose">'
        'Darrel Vaughn is the lead developer and principal technical '
        'architect of the AIDEN_IWO platform. From the original Agent '
        'Commander concept (mid-2024) through the AgentGoPro/'
        'AgentGoFlow orchestration framework and into the current '
        'IWO/PDOE two-tier architecture, Vaughn has designed, built, '
        'and led every layer of the system — including the '
        'orchestration engine, GCC Memory integration, PocketFlow '
        'execution substrate, Agentic Tools Locker, workspace filing, '
        'and the BeginnersMind cognitive model that governs agent '
        'reasoning.'
        '</p>'
        '</section>'
    )


# ── External Tooling section (IWO3-specific, secondary) ──────────


def _render_external_tooling() -> None:
    """IWO3-specific external tooling acknowledgements. These are
    NOT in the canonical IWO2 attribution register — they're added
    here as a clearly secondary section so the foundational lineage
    surface stays canonical-faithful. Smaller card style, uniform
    metadata vocabulary (Author / Organization / Type / License)
    because these external services share the same shape (unlike
    the foundational lineage cards)."""

    entries: list[dict] = [
        {
            "icon": "▣",
            "title": "Gamma",
            "subtitle": "Presentation and document rendering adapter",
            "license_label": "Commercial API",
            "license_color": "violet",
            "rows": [
                ("Author", "Gamma"),
                ("Organization", "Gamma"),
                ("Type", "External rendering / output adapter"),
                ("License", "Service terms (commercial API)"),
            ],
            "blurb": (
                "Gamma is used by the IWO product line as an external "
                "rendering / delivery system for high-quality "
                "presentation and document outputs, especially for "
                "template-governed PPTX/PDF workflows. IWO3 "
                "acknowledges Gamma as an external presentation/"
                "document rendering platform used within its "
                "adapter-driven output architecture."
            ),
        },
        {
            "icon": "◈",
            "title": "Stitch (Google) — via MCP",
            "subtitle": "Design-generation and MCP-backed design tooling",
            "license_label": "Commercial API",
            "license_color": "violet",
            "rows": [
                ("Author", "Google Stitch"),
                ("Organization", "Google"),
                ("Type", "MCP-backed external tooling"),
                ("License", "Service terms (Google Stitch)"),
            ],
            "blurb": (
                "Stitch was integrated into IWO3 as part of the Tool "
                "Locker and design-oriented sub-agent capability "
                "surface. It is used through MCP-backed runtime "
                "tooling rather than as a native orchestration "
                "framework. IWO3 acknowledges Stitch as an external "
                "design-tool integration used through MCP-backed "
                "tooling in the Tool Locker and related sub-agent "
                "workflows."
            ),
        },
        {
            "icon": "⌕",
            "title": "Brave Search API",
            "subtitle": "Live web search capability for tool-assisted sub-agents",
            "license_label": "Commercial API",
            "license_color": "violet",
            "rows": [
                ("Author", "Brave"),
                ("Organization", "Brave Software"),
                ("Type", "External live-search provider"),
                ("License", "Service terms (Brave Search API)"),
            ],
            "blurb": (
                "Brave Search was integrated as a live search tool "
                "for IWO3&rsquo;s Tool Locker / runtime tool surface. "
                "It contributes current web-search capability for "
                "agents that need retrieval beyond local state, "
                "especially in research, design, and content-oriented "
                "workflows."
            ),
        },
        {
            "icon": "✦",
            "title": "Perplexity API",
            "subtitle": "Live answer-oriented search and synthesis support",
            "license_label": "Commercial API",
            "license_color": "violet",
            "rows": [
                ("Author", "Perplexity"),
                ("Organization", "Perplexity"),
                ("Type", "External retrieval / synthesis provider"),
                ("License", "Service terms (Perplexity API)"),
            ],
            "blurb": (
                "Perplexity was integrated as an additional external "
                "search/retrieval path within IWO3&rsquo;s runtime "
                "tool layer. It contributes answer-oriented search "
                "and retrieval support for agents that benefit from "
                "external synthesis capabilities during tool-assisted "
                "execution."
            ),
        },
    ]

    st.html(
        '<section class="iwo3-attr-tooling-section">'
        '<h2 class="iwo3-attr-tooling-heading">External Tooling Used by IWO3</h2>'
        '<p class="iwo3-attr-tooling-sub">'
        'Third-party services and APIs integrated by IWO3 for runtime '
        'capability. These are operational dependencies, not '
        'foundational lineage of the orchestration architecture above.'
        '</p>'
        '</section>'
    )

    for entry in entries:
        rows_html = _metadata_grid([
            _info_row(label, _esc(value)) for label, value in entry["rows"]
        ])
        body = (
            f'<p class="iwo3-attr-copy">{entry["blurb"]}</p>'
        )
        st.html(
            f'<section class="iwo3-attr-tool-card">'
            f'<header class="iwo3-attr-head iwo3-attr-head--small">'
            f'<div class="iwo3-attr-head-main">'
            f'<div class="iwo3-attr-icon iwo3-attr-icon--violet">'
            f'{_esc(entry["icon"])}</div>'
            f'<div>'
            f'<h3 class="iwo3-attr-name">{_esc(entry["title"])}</h3>'
            f'<div class="iwo3-attr-sub">{_esc(entry["subtitle"])}</div>'
            f'</div>'
            f'</div>'
            f'<span class="iwo3-attr-badge iwo3-attr-badge--{_esc(entry["license_color"])}">'
            f'⚖ {_esc(entry["license_label"])}'
            f'</span>'
            f'</header>'
            f'<div class="iwo3-attr-body">'
            f'{rows_html}'
            f'{body}'
            f'</div>'
            f'</section>'
        )


# ── Page CSS ─────────────────────────────────────────────────────


_CSS = """
<style>
  .iwo3-attr-wrap {
    max-width: 980px;
    margin: 0 auto;
    padding-bottom: 36px;
  }
  .iwo3-attr-back {
    color: #374151;
    font-size: 0.92rem;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 18px;
  }
  .iwo3-attr-back:hover { color: #111827; }
  .iwo3-attr-title {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 2.9rem;
    line-height: 1.02;
    color: #111827;
    letter-spacing: -0.03em;
    margin: 0 0 10px 0;
  }
  .iwo3-attr-subtitle {
    font-size: 1rem;
    line-height: 1.55;
    color: #6B7280;
    max-width: 920px;
    margin-bottom: 4px;
  }
  .iwo3-attr-collected {
    font-size: 0.86rem;
    color: #6B7280;
    margin-bottom: 26px;
  }

  /* Card primitives */
  .iwo3-attr-card {
    border: 1px solid #E5E7EB;
    border-radius: 16px;
    background: #FFFFFF;
    padding: 22px 24px 24px 24px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    margin-bottom: 18px;
  }
  .iwo3-attr-head {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 18px;
    margin-bottom: 18px;
  }
  .iwo3-attr-head-main {
    display: flex;
    align-items: flex-start;
    gap: 14px;
    min-width: 0;
  }
  .iwo3-attr-icon {
    width: 42px;
    height: 42px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.15rem;
    flex-shrink: 0;
  }
  .iwo3-attr-icon--amber  { background: #FEF3C7; color: #B45309; }
  .iwo3-attr-icon--rose   { background: #FFE4E6; color: #BE123C; }
  .iwo3-attr-icon--purple { background: #EDE9FE; color: #6D28D9; }
  .iwo3-attr-icon--blue   { background: #DBEAFE; color: #1D4ED8; }
  .iwo3-attr-icon--violet { background: #EDE9FE; color: #6D28D9; }
  .iwo3-attr-name {
    font-size: 1.06rem;
    font-weight: 700;
    color: #111827;
    line-height: 1.2;
    margin: 0 0 3px 0;
  }
  .iwo3-attr-sub {
    font-size: 0.94rem;
    color: #6B7280;
    line-height: 1.4;
  }

  /* Badge */
  .iwo3-attr-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 600;
    white-space: nowrap;
    gap: 4px;
  }
  .iwo3-attr-badge--red     { background: #DC2626; color: #FFFFFF; }
  .iwo3-attr-badge--default { background: #1F2937; color: #FFFFFF; }
  .iwo3-attr-badge--purple  { background: #6D28D9; color: #FFFFFF; }
  .iwo3-attr-badge--outline { background: #FFFFFF; color: #374151; border: 1px solid #D1D5DB; }
  .iwo3-attr-badge--violet  { background: #EDE9FE; color: #6D28D9; }

  /* Metadata grid */
  .iwo3-attr-grid {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 18px;
  }
  .iwo3-info-row {
    display: grid;
    grid-template-columns: 140px 1fr;
    column-gap: 18px;
    align-items: baseline;
  }
  .iwo3-info-row .k {
    color: #6B7280;
    font-size: 0.92rem;
    font-weight: 500;
  }
  .iwo3-info-row .v {
    color: #111827;
    font-size: 0.94rem;
  }

  /* Sections */
  .iwo3-attr-section {
    border-top: 1px solid #E5E7EB;
    padding-top: 16px;
    margin-top: 16px;
  }
  .iwo3-attr-section h4 {
    margin: 0 0 10px 0;
    font-size: 0.98rem;
    font-weight: 700;
    color: #111827;
  }
  .iwo3-attr-copy {
    color: #4B5563;
    font-size: 0.95rem;
    line-height: 1.65;
  }
  .iwo3-attr-copy p { margin: 0 0 12px 0; }
  .iwo3-attr-copy p:last-child { margin-bottom: 0; }

  /* Timeline */
  .iwo3-attr-timeline {
    display: grid;
    grid-template-columns: 130px 1fr;
    gap: 8px 16px;
    color: #4B5563;
    font-size: 0.94rem;
    line-height: 1.55;
  }
  .iwo3-attr-timeline .t {
    color: #6B7280;
    text-align: right;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas,
      "Liberation Mono", "Courier New", monospace;
    font-size: 0.78rem;
    padding-top: 2px;
    font-variant-numeric: tabular-nums;
  }
  .iwo3-attr-timeline .n {
    color: #4B5563;
  }

  /* Panels */
  .iwo3-attr-panel {
    border-radius: 12px;
    padding: 14px 16px;
    margin-top: 14px;
  }
  .iwo3-attr-panel h4 {
    margin: 0 0 8px 0;
    font-size: 0.98rem;
    font-weight: 700;
    color: #111827;
  }
  .iwo3-attr-panel.amber  { background: #FFFBEB; border: 1px solid #FDE68A; }
  .iwo3-attr-panel.rose   { background: #FFF1F2; border: 1px solid #FBCFE8; }
  .iwo3-attr-panel.purple { background: #FAF5FF; border: 1px solid #E9D5FF; }
  .iwo3-attr-panel.blue   { background: #EFF6FF; border: 1px solid #BFDBFE; }
  .iwo3-attr-panel.note   { background: #F9FAFB; border: 1px solid #E5E7EB; }
  .iwo3-attr-panel .copy {
    color: #4B5563;
    font-size: 0.93rem;
    line-height: 1.65;
  }
  .iwo3-attr-panel .copy p { margin: 0 0 8px 0; }
  .iwo3-attr-panel .copy p:last-child { margin-bottom: 0; }

  /* Aiden precedence note (rose) */
  .iwo3-attr-precedence {
    background: #FFF1F2;
    border: 1px solid #FBCFE8;
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 12px;
  }
  .iwo3-attr-precedence-title {
    font-size: 0.74rem;
    font-weight: 700;
    color: #9F1239;
    letter-spacing: 0.03em;
    margin-bottom: 4px;
  }
  .iwo3-attr-precedence-body {
    color: #4B5563;
    font-size: 0.92rem;
    line-height: 1.55;
  }
  .iwo3-attr-tail {
    margin-top: 12px;
    color: #4B5563;
    font-size: 0.92rem;
    line-height: 1.55;
  }

  /* AgentGoPro / BeginnersMind formula + ASCII diagram */
  .iwo3-attr-formula {
    background: #F1F5F9;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 14px 16px;
    margin: 12px 0;
    color: #4B5563;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.78rem;
    line-height: 1.55;
  }
  .iwo3-attr-formula p { margin: 0 0 6px 0; }
  .iwo3-attr-formula p:last-child { margin-bottom: 0; }
  .iwo3-attr-ascii {
    background: #F1F5F9;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
    padding: 14px 16px;
    margin: 12px 0;
    color: #4B5563;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.78rem;
    line-height: 1.45;
    overflow-x: auto;
    white-space: pre;
  }
  .iwo3-attr-fineprint {
    color: #6B7280;
    font-size: 0.78rem;
    line-height: 1.5;
    margin: 4px 0 0 0;
  }
  .iwo3-attr-code {
    background: #F3F4F6;
    color: #111827;
    border-radius: 4px;
    padding: 1px 6px;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    font-size: 0.82rem;
  }
  .iwo3-attr-link {
    color: #2563EB;
    text-decoration: none;
    border-bottom: 1px dotted #93C5FD;
  }
  .iwo3-attr-link:hover { color: #1D4ED8; border-bottom-style: solid; }

  /* Lead Developer card */
  .iwo3-attr-leaddev {
    margin-top: 28px;
    padding: 22px 24px;
    border: 1px solid #FCD34D55;
    border-radius: 16px;
    background: linear-gradient(120deg, #FFFBEB 0%, #FFFFFF 50%, #EFF6FF 100%);
  }
  .iwo3-attr-leaddev-row {
    display: flex;
    align-items: center;
    gap: 16px;
  }
  .iwo3-attr-leaddev-icon {
    width: 56px;
    height: 56px;
    border-radius: 14px;
    background: #FEF3C7;
    color: #B45309;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.6rem;
    flex-shrink: 0;
    border: 1px solid #FDE68A;
  }
  .iwo3-attr-leaddev-eyebrow {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.16em;
    color: #B45309;
    text-transform: uppercase;
  }
  .iwo3-attr-leaddev-name {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.78rem;
    font-weight: 700;
    color: #111827;
    margin: 2px 0 4px 0;
  }
  .iwo3-attr-leaddev-role {
    color: #6B7280;
    font-size: 0.9rem;
  }
  .iwo3-attr-leaddev-rule {
    border: none;
    border-top: 1px solid #E5E7EB;
    margin: 16px 0;
  }
  .iwo3-attr-leaddev-prose {
    color: #1F2937;
    font-size: 0.95rem;
    line-height: 1.65;
    margin: 0;
  }

  /* External Tooling secondary section */
  .iwo3-attr-tooling-section {
    margin-top: 36px;
    padding-top: 16px;
    border-top: 2px solid #E5E7EB;
  }
  .iwo3-attr-tooling-heading {
    font-family: Georgia, "Times New Roman", serif;
    font-size: 1.4rem;
    color: #111827;
    margin: 0 0 6px 0;
    font-weight: 700;
  }
  .iwo3-attr-tooling-sub {
    color: #6B7280;
    font-size: 0.9rem;
    margin-bottom: 12px;
  }
  .iwo3-attr-tool-card {
    border: 1px solid #E5E7EB;
    border-radius: 14px;
    background: #FFFFFF;
    padding: 18px 20px 20px 20px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.03);
    margin-bottom: 14px;
  }
  .iwo3-attr-head--small { margin-bottom: 14px; }
  .iwo3-attr-tool-card .iwo3-attr-icon {
    width: 36px;
    height: 36px;
    border-radius: 10px;
  }
  .iwo3-attr-tool-card .iwo3-attr-name { font-size: 1rem; }

  /* Footer */
  .iwo3-attr-footer {
    margin-top: 36px;
    padding-top: 18px;
    border-top: 1px solid #E5E7EB;
    text-align: center;
    color: #6B7280;
    font-size: 0.88rem;
  }
  .iwo3-attr-footer p { margin: 2px 0; }
  .iwo3-attr-footer .small { font-size: 0.78rem; }

  @media (max-width: 820px) {
    .iwo3-attr-title { font-size: 2.2rem; }
    .iwo3-attr-head { flex-direction: column; }
    .iwo3-info-row,
    .iwo3-attr-timeline {
      grid-template-columns: 1fr;
    }
    .iwo3-attr-timeline .t { text-align: left; }
  }
</style>
"""


# ── Entry point ──────────────────────────────────────────────────


def main() -> None:
    st.html(_CSS)
    st.html('<div class="iwo3-attr-wrap">')

    if st.button("← Back", key="attr-back", type="tertiary"):
        # Authenticated callers came from the Tier Overview surface;
        # public/anonymous callers came from the landing page. The
        # Tier Overview switch_page is the existing legacy default;
        # if it's unreachable (no auth context), Streamlit raises
        # which Streamlit's own runtime handles by ignoring.
        try:
            st.switch_page("views/tier_overview.py")
        except Exception:  # noqa: BLE001
            try:
                st.switch_page("Home.py")
            except Exception:  # noqa: BLE001
                pass

    st.html(
        '<h1 class="iwo3-attr-title">Attribution Register</h1>'
        '<div class="iwo3-attr-subtitle">'
        'AgentGoPro/AgentGoFlow, Aiden Zephyr/TIB, GCC Memory '
        '&amp; PocketFlow — foundational lineages of IWO/PDOE.'
        '</div>'
        f'<div class="iwo3-attr-collected">Collected {_esc(_COLLECTED_DATE)}</div>'
    )

    # Foundational lineage — order mirrors the canonical reference.
    _render_card_agentgoflow()
    _render_card_aiden_zephyr()
    _render_card_gcc_memory()
    _render_card_pocketflow()

    # Lead Developer card sits between the foundational cards and
    # the external-tooling section, matching canonical layout.
    _render_lead_developer_card()

    # IWO3-specific external tooling — clearly secondary section.
    _render_external_tooling()

    # Footer — IWO3 (not IWO2).
    st.html(
        '<footer class="iwo3-attr-footer">'
        '<p>AIDEN_IWO3 — Intelligent Work Orchestration</p>'
        '<p class="small">Lead Developer &amp; Principal Technical '
        'Architect: Darrel Vaughn | LuaAzullaB</p>'
        '</footer>'
    )

    st.html('</div>')


main()

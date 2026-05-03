"""Attribution Register — document-style provenance surface for IWO3.

Mirrors the IWO2-inspired register layout rather than rendering as a
settings/admin page. First release is repo-tracked content with no DB
dependency so the public surface stays stable while Tool Locker evolves.
"""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from shell import page_requires_api


_COLLECTED_DATE = "2026-05-02"


_ENTRIES: list[dict[str, Any]] = [
    {
        "name": "AgentGoPro/AgentGoFlow",
        "subtitle": "LuaAzullaB orchestration framework",
        "badge": ("Proprietary", "red"),
        "icon": "◫",
        "author": "Darrel Vaughn",
        "organization": "10Touros / LuaAzullaB",
        "category": "Foundational Lineage",
        "period": "Mid-2024 to Aug 2025",
        "origin": (
            "AgentGoPro/AgentGoFlow established the earliest practical "
            "orchestration patterns that later informed the PDOE and IWO "
            "architecture. It was developed independently by Darrel Vaughn "
            "through 10Touros and LuaAzullaB as a coordination framework "
            "for LLM-driven agent work, structured delegation, and "
            "workflow-governed execution. It predates the later adoption "
            "of PocketFlow and the formalization of GCC Memory as "
            "separate production layers."
        ),
        "core_concept": (
            "AgentGoPro/AgentGoFlow contributed the foundational ideas of "
            "tiered agent authority, structured handoff, execution-vs-"
            "orchestration separation, and workflow-mediated coordination. "
            "These ideas remain visible in IWO3 through role-based "
            "orchestration, sub-agent routing, governed execution, and "
            "lifecycle-driven work-order progression."
        ),
        "timeline": [
            ("Jun 2024", "early orchestration planning and agent-control experiments"),
            ("Jul 2024", "prompt-language and coordination structure established"),
            ("Aug 2024", "multi-agent team pattern stabilized"),
            ("Nov 2024", "deployment and runtime infrastructure hardened"),
            ("Dec 2024", "earlier project naming still in use during active development"),
            ("Jan 2025", "orchestration patterns expanded and generalized"),
            ("Feb-Aug 2025", "concepts matured into the broader PDOE architecture"),
            ("Through Aug 2025", "PocketFlow and GCC Memory adopted downstream as execution and persistence layers"),
        ],
        "license_notice": (
            "AgentGoPro/AgentGoFlow is proprietary software and framework "
            "IP associated with Darrel Vaughn and the operating entities "
            "under which the work was developed. It is not presented as "
            "open-source software. Reproduction, redistribution, or "
            "derivative reuse of its design patterns, implementation "
            "details, or documentation should be treated as rights-"
            "reserved unless separately authorized."
        ),
        "attribution_statement": (
            "IWO3/PDOE acknowledges AgentGoPro/AgentGoFlow as a "
            "foundational precursor to its orchestration model. The later "
            "adoption of other frameworks and infrastructure components "
            "builds on, rather than replaces, this original orchestration "
            "lineage."
        ),
    },
    {
        "name": "LuaAzullaB Orchestration Framework",
        "subtitle": "Conceptual orchestration model and workshop lineage",
        "badge": ("Proprietary", "red"),
        "icon": "◎",
        "author": "Darrel Vaughn",
        "organization": "LuaAzullaB",
        "category": "Foundational Lineage",
        "period": "2025",
        "origin": (
            "The LuaAzullaB Orchestration Framework consolidated workshop-"
            "era thinking around structured execution, factual outputs, "
            "governed workflows, and operationalized agent systems. It "
            "served as a conceptual bridge between earlier orchestration "
            "experiments and the more explicit PDOE/IWO architecture."
        ),
        "core_concept": (
            "This framework emphasized that orchestration is not just "
            "message passing between models, but a governed relationship "
            "between workflow, execution, results, and goals. That framing "
            "directly supports IWO3’s treatment of work orders, workflows, "
            "lifecycle states, review gates, and output contracts."
        ),
        "timeline": [
            ("Early 2025", "framework language consolidated through internal development and workshops"),
            ("2025", "orchestration formula and governance concepts refined"),
            ("2025 onward", "concepts reflected in PDOE and IWO3 architecture planning"),
        ],
        "license_notice": (
            "This framework is treated as proprietary internal methodology "
            "unless otherwise released under explicit terms."
        ),
        "attribution_statement": (
            "IWO3 acknowledges the LuaAzullaB Orchestration Framework as "
            "part of the conceptual foundation behind its governed "
            "orchestration model."
        ),
    },
    {
        "name": "Aiden Zephyr / TIB",
        "subtitle": "Spec-level agent architecture and sub-agent lineage",
        "badge": ("Internal", "gray"),
        "icon": "⟡",
        "author": "Darrel Vaughn",
        "organization": "LuaAzullaB / AIDEN",
        "category": "Foundational Lineage",
        "period": "2024-2025",
        "origin": (
            "Aiden Zephyr/TIB represents the spec-level evolution of "
            "sub-agent identity, delegation logic, and role-driven "
            "cognition within the broader AIDEN family. It shaped the "
            "internal logic of role specialization, routing, and governed "
            "execution."
        ),
        "core_concept": (
            "Its main contribution is the formalization of agent identity, "
            "delegation boundaries, and specialized sub-agent roles. These "
            "ideas are reflected in IWO3’s Tier 1 / Tier 1.5 / Tier 2 "
            "structure and selective capability assignment model."
        ),
        "timeline": [
            ("2024", "sub-agent specialization patterns began forming"),
            ("2025", "role identity and delegation architecture became more explicit"),
            ("2025 onward", "integrated into the broader IWO successor direction"),
        ],
        "license_notice": (
            "This architecture is treated as internal/proprietary product "
            "architecture unless separately released."
        ),
        "attribution_statement": (
            "IWO3 acknowledges Aiden Zephyr/TIB as a direct lineage source "
            "for its role-based sub-agent system and delegation structure."
        ),
    },
    {
        "name": "PocketFlow",
        "subtitle": "Execution substrate for iterative workflow runs",
        "badge": ("Open Source", "green"),
        "icon": "◌",
        "author": "PocketFlow contributors",
        "organization": "PocketFlow project",
        "category": "Framework",
        "period": "Adopted downstream in PDOE/IWO",
        "origin": (
            "PocketFlow was adopted as an execution substrate after the "
            "earlier orchestration patterns were already established. It "
            "provided a practical framework for iterative plan/execute/"
            "evaluate/refine execution loops."
        ),
        "core_concept": (
            "PocketFlow contributes the execution-cycle machinery that "
            "supports structured multi-step agent work, iterative "
            "refinement, and controlled completion loops. In IWO3, it is "
            "part of the execution layer rather than the origin of the "
            "orchestration model itself."
        ),
        "timeline": [
            ("Pre-adoption", "orchestration concepts already existed upstream"),
            ("Adoption phase", "PocketFlow selected as the execution substrate"),
            ("Later", "integrated into PDOE/IWO and extended by product-specific governance"),
        ],
        "license_notice": (
            "Open-source license applies according to the PocketFlow "
            "project’s published terms and repository."
        ),
        "attribution_statement": (
            "IWO3 uses PocketFlow as an execution substrate while "
            "acknowledging that its orchestration model predates and "
            "extends beyond PocketFlow alone."
        ),
    },
    {
        "name": "GCC Memory",
        "subtitle": "Persistence and memory-layer influence",
        "badge": ("Open Source", "green"),
        "icon": "◍",
        "author": "GCC Memory contributors",
        "organization": "GCC Memory project",
        "category": "Framework",
        "period": "Adopted downstream in PDOE/IWO",
        "origin": (
            "GCC Memory was adopted as a persistence and memory-layer "
            "component within the broader PDOE/IWO stack after the initial "
            "orchestration model had already been established."
        ),
        "core_concept": (
            "Its contribution is persistent contextual storage, durable "
            "memory handling, and retrieval support for longer-running "
            "agent systems. In IWO3, this supports continuity, "
            "traceability, and structured context retention."
        ),
        "timeline": [
            ("Earlier orchestration phases", "persistence concerns existed conceptually"),
            ("Adoption phase", "GCC Memory chosen as memory/persistence layer"),
            ("Later", "integrated into the broader PDOE runtime pattern"),
        ],
        "license_notice": (
            "Open-source license applies according to the GCC Memory "
            "project’s published terms and repository."
        ),
        "attribution_statement": (
            "IWO3 acknowledges GCC Memory as an important persistence-layer "
            "influence within the broader PDOE stack."
        ),
    },
    {
        "name": "Gamma",
        "subtitle": "Presentation and document rendering adapter",
        "badge": ("Commercial API", "violet"),
        "icon": "▣",
        "author": "Gamma",
        "organization": "Gamma",
        "category": "External Tooling",
        "period": "Active in IWO/IWO3 delivery paths",
        "origin": (
            "Gamma is used by the IWO product line as an external "
            "rendering/delivery system for high-quality presentation and "
            "document outputs, especially for template-governed PPTX/PDF "
            "workflows."
        ),
        "core_concept": (
            "Its role is output finishing rather than orchestration. Gamma "
            "contributes polished rendering and client-facing deliverable "
            "generation where product policy selects Gamma-backed delivery."
        ),
        "timeline": [
            ("IWO2", "Gamma integrated into deliverable flows"),
            ("IWO3", "adapter model preserves Gamma as one output path among several"),
            ("Current", "active hosted/runtime integration"),
        ],
        "license_notice": (
            "Gamma is a third-party commercial service. Usage is governed "
            "by Gamma’s service terms and API/platform policies."
        ),
        "attribution_statement": (
            "IWO3 acknowledges Gamma as an external presentation/document "
            "rendering platform used within its adapter-driven output "
            "architecture."
        ),
    },
    {
        "name": "Stitch MCP",
        "subtitle": "Design-generation and MCP-backed design tooling",
        "badge": ("Commercial API", "violet"),
        "icon": "◈",
        "author": "Google Stitch",
        "organization": "Google",
        "category": "MCP / External Tooling",
        "period": "Active in Loop Eta and hosted parity rollout",
        "origin": (
            "Stitch MCP was integrated into IWO3 as part of the Tool "
            "Locker and design-oriented sub-agent capability surface. It "
            "is used through MCP-backed runtime tooling rather than as a "
            "native orchestration framework."
        ),
        "core_concept": (
            "Its role is design generation, design tooling access, and "
            "structured design-assist workflows, especially for "
            "Hank/Darla-oriented surfaces. It contributes specialized "
            "external capability, not core orchestration logic."
        ),
        "timeline": [
            ("Loop Eta", "Stitch added to runnable Tool Locker scope"),
            ("Post-close", "local env activation completed"),
            ("Hosted parity", "live hosted connection verified"),
        ],
        "license_notice": (
            "Stitch is a third-party service and is governed by its own "
            "service terms, access controls, and API/platform restrictions."
        ),
        "attribution_statement": (
            "IWO3 acknowledges Stitch as an external design-tool "
            "integration used through MCP-backed tooling in the Tool "
            "Locker and related sub-agent workflows."
        ),
    },
    {
        "name": "Brave Search API",
        "subtitle": "Live web search capability for tool-assisted sub-agents",
        "badge": ("Commercial API", "violet"),
        "icon": "⌕",
        "author": "Brave",
        "organization": "Brave Software",
        "category": "External Tooling",
        "period": "Active in post-close Tool Locker runtime",
        "origin": (
            "Brave Search was integrated as a live search tool for IWO3’s "
            "growing Tool Locker/runtime tool surface."
        ),
        "core_concept": (
            "It contributes current web-search capability for agents that "
            "need retrieval beyond local state, especially in research, "
            "design, and content-oriented workflows."
        ),
        "timeline": [
            ("Loop Eta", "search chain ported into IWO3 runtime"),
            ("Post-close", "local live activation completed"),
            ("Hosted parity", "live hosted verification completed"),
        ],
        "license_notice": (
            "Brave Search is a third-party commercial/API service governed "
            "by Brave’s platform and service terms."
        ),
        "attribution_statement": (
            "IWO3 acknowledges Brave Search as an external live-search "
            "provider used for tool-assisted runtime retrieval."
        ),
    },
    {
        "name": "Perplexity API",
        "subtitle": "Live answer-oriented search and synthesis support",
        "badge": ("Commercial API", "violet"),
        "icon": "✦",
        "author": "Perplexity",
        "organization": "Perplexity",
        "category": "External Tooling",
        "period": "Active in post-close Tool Locker runtime",
        "origin": (
            "Perplexity was integrated as an additional external "
            "search/retrieval path within IWO3’s runtime tool layer."
        ),
        "core_concept": (
            "It contributes answer-oriented search and retrieval support "
            "for agents that benefit from external synthesis capabilities "
            "during tool-assisted execution."
        ),
        "timeline": [
            ("Loop Eta", "search tooling ported into IWO3 runtime"),
            ("Post-close", "local live activation completed"),
            ("Hosted parity", "hosted env synced for live use"),
        ],
        "license_notice": (
            "Perplexity is a third-party commercial/API service governed "
            "by its own service terms and API restrictions."
        ),
        "attribution_statement": (
            "IWO3 acknowledges Perplexity as an external retrieval and "
            "synthesis provider used through the Tool Locker/runtime tool "
            "layer."
        ),
    },
]


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
    background: #FEF3C7;
    color: #B45309;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.15rem;
    flex-shrink: 0;
  }
  .iwo3-attr-name {
    font-size: 1.06rem;
    font-weight: 700;
    color: #111827;
    line-height: 1.2;
    margin-bottom: 3px;
  }
  .iwo3-attr-sub {
    font-size: 0.94rem;
    color: #6B7280;
    line-height: 1.4;
  }
  .iwo3-attr-badge {
    display: inline-flex;
    align-items: center;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 0.74rem;
    font-weight: 600;
    white-space: nowrap;
  }
  .iwo3-attr-badge.red { background: #DC2626; color: #FFFFFF; }
  .iwo3-attr-badge.green { background: #D1FAE5; color: #065F46; }
  .iwo3-attr-badge.violet { background: #EDE9FE; color: #6D28D9; }
  .iwo3-attr-badge.gray { background: #F3F4F6; color: #374151; }
  .iwo3-attr-grid {
    display: grid;
    grid-template-columns: 140px 1fr;
    column-gap: 18px;
    row-gap: 10px;
    margin-bottom: 18px;
  }
  .iwo3-attr-grid .k {
    color: #6B7280;
    font-size: 0.92rem;
  }
  .iwo3-attr-grid .v {
    color: #111827;
    font-size: 0.94rem;
  }
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
  .iwo3-attr-timeline {
    display: grid;
    grid-template-columns: 110px 1fr;
    gap: 6px 12px;
    color: #4B5563;
    font-size: 0.94rem;
    line-height: 1.55;
  }
  .iwo3-attr-timeline .t {
    color: #6B7280;
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
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
  .iwo3-attr-panel.warn {
    background: #FFFBEB;
    border: 1px solid #FDE68A;
  }
  .iwo3-attr-panel.note {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
  }
  .iwo3-attr-panel .copy {
    color: #4B5563;
    font-size: 0.93rem;
    line-height: 1.65;
  }
  @media (max-width: 820px) {
    .iwo3-attr-title { font-size: 2.2rem; }
    .iwo3-attr-head { flex-direction: column; }
    .iwo3-attr-grid,
    .iwo3-attr-timeline {
      grid-template-columns: 1fr;
    }
    .iwo3-attr-timeline .t { text-align: left; }
  }
</style>
"""


def _esc(value: Any) -> str:
    return escape(str(value))


def _render_timeline(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f'<div class="t">{_esc(period)}</div><div>{_esc(note)}</div>'
        for period, note in rows
    )
    return f'<div class="iwo3-attr-timeline">{body}</div>'


def _render_entry(entry: dict[str, Any]) -> None:
    badge_label, badge_color = entry["badge"]
    st.markdown(
        f"""
        <div class="iwo3-attr-card">
          <div class="iwo3-attr-head">
            <div class="iwo3-attr-head-main">
              <div class="iwo3-attr-icon">{_esc(entry["icon"])}</div>
              <div>
                <div class="iwo3-attr-name">{_esc(entry["name"])}</div>
                <div class="iwo3-attr-sub">{_esc(entry["subtitle"])}</div>
              </div>
            </div>
            <div class="iwo3-attr-badge {badge_color}">{_esc(badge_label)}</div>
          </div>

          <div class="iwo3-attr-grid">
            <div class="k">Author</div><div class="v">{_esc(entry["author"])}</div>
            <div class="k">Organization</div><div class="v">{_esc(entry["organization"])}</div>
            <div class="k">Category</div><div class="v">{_esc(entry["category"])}</div>
            <div class="k">Period</div><div class="v">{_esc(entry["period"])}</div>
          </div>

          <div class="iwo3-attr-section">
            <h4>Creator &amp; Origin</h4>
            <div class="iwo3-attr-copy">{_esc(entry["origin"])}</div>
          </div>

          <div class="iwo3-attr-section">
            <h4>Core Concept</h4>
            <div class="iwo3-attr-copy">{_esc(entry["core_concept"])}</div>
          </div>

          <div class="iwo3-attr-section">
            <h4>Timeline &amp; Lineage</h4>
            {_render_timeline(entry["timeline"])}
          </div>

          <div class="iwo3-attr-panel warn">
            <h4>License Notice</h4>
            <div class="copy">{_esc(entry["license_notice"])}</div>
          </div>

          <div class="iwo3-attr-panel note">
            <h4>Attribution Statement</h4>
            <div class="copy">{_esc(entry["attribution_statement"])}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    if page_requires_api() is None:
        return

    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="iwo3-attr-wrap">', unsafe_allow_html=True)

    if st.button("← Back", key="attr-back", type="tertiary"):
        st.switch_page("views/tier_overview.py")

    st.markdown(
        """
        <h1 class="iwo3-attr-title">Attribution Register</h1>
        <div class="iwo3-attr-subtitle">
          Foundational lineages, orchestration frameworks, memory layers,
          and major external tooling that materially shaped or power IWO3/PDOE.
        </div>
        <div class="iwo3-attr-collected">Collected 2026-05-02</div>
        """,
        unsafe_allow_html=True,
    )

    for entry in _ENTRIES:
        _render_entry(entry)

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()

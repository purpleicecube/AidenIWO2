"""Tier Overview — the AIDEN tier architecture at a glance."""

from __future__ import annotations

import streamlit as st

from shell import page_requires_api


def _tier_row(icon: str, tier: str, subtitle: str, body: str) -> None:
    st.markdown(
        f"""
        <div class="iwo3-tier-card">
          <div class="t">{icon} {tier}</div>
          <div class="d">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(body)


def main() -> None:
    st.markdown("## 📐 Tier Overview")
    st.caption("AIDEN's tier architecture — what runs at each layer.")

    if page_requires_api() is None:
        return

    _tier_row(
        "🧠",
        "Tier 1 — Aiden",
        "Policy, routing, decisions",
        "Aiden is the top-level agent that interprets intake, routes work to "
        "WOs or WFs, enforces policy (RBAC, candidate-review, approval gates), "
        "and owns the final call on external sends. It does not itself render "
        "content; it decides who should.",
    )
    _tier_row(
        "🧭",
        "Tier 1.5 — PM Coordination",
        "Workflow orchestration, step coordination",
        "PM Coordination runs between Aiden and the sub-agents. It manages "
        "workflow_executions (step sequencing, retry/reopen via execution_cycles), "
        "and is the bridge to the Loop 6 lifecycle state machines.",
    )
    _tier_row(
        "🤖",
        "Tier 2 — Sub-Agents",
        "Aiden-controlled or independent",
        "Sub-agents execute: content briefs, research, PPT/PDF renders, CRM "
        "actions, channel deliveries. Each sub-agent has its own permission "
        "scope + adapter policy. Live adapter dispatch is Loop 10+.",
    )

    st.divider()
    st.markdown("### How it fits together")
    st.markdown(
        "1. **Intake** arrives via DigiFLOW (Loop 3 Phase 3.3 contract) or "
        "a future channel gateway.\n"
        "2. **Aiden (Tier 1)** inspects it, classifies as WO or WF, sets "
        "initial permissions + template choices.\n"
        "3. **PM Coordination (Tier 1.5)** opens a `workflow_execution` "
        "(if WF) or routes directly (if WO), sequences steps, handles "
        "retry/reopen via `execution_cycles`.\n"
        "4. **Sub-agents (Tier 2)** render the output into an "
        "`output_package`, hand off via an adapter with `output_handoffs` "
        "(13-field provenance), record results in `external_execution_results`.\n"
        "5. **Audit** log captures every privileged mutation end-to-end."
    )


main()

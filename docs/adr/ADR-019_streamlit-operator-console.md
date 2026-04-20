# ADR-019 — Streamlit operator console architecture

Date: 2026-04-20
Status: Accepted (Loop 8.3 closeout — IWO2-parity product shell)
Predecessors: ADR-018 (FastAPI runtime), ADR-014/015/016/017.

> **Revision 2026-04-20 (Loop 8.3 corrective):** Loop 8.1/8.2
> delivered the technical console under the original "operator
> console" label. CODEX + Darrel review found the surface lacked
> IWO2 product-shell parity (sidebar grouping, dashboard, Chat with
> Aiden, Submit Order, Design Lab). Loop 8.3 is the corrective
> phase that adds the product shell on top of the technical
> console; ADR-019 now documents both surfaces. The technical
> surface is accepted as the verification lane; the product shell
> is the user-facing MVP.
>
> **Revision 2026-04-20 (Loop 8.3 visual quality correction,
> R-014):** Darrel review of the first 8.3 cut flagged the Streamlit
> surface as "amateur, generic, and materially unlike IWO2" —
> sparse content, loose spacing, random emoji icons, purple-dominant
> palette, plain cards, sidebar weight/density off. The product
> shell was functional but not IWO2-parity. Visual rebuild executed
> using the `ui-designer` skill (at
> `/home/virgina/claude-code-skills/ui-designer/`) and a Design
> Critic Explore subagent that read the IWO2 reference image and
> produced an implementation plan (colors, icon system, CSS density,
> Streamlit limits). Palette shifted to IWO2 blue-neutral-green
> (`#2563EB` / `#1E3A8A` gradient; primary `#1E5F91`; no purple
> dominance). All emoji nav icons replaced with Streamlit
> `:material/*:` monochrome icons. Aggressive CSS rebuild on
> `shell.py` for sidebar nav density + active-state styling,
> `.iwo3-metric` / `.iwo3-panel` / `.iwo3-wo-row` / `.iwo3-tier-card`
> classes for dashboard density. Streamlit-native chrome (`Deploy`,
> toolbar, decoration, header) hidden. Dashboard rewritten with real
> aggregate data via new `GET /work_orders/metrics` route. Visual
> verification via Playwright + headless Chromium. 27/27 tests pass.
> Honest assessment: Streamlit gets us to ~75–80% IWO2 parity; the
> last 20% (exact icon fidelity, dark-mode toggle, pixel typography,
> rich interactions) would require a React rebuild. Acceptable for
> an operator-console MVP; not acceptable for customer-facing
> product UI. Re-evaluate at Loop 10+ if the surface becomes
> prospect-visible.

## Context

Loops 1–7 built schema, runtime logic, contract parity, RBAC/RLS, and
a FastAPI HTTP surface. Loop 8 is the first browser-visible
milestone: a multi-page Streamlit console that operators use to view
and act on WOs, workflows, output packages, handoffs, candidate
review, and audit trails. It is the end of the PRODUCT DIRECTIVE
2026-04-19 through-Loop-8 scope.

## Decision

### Architecture invariants

- **Streamlit never touches the DB.** Every page goes through the
  Loop 7 FastAPI routes via a thin typed HTTP client
  (`apps/console-streamlit/api_client.py`). No `asyncpg` import on
  the Streamlit side. The lint rule `no-direct-db-from-streamlit`
  (Loop 9+ candidate) will make this mechanical.
- **FastAPI is the authoritative RBAC/RLS gate.** Streamlit's role-
  aware UI (disabled buttons, hidden pages) is a UX concession, not
  a security boundary. Even if the UI exposed a disabled transition
  button, clicking it would still hit a `requirePermission`
  server-side and get a 403 (ADR-018).
- **Visual continuity with IWO2.** Theme tokens in
  `.streamlit/config.toml` mirror the IWO2 product shell: IWO2
  primary blue `#1E5F91`, dashboard gradient `#2563EB → #1E3A8A`,
  deep navy text on near-white surface, `:material/*:` monochrome
  icon set, 8 metric cards with tinted accent chips, dense sidebar
  nav with active-state pill. This discipline is enforced by the
  WS024 guidance "IWO3 UI should remain recognizably aligned with
  IWO2"; the Loop 8.3 visual correction (R-014) re-baselined the
  palette away from the earlier purple Klear.ai brand tokens after
  Darrel flagged the surface as amateur. Drift is a blocking PR
  review concern.

### Page layout (Loop 8.3 product-shell parity)

IWO2 reference image (WS024 2026-04-20 screenshot) = visual truth.
Five nav groups mirrored 1:1 via `st.navigation`:

```
apps/console-streamlit/
  Home.py                     entry + st.navigation router
  shell.py                    IWO2-parity sidebar (identity block,
                              dev-auth picker, user badge, version)
  .streamlit/config.toml      IWO2 brand tokens
  views/
    dashboard.py              8 metric cards + Recent WOs + Orchestration
    chat.py                   Chat with Aiden (local dev placeholder)
    work_orders.py            list + detail + transitions
    submit_order.py           create WO form → POST /work_orders
    system_health.py          /healthz + /readyz + /tenants probes
    workspace.py, sandbox.py  placeholders (Loop 9+)
    design_lab.py             Gamma/Stitch/Figma/Claude lanes (Loop 10+)
    tier_overview.py          Tier 1/1.5/2 architecture description
    aiden_settings.py         placeholder (Loop 9+)
    sub_agents.py             placeholder (Loop 9+)
    tools.py, pipelines.py    placeholders (Loop 9+)
    workflows.py              list + admin-gated transitions
    user_management.py        placeholder (Loop 9+)
    output_packages.py        technical console — list + handoff chain
    handoffs.py               technical console — candidate review
    audit_log.py              technical console — audit rows
```

Nav groups (match IWO2 screenshot exactly):
- **Navigation** — Dashboard, Chat with Aiden, Work Orders, Submit Order, System Health
- **Environments** — Workspace, Sandbox, Design Lab
- **Architecture** — Tier Overview
- **Configuration** — Aiden Settings, Sub-Agents, Tools, Pipelines, Workflows, User Management
- **Technical Console** — Output Packages, Handoffs, Audit Log _(Loop 8.1/8.2 surfaces preserved here; not visible to product users in the final shell)_

Sidebar shell components:
- **Identity block** — gradient purple→navy mark + "AIDEN_IWO3 / Orchestration Engine"
- **Dev-auth picker** (collapsed expander) — API base URL, acting user, tenant
- **Grouped nav** via `st.navigation(pages)`
- **User badge** — initials avatar + display label + role chip
- **Version footer** — "AIDEN_IWO3 · Loop 8.3 (dev)"

### Role-aware UI pattern

Every page that exposes a privileged action calls
`/permissions/check?permission=...` at render time. The response
decides whether the button renders enabled, disabled (with tooltip),
or is hidden entirely. The server still enforces; the preflight is
UX polish.

Example from the WO page:

```python
decision = api.check_permission("work_order:submit")
if decision.allowed:
    if st.button("→ processing"):
        api.transition_work_order(...)
else:
    st.button("→ processing", disabled=True,
              help=f"Denied — requires work_order:submit "
                   f"(your role: {decision.role})")
```

### Error rendering

FastAPI returns uniform `{error, ...}` shapes for 403/404/409. The
Streamlit client's `APIError` surfaces these as `st.error(...)`
banners with the server's own message. No handler in Streamlit
interprets the error body beyond displaying it — the shape is
fixed in the ADR-018 error mapping table.

## Consequences

**Positive**

- Loop 8 ships the first browser-visible IWO3 MVP on schedule. The
  full vertical slice the directive named (tenant pick → WO → output
  → handoff → audit) renders in Streamlit against live Loop 7 API.
- Thin client + dedicated page modules make adding new pages
  mechanical. Loop 9+ (Telegram, Slack, live adapters) can follow
  the same pattern.
- Role-aware UI feels correct for operators: they never see actions
  they can't take, but the security boundary stays server-side.

**Negative**

- Dev auth via seeded-user picker is obviously not production. Loop
  9+ replaces the sidebar with an OAuth/SSO flow; the API client
  signature stays stable.
- Streamlit's multi-page convention is directory-driven — ordering
  and page names are fragile. Renaming a page breaks the URL. For
  Loop 8 this is acceptable; Loop 9+ may migrate to explicit
  `st.Page` objects if the page count grows.
- No live-updating UI — every click triggers a full rerender. For
  Loop 8's operator flow this is fine; real-time updates are Loop
  9+ WebSocket work.

## Alternatives considered

- **Server-rendered HTML (FastAPI + Jinja2)** — rejected: Streamlit
  gives us operator interactivity + charts for free; hand-rolling
  HTML would slow Loop 8 significantly without benefit.
- **React SPA** — rejected for Loop 8 scope: a full SPA build
  pipeline is out of proportion with the MVP target; a future loop
  may revisit when the UI team is dedicated.
- **Let Streamlit read the DB directly via SQLAlchemy** — rejected:
  bypasses the RBAC + RLS + audit gate. Violates ADR-014 + ADR-015
  + ADR-018.

## References

- `IWO3_LOOP_8_SCOPE_PROPOSAL_v0.1.0.md`
- `IWO3_LOOP_8_3_SCOPE` (LOOP_8_3_RECORD.md)
- Loop 8 Phase 8.1 commit `6bfcbf3` / CI run `24660636148` (technical console)
- Loop 8 Phase 8.2 commit `65b7403` / CI run `24660791813` (technical console)
- Loop 8 Phase 8.3 commit `740b470` / CI run `24666245407` (IWO2 product-shell parity)
- Loop 8 Phase 8.3 hotfix commits `793ee09` + `32575c3` (widget-key collision + CI skip)
- Loop 8 Phase 8.3 visual correction commit (R-014, IWO2 visual-density rebuild; ui-designer skill + Design Critic subagent)
- `LOOP_8_3_RECORD.md` — per-phase record of corrective + hotfix + visual-correction passes
- `apps/console-streamlit/Home.py` + `pages/`
- ADR-018 (FastAPI runtime) — Streamlit's server-side contract
- `docs/runbooks/contracts.md` — TS/Python shape parity rules

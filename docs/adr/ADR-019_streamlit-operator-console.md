# ADR-019 — Streamlit operator console architecture

Date: 2026-04-20
Status: Accepted (Loop 8 Phase 8.2 closeout)
Predecessors: ADR-018 (FastAPI runtime), ADR-014/015/016/017.

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
  `.streamlit/config.toml` mirror the Klear.ai brand: deep navy on
  light lavender, primary purple `#8B49E2`. This discipline is
  enforced by the WS024 guidance "IWO3 UI should remain
  recognizably aligned with IWO2"; drift is a blocking PR review
  concern.

### Page layout

Multi-page app via Streamlit's `pages/` convention:

```
apps/console-streamlit/
  Home.py                       entry + sidebar dev-auth picker
  pages/
    1_Work_Orders.py            list + detail + transitions
    2_Output_Packages.py        list + detail + linked handoffs
    3_Handoffs.py               candidate-review + non-candidate list
    4_Audit_Log.py              tenant-scoped audit rows (owner-gated)
```

Sidebar (shared by every page via `st.session_state["iwo3_api"]`):
- API base URL (env-driven; `IWO3_API_BASE_URL`)
- Acting user picker (seeded fixture users — production is Loop 9+)
- Tenant picker (only 2 tenants in seed — multi-tenant prod is Loop 9+)

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
- Loop 8 Phase 8.1 commit `6bfcbf3` / CI run `24660636148`
- Loop 8 Phase 8.2 commit (this closeout)
- `apps/console-streamlit/Home.py` + `pages/`
- ADR-018 (FastAPI runtime) — Streamlit's server-side contract
- `docs/runbooks/contracts.md` — TS/Python shape parity rules

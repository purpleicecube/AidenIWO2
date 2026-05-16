"""System Health — IWO2-parity surface over the IWO3 FastAPI runtime.

Sections (top to bottom):
  1. Page header with Refresh control
  2. KPI strip: Overall Status / Uptime / Version
  3. Services grid: Database / Tier 1 / Tier 1.5 / Tier 2 / Memory
  4. System Checks list: API / Database / LLM / Gamma / Session-Auth
  5. Tenant memberships (IWO3-only, kept from prior page)
  6. Sub-Agent Runtime Status matrix (CAP-G addition, kept as-is)
  7. Footer caption with last-checked timestamp + auto-refresh hint

Auto-refresh is driven by `st.fragment(run_every="30s")` — the live
data block re-runs every 30 seconds without reloading the whole page.
The manual Refresh button triggers an immediate rerun.

All visual chrome is rendered via `st.html` against the scoped CSS
block below so the page can mirror the IWO2 shadcn-style cards,
icon tiles, and Pass/Fail badges that operators already know.
"""

from __future__ import annotations

import html as _html
from datetime import datetime

import streamlit as st

from api_client import APIError
from shell import page_requires_api


# ── CSS ─────────────────────────────────────────────────────────────


_CSS = """
<style>
  .iwo3-sh-wrap {
    max-width: 1100px;
    margin: 0 auto;
    padding-bottom: 36px;
  }
  .iwo3-sh-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 24px;
    margin-bottom: 22px;
    flex-wrap: wrap;
  }
  .iwo3-sh-title {
    font-size: 1.65rem;
    font-weight: 700;
    color: #111827;
    margin: 0 0 4px 0;
    letter-spacing: -0.01em;
  }
  .iwo3-sh-subtitle {
    color: #6B7280;
    font-size: 0.88rem;
    margin: 0;
  }
  .iwo3-sh-refresh-meta {
    color: #059669;
    font-size: 0.78rem;
    display: inline-flex;
    align-items: center;
    gap: 5px;
    margin-right: 10px;
  }

  /* Section labels */
  .iwo3-sh-section-h {
    font-size: 1.02rem;
    font-weight: 600;
    color: #111827;
    margin: 26px 0 12px 0;
  }

  /* KPI strip */
  .iwo3-sh-kpi-row {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    margin-bottom: 6px;
  }
  .iwo3-sh-kpi-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 16px 18px;
  }
  .iwo3-sh-kpi-label {
    color: #6B7280;
    font-size: 0.74rem;
    text-transform: none;
    margin-bottom: 6px;
  }
  .iwo3-sh-kpi-value {
    font-size: 1.18rem;
    font-weight: 600;
    color: #111827;
    display: inline-flex;
    align-items: center;
    gap: 9px;
  }
  .iwo3-sh-kpi-value .icon { font-size: 1.05rem; line-height: 1; }
  .iwo3-sh-kpi-value .mono {
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
  }
  .iwo3-sh-kpi-value.ok  { color: #047857; }
  .iwo3-sh-kpi-value.bad { color: #B91C1C; }

  /* Services grid */
  .iwo3-sh-services-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 14px;
  }
  .iwo3-sh-svc-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 16px 18px;
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .iwo3-sh-svc-icon {
    width: 38px;
    height: 38px;
    border-radius: 8px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: 1.05rem;
    line-height: 1;
    flex-shrink: 0;
  }
  .iwo3-sh-svc-icon.blue   { background: #DBEAFE; color: #1D4ED8; }
  .iwo3-sh-svc-icon.indigo { background: #E0E7FF; color: #4338CA; }
  .iwo3-sh-svc-icon.amber  { background: #FEF3C7; color: #B45309; }
  .iwo3-sh-svc-icon.emerald{ background: #D1FAE5; color: #047857; }
  .iwo3-sh-svc-icon.purple { background: #EDE9FE; color: #6D28D9; }
  .iwo3-sh-svc-body {
    flex: 1;
    min-width: 0;
  }
  .iwo3-sh-svc-title {
    font-size: 0.92rem;
    font-weight: 600;
    color: #111827;
    margin: 0 0 2px 0;
  }
  .iwo3-sh-svc-desc {
    font-size: 0.78rem;
    color: #6B7280;
    margin: 0;
  }
  .iwo3-sh-badge {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 4px 9px;
    border-radius: 999px;
    white-space: nowrap;
  }
  .iwo3-sh-badge.ok  { background: #D1FAE5; color: #047857; }
  .iwo3-sh-badge.bad { background: #FEE2E2; color: #B91C1C; }

  /* Checks list */
  .iwo3-sh-checks-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 6px 18px;
  }
  .iwo3-sh-check-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 0;
    border-bottom: 1px solid #F3F4F6;
  }
  .iwo3-sh-check-row:last-child { border-bottom: none; }
  .iwo3-sh-check-label {
    font-size: 0.88rem;
    color: #111827;
  }
  .iwo3-sh-check-detail {
    font-size: 0.74rem;
    color: #9CA3AF;
    margin-left: 8px;
  }
  .iwo3-sh-check-status {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.78rem;
    font-weight: 600;
  }
  .iwo3-sh-check-status.ok  { color: #047857; }
  .iwo3-sh-check-status.bad { color: #B91C1C; }

  /* Tenant rows */
  .iwo3-sh-tenant-row {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 10px 14px;
    margin-bottom: 6px;
    font-size: 0.86rem;
    color: #374151;
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }
  .iwo3-sh-tenant-row .des {
    font-weight: 600;
    color: #111827;
  }
  .iwo3-sh-tenant-row .meta { color: #6B7280; font-size: 0.78rem; }
  .iwo3-sh-tenant-row .pill {
    background: #F3F4F6;
    color: #374151;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 500;
  }

  /* Skeleton shimmer */
  .iwo3-sh-skel {
    background: linear-gradient(90deg, #F3F4F6 0%, #E5E7EB 50%, #F3F4F6 100%);
    background-size: 200% 100%;
    animation: iwo3-sh-shimmer 1.4s ease-in-out infinite;
    border-radius: 6px;
  }
  @keyframes iwo3-sh-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }
  .iwo3-sh-skel-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 10px;
    padding: 16px 18px;
    display: flex;
    align-items: center;
    gap: 14px;
  }
  .iwo3-sh-skel-icon { width: 38px; height: 38px; }
  .iwo3-sh-skel-line { height: 11px; margin-bottom: 6px; }

  /* Friendly error */
  .iwo3-sh-error-card {
    background: #FFFFFF;
    border: 1px solid #FECACA;
    border-radius: 10px;
    padding: 28px;
    text-align: center;
  }
  .iwo3-sh-error-icon {
    color: #B91C1C;
    font-size: 1.6rem;
    margin-bottom: 8px;
  }
  .iwo3-sh-error-title {
    font-size: 1.05rem;
    font-weight: 600;
    color: #111827;
    margin: 4px 0 6px 0;
  }
  .iwo3-sh-error-body {
    color: #6B7280;
    font-size: 0.84rem;
    max-width: 460px;
    margin: 0 auto;
  }

  /* Footer */
  .iwo3-sh-footer {
    color: #9CA3AF;
    font-size: 0.74rem;
    margin-top: 22px;
    text-align: left;
  }

  @media (max-width: 880px) {
    .iwo3-sh-kpi-row,
    .iwo3-sh-services-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
"""


# ── Helpers ─────────────────────────────────────────────────────────


def _esc(s: object) -> str:
    return _html.escape(str(s), quote=True)


def _format_uptime(seconds: int) -> str:
    if seconds < 0:
        seconds = 0
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days > 0:
        return f"{days}d {hours}h {mins}m"
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


# Lucide icon library — same SVG paths IWO2 uses via `lucide-react`.
# Kept as inner-content strings; `_icon()` wraps them in a sized <svg>.
# Lucide is MIT-licensed; paths copied verbatim from lucide.dev.
_LUCIDE: dict[str, str] = {
    "database": (
        '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
        '<path d="M3 5V19A9 3 0 0 0 21 19V5"/>'
        '<path d="M3 12A9 3 0 0 0 21 12"/>'
    ),
    "layers": (
        '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83'
        'l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/>'
        '<path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/>'
        '<path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>'
    ),
    "git-branch": (
        '<line x1="6" x2="6" y1="3" y2="15"/>'
        '<circle cx="18" cy="6" r="3"/>'
        '<circle cx="6" cy="18" r="3"/>'
        '<path d="M18 9a9 9 0 0 1-9 9"/>'
    ),
    "activity": (
        '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.5.5 0 0 1-.96 0'
        'L9.68 3.18a.5.5 0 0 0-.96 0l-2.35 8.36A2 2 0 0 1 4.45 13H2"/>'
    ),
    "shield": (
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01'
        'C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72'
        'a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>'
    ),
    "check-circle": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="m9 12 2 2 4-4"/>'
    ),
    "x-circle": (
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="m15 9-6 6"/>'
        '<path d="m9 9 6 6"/>'
    ),
    "clock": (
        '<circle cx="12" cy="12" r="10"/>'
        '<polyline points="12 6 12 12 16 14"/>'
    ),
    "server": (
        '<rect width="20" height="8" x="2" y="2" rx="2" ry="2"/>'
        '<rect width="20" height="8" x="2" y="14" rx="2" ry="2"/>'
        '<line x1="6" x2="6.01" y1="6" y2="6"/>'
        '<line x1="6" x2="6.01" y1="18" y2="18"/>'
    ),
    "refresh-cw": (
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/>'
        '<path d="M21 3v5h-5"/>'
        '<path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/>'
        '<path d="M8 16H3v5"/>'
    ),
}


def _icon(name: str, *, size: int = 18, css_class: str = "") -> str:
    """Render a Lucide SVG icon at the given size. Stroke inherits
    color from the surrounding element so the existing pastel-tile
    color rules and badge color rules continue to drive tone."""
    inner = _LUCIDE.get(name, "")
    cls = f' class="{_esc(css_class)}"' if css_class else ""
    return (
        f'<svg{cls} xmlns="http://www.w3.org/2000/svg" '
        f'width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="currentColor" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'{inner}'
        f'</svg>'
    )


def _badge_html(passed: bool, label_ok: str = "healthy", label_bad: str = "down") -> str:
    cls = "ok" if passed else "bad"
    glyph = _icon("check-circle", size=12) if passed else _icon("x-circle", size=12)
    text = label_ok if passed else label_bad
    return f'<span class="iwo3-sh-badge {cls}">{glyph} {_esc(text)}</span>'


def _kpi_card(label: str, value_html: str, *, ok: bool | None = None) -> str:
    tone = ""
    if ok is True:
        tone = "ok"
    elif ok is False:
        tone = "bad"
    return (
        f'<div class="iwo3-sh-kpi-card">'
        f'<div class="iwo3-sh-kpi-label">{_esc(label)}</div>'
        f'<div class="iwo3-sh-kpi-value {tone}">{value_html}</div>'
        f'</div>'
    )


def _service_card(
    *, icon_tone: str, icon_name: str, title: str, desc: str,
    status_passed: bool, status_label_ok: str, status_label_bad: str,
) -> str:
    return (
        f'<div class="iwo3-sh-svc-card">'
        f'<div class="iwo3-sh-svc-icon {icon_tone}">{_icon(icon_name, size=20)}</div>'
        f'<div class="iwo3-sh-svc-body">'
        f'<div class="iwo3-sh-svc-title">{_esc(title)}</div>'
        f'<div class="iwo3-sh-svc-desc">{_esc(desc)}</div>'
        f'</div>'
        f'{_badge_html(status_passed, status_label_ok, status_label_bad)}'
        f'</div>'
    )


def _render_skeleton() -> None:
    """3-card KPI + 5-card services + checks skeleton, IWO2-style."""
    kpi = "".join(
        '<div class="iwo3-sh-skel-card">'
        '<div style="flex:1">'
        '<div class="iwo3-sh-skel iwo3-sh-skel-line" style="width:30%"></div>'
        '<div class="iwo3-sh-skel iwo3-sh-skel-line" style="width:55%;height:18px"></div>'
        '</div></div>'
        for _ in range(3)
    )
    svc = "".join(
        '<div class="iwo3-sh-skel-card">'
        '<div class="iwo3-sh-skel iwo3-sh-skel-icon"></div>'
        '<div style="flex:1">'
        '<div class="iwo3-sh-skel iwo3-sh-skel-line" style="width:45%"></div>'
        '<div class="iwo3-sh-skel iwo3-sh-skel-line" style="width:70%"></div>'
        '</div>'
        '<div class="iwo3-sh-skel" style="width:68px;height:22px"></div>'
        '</div>'
        for _ in range(5)
    )
    st.markdown(
        f'<div class="iwo3-sh-kpi-row">{kpi}</div>'
        f'<div class="iwo3-sh-section-h">Services</div>'
        f'<div class="iwo3-sh-services-grid">{svc}</div>'
    , unsafe_allow_html=True)


def _render_unreachable(detail: str) -> None:
    st.markdown(
        '<div class="iwo3-sh-error-card">'
        '<div class="iwo3-sh-error-icon">⚠</div>'
        '<div class="iwo3-sh-error-title">System Unreachable</div>'
        '<div class="iwo3-sh-error-body">'
        'Unable to reach the IWO3 FastAPI runtime. The service may be '
        'down or restarting. '
        f'<br><span style="color:#9CA3AF;font-size:0.78rem">{_esc(detail)}</span>'
        '</div></div>'
    , unsafe_allow_html=True)


# ── Live data block (auto-refreshing fragment) ─────────────────────


@st.fragment(run_every="30s")
def _render_live_block(api) -> None:
    # 1. Pull /healthz + /readyz first so an unreachable API short-circuits
    # the entire live block with a friendly error card.
    try:
        health = api._request("GET", "/healthz")
    except APIError as err:
        _render_unreachable(f"{err.status_code} — {err.detail}")
        return

    try:
        ready = api._request("GET", "/readyz")
        db_state = ready.get("database", "unknown")
    except APIError as err:
        ready = {"status": "error", "database": "unreachable"}
        db_state = f"unreachable ({err.status_code})"

    db_ok = db_state == "connected"

    # 2. Pull /system/checks + /system/sub-agent-wiring-status. The wiring
    # status drives the Tier 1 / 1.5 / 2 service cards' "active" chips so
    # we have a single source of truth for sub-agent liveness.
    try:
        checks_resp = api._request("GET", "/system/checks")
    except APIError as err:
        checks_resp = {
            "checks": [
                {"name": "api", "label": "API Endpoint", "passed": True, "detail": "request reached console"},
                {"name": "system_checks", "label": "/system/checks endpoint", "passed": False,
                 "detail": f"{err.status_code} — {err.detail}"},
            ],
            "all_passed": False,
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

    try:
        wiring = api._request("GET", "/system/sub-agent-wiring-status")
        summary = wiring.get("summary", {}) or {}
    except APIError:
        wiring = {"roles": [], "summary": {}}
        summary = {}

    tier_1_live = bool(summary.get("tier_1_live"))
    pm_live = bool(summary.get("pm_live"))
    tier_2_chain_roles = int(summary.get("tier_2_branded_chain_roles", 0))
    degraded_roles = int(summary.get("degraded_roles", 0))

    # 3. KPI strip — Overall / Uptime / Version
    overall_ok = db_ok and bool(checks_resp.get("all_passed"))
    overall_icon = _icon("check-circle" if overall_ok else "x-circle", size=20)
    overall_html = (
        f'<span class="icon">{overall_icon}</span> '
        f'{"Operational" if overall_ok else "Degraded"}'
    )
    uptime_seconds = int(health.get("uptime_seconds", 0) or 0)
    uptime_html = (
        f'<span class="icon">{_icon("clock", size=20)}</span> '
        f'<span class="mono">{_esc(_format_uptime(uptime_seconds))}</span>'
    )
    version_html = (
        f'<span class="icon">{_icon("server", size=20)}</span> '
        f'<span class="mono">{_esc(health.get("version", "?"))}</span>'
    )

    st.markdown(
        f'<div class="iwo3-sh-kpi-row">'
        f'{_kpi_card("Overall Status", overall_html, ok=overall_ok)}'
        f'{_kpi_card("Uptime", uptime_html)}'
        f'{_kpi_card("Version", version_html)}'
        f'</div>'
    , unsafe_allow_html=True)

    # 4. Services grid — Database / Tier 1 / Tier 1.5 / Tier 2 / Memory
    # Icon vocabulary mirrors IWO2 system-health.tsx: Database, Layers,
    # GitBranch, Activity, Shield — same Lucide library.
    services = [
        _service_card(
            icon_tone="blue", icon_name="database", title="Database",
            desc="PostgreSQL persistence layer",
            status_passed=db_ok,
            status_label_ok="healthy", status_label_bad=db_state or "down",
        ),
        _service_card(
            icon_tone="indigo", icon_name="layers", title="Tier 1 — Policy",
            desc="Aiden policy gate and routing engine",
            status_passed=tier_1_live,
            status_label_ok="active", status_label_bad="off",
        ),
        _service_card(
            icon_tone="amber", icon_name="git-branch",
            title="Tier 1.5 — PM Coordination",
            desc="Workflow + PM sub-agent orchestration",
            status_passed=pm_live,
            status_label_ok="active", status_label_bad="off",
        ),
        _service_card(
            icon_tone="emerald", icon_name="activity",
            title="Tier 2 — Execution",
            desc=f"Sub-agent execution · {tier_2_chain_roles} chain role(s)",
            status_passed=tier_2_chain_roles > 0,
            status_label_ok="active", status_label_bad="no chains",
        ),
        _service_card(
            icon_tone="purple", icon_name="shield", title="Memory (V3)",
            desc="Tenant-scoped grounding + canonical facts",
            # Memory is "active" when the wiring matrix returned any roles
            # for this tenant — same liveness proxy as the rest of the
            # tenant runtime. Honest degraded surfaces are flagged below.
            status_passed=len(wiring.get("roles", [])) > 0,
            status_label_ok="active",
            status_label_bad="no roles",
        ),
    ]
    st.markdown(
        '<div class="iwo3-sh-section-h">Services</div>'
        f'<div class="iwo3-sh-services-grid">{"".join(services)}</div>'
    , unsafe_allow_html=True)

    # 5. System Checks list
    check_rows: list[str] = []
    for c in checks_resp.get("checks", []):
        passed = bool(c.get("passed"))
        detail = c.get("detail") or ""
        detail_html = (
            f'<span class="iwo3-sh-check-detail">— {_esc(detail)}</span>'
            if detail else ""
        )
        status_html = (
            f'<span class="iwo3-sh-check-status ok">{_icon("check-circle", size=14)} Pass</span>'
            if passed
            else f'<span class="iwo3-sh-check-status bad">{_icon("x-circle", size=14)} Fail</span>'
        )
        check_rows.append(
            '<div class="iwo3-sh-check-row">'
            f'<div><span class="iwo3-sh-check-label">{_esc(c.get("label", c.get("name", "")))}</span>{detail_html}</div>'
            f'{status_html}'
            '</div>'
        )
    st.markdown(
        '<div class="iwo3-sh-section-h">System Checks</div>'
        f'<div class="iwo3-sh-checks-card">{"".join(check_rows)}</div>'
    , unsafe_allow_html=True)

    # 6. Tenant memberships (IWO3-only, preserved)
    try:
        tenants = api.list_tenants()
    except APIError as err:
        tenants = []
        st.markdown(
            '<div class="iwo3-sh-section-h">Tenant Surfaces</div>'
            f'<div class="iwo3-sh-error-card" style="padding:14px">'
            f'<div style="color:#B91C1C;font-size:0.84rem">❌ /tenants — {_esc(err.detail)}</div>'
            '</div>'
        , unsafe_allow_html=True)

    if tenants:
        rows_html = "".join(
            '<div class="iwo3-sh-tenant-row">'
            f'<span class="des">{_esc(t.designation)}</span>'
            f'<span class="pill">role · {_esc(t.role)}</span>'
            f'<span class="pill">membership · {_esc(t.membership_status)}</span>'
            '</div>'
            for t in tenants
        )
        st.markdown(
            '<div class="iwo3-sh-section-h">Tenant Surfaces</div>'
            f'{rows_html}'
        , unsafe_allow_html=True)

    # 7. Sub-Agent Runtime Status (CAP-G surface, preserved + restyled)
    st.markdown('<div class="iwo3-sh-section-h">Sub-Agent Runtime Status</div>', unsafe_allow_html=True)
    st.caption(
        "Live wiring + degraded-surface matrix per "
        "IWO3_SUBAGENT_WIRING_MATRIX_AND_STATUS_SURFACE_v0.1.0. "
        "Computed from runtime truth — not hand-maintained."
    )

    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.metric("Tier-1 (Aiden)", "live" if tier_1_live else "off")
    with s2:
        st.metric("Tier-1.5 (PM)", "live" if pm_live else "off")
    with s3:
        st.metric("Tier-2 in branded chains", tier_2_chain_roles)
    with s4:
        st.metric(
            "Degraded roles",
            degraded_roles,
            delta=("attention" if degraded_roles > 0 else None),
            delta_color="inverse" if degraded_roles > 0 else "normal",
        )

    roles = wiring.get("roles", [])
    if not roles:
        st.info("No role rows returned for this tenant.")
    else:
        rows = []
        for r in roles:
            rows.append(
                {
                    "Role": r.get("display_name") or r.get("role_key"),
                    "Layer": r.get("layer"),
                    "LLM enabled": "✓" if r.get("llm_enabled") else "—",
                    "Direct path": "✓" if r.get("direct_work_order_path") else "—",
                    "Workflow path": "✓" if r.get("workflow_path") else "—",
                    "Branded chain": "✓" if r.get("branded_chain_path") else "—",
                    "Surfaces": ", ".join(r.get("surfaces") or []) or "—",
                    "Degraded": "⚠️" if r.get("degraded") else "—",
                    "Last invoked": r.get("last_invoked_at") or "—",
                    "Last success": r.get("last_success_at") or "—",
                    "Last failure": r.get("last_failure_at") or "—",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        degraded_rows = [r for r in roles if r.get("degraded")]
        if degraded_rows:
            with st.expander(f"Degraded reasons ({len(degraded_rows)})"):
                for r in degraded_rows:
                    st.markdown(
                        f"**{r.get('display_name') or r.get('role_key')}** — "
                        f"{r.get('degraded_reason') or 'no reason recorded'}"
                    )

    # 8. Footer caption
    last_checked = (
        checks_resp.get("generated_at")
        or wiring.get("generated_at")
        or datetime.utcnow().isoformat() + "Z"
    )
    st.markdown(
        '<div class="iwo3-sh-footer">'
        f'Last checked: {_esc(last_checked)} · Auto-refreshes every 30s · '
        f'baseline {_esc(wiring.get("baseline_commit", "?"))}'
        '</div>'
    , unsafe_allow_html=True)


# ── Page entry point ────────────────────────────────────────────────


def main() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    st.markdown('<div class="iwo3-sh-wrap">', unsafe_allow_html=True)

    # Page header with Refresh control. The Refresh button forces an
    # immediate rerun; the fragment below also auto-refreshes every 30s.
    header_left, header_right = st.columns([4, 1])
    with header_left:
        st.markdown(
            '<div class="iwo3-sh-header" style="margin-bottom:0">'
            '<div>'
            '<h1 class="iwo3-sh-title">System Health</h1>'
            '<p class="iwo3-sh-subtitle">'
            'Live checks against the IWO3 FastAPI runtime, Postgres backing '
            'store, and sub-agent wiring.'
            '</p>'
            '</div>'
            '</div>'
        , unsafe_allow_html=True)
    with header_right:
        refreshed = st.session_state.pop("iwo3_sh_refreshed", False)
        if refreshed:
            st.markdown(
                '<div class="iwo3-sh-refresh-meta">'
                f'{_icon("check-circle", size=14)} Refreshed'
                '</div>'
            , unsafe_allow_html=True)
        # Streamlit's button label supports the ":material/<name>:"
        # token; refresh maps to Material's circular-arrow which is
        # the closest match to Lucide's RefreshCw used in IWO2.
        if st.button(
            ":material/refresh: Refresh",
            key="iwo3_sh_refresh", type="secondary",
            use_container_width=True,
        ):
            st.session_state["iwo3_sh_refreshed"] = True
            st.rerun()

    api = page_requires_api()
    if api is None:
        st.markdown('</div>', unsafe_allow_html=True)
        return

    _render_live_block(api)

    st.markdown('</div>', unsafe_allow_html=True)


main()

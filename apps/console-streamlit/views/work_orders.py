"""Work Orders — IWO3 Console.

List + detail + transitions. Each transition button preflights the
required permission via /permissions/check so role-denied actions
render disabled with a "requires X" tooltip; the server-side
requirePermission is still the authoritative gate.

2026-05-17 (Sandbox Loop α Darkmode — parity uplift) — the expanded
content per WO mirrors the IWO2 detail-page idiom: status badge,
two-column body, Properties / Deliverables / Aiden Result cards,
Quality Review banner. Reusable `iwo3-banner-*` + `iwo3-badge-*` +
`iwo3-card-*` CSS classes establish the semantic status/banner
pattern for use across other IWO3 surfaces.

2026-05-17 (Sandbox Loop α Darkmode — composition polish) — the
parity surface is consolidated into one anchored summary band
(title + badge + priority + ID + type + relative timeline), the
top toolbar is compressed (tertiary visual weight, no group label),
the transitions strip is collapsed into a single `Status ▾` popover
with short labels (fixes `awaiting_operator` wrap), Properties is
trimmed to only the rows NOT already in the summary band, the
description loses its card chrome (just typography), and the
recovery row sheds its group label. Same accepted semantic
language; better composition.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import streamlit as st

from api_client import APIError
from shell import page_requires_api


SAFE_TRANSITIONS: dict[str, list[str]] = {
    "pending": ["processing", "cancelled", "deferred"],
    "processing": ["completed", "blocked", "awaiting_operator", "failed", "cancelled"],
    "blocked": ["processing", "cancelled", "failed"],
    "awaiting_operator": ["processing", "cancelled", "failed"],
    "deferred": ["processing", "cancelled"],
    "completed": ["processing"],
    "done": ["processing"],
    "failed": ["processing"],
    "cancelled": [],
}


PERM_FOR_TRANSITION: dict[str, str] = {
    "processing": "work_order:submit",
    "completed": "work_order:update",
    "done": "work_order:update",
    "blocked": "work_order:update",
    "awaiting_operator": "work_order:update",
    "failed": "work_order:update",
    "cancelled": "work_order:cancel",
    "deferred": "work_order:update",
}


# Short labels for transition controls — fixes the awkward
# `awaiting_operator` wrap inside the transitions popover.
_TRANSITION_LABEL: dict[str, str] = {
    "pending": "Pending",
    "processing": "Processing",
    "blocked": "Blocked",
    "awaiting_operator": "Await operator",
    "deferred": "Deferred",
    "completed": "Completed",
    "done": "Done",
    "failed": "Failed",
    "cancelled": "Cancelled",
}


# ─── Detail-page polish CSS (Sandbox Loop α — polish pass 2026-05-17).
# Refinement of the prior parity CSS: lighter chrome, tighter padding,
# subtle dividers replacing some card outlines so the surface reads as
# one panel instead of stacked boxes. Same accepted color/icon
# language. Scoped names preserved so other IWO3 pages can pick up the
# pattern unchanged. ─────────────────────────────────────────────────
_DETAIL_CSS = """
<style>
  /* ── Anchored summary band (replaces floating badge header) ──────
     Title + badge + priority feel like one strong identity instead of
     three separate floating chips. Subtle bottom border instead of a
     card outline keeps the surface coherent. */
  .iwo3-summary-band {
    padding: 4px 0 10px 0;
    margin-bottom: 10px;
    border-bottom: 1px solid #E5E7EB;
  }
  .iwo3-summary-band .iwo3-sb-row {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  }
  .iwo3-summary-band .iwo3-sb-title {
    font-size: 1.08rem; font-weight: 700; color: #111827;
    margin: 0; line-height: 1.3; flex: 1 1 auto; min-width: 0;
    word-break: break-word;
  }
  .iwo3-summary-band .iwo3-sb-meta {
    margin-top: 6px;
    color: #6B7280; font-size: 0.76rem;
    display: flex; gap: 10px; flex-wrap: wrap; align-items: center;
  }
  .iwo3-summary-band .iwo3-sb-meta code {
    background: #F3F4F6; color: #374151;
    padding: 1px 6px; border-radius: 4px; font-size: 0.72rem;
  }
  .iwo3-summary-band .iwo3-sb-meta .sep { color: #D1D5DB; }

  /* ── IWO2-style status badge family ─────────────────────────────
     Soft tinted fill, darker same-family text, thin border, Lucide
     icon. Preserved from the parity pass. */
  .iwo3-badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 9px; border-radius: 5px;
    border: 1px solid transparent;
    font-size: 0.76rem; font-weight: 600; line-height: 1.1;
    white-space: nowrap;
  }
  .iwo3-badge svg { width: 13px; height: 13px; }
  .iwo3-badge.completed  { background:#ECFDF5; color:#047857; border-color:#A7F3D0; }
  .iwo3-badge.processing { background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE; }
  .iwo3-badge.pending    { background:#F9FAFB; color:#374151; border-color:#E5E7EB; }
  .iwo3-badge.blocked    { background:#FEF2F2; color:#B91C1C; border-color:#FECACA; }
  .iwo3-badge.awaiting   { background:#FFFBEB; color:#B45309; border-color:#FDE68A; }
  .iwo3-badge.deferred   { background:#F0F9FF; color:#0369A1; border-color:#BAE6FD; }
  .iwo3-badge.failed     { background:#FEF2F2; color:#B91C1C; border-color:#FECACA; }
  .iwo3-badge.cancelled  { background:#F3F4F6; color:#4B5563; border-color:#D1D5DB; }
  .iwo3-badge.reopened   { background:#F5F3FF; color:#6D28D9; border-color:#DDD6FE; }

  /* Priority chip. */
  .iwo3-prio {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 7px; border-radius: 4px;
    font-size: 0.70rem; font-weight: 600; line-height: 1.1;
    border: 1px solid transparent;
  }
  .iwo3-prio.critical { background:#FEF2F2; color:#B91C1C; border-color:#FECACA; }
  .iwo3-prio.high     { background:#FFF7ED; color:#C2410C; border-color:#FED7AA; }
  .iwo3-prio.medium   { background:#EFF6FF; color:#1D4ED8; border-color:#BFDBFE; }
  .iwo3-prio.low      { background:#F9FAFB; color:#4B5563; border-color:#E5E7EB; }

  /* ── Banner family — high-attention status callouts only ────────
     Quality Review + terminal-state banners. Tightened margins so
     they sit closer to the summary band; same color language. */
  .iwo3-banner {
    border-radius: 6px;
    border: 1px solid transparent;
    border-left-width: 3px;
    padding: 10px 12px;
    margin: 4px 0 10px 0;
    font-size: 0.84rem;
    line-height: 1.45;
  }
  .iwo3-banner .iwo3-banner-hdr {
    display: inline-flex; align-items: center; gap: 6px;
    font-weight: 700; font-size: 0.88rem; margin-bottom: 4px;
  }
  .iwo3-banner .iwo3-banner-hdr svg { width: 15px; height: 15px; }
  .iwo3-banner ul { margin: 4px 0 0 18px; padding: 0; }
  .iwo3-banner li { margin: 2px 0; }
  .iwo3-banner.amber  { background:#FFFBEB; border-color:#FDE68A; border-left-color:#D97706; color:#92400E; }
  .iwo3-banner.red    { background:#FEF2F2; border-color:#FECACA; border-left-color:#DC2626; color:#991B1B; }
  .iwo3-banner.green  { background:#ECFDF5; border-color:#A7F3D0; border-left-color:#059669; color:#065F46; }
  .iwo3-banner.sky    { background:#F0F9FF; border-color:#BAE6FD; border-left-color:#0284C7; color:#075985; }
  .iwo3-banner.violet { background:#F5F3FF; border-color:#DDD6FE; border-left-color:#7C3AED; color:#5B21B6; }

  /* ── Description as flow, not a card ────────────────────────────
     Drops the bordered/background wrap from the parity pass —
     description reads as content, not as a stacked box. */
  .iwo3-desc-flow {
    padding: 2px 0 8px 0;
    margin-bottom: 6px;
  }
  .iwo3-desc-flow .iwo3-desc-body {
    color: #374151; font-size: 0.88rem; line-height: 1.55;
    white-space: pre-wrap;
  }
  .iwo3-desc-flow .iwo3-desc-empty {
    color: #9CA3AF; font-style: italic; font-size: 0.82rem;
  }

  /* ── Compact cards (right rail) ─────────────────────────────────
     Tightened padding; semantic accent on the deliv + results cards;
     Properties stays neutral so it doesn't compete with the others. */
  .iwo3-card {
    background: #FFFFFF;
    border: 1px solid #E5E7EB;
    border-radius: 6px;
    padding: 10px 12px;
    margin-bottom: 8px;
  }
  .iwo3-card .iwo3-card-hdr {
    display: inline-flex; align-items: center; gap: 6px;
    font-weight: 600; color: #111827; font-size: 0.80rem;
    margin-bottom: 6px;
    text-transform: uppercase; letter-spacing: 0.02em;
  }
  .iwo3-card .iwo3-card-hdr svg { width: 13px; height: 13px; color: #4B5563; }
  .iwo3-card.iwo3-card-deliv {
    border-left: 3px solid #10B981; background: #F0FDF4;
  }
  .iwo3-card.iwo3-card-deliv .iwo3-card-hdr { color:#065F46; }
  .iwo3-card.iwo3-card-deliv .iwo3-card-hdr svg { color:#059669; }
  .iwo3-card.iwo3-card-results {
    border-left: 3px solid #6366F1; background: #F5F3FF;
  }
  .iwo3-card.iwo3-card-results .iwo3-card-hdr { color:#4338CA; }
  .iwo3-card.iwo3-card-results .iwo3-card-hdr svg { color:#4F46E5; }
  .iwo3-card.iwo3-card-props { background: #F9FAFB; }

  /* Property rows — keys muted left, values strong right. */
  .iwo3-prop-row {
    display: flex; justify-content: space-between; align-items: baseline;
    gap: 10px; padding: 4px 0; border-top: 1px solid #F3F4F6;
  }
  .iwo3-prop-row:first-of-type { border-top: none; padding-top: 0; }
  .iwo3-prop-row .k {
    color: #6B7280; font-size: 0.72rem; font-weight: 500;
    text-transform: uppercase; letter-spacing: 0.02em;
    flex-shrink: 0;
  }
  .iwo3-prop-row .v {
    color: #111827; font-size: 0.80rem; font-weight: 500;
    text-align: right; word-break: break-word; min-width: 0;
  }
  .iwo3-prop-row .v code {
    background: #FFFFFF; color: #374151;
    padding: 1px 6px; border-radius: 4px; font-size: 0.72rem;
    border: 1px solid #E5E7EB;
  }

  /* Deliverable + results inner items — compact. */
  .iwo3-deliv-item {
    background: #FFFFFF; border: 1px solid #D1FAE5;
    border-radius: 5px; padding: 7px 9px; margin-top: 4px;
  }
  .iwo3-deliv-item .t {
    color: #065F46; font-weight: 600; font-size: 0.82rem;
  }
  .iwo3-deliv-item .m {
    color: #6B7280; font-size: 0.72rem; margin-top: 2px;
  }
  .iwo3-results-pre {
    background: #FFFFFF; border: 1px solid #DDD6FE;
    border-radius: 5px; padding: 7px 9px; margin-top: 4px;
    color: #1F2937; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 0.72rem; line-height: 1.4; overflow-x: auto;
    white-space: pre-wrap; word-break: break-word;
  }
  .iwo3-results-meta {
    font-size: 0.80rem; color:#3730A3; margin-bottom: 2px;
  }
  .iwo3-results-meta code {
    background:#FFFFFF; color:#312E81;
    border:1px solid #DDD6FE; padding:1px 5px;
    border-radius:4px; font-size:0.72rem;
  }

  /* ── Subtle section divider for in-column rhythm ───────────────── */
  .iwo3-section-gap { height: 4px; }
</style>
"""


# ─── Inline Lucide icon registry (MIT — github.com/lucide-icons/lucide).
#     SVG paths inlined verbatim so the parity icons render
#     deterministically inside `unsafe_allow_html=True` blocks.
#     `st.html` strips SVG via DOMPurify; `st.markdown(..., unsafe=True)`
#     preserves it. ───────────────────────────────────────────────────
_LUCIDE: dict[str, str] = {
    "check-circle": '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
    "rotate-cw":    '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "hourglass":    '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/>',
    "alert-circle": '<circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
    "clock":        '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "x-circle":     '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    "ban":          '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    "calendar":     '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
    "shield-alert": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="M12 8v4"/><path d="M12 16h.01"/>',
    "alert-octagon":'<polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>',
    "package":      '<path d="M16.5 9.4 7.55 4.24"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.29 7.3 12 12.27 20.71 7.3"/><line x1="12" x2="12" y1="22.08" y2="12"/>',
    "bot":          '<path d="M12 8V4H8"/><rect width="16" height="12" x="4" y="8" rx="2"/><path d="M2 14h2"/><path d="M20 14h2"/><path d="M15 13v2"/><path d="M9 13v2"/>',
    "user-cog":     '<circle cx="18" cy="15" r="3"/><circle cx="9" cy="7" r="4"/><path d="M10 15H6a4 4 0 0 0-4 4v2"/><path d="m21.7 16.4-.9-.3"/><path d="m15.2 13.9-.9-.3"/><path d="m16.6 18.7.3-.9"/><path d="m19.1 12.2.3-.9"/><path d="m19.6 18.7-.4-1"/><path d="m16.8 12.3-.4-1"/><path d="m14.3 16.6 1-.4"/><path d="m20.7 13.8 1-.4"/>',
    "calendar-clock":'<path d="M21 7.5V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h3.5"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h5"/><path d="M17.5 17.5 16 16.3V14"/><circle cx="16" cy="16" r="6"/>',
    "play-circle":  '<circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/>',
    "arrow-right":  '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    "edit":         '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-.497z"/><path d="m15 5 4 4"/>',
    "restart":      '<path d="M3 12a9 9 0 1 0 9-9 9.74 9.74 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "send":         '<path d="M14.536 21.686a.5.5 0 0 0 .937-.024l6.5-19a.496.496 0 0 0-.635-.635l-19 6.5a.5.5 0 0 0-.024.937l7.93 3.18a2 2 0 0 1 1.112 1.11z"/><path d="m21.854 2.147-10.94 10.939"/>',
    "presentation": '<path d="M2 3h20"/><path d="M21 3v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3"/><path d="m7 21 5-5 5 5"/>',
    "file-text":    '<path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5z"/><polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/><line x1="16" x2="8" y1="17" y2="17"/>',
    "list-checks":  '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
    "users":        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "info":         '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
}


def _icon(name: str, size: int = 14, color: str = "currentColor") -> str:
    """Inline an MIT-licensed Lucide SVG by registry key."""
    body = _LUCIDE.get(name, "")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
    )


# ─── Status / priority badge config (IWO2 detail-page parity) ────────
# (badge-variant, lucide icon name, human label)
_STATUS_BADGE: dict[str, tuple[str, str, str]] = {
    "pending":           ("pending", "hourglass", "Pending"),
    "processing":        ("processing", "rotate-cw", "Processing"),
    "blocked":           ("blocked", "alert-circle", "Blocked"),
    "awaiting_operator": ("awaiting", "clock", "Awaiting operator"),
    "deferred":          ("deferred", "calendar", "Deferred"),
    "completed":         ("completed", "check-circle", "Completed"),
    "done":              ("completed", "check-circle", "Done"),
    "failed":            ("failed", "x-circle", "Failed"),
    "cancelled":         ("cancelled", "ban", "Cancelled"),
    "reopened":          ("reopened", "restart", "Reopened"),
}


def _iwo2_status_badge(status: str) -> str:
    variant, icon, label = _STATUS_BADGE.get(
        status, ("cancelled", "info", status.replace("_", " "))
    )
    return (
        f'<span class="iwo3-badge {variant}">{_icon(icon, size=13)}'
        f'<span>{label}</span></span>'
    )


def _iwo2_priority_badge(priority: str) -> str:
    return f'<span class="iwo3-prio {priority}">{priority}</span>'


def _ts(ts: str | None) -> str:
    if not ts:
        return "-"
    return ts.replace("T", " ").replace("+00:00", " UTC")


def _ts_relative(ts: str | None) -> str:
    """Render an ISO timestamp as a compact relative string for the
    summary band meta line. Falls back to ISO date for anything older
    than a week."""
    if not ts:
        return "-"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt
        secs = int(delta.total_seconds())
        if secs < 0:
            return ts.split("T")[0]
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        if secs < 7 * 86400:
            return f"{secs // 86400}d ago"
        return dt.date().isoformat()
    except (ValueError, TypeError):
        return ts.split("T")[0] if "T" in ts else ts


def _metadata_work_order_id(metadata: dict[str, Any]) -> str | None:
    return (
        metadata.get("workOrderId")
        or metadata.get("work_order_id")
        or metadata.get("work_orderId")
    )


def _audit_summary(action: str, metadata: dict[str, Any]) -> str:
    if action == "llm.invoked":
        role = metadata.get("agentRole") or "unknown-role"
        decision = metadata.get("decisionKind") or "decision"
        provider = metadata.get("provider") or "unknown-provider"
        model = metadata.get("model") or "unknown-model"
        total = metadata.get("totalTokens")
        token_note = f" ({total} tokens)" if total else ""
        return (
            f"{role} via {provider}/{model} produced `{decision}`{token_note}."
        )
    if action == "llm.failed":
        role = metadata.get("agentRole") or "unknown-role"
        kind = metadata.get("kind") or "failure"
        detail = metadata.get("detail") or "No detail recorded."
        return f"{role} failed with `{kind}`: {detail}"
    if action == "workflow_execution.started":
        template = metadata.get("templateKey") or "unknown-template"
        steps = metadata.get("stepCount")
        step_note = f" with {steps} planned steps" if steps else ""
        return f"PM started workflow `{template}`{step_note}."
    if action == "output_package.created":
        kind = metadata.get("outputKind") or "output"
        title = metadata.get("title") or "Untitled package"
        return f"Created output package `{title}` of kind `{kind}`."
    if action.startswith("adapter_dispatch."):
        handoff_id = metadata.get("handoffId") or "-"
        external = metadata.get("externalReference") or "-"
        stage = action.removeprefix("adapter_dispatch.")
        return (
            f"Adapter handoff `{handoff_id}` is `{stage}`"
            f" (external ref: `{external}`)."
        )
    if action == "work_order.transitioned":
        return (
            f"Work order moved to `{metadata.get('to') or '-'}`"
            f" from `{metadata.get('from') or '-'}`."
        )
    reason = metadata.get("reason")
    if reason:
        return reason
    return "Raw audit metadata available below."


def _group_audit_rows(rows: list[Any]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        wo_id = row.target_id if row.target_type == "work_order" else None
        if not wo_id:
            wo_id = _metadata_work_order_id(row.metadata)
        if wo_id:
            grouped[wo_id].append(row)
    return grouped


# Kept for backwards-compat with the Lifecycle tab's existing markup —
# the IWO2 parity surface uses _iwo2_status_badge() instead.
_STATUS_EMOJI = {
    "pending": "🟡",
    "processing": "🔵",
    "blocked": "🔴",
    "awaiting_operator": "🟠",
    "deferred": "⚪",
    "completed": "🟢",
    "done": "🟢",
    "failed": "❌",
    "cancelled": "⚫",
}


def _state_chip(status: str) -> str:
    return f"{_STATUS_EMOJI.get(status, '⚫')} `{status}`"


def _status_chip_class(status: str) -> str:
    if status in ("completed", "done"):
        return "iwo3-chip green"
    if status == "reopened":
        return "iwo3-chip violet"
    if status in ("deferred",):
        return "iwo3-chip sky"
    if status in ("cancelled", "archived"):
        return "iwo3-chip gray"
    if status == "failed":
        return "iwo3-chip red"
    if status in ("blocked", "awaiting_operator"):
        return "iwo3-chip amber"
    return "iwo3-chip blue"


def _priority_chip_class(priority: str) -> str:
    if priority == "critical":
        return "iwo3-chip red"
    if priority == "high":
        return "iwo3-chip amber"
    return "iwo3-chip blue"


def _status_chip_html(status: str) -> str:
    label = status.replace("_", " ")
    emoji = _STATUS_EMOJI.get(status, "⚫")
    return (
        f'<span class="{_status_chip_class(status)}">'
        f"<span>{emoji}</span>{label}</span>"
    )


def _priority_chip_html(priority: str) -> str:
    return (
        f'<span class="{_priority_chip_class(priority)}">'
        f"{priority}</span>"
    )


def _aiden_decision_card(audit_rows: list[Any]) -> None:
    """Surface the most recent Aiden Tier-1 decision at the top of the
    Lifecycle tab so operators can see what Aiden chose without reading
    every row. Returns silently if no Aiden invocation exists yet."""
    aiden = next(
        (
            r for r in audit_rows
            if r.action == "llm.invoked"
            and (r.metadata.get("agentRole") or "").startswith("aiden_")
        ),
        None,
    )
    if aiden is None:
        return
    md = aiden.metadata
    decision = md.get("decisionKind") or "(unknown)"
    provider = md.get("provider") or "-"
    model = md.get("model") or "-"
    tokens = md.get("totalTokens")
    latency = md.get("latencyMs")
    st.markdown("**Aiden decided**")
    st.markdown(
        f"`{decision}` via **{provider}** / `{model}`"
        + (f" · {latency}ms" if latency else "")
        + (f" · {tokens} tokens" if tokens else "")
    )


def _render_lifecycle(wo: Any, audit_rows: list[Any]) -> None:
    if not audit_rows:
        st.caption("No audit evidence yet for this work order.")
        return

    _aiden_decision_card(audit_rows)
    st.markdown(
        " ".join(
            [
                "**Current state:**",
                _status_chip_html(wo.status),
                "&nbsp;&nbsp;**Priority:**",
                _priority_chip_html(wo.priority),
            ]
        ),
        unsafe_allow_html=True,
    )

    st.markdown("**What happened**")
    for row in audit_rows[:6]:
        st.markdown(
            f"- `{_ts(row.created_at)}` · **{row.action}** — "
            f"{_audit_summary(row.action, row.metadata)}"
        )

    latest_invocation = next(
        (row for row in audit_rows if row.action == "llm.invoked"), None
    )
    if latest_invocation is not None:
        md = latest_invocation.metadata
        stats = [
            ("Latest role", md.get("agentRole") or "-"),
            ("Decision/output", md.get("decisionKind") or "-"),
            ("Provider", md.get("provider") or "-"),
            ("Tokens", str(md.get("totalTokens") or "-")),
        ]
        stat_html = "".join(
            (
                '<div class="iwo3-stat">'
                f'<div class="k">{label}</div>'
                f'<div class="v">{value}</div>'
                "</div>"
            )
            for label, value in stats
        )
        st.markdown(
            f'<div class="iwo3-stat-strip">{stat_html}</div>',
            unsafe_allow_html=True,
        )


def _render_outputs(packages: list[Any], handoffs_by_package: dict[str, list[Any]]) -> None:
    if not packages:
        st.caption("No output packages have been created for this work order yet.")
        return

    for pkg in packages:
        st.markdown(
            f"**{pkg.title}** · `{pkg.output_kind}` · `{pkg.status}`"
        )
        st.caption(f"Package `{pkg.id}` · created {_ts(pkg.created_at)}")
        handoffs = handoffs_by_package.get(pkg.id, [])
        if not handoffs:
            st.caption("No handoffs linked to this package yet.")
            continue
        for handoff in handoffs:
            st.markdown(
                f"- Handoff `{handoff.id}` · status `{handoff.status}` · "
                f"candidate `{handoff.candidate_status}`"
            )
            extra = []
            if handoff.external_destination:
                extra.append(f"destination `{handoff.external_destination}`")
            if handoff.external_reference:
                extra.append(f"external ref `{handoff.external_reference}`")
            if handoff.created_at:
                extra.append(f"created {_ts(handoff.created_at)}")
            if extra:
                st.caption(" · ".join(extra))


def _render_audit_panel(wo_id: str, audit_rows: list[Any]) -> None:
    if st.button("Open full Audit Log page", key=f"audit-page-{wo_id}"):
        st.session_state["audit_log_work_order_filter"] = wo_id
        st.switch_page("views/audit_log.py")

    if not audit_rows:
        st.caption("No audit rows recorded yet.")
        return

    for row in audit_rows:
        with st.expander(
            f"{_ts(row.created_at)} · {row.action}",
            expanded=False,
        ):
            st.markdown(_audit_summary(row.action, row.metadata))
            st.markdown(
                f"**Target:** `{row.target_type or '-'} / {row.target_id or '-'}`"
            )
            st.code(
                json.dumps(row.metadata, indent=2, default=str),
                language="json",
            )


def _esc(value: Any) -> str:
    if value is None:
        return "-"
    return str(value).replace("<", "&lt;").replace(">", "&gt;")


# ─── IWO2 detail-page parity render helpers — POLISHED ───────────────


def _render_summary_band(wo: Any) -> None:
    """Anchored summary band — title + badge + priority feel like ONE
    identity instead of separate floating chips. A compact metadata
    line below carries ID / Type / created/updated relative times.
    Polish-pass replacement for `_render_status_header`."""
    title_html = _esc(wo.title or "Untitled")
    badge_html = _iwo2_status_badge(wo.status)
    prio_html = _iwo2_priority_badge(wo.priority)
    id_short = _esc((wo.id or "")[:8])
    type_html = _esc(wo.type)
    created_rel = _esc(_ts_relative(wo.created_at))
    updated_rel = _esc(_ts_relative(wo.updated_at))

    meta_chunks = [
        f'<span>ID <code>{id_short}</code></span>',
        f'<span>Type <code>{type_html}</code></span>',
        f'<span>Created {created_rel}</span>',
    ]
    if updated_rel and updated_rel != created_rel:
        meta_chunks.append(f'<span>Updated {updated_rel}</span>')
    if getattr(wo, "correlation_id", None):
        meta_chunks.append(
            f'<span>Corr <code>{_esc((wo.correlation_id or "")[:8])}</code></span>'
        )
    meta_html = '<span class="sep">·</span>'.join(meta_chunks)

    st.markdown(
        '<div class="iwo3-summary-band">'
        '<div class="iwo3-sb-row">'
        f'<h3 class="iwo3-sb-title">{title_html}</h3>'
        f'{badge_html}{prio_html}'
        '</div>'
        f'<div class="iwo3-sb-meta">{meta_html}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _quality_review_data(audit_rows: list[Any]) -> dict[str, Any] | None:
    """Return the most recent Darla brand-attestation quality review,
    or None if no Darla audit row exists yet. BUG-068 contract: Darla
    emits `darla.qa_passed` / `darla.qa_needs_revision` / `darla.qa_blocked`
    audit events with structured `issues[]` + `recommendations[]` in
    metadata. We surface the latest of those at banner severity."""
    target_actions = {
        "darla.qa_passed",
        "darla.qa_needs_revision",
        "darla.qa_blocked",
    }
    for row in audit_rows:
        if row.action in target_actions:
            return {"action": row.action, "metadata": row.metadata or {}}
    return None


def _render_quality_review_banner(qr: dict[str, Any] | None) -> None:
    """IWO2 QualityReviewSummary parity: amber for needs_revision, red
    for blocked, green for passed. Issues + recommendations lists when
    present in audit metadata. Returns silently if Darla hasn't run."""
    if qr is None:
        return
    action = qr["action"]
    md = qr["metadata"]
    if action == "darla.qa_passed":
        variant = "green"
        icon = "check-circle"
        title = "Quality Review — Passed"
    elif action == "darla.qa_blocked":
        variant = "red"
        icon = "alert-octagon"
        title = "Quality Review — Blocked"
    else:
        variant = "amber"
        icon = "shield-alert"
        title = "Quality Review — Needs Revision"

    issues = md.get("issues") or md.get("findings") or []
    recs = md.get("recommendations") or md.get("recommended_actions") or []
    summary = md.get("summary") or md.get("note") or ""

    body_parts: list[str] = []
    if summary:
        body_parts.append(f'<div>{_esc(summary)}</div>')
    if issues:
        items = "".join(f"<li>{_esc(i)}</li>" for i in issues if i)
        body_parts.append(f'<div><strong>Issues</strong><ul>{items}</ul></div>')
    if recs:
        items = "".join(f"<li>{_esc(r)}</li>" for r in recs if r)
        body_parts.append(f'<div><strong>Recommended actions</strong><ul>{items}</ul></div>')
    if not body_parts:
        body_parts.append('<div>No additional detail in audit metadata.</div>')

    st.markdown(
        f'<div class="iwo3-banner {variant}">'
        f'<div class="iwo3-banner-hdr">{_icon(icon, size=15)}<span>{title}</span></div>'
        f'{"".join(body_parts)}'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_terminal_banner(wo: Any) -> None:
    """Render IWO2-style operator-significant status banners for the
    in-trouble states: blocked / awaiting_operator / failed / deferred.
    Completed and processing don't get a banner — the badge in the
    summary band is enough."""
    status = wo.status
    if status == "blocked":
        variant, icon, title = "red", "alert-circle", "Blocked"
        body = (
            "This work order is blocked. Use Edit / Reopen / Redispatch "
            "below to recover, or move it to another state."
        )
    elif status == "awaiting_operator":
        variant, icon, title = "amber", "user-cog", "Awaiting operator"
        body = (
            "A candidate review or operator decision is required before "
            "this work order can progress."
        )
    elif status == "failed":
        variant, icon, title = "red", "x-circle", "Failed"
        body = (
            "This work order ended in a failed terminal state. Reopen "
            "below to retry after addressing the root cause."
        )
    elif status == "deferred":
        variant, icon, title = "sky", "calendar-clock", "Deferred"
        body = (
            "This work order is deferred. Move it back to processing "
            "when ready to resume."
        )
    else:
        return
    st.markdown(
        f'<div class="iwo3-banner {variant}">'
        f'<div class="iwo3-banner-hdr">{_icon(icon, size=15)}<span>{title}</span></div>'
        f'<div>{body}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_description_flow(wo: Any) -> None:
    """Description as flowing typography — no card chrome. Title is in
    the summary band; this is just the body content. Polish-pass
    replacement for `_render_description_card` (which wrapped the body
    in another box, contributing to the stacked-box feel)."""
    if wo.description:
        body_html = _esc(wo.description)
        st.markdown(
            '<div class="iwo3-desc-flow">'
            f'<div class="iwo3-desc-body">{body_html}</div>'
            '</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="iwo3-desc-flow">'
            '<div class="iwo3-desc-empty">No description provided.</div>'
            '</div>',
            unsafe_allow_html=True,
        )


def _render_properties_card(wo: Any) -> None:
    """Slim Properties card — only the fields NOT already in the
    summary band. Status/Priority/ID/Type/Created/Updated/Correlation
    are all in the band; this is the supporting metadata that
    operators occasionally need but doesn't need to scream."""
    rows: list[tuple[str, str]] = [
        ("Submitter", f"<code>{_esc((wo.submitted_by_user_id or '')[:8])}</code>"),
        ("Full ID", f"<code>{_esc(wo.id)}</code>"),
    ]
    if getattr(wo, "correlation_id", None):
        rows.append(("Full corr.", f"<code>{_esc(wo.correlation_id)}</code>"))

    row_html = "".join(
        f'<div class="iwo3-prop-row"><span class="k">{k}</span>'
        f'<span class="v">{v}</span></div>'
        for k, v in rows
    )
    st.markdown(
        '<div class="iwo3-card iwo3-card-props">'
        f'<div class="iwo3-card-hdr">{_icon("list-checks")}<span>Properties</span></div>'
        f'{row_html}'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_deliverables_card(packages: list[Any]) -> None:
    """IWO2 Deliverables card — emerald-tinted border + soft green bg,
    listing the WO's output_packages. Returns silently when there are
    no packages yet."""
    if not packages:
        return
    items_html = "".join(
        '<div class="iwo3-deliv-item">'
        f'<div class="t">{_esc(p.title or "Untitled")}</div>'
        f'<div class="m">kind <code>{_esc(p.output_kind)}</code> · '
        f'status <code>{_esc(p.status)}</code> · created {_esc(_ts_relative(p.created_at))}</div>'
        '</div>'
        for p in packages
    )
    st.markdown(
        '<div class="iwo3-card iwo3-card-deliv">'
        f'<div class="iwo3-card-hdr">{_icon("package")}<span>Deliverables</span></div>'
        f'{items_html}'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_results_card(audit_rows: list[Any]) -> None:
    """IWO2 Aiden Result / decision card — surfaces the latest Aiden
    Tier-1 decision (kind + provider/model + token + latency) plus
    optional structured payload in a soft violet-tinted card with a
    JSON pre-block. Returns silently when Aiden hasn't run."""
    aiden = next(
        (
            r for r in audit_rows
            if r.action == "llm.invoked"
            and (r.metadata.get("agentRole") or "").startswith("aiden_")
        ),
        None,
    )
    if aiden is None:
        return
    md = aiden.metadata or {}
    decision = md.get("decisionKind") or "(unknown)"
    provider = md.get("provider") or "-"
    model = md.get("model") or "-"
    tokens = md.get("totalTokens")
    latency = md.get("latencyMs")
    meta_line = (
        f'<code>{_esc(decision)}</code> via <code>{_esc(provider)}</code>'
        f' / <code>{_esc(model)}</code>'
    )
    if latency:
        meta_line += f" · {_esc(latency)}ms"
    if tokens:
        meta_line += f" · {_esc(tokens)} tokens"

    payload_keys = ("payload", "result", "output", "decision", "summary")
    payload: dict[str, Any] = {}
    for k in payload_keys:
        if k in md and md[k]:
            payload[k] = md[k]
    pre_html = ""
    if payload:
        pretty = json.dumps(payload, indent=2, default=str)[:2000]
        pre_html = f'<div class="iwo3-results-pre">{_esc(pretty)}</div>'

    st.markdown(
        '<div class="iwo3-card iwo3-card-results">'
        f'<div class="iwo3-card-hdr">{_icon("bot")}<span>Aiden Result</span></div>'
        f'<div class="iwo3-results-meta">{meta_line}</div>'
        f'{pre_html}'
        '</div>',
        unsafe_allow_html=True,
    )


def _render_top_toolbar(api, wo: Any) -> None:
    """Compressed action toolbar — tertiary visual weight, no group
    label, tighter spacing. The buttons support the page; they no
    longer dominate it. Polish-pass cleanup of the prior 4-equal-cols
    `type=primary` row that read as heavy."""
    # Narrower columns + trailing spacer so the toolbar sits on the
    # left third of the row rather than spanning the full width.
    cols = st.columns([2, 2, 2, 2, 4])

    with cols[0]:
        if st.button(
            "Run Aiden",
            key=f"dispatch-{wo.id}",
            type="secondary",
            help=(
                "Aiden Tier 1 classifies; if work_order_brief, Tier 2 "
                "produces the deliverable; if workflow_brief, PM Tier 1.5 "
                "instantiates the workflow."
            ),
            use_container_width=True,
        ):
            with st.spinner("dispatching…"):
                try:
                    r = api.dispatch_work_order(wo.id)
                except APIError as err:
                    st.error(f"❌ {err.status_code} — {err.detail}")
                    r = None
            if r:
                if r.get("ok"):
                    kind = r.get("decision_kind")
                    if kind == "work_order_brief":
                        st.success(
                            f"✅ {kind} → output_package `{r.get('output_package_id')}`"
                        )
                    elif kind == "workflow_brief":
                        st.success(
                            f"✅ {kind} → execution `{r.get('workflow_execution_id')}` "
                            f"({len(r.get('step_run_ids') or [])} steps)"
                        )
                    else:
                        st.success(f"✅ {kind}")
                    st.rerun()
                else:
                    if r.get("decision_kind") == "clarification":
                        st.warning(f"❓ Aiden asked: {r.get('clarification_question')}")
                    else:
                        st.warning(f"⚠️ {r.get('error')}")

    with cols[1]:
        if st.button(
            "Next step",
            key=f"advance-step-{wo.id}",
            type="secondary",
            help=(
                "Advance the next pending step in this WO's running "
                "workflow chain. Background worker also advances pending "
                "steps every ~10s without operator action."
            ),
            use_container_width=True,
        ):
            with st.spinner("running next step…"):
                try:
                    r = api.run_next_workflow_step_by_wo(wo.id)
                except APIError as err:
                    if err.status_code == 404:
                        d = err.detail or {}
                        st.info(f"⏸ {d.get('hint', d)}")
                    else:
                        st.error(f"❌ {err.status_code} — {err.detail}")
                    r = None
            if r:
                if r.get("ok"):
                    if r.get("workflow_finished"):
                        st.success("✅ workflow finished — all steps complete")
                    else:
                        pkg_id = r.get("output_package_id")
                        pkg_suffix = f" → output_package `{pkg_id}`" if pkg_id else ""
                        st.success(
                            f"✅ advanced `{r.get('step_key')}` "
                            f"(step_run `{r.get('step_run_id')}`){pkg_suffix}"
                        )
                    st.rerun()
                else:
                    st.warning(f"⚠️ {r.get('error')}")

    with cols[2]:
        if st.button(
            "Render Gamma",
            key=f"render-{wo.id}",
            type="secondary",
            help=(
                "One-shot dispatch of this WO's latest gamma_*-kinded "
                "output_package to Gamma. Use after Tier 2 has produced "
                "the package but the auto-dispatch hook didn't fire."
            ),
            use_container_width=True,
        ):
            with st.spinner("submitting to Gamma…"):
                try:
                    r = api.render_work_order(wo.id)
                except APIError as err:
                    if err.status_code == 404:
                        st.warning(
                            "No gamma_*-kinded output_package on this WO yet — "
                            "run Aiden + Tier 2 first."
                        )
                    elif err.status_code == 409:
                        d = err.detail or {}
                        st.info(
                            f"⏸ A handoff is already in flight for this package. {d}"
                        )
                    else:
                        st.error(f"❌ {err.status_code} — {err.detail}")
                    r = None
            if r:
                if r.get("ok"):
                    handoff = r.get("handoff_id")
                    ext_ref = r.get("external_reference")
                    st.success(
                        f"✅ submitted to Gamma — handoff `{handoff}` "
                        f"(gamma generation `{ext_ref}`). Poll worker will advance."
                    )
                    st.rerun()
                else:
                    st.warning(f"⚠️ {r.get('error')}")

    with cols[3]:
        if st.button(
            "Audit ↗",
            key=f"audit-jump-{wo.id}",
            type="tertiary",
            help="Open the dedicated Audit Log page filtered to this WO.",
            use_container_width=True,
        ):
            st.session_state["audit_log_work_order_filter"] = wo.id
            st.switch_page("views/audit_log.py")


def _flash_recovery(wo_id: str, level: str, msg: str) -> None:
    """FF.AI Hotfix (2026-05-17) — stash a recovery-panel result into
    session_state and rerun, so the next render shows the message at
    full column-left width instead of inside the narrow rec_cols where
    long Aiden assistant_reply text wraps to one-word-per-line and
    produces a "broken UI" look.

    Scoped per `wo_id` so multiple WOs on the same page don't trample
    each other's flashes."""
    st.session_state[f"_recovery_flash_{wo_id}"] = {"level": level, "msg": msg}
    st.rerun()


def _render_recovery_flash(wo_id: str) -> None:
    """Pop and render the recovery flash for `wo_id` at full width.
    Long messages (Aiden assistant_reply) truncate to ~280 chars with
    an expander for the full text — avoids the previous behavior of
    dumping a 3-screen reply into a narrow yellow column."""
    flash = st.session_state.pop(f"_recovery_flash_{wo_id}", None)
    if not flash:
        return
    level = flash.get("level") or "warning"
    msg = flash.get("msg") or ""
    if level == "success":
        st.success(msg)
    elif level == "error":
        st.error(msg)
    else:
        if len(msg) > 280:
            st.warning(msg[:280].rstrip() + "…")
            with st.expander("Show full message"):
                st.markdown(msg)
        else:
            st.warning(msg)


def _operator_recovery_panel(api, wo: Any) -> None:
    """Loop Xi — Reopen / Edit / Redispatch.

    Polish pass: no `Recovery` group label, narrow column layout so the
    controls sit on the left without dominating the description column.
    Only renders if the WO is in a status where at least one of the
    three actions is legal.

    BUG-060 (2026-05-10): widened `is_active` from ("pending",
    "processing") to include all non-terminal states where operator
    amendment is operationally useful — `blocked`,
    `awaiting_operator`, and `deferred`. Now in lockstep with backend
    _EDITABLE_STATUSES / _REDISPATCHABLE_STATUSES."""
    is_terminal = wo.status in ("completed", "done", "failed")
    is_active = wo.status in (
        "pending",
        "processing",
        "blocked",
        "awaiting_operator",
        "deferred",
    )
    if not (is_terminal or is_active):
        return

    # Render any flash from a prior button click at full column-left
    # width BEFORE the narrow rec_cols layout below. Without this,
    # st.warning(...) inside rec_cols[N] inherits the narrow column
    # width and word-wraps every word onto its own line.
    _render_recovery_flash(wo.id)

    try:
        decision = api.check_permission("work_order:update")
    except APIError as err:
        st.caption(f"⚠️ perm check failed: {err.detail}")
        return
    if not decision.allowed:
        st.caption(
            f"_Recovery requires `work_order:update` "
            f"(your role: `{decision.role}`)._"
        )
        return

    # Narrow row — 3 buttons take ~half the column width, leaving the
    # other half as breathing space so the controls don't dominate the
    # description above.
    rec_cols = st.columns([2, 2, 2, 6])

    if is_terminal:
        with rec_cols[0]:
            with st.popover(
                "Reopen", icon=":material/restart_alt:", use_container_width=True
            ):
                st.markdown("**Reopen this work order**")
                st.caption(
                    "Moves the WO from terminal back to `processing`. A "
                    "reason is required and recorded in the audit trail."
                )
                reason = st.text_area(
                    "Reason",
                    key=f"reopen-reason-{wo.id}",
                    max_chars=500,
                    placeholder="e.g., template wrong; needs Klear branding",
                )
                if st.button(
                    "Confirm Reopen",
                    key=f"reopen-confirm-{wo.id}",
                    type="primary",
                    disabled=not reason.strip(),
                ):
                    with st.spinner("reopening…"):
                        try:
                            result = api.reopen_work_order(
                                wo.id, reason=reason.strip()
                            )
                            st.success(
                                f"✅ Reopened — cycle `{result.get('cycle_id') or '-'}`"
                                + (
                                    " · prior assignments cleared"
                                    if result.get("cleared_assignments")
                                    else ""
                                )
                            )
                            st.rerun()
                        except APIError as err:
                            st.error(f"❌ {err.status_code} — {err.detail}")

    if is_active:
        with rec_cols[0]:
            with st.popover(
                "Edit", icon=":material/edit:", use_container_width=True
            ):
                st.markdown("**Edit this work order**")
                st.caption(
                    "Partial update. Only changed fields are written; "
                    "blank fields keep their current value."
                )
                new_title = st.text_input(
                    "Title",
                    value=wo.title,
                    max_chars=240,
                    key=f"edit-title-{wo.id}",
                )
                new_desc = st.text_area(
                    "Description",
                    value=wo.description or "",
                    max_chars=8000,
                    height=140,
                    key=f"edit-desc-{wo.id}",
                )
                type_options = (
                    "content_brief",
                    "deck_build",
                    "data_analysis",
                    "research",
                    "code_change",
                    "decision_request",
                    "ops_task",
                    "general",
                )
                new_type = st.selectbox(
                    "Type",
                    options=type_options,
                    index=(
                        type_options.index(wo.type)
                        if wo.type in type_options
                        else 0
                    ),
                    key=f"edit-type-{wo.id}",
                )
                priority_options = ("low", "medium", "high", "critical")
                new_priority = st.selectbox(
                    "Priority",
                    options=priority_options,
                    index=(
                        priority_options.index(wo.priority)
                        if wo.priority in priority_options
                        else 1
                    ),
                    key=f"edit-prio-{wo.id}",
                )
                tp_options = [("(no change)", None)]
                try:
                    tps = api.list_template_profiles(status="active")
                    for tp in tps:
                        label = (
                            f"{tp.get('profile_key')} · {tp.get('output_kind')}"
                        )
                        tp_options.append((label, tp.get("id")))
                except APIError as err:
                    st.caption(f"⚠️ template list unavailable: {err.detail}")
                tp_choice = st.selectbox(
                    "Template profile (optional)",
                    options=[label for label, _ in tp_options],
                    index=0,
                    key=f"edit-tp-{wo.id}",
                    help=(
                        "Explicit template selection. Improves on IWO2 "
                        "where templates were inferred from description prose."
                    ),
                )
                tp_id = next(
                    (tid for label, tid in tp_options if label == tp_choice),
                    None,
                )
                if st.button(
                    "Save edits",
                    key=f"edit-save-{wo.id}",
                    type="primary",
                ):
                    payload: dict[str, Any] = {}
                    if new_title and new_title != wo.title:
                        payload["title"] = new_title
                    if new_desc != (wo.description or ""):
                        payload["description"] = new_desc
                    if new_type and new_type != wo.type:
                        payload["type"] = new_type
                    if new_priority and new_priority != wo.priority:
                        payload["priority"] = new_priority
                    if tp_id is not None:
                        payload["template_profile_id"] = tp_id
                    if not payload:
                        st.info("No changes to save.")
                    else:
                        with st.spinner("saving…"):
                            try:
                                api.edit_work_order(wo.id, **payload)
                                st.success(
                                    f"✅ Saved — fields: "
                                    f"{', '.join(sorted(payload.keys()))}"
                                )
                                st.rerun()
                            except APIError as err:
                                st.error(
                                    f"❌ {err.status_code} — {err.detail}"
                                )

        with rec_cols[1]:
            if st.button(
                "Redispatch",
                key=f"redispatch-{wo.id}",
                use_container_width=True,
                help=(
                    "Re-fire Aiden Tier 1 → Tier 2/Workflow on the "
                    "current WO contents. Use after Edit to send the "
                    "revised brief through the pipeline."
                ),
            ):
                with st.spinner("redispatching…"):
                    try:
                        r = api.redispatch_work_order(wo.id)
                    except APIError as err:
                        st.error(f"❌ {err.status_code} — {err.detail}")
                        r = None
                if r:
                    if r.get("ok"):
                        kind = r.get("decision_kind") or "redispatched"
                        st.success(f"✅ {kind}")
                        st.rerun()
                    elif r.get("decision_kind") == "clarification":
                        _flash_recovery(
                            wo.id,
                            "warning",
                            f"❓ Aiden asked: {r.get('clarification_question')}",
                        )
                    else:
                        _flash_recovery(
                            wo.id, "warning", f"⚠️ {r.get('error')}"
                        )


def _transition_button(api, wo_id: str, from_status: str, to_status: str) -> None:
    """One-row transition button used inside the Status popover. Short
    label via `_TRANSITION_LABEL` so `awaiting_operator` reads as
    `Await operator` and never wraps awkwardly."""
    perm = PERM_FOR_TRANSITION.get(to_status, "work_order:update")
    try:
        decision = api.check_permission(perm)
    except APIError as err:
        st.caption(f"⚠️ perm check failed: {err.detail}")
        return
    label = _TRANSITION_LABEL.get(to_status, to_status.replace("_", " ").title())
    label_with_arrow = f"→ {label}"
    if decision.allowed:
        if st.button(
            label_with_arrow,
            key=f"btn-{wo_id}-{to_status}",
            use_container_width=True,
        ):
            try:
                result = api.transition_work_order(wo_id, to_status)
                st.success(
                    f"Transitioned {from_status} → {result['to']} "
                    f"(event: `{result['event']}`)"
                )
                st.rerun()
            except APIError as err:
                st.error(f"❌ {err.status_code} — {err.detail}")
    else:
        st.button(
            label_with_arrow,
            key=f"btn-{wo_id}-{to_status}",
            disabled=True,
            use_container_width=True,
            help=f"Denied — requires `{perm}` (your role: `{decision.role}`)",
        )


def _render_transitions_popover(api, wo: Any) -> None:
    """Collapse the prior multi-column transition strip into a single
    `Status ▾` popover. Vertical list inside, one row per legal
    target. Solves the wrapped-label problem from the parity pass —
    `awaiting_operator` now reads as `→ Await operator` on its own
    line and never wraps."""
    legal = SAFE_TRANSITIONS.get(wo.status, [])
    if not legal:
        # Terminal — render a quiet caption inline.
        st.caption(f"Terminal — no transitions out of `{wo.status}`.")
        return

    # Narrow popover trigger so it sits on the left third without
    # spanning the full column.
    trigger_cols = st.columns([3, 9])
    with trigger_cols[0]:
        with st.popover(
            "Status ▾",
            use_container_width=True,
            help="Move this work order to another legal state.",
        ):
            st.markdown(
                f"**Move from `{wo.status}` to:**",
                unsafe_allow_html=False,
            )
            for target in legal:
                _transition_button(api, wo.id, wo.status, target)


def main() -> None:
    st.markdown(
        """
        <h2 style="margin:0 0 2px 0; font-size:1.5rem; font-weight:700;">Work Orders</h2>
        <div style="color:#6B7280; font-size:0.86rem; margin-bottom:14px;">
          Tenant-scoped work orders with role-aware transition actions.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(_DETAIL_CSS, unsafe_allow_html=True)

    api = page_requires_api()
    if api is None:
        return

    try:
        wos = api.list_work_orders()
    except APIError as err:
        st.error(f"❌ {err.status_code} — {err.detail}")
        return

    try:
        all_packages = api.list_output_packages()
    except APIError:
        all_packages = []

    try:
        all_handoffs = api.list_output_handoffs()
    except APIError:
        all_handoffs = []

    audit_allowed = False
    audit_rows: list[Any] = []
    try:
        if api.check_permission("audit_log:read").allowed:
            audit_allowed = True
            audit_rows = api.list_audit_log(limit=300)
    except APIError:
        audit_allowed = False
        audit_rows = []

    packages_by_wo: dict[str, list[Any]] = defaultdict(list)
    for pkg in all_packages:
        if pkg.work_order_id:
            packages_by_wo[pkg.work_order_id].append(pkg)

    handoffs_by_package: dict[str, list[Any]] = defaultdict(list)
    for handoff in all_handoffs:
        if handoff.output_package_id:
            handoffs_by_package[handoff.output_package_id].append(handoff)

    audit_by_wo = _group_audit_rows(audit_rows)

    if not wos:
        st.info("No work orders in this tenant yet.")
        if st.button("＋ Create one"):
            st.switch_page("views/submit_order.py")
        return

    statuses = sorted({wo.status for wo in wos})
    status_filter = st.multiselect("Status", options=statuses, default=statuses)

    focus_id = st.session_state.pop("work_orders_focus_id", None)
    if not focus_id:
        qp_focus = st.query_params.get("focus")
        if isinstance(qp_focus, str) and qp_focus.strip():
            focus_id = qp_focus.strip()
            try:
                del st.query_params["focus"]
            except KeyError:
                pass
    if focus_id:
        st.info(
            "Showing the work order opened from another surface. The expander "
            "is open by default; clear status filters above if it doesn't "
            "appear (it may be in a status you've filtered out)."
        )

    def _sort_key(wo):
        return (wo.created_at or "", wo.id)

    wos_sorted = sorted(wos, key=_sort_key, reverse=True)
    filtered = [wo for wo in wos_sorted if wo.status in status_filter]
    st.caption(f"Showing {len(filtered)} / {len(wos)} work orders (latest first)")

    for wo in filtered:
        is_focused = bool(focus_id and wo.id == focus_id)
        with st.expander(
            f"**{wo.title}** — {_state_chip(wo.status)} · priority `{wo.priority}`",
            expanded=is_focused,
        ):
            # ── 1. Anchored summary band (title + badge + priority + meta)
            _render_summary_band(wo)

            # ── 2. Compact toolbar (Run Aiden / Next step / Render Gamma / Audit)
            _render_top_toolbar(api, wo)

            related_audit = audit_by_wo.get(wo.id, [])
            related_packages = packages_by_wo.get(wo.id, [])

            # ── 3. Banners (only render when they have something to say)
            _render_quality_review_banner(_quality_review_data(related_audit))
            _render_terminal_banner(wo)

            # ── 4. Body: two-column (description flow + recovery + transitions
            #     on the left; right rail with Properties + Deliverables +
            #     Results)
            col_left, col_right = st.columns([2, 1])
            with col_left:
                _render_description_flow(wo)
                _operator_recovery_panel(api, wo)
                _render_transitions_popover(api, wo)

            with col_right:
                _render_properties_card(wo)
                _render_deliverables_card(related_packages)
                _render_results_card(related_audit)

            # ── 5. Tabs preserved for full evidence detail
            tabs = st.tabs(["Lifecycle", "Outputs", "Audit"])
            with tabs[0]:
                _render_lifecycle(wo, related_audit)
            with tabs[1]:
                _render_outputs(related_packages, handoffs_by_package)
            with tabs[2]:
                if audit_allowed:
                    _render_audit_panel(wo.id, related_audit)
                else:
                    st.caption(
                        "Audit details are available on the Audit Log page for "
                        "roles that hold `audit_log:read`."
                    )


main()

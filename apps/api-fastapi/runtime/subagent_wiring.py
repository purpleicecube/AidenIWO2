"""Loop CAP-G CLOSEOUT Slice C — sub-agent wiring status surface.

Computes the live runtime truth matrix per
`IWO3_SUBAGENT_WIRING_MATRIX_AND_STATUS_SURFACE_v0.1.0`:

  - which roles are llm_enabled in `llm_configs` for the tenant
  - which roles are direct-routing reachable (KNOWN_TIER_2_ROLES)
  - which roles appear in workflow_template_steps (workflow path)
  - which roles appear in seeded branded chains (cap_branded_*)
  - which surfaces each role covers via output_surface_routes
  - which roles are degraded (`adapter_unavailable` adapters wired
    in the chain primary spot)
  - last_invoked_at / last_success_at / last_failure_at from
    action_audit_log

Truth rules (per spec):
  - separate `runtime-supported` from `seeded in branded flows`
  - separate `live native` from `fallback-only` from `controlled degraded`
  - exclude legacy seed labels (`mark`, `pm_alpha`, `agent_system`)
    from the live matrix

This module is consumed by:
  - `routes/system_status.py` (FastAPI endpoint)
  - `runtime/aiden_tools.py` (sub_agent_wiring_status tool)
  - Streamlit `views/system_health.py` (operator surface)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from .tier_1_aiden import KNOWN_TIER_2_ROLES


# Display names per role key.
_DISPLAY_NAMES: dict[str, str] = {
    "aiden_tier_1": "Aiden",
    "pm_tier_15": "PM",
    "mark_tier_2": "Mark",
    "tom_tier_2": "Tom",
    "hank_tier_2": "Hank",
    "sop_master_tier_2": "SOP Master",
    "darla_tier_2": "Darla",
    "paul_tier_2": "Paul",
    "jamie_tier_2": "Jamie",
    "nyx_tier_2": "Nyx",
    "polaris_tier_2": "Polaris",
}


# Layer per role key (informational; used by the matrix UI for grouping).
_LAYER: dict[str, str] = {
    "aiden_tier_1": "tier_1",
    "pm_tier_15": "tier_1_5",
    "mark_tier_2": "tier_2",
    "tom_tier_2": "tier_2",
    "hank_tier_2": "tier_2",
    "sop_master_tier_2": "tier_2",
    "darla_tier_2": "tier_2",
    "paul_tier_2": "tier_2",
    "jamie_tier_2": "tier_2",
    "nyx_tier_2": "tier_2",
    "polaris_tier_2": "tier_2",
}


# Legacy seed labels that should NEVER appear in the live matrix.
# Workflow_template_steps from pre-CAP-C loops use these; the live
# Tier-2 router normalizes them to *_tier_2 forms, but a status
# surface that reports them as live sub-agents would be wrong.
_LEGACY_SEED_LABELS: set[str] = {
    "mark",
    "pm_alpha",
    "agent_system",
    # Bare role aliases the runtime normalizes — not live sub-agents.
    "tom",
    "hank",
    "paul",
    "darla",
    "sop_master",
    "sop-master",
    "sop",
    "jamie",
    "nyx",
    "polaris",
}


# Per-role canonical (live) role keys. The matrix only reports rows
# from this set; legacy seed labels are mapped through but never
# surfaced as their own row.
_CANONICAL_ROLE_KEYS: tuple[str, ...] = (
    "aiden_tier_1",
    "pm_tier_15",
    "mark_tier_2",
    "tom_tier_2",
    "hank_tier_2",
    "sop_master_tier_2",
    "darla_tier_2",
    "paul_tier_2",
    "jamie_tier_2",
    "nyx_tier_2",
    "polaris_tier_2",
)


# Adapter keys that ship as `adapter_unavailable` stubs in CAP-F
# (degraded posture; routes fall through to fallback). Encoded here
# so the wiring matrix can mark surfaces degraded honestly without
# requiring runtime introspection of every adapter handler.
_DEGRADED_ADAPTER_KEYS: set[str] = {
    "sandbox_pdf",
    "sandbox_docx",
    "figma_html_render",
    "twentyfirst_html_render",
}


def _coerce_iso(ts: Optional[datetime]) -> Optional[str]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.isoformat()


async def _load_llm_config_enabled(
    conn: asyncpg.Connection, *, client_id: str
) -> dict[str, bool]:
    rows = await conn.fetch(
        """
        SELECT agent_role, enabled
          FROM llm_configs
         WHERE client_id = $1::uuid
        """,
        client_id,
    )
    return {r["agent_role"]: bool(r["enabled"]) for r in rows}


async def _load_workflow_step_role_usage(
    conn: asyncpg.Connection, *, client_id: str
) -> tuple[set[str], set[str]]:
    """Return (workflow_role_keys, branded_chain_role_keys) — both
    normalized. workflow_role_keys are all assigned_sub_agent_key
    values that appear in workflow_template_steps reachable for this
    tenant; branded_chain_role_keys are the subset that appears in
    cap_branded_* chains."""
    rows = await conn.fetch(
        """
        SELECT wts.assigned_sub_agent_key, w.key AS workflow_key
          FROM workflow_template_steps wts
          JOIN workflow_templates wt ON wt.id = wts.template_id
          JOIN workflows w ON w.id = wt.workflow_id
         WHERE w.client_id = $1::uuid
        """,
        client_id,
    )
    workflow_roles: set[str] = set()
    branded_roles: set[str] = set()
    for r in rows:
        raw = r["assigned_sub_agent_key"]
        if not raw:
            continue
        # Normalize using the same mapping the Tier-2 router uses;
        # legacy labels are mapped to canonical *_tier_2 forms.
        norm = _normalize_role_for_matrix(raw)
        if norm is None:
            continue  # legacy label that doesn't map cleanly — exclude
        workflow_roles.add(norm)
        if (r["workflow_key"] or "").startswith("cap_branded_"):
            branded_roles.add(norm)
    return workflow_roles, branded_roles


def _normalize_role_for_matrix(raw: str) -> Optional[str]:
    """Map a workflow_template_steps.assigned_sub_agent_key to a
    canonical live role key. Returns None for labels that should be
    excluded from the matrix entirely (e.g. `agent_system`)."""
    raw = (raw or "").strip()
    if not raw:
        return None
    # Already canonical
    if raw in _CANONICAL_ROLE_KEYS:
        return raw
    # Legacy short forms → canonical *_tier_2
    mapping = {
        "mark": "mark_tier_2",
        "tom": "tom_tier_2",
        "hank": "hank_tier_2",
        "paul": "paul_tier_2",
        "darla": "darla_tier_2",
        "sop_master": "sop_master_tier_2",
        "sop-master": "sop_master_tier_2",
        "sop": "sop_master_tier_2",
        "jamie": "jamie_tier_2",
        "nyx": "nyx_tier_2",
        "polaris": "polaris_tier_2",
        "pm_alpha": "pm_tier_15",
    }
    canonical = mapping.get(raw)
    if canonical:
        return canonical
    # Unknown / agent_system / etc.
    return None


async def _load_surface_coverage(
    conn: asyncpg.Connection,
) -> dict[str, list[str]]:
    """Per-role surface coverage derived from the branded chain
    workflow_template_steps. Returns {role_key: [output_kind, ...]}.

    The chain's `render` step's assigned_sub_agent_key carries the
    role that renders for each output_kind. Mark (content_brief),
    Darla (brand_qa), and Paul (deliver) are the same across all
    chains, so their surface coverage is the union of all branded
    output_kinds present.
    """
    rows = await conn.fetch(
        """
        SELECT wts.assigned_sub_agent_key,
               wts.step_key,
               (wt.config->>'outputKind')::text AS output_kind
          FROM workflow_template_steps wts
          JOIN workflow_templates wt ON wt.id = wts.template_id
          JOIN workflows w ON w.id = wt.workflow_id
         WHERE w.key LIKE 'cap_branded_%'
        """
    )
    surfaces: dict[str, set[str]] = {}
    for r in rows:
        role = _normalize_role_for_matrix(r["assigned_sub_agent_key"] or "")
        if role is None:
            continue
        ok = r["output_kind"]
        if not ok:
            continue
        surfaces.setdefault(role, set()).add(ok)
    return {k: sorted(v) for k, v in surfaces.items()}


async def _load_degraded_surfaces_from_routes(
    conn: asyncpg.Connection,
) -> dict[str, list[str]]:
    """Per-role degraded-surface list. A role surface is degraded when
    its branded chain's primary adapter is in _DEGRADED_ADAPTER_KEYS.
    For Paul (delivery), this is the per-output_kind degraded list
    (his decisions route through these adapters)."""
    rows = await conn.fetch(
        """
        SELECT output_kind, design_input_source, primary_adapter_key, fallback_adapter_keys
          FROM output_surface_routes
         WHERE is_branded = true
        """
    )
    degraded_kinds_per_role: dict[str, set[str]] = {}
    for r in rows:
        if r["primary_adapter_key"] in _DEGRADED_ADAPTER_KEYS:
            # The render step carries the kind-specific role; Paul
            # is universal across all chains. Mark these as Paul's
            # degraded surfaces + the render role's degraded surfaces.
            ok = r["output_kind"]
            design = r["design_input_source"]
            label = ok if not design else f"{ok}+{design}"
            degraded_kinds_per_role.setdefault("paul_tier_2", set()).add(label)
            # Map render role from the chain spec (mirrors CAP-C):
            # html → hank_tier_2; pptx/pdf → tom_tier_2; docx/md → sop_master_tier_2
            if ok in ("pptx", "pdf"):
                render_role = "tom_tier_2"
            elif ok == "html":
                render_role = "hank_tier_2"
            elif ok in ("docx", "md"):
                render_role = "sop_master_tier_2"
            else:
                continue
            degraded_kinds_per_role.setdefault(render_role, set()).add(label)
    return {k: sorted(v) for k, v in degraded_kinds_per_role.items()}


_INVOCATION_EVENT_PATTERNS: dict[str, dict[str, list[str]]] = {
    # role_key → {kind: [event substrings]}
    # invoked = any audit event tied to this role
    # success / failure = subset for known terminal markers
    "darla_tier_2": {
        "invoked": ["darla.qa_passed", "darla.qa_needs_revision", "darla.qa_blocked"],
        "success": ["darla.qa_passed"],
        "failure": ["darla.qa_blocked"],
    },
    "paul_tier_2": {
        "invoked": ["paul.delivery_decided"],
        "success": ["paul.delivery_decided"],
        "failure": ["paul.fallback_adapter_invoked"],
    },
}


async def _load_recent_invocation_rollup(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    role_key: str,
) -> dict[str, Optional[str]]:
    """Lookup last_invoked_at / last_success_at / last_failure_at for
    a role from action_audit_log. Returns None for roles whose audit
    surface isn't directly traceable (Mark/Tom/Hank/SOP_Master fire
    via generic Tier-2 invocations that don't carry per-role audit
    events — only Paul + Darla + Aiden have role-distinct events
    today)."""
    patterns = _INVOCATION_EVENT_PATTERNS.get(role_key)
    if patterns is None:
        return {
            "last_invoked_at": None,
            "last_success_at": None,
            "last_failure_at": None,
        }

    async def _max_for_events(events: list[str]) -> Optional[datetime]:
        if not events:
            return None
        return await conn.fetchval(
            """
            SELECT max(created_at)
              FROM action_audit_log
             WHERE client_id = $1::uuid
               AND action = ANY($2::text[])
            """,
            client_id,
            events,
        )

    return {
        "last_invoked_at": _coerce_iso(await _max_for_events(patterns.get("invoked", []))),
        "last_success_at": _coerce_iso(await _max_for_events(patterns.get("success", []))),
        "last_failure_at": _coerce_iso(await _max_for_events(patterns.get("failure", []))),
    }


def _classify_degraded(
    role_key: str,
    surfaces_for_role: list[str],
    degraded_surfaces_for_role: list[str],
) -> tuple[bool, Optional[str]]:
    """A role is `degraded` if AT LEAST ONE of its branded-chain
    surfaces routes through a degraded primary adapter. Returns
    (is_degraded, human_readable_reason)."""
    if not degraded_surfaces_for_role:
        return (False, None)
    reason = (
        f"{len(degraded_surfaces_for_role)} of {len(surfaces_for_role) or '?'} "
        f"surfaces route through adapter_unavailable stubs: "
        f"{', '.join(degraded_surfaces_for_role)}"
    )
    return (True, reason)


async def build_sub_agent_wiring_status(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    baseline_commit: str = "runtime",
) -> dict[str, Any]:
    """Build the live wiring/status matrix per spec. Computed from
    runtime truth (llm_configs / KNOWN_TIER_2_ROLES /
    workflow_template_steps / output_surface_routes / audit log) —
    no hand-maintained config."""
    enabled_map = await _load_llm_config_enabled(conn, client_id=client_id)
    workflow_roles, branded_chain_roles = await _load_workflow_step_role_usage(
        conn, client_id=client_id
    )
    surface_coverage = await _load_surface_coverage(conn)
    degraded_per_role = await _load_degraded_surfaces_from_routes(conn)

    roles_out: list[dict[str, Any]] = []
    for role_key in _CANONICAL_ROLE_KEYS:
        # `direct_work_order_path` — only Tier-2 KNOWN roles are
        # directly assignable on Aiden's work_order_brief path.
        # Aiden + PM are always on direct path conceptually (they're
        # the orchestrators).
        direct = role_key in KNOWN_TIER_2_ROLES or role_key in {
            "aiden_tier_1",
            "pm_tier_15",
        }
        in_workflow = role_key in workflow_roles
        in_branded = role_key in branded_chain_roles
        surfaces = surface_coverage.get(role_key, [])
        degraded_surfaces = degraded_per_role.get(role_key, [])
        degraded, degraded_reason = _classify_degraded(
            role_key, surfaces, degraded_surfaces
        )
        rollup = await _load_recent_invocation_rollup(
            conn, client_id=client_id, role_key=role_key
        )

        roles_out.append(
            {
                "role_key": role_key,
                "display_name": _DISPLAY_NAMES.get(role_key, role_key),
                "layer": _LAYER.get(role_key, "unknown"),
                "llm_enabled": enabled_map.get(role_key, False),
                "direct_work_order_path": direct,
                "workflow_path": in_workflow,
                "branded_chain_path": in_branded,
                "surfaces": surfaces,
                "degraded": degraded,
                "degraded_reason": degraded_reason,
                "last_invoked_at": rollup["last_invoked_at"],
                "last_success_at": rollup["last_success_at"],
                "last_failure_at": rollup["last_failure_at"],
            }
        )

    summary = {
        "tier_1_live": enabled_map.get("aiden_tier_1", False),
        "pm_live": enabled_map.get("pm_tier_15", False),
        "tier_2_direct_roles": sum(
            1
            for r in roles_out
            if r["layer"] == "tier_2" and r["direct_work_order_path"]
        ),
        "tier_2_branded_chain_roles": sum(
            1
            for r in roles_out
            if r["layer"] == "tier_2" and r["branded_chain_path"]
        ),
        "degraded_roles": sum(1 for r in roles_out if r["degraded"]),
        "legacy_seed_labels_excluded": sorted(_LEGACY_SEED_LABELS),
    }

    return {
        "baseline_commit": baseline_commit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tenant_id": client_id,
        "summary": summary,
        "roles": roles_out,
    }

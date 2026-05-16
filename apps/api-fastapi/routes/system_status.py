"""Loop CAP-G CLOSEOUT Slice C — system status routes.

  GET /system/sub-agent-wiring-status
       Returns the live wiring/status matrix for the active tenant
       per IWO3_SUBAGENT_WIRING_MATRIX_AND_STATUS_SURFACE_v0.1.0.
       Computed from runtime truth (llm_configs / KNOWN_TIER_2_ROLES /
       workflow_template_steps / output_surface_routes / audit log).
       No hand-maintained config.

Tenant scoping enforced via the standard `get_tenant_scoped_connection`
dependency. Role-key vocabulary excludes legacy seed labels (`mark`,
`pm_alpha`, `agent_system`) per spec — only canonical *_tier_2 / tier_1
/ tier_1_5 forms appear in the response.
"""

from __future__ import annotations

from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends

from deps import current_user_context, get_tenant_scoped_connection
from runtime.subagent_wiring import build_sub_agent_wiring_status


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/sub-agent-wiring-status")
async def sub_agent_wiring_status(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> dict[str, Any]:
    """Live sub-agent wiring + degraded-surface matrix for the
    active tenant. See `runtime/subagent_wiring.py` for the
    computation contract."""
    return await build_sub_agent_wiring_status(
        conn,
        client_id=ctx["client_id"],
    )

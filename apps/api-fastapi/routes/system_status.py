"""Loop CAP-G CLOSEOUT Slice C — system status routes.

  GET /system/sub-agent-wiring-status
       Returns the live wiring/status matrix for the active tenant
       per IWO3_SUBAGENT_WIRING_MATRIX_AND_STATUS_SURFACE_v0.1.0.
       Computed from runtime truth (llm_configs / KNOWN_TIER_2_ROLES /
       workflow_template_steps / output_surface_routes / audit log).
       No hand-maintained config.

  GET /system/checks
       Aggregator that rolls up the five IWO2-parity health checks
       (api / database / llm_provider / gamma / session_auth) into
       one tenant-scoped boolean matrix for the System Health page.
       Each check is honest about what passing means — see field
       comments below.

Tenant scoping enforced via the standard `get_tenant_scoped_connection`
dependency. Role-key vocabulary excludes legacy seed labels (`mark`,
`pm_alpha`, `agent_system`) per spec — only canonical *_tier_2 / tier_1
/ tier_1_5 forms appear in the response.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from deps import current_user_context, get_tenant_scoped_connection
from llm.credentials import env_var_from_credential_ref
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


class SystemCheck(BaseModel):
    name: str           # machine key, e.g. "database"
    label: str          # human label, e.g. "Database Connection"
    passed: bool
    detail: Optional[str] = None  # short reason on failure or context note


class SystemChecksResponse(BaseModel):
    checks: list[SystemCheck]
    generated_at: str
    all_passed: bool


@router.get("/checks", response_model=SystemChecksResponse)
async def system_checks(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
) -> SystemChecksResponse:
    """IWO2-parity rollup of the five System Health checks. Each check
    is tenant-scoped where it makes sense (llm + gamma) and global
    otherwise (api + database + session_auth)."""
    checks: list[SystemCheck] = []

    # 1. API Endpoint — the request reached us, so the API is up.
    checks.append(
        SystemCheck(name="api", label="API Endpoint", passed=True)
    )

    # 2. Database — SELECT 1 against the tenant-scoped pool.
    try:
        row = await conn.fetchrow("SELECT 1 AS ok")
        db_ok = bool(row and row["ok"] == 1)
        checks.append(
            SystemCheck(
                name="database",
                label="Database Connection",
                passed=db_ok,
                detail=None if db_ok else "SELECT 1 returned no row",
            )
        )
    except Exception as err:  # noqa: BLE001
        checks.append(
            SystemCheck(
                name="database",
                label="Database Connection",
                passed=False,
                detail=str(err)[:120],
            )
        )

    # 3. LLM Provider — at least one llm_config for this tenant
    # resolves a credential env var that is currently set.
    rows = await conn.fetch(
        """
        SELECT credential_ref
          FROM llm_configs
         WHERE client_id = $1 AND enabled = true
        """,
        ctx["client_id"],
    )
    llm_ok = False
    llm_total = len(rows)
    llm_resolvable = 0
    for r in rows:
        env_name = env_var_from_credential_ref(r["credential_ref"] or "")
        if env_name and os.environ.get(env_name):
            llm_resolvable += 1
            llm_ok = True
    if llm_total == 0:
        llm_detail = "no LLM configs for this tenant"
    elif llm_ok:
        llm_detail = f"{llm_resolvable}/{llm_total} configs have credentials present"
    else:
        llm_detail = f"0/{llm_total} configs resolve a present credential"
    checks.append(
        SystemCheck(
            name="llm",
            label="LLM Provider",
            passed=llm_ok,
            detail=llm_detail,
        )
    )

    # 4. Gamma — env flag enabled AND a credential row exists for
    # this tenant. Mirrors the dual-gate contract on /adapter_status/gamma.
    gamma_env = os.environ.get("GAMMA_LIVE_ENABLED", "") == "true"
    # The row's credential_ref is RESOLVED, not merely counted. This
    # check previously ran `SELECT 1` and reported "live gate +
    # credential row present" — which stayed green for months while
    # Klear's row pointed at GAMMA_REGISTRY_TEST_KEY, an env var set
    # nowhere, and every render failed with `credential_missing`. A
    # health check that proves a row exists proves nothing about
    # whether the render will work.
    gamma_row = await conn.fetchrow(
        """
        SELECT ac.credential_ref
          FROM adapter_credentials ac
          JOIN adapter_catalog cat ON cat.id = ac.adapter_catalog_id
         WHERE ac.client_id = $1 AND cat.adapter_key = 'gamma'
         LIMIT 1
        """,
        ctx["client_id"],
    )
    gamma_cred = bool(gamma_row)
    gamma_env_name = (
        env_var_from_credential_ref(gamma_row["credential_ref"])
        if gamma_cred
        else None
    )
    gamma_secret_set = bool(
        gamma_env_name and os.environ.get(gamma_env_name, "").strip()
    )
    gamma_ok = gamma_env and gamma_cred and gamma_secret_set
    if not gamma_env:
        gamma_detail = "GAMMA_LIVE_ENABLED env flag not set"
    elif not gamma_cred:
        gamma_detail = "no adapter_credentials row for this tenant"
    elif not gamma_env_name:
        gamma_detail = (
            "credential_ref is malformed "
            f"({gamma_row['credential_ref']!r}) — expected "
            "credential_ref:env:NAME"
        )
    elif not gamma_secret_set:
        gamma_detail = (
            f"credential points at env var {gamma_env_name}, which is not "
            "set or is empty — renders will fail with credential_missing"
        )
    else:
        gamma_detail = f"live gate + {gamma_env_name} resolved"
    checks.append(
        SystemCheck(
            name="gamma",
            label="Gamma API",
            passed=gamma_ok,
            detail=gamma_detail,
        )
    )

    # 5. Session / Auth — JWT signing key present and >=32 bytes.
    # Mirrors auth.jwt_tokens._resolve_signing_key contract.
    jwt_key = os.environ.get("IWO3_JWT_SIGNING_KEY", "") or ""
    session_ok = len(jwt_key.encode("utf-8")) >= 32
    if not jwt_key:
        session_detail = "IWO3_JWT_SIGNING_KEY env not set"
    elif not session_ok:
        session_detail = (
            f"IWO3_JWT_SIGNING_KEY only {len(jwt_key)} bytes; >=32 required"
        )
    else:
        session_detail = "signing key present"
    checks.append(
        SystemCheck(
            name="session_auth",
            label="Session / Auth",
            passed=session_ok,
            detail=session_detail,
        )
    )

    return SystemChecksResponse(
        checks=checks,
        generated_at=datetime.now(timezone.utc).isoformat(),
        all_passed=all(c.passed for c in checks),
    )

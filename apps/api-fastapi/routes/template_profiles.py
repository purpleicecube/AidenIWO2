"""Beta-2 phase 0.1 — tenant-scoped template_profiles read.

  GET /template_profiles?status=published&output_kind=pptx_deck

The Submit Order form populates its `template_profile` selector from
this endpoint instead of hardcoding template ids. RLS scopes the read
to the active tenant transparently.

Read-only. Mutations land in a future phase if/when operator-side
template authoring is in scope.
"""

from __future__ import annotations

from typing import Annotated, Optional

import asyncpg
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel

from deps import (
    current_user_context,
    get_tenant_scoped_connection,
    require_permission_dep,
)


router = APIRouter(prefix="/template_profiles", tags=["template_profiles"])


class TemplateProfileRow(BaseModel):
    id: str
    client_id: str
    profile_key: str
    output_kind: str
    engine: str
    external_ref: Optional[str] = None
    fidelity_required: bool
    fallback_policy: str
    status: str


class ListTemplateProfilesResponse(BaseModel):
    template_profiles: list[TemplateProfileRow]


@router.get(
    "",
    response_model=ListTemplateProfilesResponse,
    dependencies=[Depends(require_permission_dep("template_profile:read"))],
    status_code=status.HTTP_200_OK,
)
async def list_template_profiles(
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[
        asyncpg.Connection, Depends(get_tenant_scoped_connection)
    ],
    status_filter: Annotated[
        Optional[str],
        Query(
            alias="status",
            description=(
                "Filter by template_profile_status (active / archived). "
                "Default: active only (the only kind operators can pick)."
            ),
        ),
    ] = "active",
    output_kind: Annotated[
        Optional[str],
        Query(
            description=(
                "Filter by output_kind (e.g. pptx_deck, pdf_doc). "
                "Optional — omit to list all kinds for the tenant."
            ),
        ),
    ] = None,
) -> ListTemplateProfilesResponse:
    rows = await conn.fetch(
        """
        SELECT id::text                AS id,
               client_id::text         AS client_id,
               profile_key             AS profile_key,
               output_kind::text       AS output_kind,
               engine::text            AS engine,
               external_ref            AS external_ref,
               fidelity_required       AS fidelity_required,
               fallback_policy::text   AS fallback_policy,
               status::text            AS status
          FROM template_profiles
         WHERE ($1::text IS NULL OR status::text = $1::text)
           AND ($2::text IS NULL OR output_kind::text = $2::text)
         ORDER BY output_kind::text, profile_key
        """,
        status_filter,
        output_kind,
    )
    return ListTemplateProfilesResponse(
        template_profiles=[TemplateProfileRow(**dict(r)) for r in rows]
    )

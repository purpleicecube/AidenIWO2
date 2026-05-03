"""MegaLoop Theta — Tools Locker write-side + skills + MCP test routes.

Ports the IWO2 `/api/tools` surface into IWO3 with the architectural
adaptations documented in
`WS024_IWO3[Branch]/05_Artifacts/IWO3_MEGALOOP_THETA_TOOLS_LOCKER_SCOPE_v0.1.0.md`.

Two routers exposed:
  - ``tool_catalog_write_router`` (prefix ``/tool_catalog``) — POST,
    PUT, DELETE on the catalog plus ``/import_skill`` and
    ``/mcp/test_connection``.
  - ``skills_router`` (prefix ``/skills``) — GET ``/available`` for the
    Import Skills modal's filesystem scan.

Read-side ``GET /tool_catalog`` lives in routes/llm.py and remains the
canonical list endpoint; this module's writes share the same
ToolCatalogRow shape so callers can reuse the model.

RBAC:
  - tool_catalog:create        POST   /tool_catalog
  - tool_catalog:update        PUT    /tool_catalog/{tool_key}
  - tool_catalog:delete        DELETE /tool_catalog/{tool_key}
  - tool_catalog:import_skill  POST   /tool_catalog/import_skill
                               GET    /skills/available
  - tool_catalog:test_mcp      POST   /tool_catalog/mcp/test_connection

Audit:
  - tool_catalog.created
  - tool_catalog.updated   (Loop Eta vocabulary, reused on PUT)
  - tool_catalog.deleted
  - tool_catalog.skill_imported
  - tool_catalog.mcp_tested

Skills directory:
  - Defaults to ``{repo_root}/.local/skills/`` (matches IWO2). Override
    via ``IWO3_SKILLS_DIR`` env. Path-traversal guard on every read.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Annotated, Any, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, status
from pydantic import BaseModel, Field, field_validator

from authz.audit_writer import write_audit_row
from contracts.enums import (
    TOOL_ACCESS_TIER,
    TOOL_CATEGORY,
    TOOL_DEFAULT_TIER,
    TOOL_RUNTIME_STATUS,
    TOOL_TYPE,
)
from deps import (
    current_user_context,
    get_db_connection,
    require_permission_dep,
)
from runtime.mcp_client import McpClientError, McpSession


tool_catalog_write_router = APIRouter(
    prefix="/tool_catalog", tags=["tool_catalog"]
)
skills_router = APIRouter(prefix="/skills", tags=["tool_catalog"])


# ── Constants ────────────────────────────────────────────────────────


# Repository root one level above apps/api-fastapi/.
_REPO_ROOT = Path(__file__).resolve().parents[3]


def _skills_dir() -> Path:
    """Resolve the skills directory at request time.

    Honours `IWO3_SKILLS_DIR` env override; otherwise defaults to
    `{repo_root}/.local/skills/`. Per scope §D4 the directory is
    filesystem-only for v1.
    """
    override = os.environ.get("IWO3_SKILLS_DIR")
    if override:
        return Path(override).resolve()
    return (_REPO_ROOT / ".local" / "skills").resolve()


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DIRNAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_TOOL_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_MAX_SKILL_BODY = 200_000  # bytes — guard against blow-up on deep references trees


# ── Models ───────────────────────────────────────────────────────────


class CreateToolRequest(BaseModel):
    """Body for POST /tool_catalog. Mirrors IWO2's `insertToolSchema`
    with IWO3-native field names. All fields except `tool_key`,
    `display_name`, `description`, `category`, `runtime_status`,
    `default_tier`, and `tool_type` are optional.
    """

    tool_key: str = Field(..., min_length=2, max_length=96)
    display_name: str = Field(..., min_length=1, max_length=160)
    description: str = Field(..., min_length=1)
    category: str
    runtime_status: str
    default_tier: str
    tool_type: str
    iwo2_origin: Optional[str] = Field(None, max_length=96)
    handler_ref: Optional[str] = Field(None, max_length=256)
    args_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    notes: Optional[str] = None
    version_label: str = "1.0.0"
    execution_mode: str = "prompt_injection"
    skill_content: Optional[str] = None
    skill_instructions: Optional[str] = None
    trigger_conditions: list[dict[str, Any]] = Field(default_factory=list)
    source_code: Optional[str] = None
    entry_point: Optional[str] = Field(None, max_length=256)
    runtime_environment: Optional[str] = Field(None, max_length=64)
    sandbox_config: dict[str, Any] = Field(default_factory=dict)
    mcp_config: dict[str, Any] = Field(default_factory=dict)
    credentials: list[dict[str, Any]] = Field(default_factory=list)
    usage_instructions: Optional[str] = None
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    access_tier: str = "any"
    max_concurrent: int = 0
    default_lease_seconds: int = 300
    max_lease_seconds: int = 3600
    daily_usage_limit: Optional[int] = None
    cost_ceiling_per_day: Optional[str] = None
    requires_approval: bool = False
    restricted: bool = False
    restricted_reason: Optional[str] = None

    @field_validator("tool_key")
    @classmethod
    def _validate_tool_key(cls, v: str) -> str:
        if not _TOOL_KEY_RE.match(v):
            raise ValueError(
                "tool_key must be lowercase letters, digits, underscore, "
                "hyphen; first char must be a letter or digit"
            )
        return v

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        if v not in TOOL_CATEGORY:
            raise ValueError(
                f"category must be one of {TOOL_CATEGORY}, got {v!r}"
            )
        return v

    @field_validator("runtime_status")
    @classmethod
    def _validate_runtime_status(cls, v: str) -> str:
        if v not in TOOL_RUNTIME_STATUS:
            raise ValueError(
                f"runtime_status must be one of {TOOL_RUNTIME_STATUS}, got {v!r}"
            )
        return v

    @field_validator("default_tier")
    @classmethod
    def _validate_default_tier(cls, v: str) -> str:
        if v not in TOOL_DEFAULT_TIER:
            raise ValueError(
                f"default_tier must be one of {TOOL_DEFAULT_TIER}, got {v!r}"
            )
        return v

    @field_validator("tool_type")
    @classmethod
    def _validate_tool_type(cls, v: str) -> str:
        if v not in TOOL_TYPE:
            raise ValueError(
                f"tool_type must be one of {TOOL_TYPE}, got {v!r}"
            )
        return v

    @field_validator("access_tier")
    @classmethod
    def _validate_access_tier(cls, v: str) -> str:
        if v not in TOOL_ACCESS_TIER:
            raise ValueError(
                f"access_tier must be one of {TOOL_ACCESS_TIER}, got {v!r}"
            )
        return v


class UpdateToolRequest(BaseModel):
    """Body for PUT /tool_catalog/{tool_key}. Every field optional;
    omitted fields preserve the current value. tool_key itself is
    immutable (URL slug)."""

    display_name: Optional[str] = Field(None, min_length=1, max_length=160)
    description: Optional[str] = None
    category: Optional[str] = None
    runtime_status: Optional[str] = None
    default_tier: Optional[str] = None
    tool_type: Optional[str] = None
    iwo2_origin: Optional[str] = None
    handler_ref: Optional[str] = None
    args_schema: Optional[dict[str, Any]] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None
    version_label: Optional[str] = None
    execution_mode: Optional[str] = None
    skill_content: Optional[str] = None
    skill_instructions: Optional[str] = None
    trigger_conditions: Optional[list[dict[str, Any]]] = None
    source_code: Optional[str] = None
    entry_point: Optional[str] = None
    runtime_environment: Optional[str] = None
    sandbox_config: Optional[dict[str, Any]] = None
    mcp_config: Optional[dict[str, Any]] = None
    credentials: Optional[list[dict[str, Any]]] = None
    usage_instructions: Optional[str] = None
    input_schema: Optional[dict[str, Any]] = None
    output_schema: Optional[dict[str, Any]] = None
    access_tier: Optional[str] = None
    max_concurrent: Optional[int] = None
    default_lease_seconds: Optional[int] = None
    max_lease_seconds: Optional[int] = None
    daily_usage_limit: Optional[int] = None
    cost_ceiling_per_day: Optional[str] = None
    requires_approval: Optional[bool] = None
    restricted: Optional[bool] = None
    restricted_reason: Optional[str] = None


class ImportSkillRequest(BaseModel):
    dir_name: str = Field(..., min_length=1, max_length=128)
    name_override: Optional[str] = Field(None, max_length=160)
    description_override: Optional[str] = None

    @field_validator("dir_name")
    @classmethod
    def _validate_dir_name(cls, v: str) -> str:
        # Reject path-traversal + absolute paths + slashes upfront. The
        # backend re-validates with realpath() against the skills dir
        # but this is the operator-friendly first gate.
        if "/" in v or "\\" in v or ".." in v:
            raise ValueError("dir_name must not contain slashes or '..'")
        if not _DIRNAME_RE.match(v):
            raise ValueError(
                "dir_name must be alphanumeric / underscore / hyphen only"
            )
        return v


class McpTestRequest(BaseModel):
    """Body for POST /tool_catalog/mcp/test_connection. Mirrors the
    IWO2 endpoint at /api/locker/mcp/test."""

    mcp_config: dict[str, Any]


class TestMcpResponse(BaseModel):
    ok: bool
    server_name: Optional[str] = None
    transport: Optional[str] = None
    tool_count: Optional[int] = None
    tool_names: list[str] = []
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    kind: Optional[str] = None


class AvailableSkill(BaseModel):
    dir_name: str
    name: str
    slug: str
    description: str
    category: str = "general"
    already_imported: bool = False
    has_references: bool = False
    reference_files: list[str] = []
    file_count: int = 0


class ListAvailableSkillsResponse(BaseModel):
    skills_dir: str
    skills: list[AvailableSkill]


# ── Helpers ──────────────────────────────────────────────────────────


def _jsonb_or_default(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Mirror of routes.llm._jsonb hydration so create/update returns
    the same shape as GET /tool_catalog."""
    d = dict(row)
    for jsonb_field, default in (
        ("args_schema", {}),
        ("trigger_conditions", []),
        ("sandbox_config", {}),
        ("mcp_config", {}),
        ("credentials", []),
        ("input_schema", {}),
        ("output_schema", {}),
    ):
        d[jsonb_field] = _jsonb_or_default(d.get(jsonb_field), default)
    if d.get("created_at") is not None and not isinstance(d["created_at"], str):
        d["created_at"] = str(d["created_at"])
    if d.get("updated_at") is not None and not isinstance(d["updated_at"], str):
        d["updated_at"] = str(d["updated_at"])
    return d


_TOOL_CATALOG_SELECT = """
    SELECT tool_key,
           display_name,
           description,
           category::text       AS category,
           runtime_status::text AS runtime_status,
           args_schema,
           handler_ref,
           default_tier::text   AS default_tier,
           iwo2_origin,
           enabled,
           tool_type::text      AS tool_type,
           version_label,
           execution_mode,
           skill_content,
           skill_instructions,
           trigger_conditions,
           source_code,
           entry_point,
           runtime_environment,
           sandbox_config,
           mcp_config,
           credentials,
           usage_instructions,
           input_schema,
           output_schema,
           access_tier::text    AS access_tier,
           max_concurrent,
           default_lease_seconds,
           max_lease_seconds,
           daily_usage_limit,
           cost_ceiling_per_day,
           requires_approval,
           restricted,
           restricted_reason,
           restricted_by_user_id::text AS restricted_by_user_id,
           notes,
           created_at::text     AS created_at,
           updated_at::text     AS updated_at
"""


# ── POST /tool_catalog (create) ──────────────────────────────────────


@tool_catalog_write_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission_dep("tool_catalog:create"))],
)
async def create_tool(
    body: CreateToolRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> dict[str, Any]:
    # Reject duplicate tool_key with a clean 409 instead of the
    # asyncpg 23505 leak.
    existing = await conn.fetchval(
        "SELECT 1 FROM tool_catalog WHERE tool_key = $1",
        body.tool_key,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "duplicate_tool_key", "tool_key": body.tool_key},
        )

    new_id = str(uuid.uuid4())
    row = await conn.fetchrow(
        f"""
        INSERT INTO tool_catalog
          (id, tool_key, display_name, description, category, runtime_status,
           args_schema, handler_ref, default_tier, iwo2_origin, enabled,
           notes, tool_type, version_label, execution_mode,
           skill_content, skill_instructions, trigger_conditions,
           source_code, entry_point, runtime_environment, sandbox_config,
           mcp_config, credentials, usage_instructions,
           input_schema, output_schema, access_tier, max_concurrent,
           default_lease_seconds, max_lease_seconds, daily_usage_limit,
           cost_ceiling_per_day, requires_approval, restricted,
           restricted_reason)
        VALUES
          ($1::uuid, $2, $3, $4, $5::tool_category, $6::tool_runtime_status,
           $7::jsonb, $8, $9::tool_default_tier, $10, $11,
           $12, $13::tool_type, $14, $15,
           $16, $17, $18::jsonb,
           $19, $20, $21, $22::jsonb,
           $23::jsonb, $24::jsonb, $25,
           $26::jsonb, $27::jsonb, $28::tool_access_tier, $29,
           $30, $31, $32,
           $33, $34, $35,
           $36)
        RETURNING {_TOOL_CATALOG_SELECT.strip()[7:]}  -- strip leading SELECT
        """.replace("RETURNING SELECT", "RETURNING"),
        new_id,
        body.tool_key,
        body.display_name,
        body.description,
        body.category,
        body.runtime_status,
        json.dumps(body.args_schema),
        body.handler_ref,
        body.default_tier,
        body.iwo2_origin,
        body.enabled,
        body.notes,
        body.tool_type,
        body.version_label,
        body.execution_mode,
        body.skill_content,
        body.skill_instructions,
        json.dumps(body.trigger_conditions),
        body.source_code,
        body.entry_point,
        body.runtime_environment,
        json.dumps(body.sandbox_config),
        json.dumps(body.mcp_config),
        json.dumps(body.credentials),
        body.usage_instructions,
        json.dumps(body.input_schema),
        json.dumps(body.output_schema),
        body.access_tier,
        body.max_concurrent,
        body.default_lease_seconds,
        body.max_lease_seconds,
        body.daily_usage_limit,
        body.cost_ceiling_per_day,
        body.requires_approval,
        body.restricted,
        body.restricted_reason,
    )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="tool_catalog.created",
        target_type="tool_catalog",
        target_id=new_id,
        metadata={
            "tool_key": body.tool_key,
            "tool_type": body.tool_type,
            "category": body.category,
            "runtime_status": body.runtime_status,
            "default_tier": body.default_tier,
        },
    )
    return _row_to_dict(row)


# ── PUT /tool_catalog/{tool_key} (update) ────────────────────────────


@tool_catalog_write_router.put(
    "/{tool_key}",
    dependencies=[Depends(require_permission_dep("tool_catalog:update"))],
)
async def update_tool(
    tool_key: Annotated[
        str, PathParam(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=96)
    ],
    body: UpdateToolRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> dict[str, Any]:
    existing = await conn.fetchrow(
        "SELECT id::text AS id FROM tool_catalog WHERE tool_key = $1",
        tool_key,
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "tool_not_found", "tool_key": tool_key},
        )

    # Build the UPDATE SET dynamically from the non-None body fields.
    set_clauses: list[str] = []
    args: list[Any] = [tool_key]
    changed: dict[str, Any] = {}

    def add(field: str, value: Any, cast: Optional[str] = None) -> None:
        args.append(value)
        idx = len(args)
        casted = f"${idx}::{cast}" if cast else f"${idx}"
        set_clauses.append(f'"{field}" = {casted}')
        changed[field] = value

    enum_fields: dict[str, Optional[tuple[str, str]]] = {
        "category": ("tool_category", str(TOOL_CATEGORY)),
        "runtime_status": ("tool_runtime_status", str(TOOL_RUNTIME_STATUS)),
        "default_tier": ("tool_default_tier", str(TOOL_DEFAULT_TIER)),
        "tool_type": ("tool_type", str(TOOL_TYPE)),
        "access_tier": ("tool_access_tier", str(TOOL_ACCESS_TIER)),
    }
    enum_membership: dict[str, tuple[str, ...]] = {
        "category": TOOL_CATEGORY,
        "runtime_status": TOOL_RUNTIME_STATUS,
        "default_tier": TOOL_DEFAULT_TIER,
        "tool_type": TOOL_TYPE,
        "access_tier": TOOL_ACCESS_TIER,
    }
    jsonb_fields = {
        "args_schema",
        "trigger_conditions",
        "sandbox_config",
        "mcp_config",
        "credentials",
        "input_schema",
        "output_schema",
    }
    plain_fields = [
        "display_name", "description", "iwo2_origin", "handler_ref",
        "enabled", "notes", "version_label", "execution_mode",
        "skill_content", "skill_instructions", "source_code", "entry_point",
        "runtime_environment", "usage_instructions", "max_concurrent",
        "default_lease_seconds", "max_lease_seconds", "daily_usage_limit",
        "cost_ceiling_per_day", "requires_approval", "restricted",
        "restricted_reason",
    ]
    body_dump = body.model_dump(exclude_unset=True)
    for field in plain_fields:
        if field in body_dump:
            add(field, body_dump[field])
    for field in jsonb_fields:
        if field in body_dump:
            add(field, json.dumps(body_dump[field]), cast="jsonb")
    for field, cast_info in enum_fields.items():
        if field in body_dump:
            value = body_dump[field]
            allowed = enum_membership[field]
            if value not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": f"invalid_{field}",
                        "value": value,
                        "allowed": list(allowed),
                    },
                )
            add(field, value, cast=cast_info[0] if cast_info else None)

    if not set_clauses:
        # Nothing to update — return the existing row.
        row = await conn.fetchrow(
            f"{_TOOL_CATALOG_SELECT} FROM tool_catalog WHERE tool_key = $1",
            tool_key,
        )
        return _row_to_dict(row)

    set_clauses.append('"updated_at" = now()')
    sql = (
        f"UPDATE tool_catalog SET {', '.join(set_clauses)} "
        f"WHERE tool_key = $1 "
        f"RETURNING {_TOOL_CATALOG_SELECT.strip()[7:]}"
    ).replace("RETURNING SELECT", "RETURNING")
    row = await conn.fetchrow(sql, *args)

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="tool_catalog.updated",
        target_type="tool_catalog",
        target_id=existing["id"],
        metadata={
            "tool_key": tool_key,
            "changedFields": sorted(changed.keys()),
        },
    )
    return _row_to_dict(row)


# ── DELETE /tool_catalog/{tool_key} ─────────────────────────────────


@tool_catalog_write_router.delete(
    "/{tool_key}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission_dep("tool_catalog:delete"))],
)
async def delete_tool(
    tool_key: Annotated[
        str, PathParam(pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=96)
    ],
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> None:
    # Refuse to delete a tool that has any sub_agent_tools assignments.
    # Mirrors IWO2's RESTRICT FK behaviour but with a clean 409.
    in_use = await conn.fetchval(
        "SELECT count(*)::int FROM sub_agent_tools WHERE tool_key = $1",
        tool_key,
    )
    if in_use and int(in_use) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "tool_in_use",
                "tool_key": tool_key,
                "assignment_count": int(in_use),
                "hint": "revoke sub-agent assignments before deleting",
            },
        )

    existing = await conn.fetchrow(
        "SELECT id::text AS id FROM tool_catalog WHERE tool_key = $1",
        tool_key,
    )
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "tool_not_found", "tool_key": tool_key},
        )
    await conn.execute(
        "DELETE FROM tool_catalog WHERE tool_key = $1", tool_key
    )
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="tool_catalog.deleted",
        target_type="tool_catalog",
        target_id=existing["id"],
        metadata={"tool_key": tool_key},
    )


# ── GET /skills/available ───────────────────────────────────────────


_CATEGORY_HINTS: dict[str, str] = {
    "docx": "document",
    "pdf": "document",
    "pptx": "document",
    "xlsx": "document",
    "algorithmic-art": "creative",
    "canvas-design": "creative",
    "frontend-design": "creative",
    "brand-guidelines": "creative",
    "theme-factory": "creative",
    "slack-gif-creator": "creative",
    "klearai-pptx": "creative",
    "mcp-builder": "development",
    "webapp-testing": "development",
    "web-artifacts-builder": "development",
    "skill-creator": "development",
    "internal-comms": "productivity",
    "doc-coauthoring": "productivity",
}


def _parse_frontmatter(content: str, key: str) -> str:
    """Pull a single value out of a SKILL.md YAML frontmatter block.
    Tolerates quoted multi-line values; falls back to unquoted line."""
    fm_match = re.match(r"^---\s*\n([\s\S]*?)\n---", content)
    if fm_match is None:
        return ""
    fm = fm_match.group(1)
    quoted = re.search(rf'^{re.escape(key)}:\s*"([\s\S]*?)"', fm, re.MULTILINE)
    if quoted:
        return re.sub(r"\s+", " ", quoted.group(1)).strip()
    quoted = re.search(rf"^{re.escape(key)}:\s*'([\s\S]*?)'", fm, re.MULTILINE)
    if quoted:
        return re.sub(r"\s+", " ", quoted.group(1)).strip()
    line = re.search(rf"^{re.escape(key)}:\s*(.+)$", fm, re.MULTILINE)
    if line:
        return line.group(1).strip()
    return ""


def _safe_skill_dir(dir_name: str) -> Path:
    """Resolve a single skill directory under the skills root with
    full path-traversal protection."""
    root = _skills_dir()
    candidate = (root / dir_name).resolve()
    if not str(candidate).startswith(str(root) + os.sep):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "path_traversal_rejected",
                "dir_name": dir_name,
            },
        )
    if not candidate.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "skill_dir_not_found", "dir_name": dir_name},
        )
    return candidate


@skills_router.get(
    "/available",
    response_model=ListAvailableSkillsResponse,
    dependencies=[Depends(require_permission_dep("tool_catalog:import_skill"))],
)
async def list_available_skills(
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> ListAvailableSkillsResponse:
    root = _skills_dir()
    if not root.is_dir():
        return ListAvailableSkillsResponse(skills_dir=str(root), skills=[])

    rows = await conn.fetch("SELECT tool_key FROM tool_catalog")
    existing_slugs = {r["tool_key"] for r in rows}

    skills: list[AvailableSkill] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue
        try:
            content = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        name = _parse_frontmatter(content, "name") or entry.name
        description = _parse_frontmatter(content, "description")
        slug = f"skill-{re.sub(r'[^a-z0-9]+', '-', entry.name.lower()).strip('-')}"
        refs_dir = entry / "references"
        ref_files: list[str] = []
        if refs_dir.is_dir():
            ref_files = sorted(
                f.name for f in refs_dir.iterdir() if f.suffix == ".md"
            )
        category = _CATEGORY_HINTS.get(entry.name, "general")
        file_count = sum(1 for _ in entry.rglob("*") if _.is_file())

        skills.append(
            AvailableSkill(
                dir_name=entry.name,
                name=name,
                slug=slug,
                description=description,
                category=category,
                already_imported=slug in existing_slugs,
                has_references=len(ref_files) > 0,
                reference_files=ref_files,
                file_count=file_count,
            )
        )

    return ListAvailableSkillsResponse(skills_dir=str(root), skills=skills)


# ── POST /tool_catalog/import_skill ──────────────────────────────────


@tool_catalog_write_router.post(
    "/import_skill",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission_dep("tool_catalog:import_skill"))],
)
async def import_skill(
    body: ImportSkillRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> dict[str, Any]:
    skill_dir = _safe_skill_dir(body.dir_name)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "skill_md_missing", "dir_name": body.dir_name},
        )
    content = skill_md.read_text(encoding="utf-8", errors="replace")
    skill_name = (
        body.name_override
        or _parse_frontmatter(content, "name")
        or " ".join(
            w.capitalize() for w in re.split(r"[-_]", body.dir_name) if w
        )
    )
    description = (
        body.description_override
        or _parse_frontmatter(content, "description")
        or f"Imported skill: {body.dir_name}"
    )

    full_body = content
    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        for ref in sorted(refs_dir.iterdir()):
            if ref.suffix == ".md":
                full_body += (
                    f"\n\n---\n## Reference: {ref.name}\n"
                    + ref.read_text(encoding="utf-8", errors="replace")
                )
    for sibling in sorted(skill_dir.iterdir()):
        if (
            sibling.suffix == ".md"
            and sibling.name != "SKILL.md"
            and sibling.is_file()
        ):
            full_body += (
                f"\n\n---\n## Reference: {sibling.name}\n"
                + sibling.read_text(encoding="utf-8", errors="replace")
            )

    if len(full_body.encode("utf-8")) > _MAX_SKILL_BODY:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "skill_body_too_large",
                "size_bytes": len(full_body.encode("utf-8")),
                "max_bytes": _MAX_SKILL_BODY,
            },
        )

    slug = f"skill-{re.sub(r'[^a-z0-9]+', '-', body.dir_name.lower()).strip('-')}"
    existing = await conn.fetchval(
        "SELECT 1 FROM tool_catalog WHERE tool_key = $1", slug
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "skill_already_imported",
                "tool_key": slug,
                "dir_name": body.dir_name,
            },
        )

    new_id = str(uuid.uuid4())
    row = await conn.fetchrow(
        f"""
        INSERT INTO tool_catalog
          (id, tool_key, display_name, description, category, runtime_status,
           args_schema, default_tier, enabled,
           tool_type, version_label, execution_mode, skill_content,
           access_tier)
        VALUES
          ($1::uuid, $2, $3, $4, 'skill_only'::tool_category,
           'skill_only'::tool_runtime_status,
           '{{}}'::jsonb, 'either'::tool_default_tier, true,
           'skill'::tool_type, '1.0.0', 'prompt_injection', $5,
           'any'::tool_access_tier)
        RETURNING {_TOOL_CATALOG_SELECT.strip()[7:]}
        """.replace("RETURNING SELECT", "RETURNING"),
        new_id,
        slug,
        skill_name,
        description,
        full_body,
    )

    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="tool_catalog.skill_imported",
        target_type="tool_catalog",
        target_id=new_id,
        metadata={
            "dir_name": body.dir_name,
            "tool_key": slug,
            "skill_name": skill_name,
            "skill_body_bytes": len(full_body.encode("utf-8")),
        },
    )
    return _row_to_dict(row)


# ── POST /tool_catalog/mcp/test_connection ───────────────────────────


@tool_catalog_write_router.post(
    "/mcp/test_connection",
    response_model=TestMcpResponse,
    dependencies=[Depends(require_permission_dep("tool_catalog:test_mcp"))],
)
async def test_mcp_connection(
    body: McpTestRequest,
    ctx: Annotated[dict, Depends(current_user_context)],
    conn: Annotated[asyncpg.Connection, Depends(get_db_connection)],
) -> TestMcpResponse:
    """Open an ad-hoc MCP session against the supplied config, list its
    tools, return the result. Audits every call (success or failure)
    so an operator probing arbitrary stdio commands leaves a trail."""
    cfg = body.mcp_config or {}
    transport = cfg.get("transport") or "stdio"
    server_name = cfg.get("server_name") or cfg.get("serverName") or "ad-hoc"

    if transport not in {"stdio", "sse"}:
        return TestMcpResponse(
            ok=False,
            transport=transport,
            server_name=server_name,
            error=f"unsupported transport: {transport!r}",
            kind="config_invalid",
        )

    if transport == "sse":
        # SSE transport is documented in IWO2 but the McpSession SDK
        # wrapper currently only knows stdio. Surface a clear gap to
        # the operator instead of pretending to test.
        await write_audit_row(
            conn,
            client_id=ctx["client_id"],
            actor_user_id=ctx["user_id"],
            event="tool_catalog.mcp_tested",
            target_type="tool_catalog",
            target_id=None,
            metadata={
                "transport": transport,
                "server_name": server_name,
                "ok": False,
                "kind": "sse_not_implemented",
            },
        )
        return TestMcpResponse(
            ok=False,
            transport=transport,
            server_name=server_name,
            error=(
                "SSE transport is not yet wired in IWO3. Use stdio for "
                "MegaLoop Theta v1; SSE arrives in a future loop."
            ),
            kind="sse_not_implemented",
        )

    command = cfg.get("command") or ""
    args_field = cfg.get("args") or []
    if isinstance(args_field, str):
        args_list = [a for a in (s.strip() for s in args_field.split(",")) if a]
    else:
        args_list = [str(a) for a in args_field]
    env_field = cfg.get("env") or {}
    env_dict = {str(k): str(v) for k, v in env_field.items() if k}

    if not command:
        return TestMcpResponse(
            ok=False,
            transport=transport,
            server_name=server_name,
            error="command is required for stdio transport",
            kind="config_invalid",
        )

    started = time.monotonic()
    err_kind: Optional[str] = None
    err_detail: Optional[str] = None
    tool_count: Optional[int] = None
    tool_names: list[str] = []
    full_command = [command, *args_list]
    try:
        session = await McpSession.open(
            server_name=server_name,
            command=full_command,
            env=env_dict or None,
            timeout_s=15.0,
        )
        try:
            tools = await session.list_tools()
            tool_names = [
                str(t.get("name") if isinstance(t, dict) else getattr(t, "name", t))
                for t in tools
            ][:25]
            tool_count = len(tools)
        finally:
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                pass
    except McpClientError as exc:
        err_kind = exc.kind
        err_detail = str(exc)
    except asyncio.TimeoutError:
        err_kind = "timeout"
        err_detail = "MCP session start or list_tools exceeded 15s"
    except Exception as exc:  # noqa: BLE001
        err_kind = "unexpected"
        err_detail = f"{type(exc).__name__}: {exc}"
    latency_ms = int((time.monotonic() - started) * 1000)

    ok = err_kind is None
    await write_audit_row(
        conn,
        client_id=ctx["client_id"],
        actor_user_id=ctx["user_id"],
        event="tool_catalog.mcp_tested",
        target_type="tool_catalog",
        target_id=None,
        metadata={
            "transport": transport,
            "server_name": server_name,
            "command": command,
            "args": args_list,
            "ok": ok,
            "tool_count": tool_count,
            "latency_ms": latency_ms,
            "kind": err_kind,
            "detail": err_detail,
        },
    )

    return TestMcpResponse(
        ok=ok,
        transport=transport,
        server_name=server_name,
        tool_count=tool_count,
        tool_names=tool_names,
        latency_ms=latency_ms,
        error=err_detail,
        kind=err_kind,
    )

"""Loop CAP-F Φ.9 — sandbox (local) render adapters.

Five adapter dispatch helpers paralleling `dispatch_gamma_for_package`
for the local-render branded chains:

  dispatch_sandbox_pptx_for_package  — python-pptx; functional
  dispatch_sandbox_html_for_package  — f-string Jinja-free template; functional
  dispatch_sandbox_md_for_package    — stdlib markdown; functional
  dispatch_sandbox_pdf_for_package   — stub; emits adapter_unavailable
                                       until fpdf2 / weasyprint dep
                                       is provisioned
  dispatch_sandbox_docx_for_package  — stub; emits adapter_unavailable
                                       until python-docx dep is provisioned

Each dispatcher:
  1. Idempotency check (same as Gamma — refuses if non-terminal
     handoff already exists for the package).
  2. Loads the package + template_profile via
     `_load_package_and_template`.
  3. Loads tenant brand profile (palette/fonts) for styling.
  4. Renders the content_blocks to the target format using stdlib
     or the available dep.
  5. Writes the rendered bytes to a workspace artifact (under a
     `Branded Outputs/` folder), capturing the new artifact id as
     `external_reference`.
  6. Inserts an output_handoffs row with status='completed' (sandbox
     renders are synchronous — no polling needed) + writes
     `adapter_dispatch.submitted` audit.
  7. Returns a DispatchResult.

For adapter_unavailable stubs, the helper writes a `failed`
output_handoffs row with the `adapter_unavailable` kind in metadata
and raises DispatchError so the chain-runtime side can trigger Paul's
fallback path.

Architectural locks honored (per CAP v0.3.0):
  - P5     — adapter call wrapped by Paul (CAP-D) at the chain-step
             level (CAP-F wire-up pass in execute_step_run).
  - P8     — same dispatch shape as Gamma; no surface-specific
             shortcuts.
  - Firewall — caller (chain runtime / dispatch route) passes a
             tenant-scoped FastAPI conn; reads carry explicit
             `client_id` predicates.
"""

from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import asyncpg

from authz.audit_writer import write_audit_row

from .dispatch import (
    DispatchError,
    DispatchResult,
    _insert_handoff,
    _load_package_and_template,
    _resolve_adapter_catalog_id,
)


# ── Helpers shared across sandbox renderers ──────────────────────


async def _load_brand_palette_and_fonts(
    conn: asyncpg.Connection, *, client_id: str
) -> dict:
    """Return a small dict with `primary`, `secondary`, `accent`,
    `heading_font`, `body_font`. Defaults to plain monochrome /
    sans-serif when no brand profile exists."""
    row = await conn.fetchrow(
        """
        SELECT palette_json::text AS palette_json,
               fonts_json::text   AS fonts_json
        FROM client_brand_profiles
        WHERE client_id = $1::uuid
        """,
        client_id,
    )
    out = {
        "primary": "#000000",
        "secondary": "#333333",
        "accent": "#666666",
        "bg": "#FFFFFF",
        "heading_font": "Arial",
        "body_font": "Arial",
    }
    if row is None:
        return out
    palette: Any = {}
    fonts: Any = {}
    if row["palette_json"]:
        try:
            palette = json.loads(row["palette_json"])
        except (json.JSONDecodeError, ValueError):
            palette = {}
    if row["fonts_json"]:
        try:
            fonts = json.loads(row["fonts_json"])
        except (json.JSONDecodeError, ValueError):
            fonts = {}
    if isinstance(palette, dict):
        for k in ("primary", "secondary", "accent"):
            if k in palette:
                out[k] = palette[k]
        neutrals = palette.get("neutrals")
        if isinstance(neutrals, dict) and "bg" in neutrals:
            out["bg"] = neutrals["bg"]
    if isinstance(fonts, dict):
        if "heading" in fonts:
            out["heading_font"] = fonts["heading"]
        if "body" in fonts:
            out["body_font"] = fonts["body"]
    return out


def _extract_text_body(content_blocks: Any) -> str:
    """Pull the markdown body out of an output_package.content_blocks
    jsonb. Defensive parsing — content_blocks shape varies across
    Tier-2 sub-agents."""
    if isinstance(content_blocks, str):
        try:
            content_blocks = json.loads(content_blocks)
        except (json.JSONDecodeError, ValueError):
            return content_blocks or ""
    if not isinstance(content_blocks, dict):
        return ""
    for key in ("content_markdown", "markdown", "body", "text", "content"):
        v = content_blocks.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _idempotency_check_sync(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
):
    """Awaitable that raises DispatchError if a non-terminal handoff
    already exists. Same shape as dispatch_gamma_for_package."""
    return conn.fetchval(
        """
        SELECT id::text
          FROM output_handoffs
         WHERE output_package_id = $1::uuid
           AND client_id = $2::uuid
           AND status::text NOT IN ('failed', 'completed', 'cancelled')
         ORDER BY created_at DESC LIMIT 1
        """,
        output_package_id,
        client_id,
    )


async def _write_workspace_artifact(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    filename: str,
    extracted_text: str,
    metadata: dict,
    actor_user_id: Optional[str] = None,
) -> str:
    """Write a workspace artifact under the 'Branded Outputs/' folder
    (creating it if needed) and return the artifact id. The artifact
    row stores `extracted_text` (the rendered content as text);
    binary file bytes for PPTX/PDF are persisted in metadata under
    'rendered_bytes_base64' for downstream consumption (operator
    download)."""
    # workspace_folders.created_by_user_id is NOT NULL. Fall back to
    # the first active operator on the tenant when actor_user_id is
    # not supplied (e.g. async dispatch path). Matches the Lambda
    # D-L4 sentinel-resolution pattern.
    creator_id = actor_user_id
    if creator_id is None:
        creator_id = await conn.fetchval(
            """
            SELECT u.id::text
              FROM users u
              JOIN client_memberships m ON m.user_id = u.id
             WHERE m.client_id = $1::uuid
               AND m.status = 'active'
               AND u.status = 'active'
             ORDER BY u.created_at
             LIMIT 1
            """,
            client_id,
        )
    # Ensure the Branded Outputs folder exists for this tenant.
    folder_id = await conn.fetchval(
        """
        SELECT id::text
        FROM workspace_folders
        WHERE client_id = $1::uuid
          AND name = 'Branded Outputs'
          AND parent_folder_id IS NULL
          AND deleted_at IS NULL
        LIMIT 1
        """,
        client_id,
    )
    if folder_id is None:
        folder_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO workspace_folders
              (id, client_id, name, parent_folder_id, created_by_user_id, created_at, updated_at)
            VALUES ($1::uuid, $2::uuid, 'Branded Outputs', NULL, $3::uuid, now(), now())
            """,
            folder_id,
            client_id,
            creator_id,
        )

    artifact_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO artifacts
          (id, client_id, source_type, content_class,
           filename, storage_ref, extracted_text, workspace_folder_id,
           metadata, created_by_user_id)
        VALUES ($1::uuid, $2::uuid, 'generated'::artifact_source_type,
                'c0'::artifact_content_class,
                $3, $4, $5, $6::uuid, $7::jsonb, $8::uuid)
        """,
        artifact_id,
        client_id,
        filename,
        f"workspace://branded_outputs/{filename}",
        extracted_text,
        folder_id,
        json.dumps(metadata),
        creator_id,
    )
    return artifact_id


async def _common_dispatch_tail(
    conn: asyncpg.Connection,
    *,
    pkg: dict,
    client_id: str,
    actor_user_id: Optional[str],
    adapter_key: str,
    artifact_id: str,
    external_destination: str,
    handoff_metadata: dict,
) -> DispatchResult:
    """Insert handoff + audit + return result. Shared by all sandbox
    + mcp renderers so the dispatch surface stays consistent."""
    adapter_catalog_id = await _resolve_adapter_catalog_id(conn, adapter_key)
    handoff_id = await _insert_handoff(
        conn,
        client_id=client_id,
        work_order_id=pkg["work_order_id"],
        output_package_id=pkg["id"],
        adapter_catalog_id=adapter_catalog_id,
        template_profile_id=pkg["template_profile_id"],
        external_reference=artifact_id,
        gamma_url=external_destination,
        correlation_id=pkg["correlation_id"],
    )
    # Update handoff status to 'completed' — sandbox renders are sync,
    # no polling needed. (Gamma sets 'submitted'; the poll worker
    # advances it later.)
    await conn.execute(
        """
        UPDATE output_handoffs
           SET status = 'completed'::output_handoff_status,
               metadata = metadata || $2::jsonb,
               updated_at = now()
         WHERE id = $1::uuid
        """,
        handoff_id,
        json.dumps(handoff_metadata),
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="adapter_dispatch.submitted",
        target_type="output_handoff",
        target_id=handoff_id,
        metadata={
            "adapter_key": adapter_key,
            "output_package_id": pkg["id"],
            "template_profile_id": pkg["template_profile_id"],
            "external_reference": artifact_id,
            "external_destination": external_destination,
            "endpoint": "sandbox:local",
            "mode": "sync",
        },
    )
    return DispatchResult(
        handoff_id=handoff_id,
        output_package_id=pkg["id"],
        external_reference=artifact_id,
        gamma_url=external_destination,
        adapter_key=adapter_key,
    )


async def _raise_adapter_unavailable(
    conn: asyncpg.Connection,
    *,
    pkg: dict,
    client_id: str,
    actor_user_id: Optional[str],
    adapter_key: str,
    reason: str,
) -> None:
    """Write a `failed` handoff with adapter_unavailable taxonomy +
    raise DispatchError. Caller (Paul / chain runtime) sees the
    failure and triggers fallback adapter."""
    adapter_catalog_id = await _resolve_adapter_catalog_id(conn, adapter_key)
    handoff_id = await _insert_handoff(
        conn,
        client_id=client_id,
        work_order_id=pkg["work_order_id"],
        output_package_id=pkg["id"],
        adapter_catalog_id=adapter_catalog_id,
        template_profile_id=pkg["template_profile_id"],
        external_reference="",
        gamma_url=None,
        correlation_id=pkg["correlation_id"],
    )
    await conn.execute(
        """
        UPDATE output_handoffs
           SET status = 'failed'::output_handoff_status,
               metadata = metadata || $2::jsonb,
               updated_at = now()
         WHERE id = $1::uuid
        """,
        handoff_id,
        json.dumps(
            {
                "kind": "adapter_unavailable",
                "adapter_key": adapter_key,
                "reason": reason,
            }
        ),
    )
    await write_audit_row(
        conn,
        client_id=client_id,
        actor_user_id=actor_user_id,
        event="adapter_dispatch.submitted",
        target_type="output_handoff",
        target_id=handoff_id,
        metadata={
            "adapter_key": adapter_key,
            "output_package_id": pkg["id"],
            "kind": "adapter_unavailable",
            "reason": reason,
        },
    )
    raise DispatchError("adapter_unavailable", reason)


# ── Renderer 1: sandbox_pptx (python-pptx) ────────────────────────


async def dispatch_sandbox_pptx_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Local PPTX render via python-pptx. Produces a brand-colored
    title slide + content slides from the package's markdown body."""
    existing = await _idempotency_check_sync(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    if existing is not None:
        raise DispatchError(
            "handoff_already_exists",
            f"output_handoff {existing} already in flight",
        )

    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    brand = await _load_brand_palette_and_fonts(conn, client_id=client_id)
    body = _extract_text_body(pkg["content_blocks"])

    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor
    except ImportError:
        return await _raise_adapter_unavailable(
            conn,
            pkg=pkg,
            client_id=client_id,
            actor_user_id=actor_user_id,
            adapter_key="sandbox_pptx",
            reason="python-pptx not installed",
        )

    def _hex_to_rgb(hex_color: str) -> RGBColor:
        h = hex_color.lstrip("#")
        return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    prs = Presentation()
    # Title slide
    title_slide = prs.slides.add_slide(prs.slide_layouts[0])
    title_slide.shapes.title.text = pkg["title"] or "(untitled)"
    if title_slide.placeholders and len(title_slide.placeholders) > 1:
        title_slide.placeholders[1].text = pkg["summary"] or ""
    # Color the title text per brand primary.
    try:
        for run in title_slide.shapes.title.text_frame.paragraphs[0].runs:
            run.font.color.rgb = _hex_to_rgb(brand["primary"])
            run.font.name = brand["heading_font"]
    except Exception:  # noqa: BLE001
        pass

    # Body slides — naive split on double-newline, max 8 slides.
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()][:8]
    for para in paragraphs:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = para.split("\n", 1)[0][:80]
        if slide.placeholders and len(slide.placeholders) > 1:
            slide.placeholders[1].text = para[:1200]
        try:
            for run in slide.shapes.title.text_frame.paragraphs[0].runs:
                run.font.color.rgb = _hex_to_rgb(brand["primary"])
                run.font.name = brand["heading_font"]
        except Exception:  # noqa: BLE001
            pass

    buf = io.BytesIO()
    prs.save(buf)
    pptx_bytes = buf.getvalue()

    filename = f"{(pkg['title'] or 'branded').replace(' ', '_')[:40]}_{output_package_id[:8]}.pptx"
    import base64

    artifact_id = await _write_workspace_artifact(
        conn,
        client_id=client_id,
        filename=filename,
        extracted_text=body,
        metadata={
            "kind": "sandbox_pptx",
            "byte_size": len(pptx_bytes),
            "slide_count": len(prs.slides),
            "rendered_bytes_base64": base64.b64encode(pptx_bytes).decode("ascii"),
        },
    )

    return await _common_dispatch_tail(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="sandbox_pptx",
        artifact_id=artifact_id,
        external_destination=f"workspace://branded_outputs/{filename}",
        handoff_metadata={
            "kind": "sandbox_pptx",
            "slide_count": len(prs.slides),
            "byte_size": len(pptx_bytes),
        },
    )


# ── Renderer 2: sandbox_html (f-string template) ──────────────────


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --brand-primary: {primary};
    --brand-secondary: {secondary};
    --brand-accent: {accent};
    --brand-bg: {bg};
    --brand-heading-font: {heading_font}, system-ui, sans-serif;
    --brand-body-font: {body_font}, system-ui, sans-serif;
  }}
  body {{
    background: var(--brand-bg);
    color: #0A0A0A;
    font-family: var(--brand-body-font);
    margin: 0;
    padding: 2rem;
  }}
  h1, h2, h3 {{
    color: var(--brand-primary);
    font-family: var(--brand-heading-font);
  }}
  .summary {{ color: var(--brand-secondary); font-size: 1.1rem; margin-bottom: 1.5rem; }}
  .body {{ max-width: 70ch; line-height: 1.6; }}
  .accent {{ color: var(--brand-accent); }}
  footer {{ margin-top: 4rem; color: var(--brand-secondary); font-size: 0.85rem; }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <div class="summary">{summary}</div>
  <div class="body">{body_html}</div>
  <footer>Rendered via IWO3 sandbox_html adapter · output_package {pkg_short_id}</footer>
</body>
</html>
"""


def _markdown_paragraphs_to_html(body: str) -> str:
    """Trivial markdown → HTML: split paragraphs, wrap in <p>, escape
    angle brackets. Good enough for branded landing pages without a
    real markdown lib."""
    if not body:
        return ""
    import html

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    return "\n".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)


async def dispatch_sandbox_html_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Local self-contained HTML render via stdlib + brand profile."""
    existing = await _idempotency_check_sync(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    if existing is not None:
        raise DispatchError(
            "handoff_already_exists",
            f"output_handoff {existing} already in flight",
        )

    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    brand = await _load_brand_palette_and_fonts(conn, client_id=client_id)
    body = _extract_text_body(pkg["content_blocks"])

    html_str = _HTML_TEMPLATE.format(
        title=(pkg["title"] or "(untitled)"),
        summary=(pkg["summary"] or ""),
        body_html=_markdown_paragraphs_to_html(body),
        primary=brand["primary"],
        secondary=brand["secondary"],
        accent=brand["accent"],
        bg=brand["bg"],
        heading_font=brand["heading_font"],
        body_font=brand["body_font"],
        pkg_short_id=output_package_id[:8],
    )

    filename = f"{(pkg['title'] or 'branded').replace(' ', '_')[:40]}_{output_package_id[:8]}.html"

    artifact_id = await _write_workspace_artifact(
        conn,
        client_id=client_id,
        filename=filename,
        extracted_text=html_str,
        metadata={
            "kind": "sandbox_html",
            "byte_size": len(html_str.encode("utf-8")),
        },
    )

    return await _common_dispatch_tail(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="sandbox_html",
        artifact_id=artifact_id,
        external_destination=f"workspace://branded_outputs/{filename}",
        handoff_metadata={
            "kind": "sandbox_html",
            "byte_size": len(html_str.encode("utf-8")),
        },
    )


# ── Renderer 3: sandbox_md (stdlib) ───────────────────────────────


async def dispatch_sandbox_md_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Local markdown render via stdlib. Wraps the body with a
    brand-prefixed frontmatter block (palette + voice signal) so
    downstream consumers see the brand context."""
    existing = await _idempotency_check_sync(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    if existing is not None:
        raise DispatchError(
            "handoff_already_exists",
            f"output_handoff {existing} already in flight",
        )

    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    brand = await _load_brand_palette_and_fonts(conn, client_id=client_id)
    body = _extract_text_body(pkg["content_blocks"])

    frontmatter = (
        "---\n"
        f"title: {pkg['title'] or '(untitled)'}\n"
        f"summary: {pkg['summary'] or ''}\n"
        f"brand_primary: {brand['primary']}\n"
        f"brand_heading_font: {brand['heading_font']}\n"
        f"rendered_by: iwo3.sandbox_md\n"
        f"package_id: {output_package_id}\n"
        "---\n\n"
    )
    md_str = frontmatter + (body or "(no body content)")

    filename = f"{(pkg['title'] or 'branded').replace(' ', '_')[:40]}_{output_package_id[:8]}.md"

    artifact_id = await _write_workspace_artifact(
        conn,
        client_id=client_id,
        filename=filename,
        extracted_text=md_str,
        metadata={
            "kind": "sandbox_md",
            "byte_size": len(md_str.encode("utf-8")),
        },
    )

    return await _common_dispatch_tail(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="sandbox_md",
        artifact_id=artifact_id,
        external_destination=f"workspace://branded_outputs/{filename}",
        handoff_metadata={
            "kind": "sandbox_md",
            "byte_size": len(md_str.encode("utf-8")),
        },
    )


# ── Renderer 4: sandbox_pdf (stub — adapter_unavailable) ──────────


async def dispatch_sandbox_pdf_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Stub. Real PDF renderer needs fpdf2 or weasyprint dep
    provisioning (out of CAP-F scope per CODEX 2026-05-16 scope
    lock). Surfaces the adapter contract + adapter_unavailable
    behavior so Paul's fallback path can be exercised."""
    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    return await _raise_adapter_unavailable(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="sandbox_pdf",
        reason="sandbox_pdf renderer not yet provisioned; install fpdf2 or weasyprint and remove this stub",
    )


# ── Renderer 5: sandbox_docx (stub — adapter_unavailable) ─────────


async def dispatch_sandbox_docx_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Stub. Real DOCX renderer needs python-docx dep provisioning."""
    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    return await _raise_adapter_unavailable(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="sandbox_docx",
        reason="sandbox_docx renderer not yet provisioned; install python-docx and remove this stub",
    )

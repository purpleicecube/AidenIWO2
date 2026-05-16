"""Loop CAP-F Φ.9 — MCP-backed render adapters for design-input
HTML chains.

Three adapter dispatch helpers paralleling sandbox_renderers for
the design-input HTML lanes:

  dispatch_stitch_html_render_for_package        — wraps Theta-shipped Stitch MCP; functional
  dispatch_figma_html_render_for_package         — stub (no server-side Figma MCP); adapter_unavailable
  dispatch_twentyfirst_html_render_for_package   — stub (21st-Magic tools are Claude-Code-side, not server-side); adapter_unavailable

Each helper follows the same dispatch shape as
`sandbox_renderers.dispatch_sandbox_*_for_package`:
  1. Idempotency check
  2. Load package + brand profile
  3. Call MCP tool (or stub)
  4. Save rendered HTML as workspace artifact
  5. Insert + complete handoff + audit
  6. Return DispatchResult

Stub renderers raise DispatchError("adapter_unavailable", ...) so
Paul's fallback path is exercised. CAP-E registry seed configures
sandbox_html as the fallback for design-input HTML chains, so a
Figma-intent WO falling through to sandbox_html is the expected
graceful-degradation behavior until Figma MCP is provisioned.
"""

from __future__ import annotations

from typing import Optional

import asyncpg

from .dispatch import DispatchError, DispatchResult, _load_package_and_template
from .sandbox_renderers import (
    _common_dispatch_tail,
    _extract_text_body,
    _idempotency_check_sync,
    _load_brand_palette_and_fonts,
    _raise_adapter_unavailable,
    _write_workspace_artifact,
)


_STITCH_HTML_WRAPPER = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --brand-primary: {primary};
    --brand-secondary: {secondary};
    --brand-bg: {bg};
    --brand-heading-font: {heading_font}, system-ui, sans-serif;
    --brand-body-font: {body_font}, system-ui, sans-serif;
  }}
  body {{ background: var(--brand-bg); font-family: var(--brand-body-font); margin: 0; }}
  .stitch-region {{ max-width: 1100px; margin: 2rem auto; padding: 1.5rem; }}
  .stitch-region h1, .stitch-region h2 {{ color: var(--brand-primary); font-family: var(--brand-heading-font); }}
  .stitch-source {{ margin-top: 4rem; color: var(--brand-secondary); font-size: 0.85rem; }}
</style>
</head>
<body>
  <div class="stitch-region">
{stitch_body}
  </div>
  <div class="stitch-region stitch-source">Rendered via Stitch MCP + IWO3 brand frame · output_package {pkg_short_id}</div>
</body>
</html>
"""


async def dispatch_stitch_html_render_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Wrap the Theta-shipped Stitch MCP into an AdapterContract-style
    dispatch. Calls Stitch via the existing `mcp_client` to render
    a design from the package's intake intent, then wraps the
    Stitch output in a brand-frame HTML.

    Falls back to `adapter_unavailable` if Stitch MCP isn't
    reachable (env not configured); Paul's fallback path then routes
    to sandbox_html per the CAP-E registry fallback chain."""
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

    # Try the Stitch MCP via the existing runtime/mcp_client + the
    # Theta-shipped stitch tool. If MCP isn't configured for this
    # process (no STITCH_API_KEY / no STITCH_MCP_COMMAND), fall
    # through to adapter_unavailable so Paul's fallback fires.
    try:
        from runtime.tools.stitch_mcp import _stitch_design  # type: ignore
    except ImportError:
        return await _raise_adapter_unavailable(
            conn,
            pkg=pkg,
            client_id=client_id,
            actor_user_id=actor_user_id,
            adapter_key="stitch_html_render",
            reason="stitch MCP module not importable",
        )

    try:
        stitch_result = await _stitch_design(
            {
                "prompt": (pkg["title"] or "") + "\n\n" + (body[:2000]),
                "kind": "html",
            }
        )
    except Exception as exc:  # noqa: BLE001
        return await _raise_adapter_unavailable(
            conn,
            pkg=pkg,
            client_id=client_id,
            actor_user_id=actor_user_id,
            adapter_key="stitch_html_render",
            reason=f"stitch MCP call failed: {exc}",
        )

    # Stitch may return a markup fragment or a full HTML doc; wrap
    # whichever we got in the brand frame.
    stitch_body = ""
    if isinstance(stitch_result, dict):
        stitch_body = (
            stitch_result.get("html")
            or stitch_result.get("content")
            or stitch_result.get("text")
            or ""
        )
    elif isinstance(stitch_result, str):
        stitch_body = stitch_result

    if not stitch_body:
        return await _raise_adapter_unavailable(
            conn,
            pkg=pkg,
            client_id=client_id,
            actor_user_id=actor_user_id,
            adapter_key="stitch_html_render",
            reason="stitch MCP returned empty body",
        )

    full_html = _STITCH_HTML_WRAPPER.format(
        title=(pkg["title"] or "(untitled)"),
        primary=brand["primary"],
        secondary=brand["secondary"],
        bg=brand["bg"],
        heading_font=brand["heading_font"],
        body_font=brand["body_font"],
        stitch_body=stitch_body,
        pkg_short_id=output_package_id[:8],
    )

    filename = f"{(pkg['title'] or 'branded_stitch').replace(' ', '_')[:40]}_{output_package_id[:8]}.html"

    artifact_id = await _write_workspace_artifact(
        conn,
        client_id=client_id,
        filename=filename,
        extracted_text=full_html,
        metadata={
            "kind": "stitch_html_render",
            "byte_size": len(full_html.encode("utf-8")),
            "stitch_source": "mcp",
        },
    )

    return await _common_dispatch_tail(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="stitch_html_render",
        artifact_id=artifact_id,
        external_destination=f"workspace://branded_outputs/{filename}",
        handoff_metadata={
            "kind": "stitch_html_render",
            "byte_size": len(full_html.encode("utf-8")),
        },
    )


async def dispatch_figma_html_render_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Stub. No server-side Figma MCP exists yet. Tenant adapter
    credentials for Figma are gated by `client_adapter_configs`
    (Q-PG-8 disposition); when Figma MCP is provisioned + tenant
    enables it, this adapter wraps the call. Until then,
    adapter_unavailable triggers fallback to sandbox_html per the
    CAP-E registry chain."""
    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    return await _raise_adapter_unavailable(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="figma_html_render",
        reason="server-side Figma MCP not provisioned (Q-PG-8 deferred)",
    )


async def dispatch_twentyfirst_html_render_for_package(
    conn: asyncpg.Connection,
    *,
    output_package_id: str,
    client_id: str,
    actor_user_id: Optional[str],
) -> DispatchResult:
    """Stub. The `mcp__magic__*` 21st-Magic tools are Claude-Code-side
    MCP tools — they run in Claude's process, not in the FastAPI
    runtime. A server-side wrapper would need a separate MCP-server
    integration (out of CAP-F scope). Fallback to sandbox_html
    per the CAP-E registry chain."""
    pkg = await _load_package_and_template(
        conn, output_package_id=output_package_id, client_id=client_id
    )
    return await _raise_adapter_unavailable(
        conn,
        pkg=pkg,
        client_id=client_id,
        actor_user_id=actor_user_id,
        adapter_key="twentyfirst_html_render",
        reason="21st-Magic MCP tools run Claude-Code-side, not server-side",
    )

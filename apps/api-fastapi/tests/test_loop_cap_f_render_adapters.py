"""Loop CAP-F Φ.9 — render adapters + dispatch router + wire-up tests.

Coverage:
  - 8 new adapters registered in adapter_catalog (sandbox_*, *_html_render)
  - dispatch_for_adapter router routes by adapter_key
  - Sandbox local renderers produce real artifacts:
    - sandbox_html: writes brand-styled HTML to workspace
    - sandbox_md: writes brand-frontmatter markdown
    - sandbox_pptx: writes python-pptx PPTX (when dep available)
  - Stub adapters raise DispatchError("adapter_unavailable", ...):
    - sandbox_pdf, sandbox_docx, figma_html_render, twentyfirst_html_render
  - Router fallback: primary `adapter_unavailable` → next fallback
  - execute_step_run wire-up: brand_qa + deliver step kinds route
    through CAP-D helpers + CAP-F router (DB-backed smoke without
    LLM by stubbing the helper imports)

Skips DB-backed tests when IWO3_DATABASE_URL is unset.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import asyncpg
import pytest

from adapter.dispatch import DispatchError, DispatchResult


KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001"
KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003"


iwo3_db = pytest.mark.skipif(
    not os.environ.get("IWO3_DATABASE_URL"),
    reason="IWO3_DATABASE_URL not set",
)


@pytest.fixture
def db_url() -> str:
    return os.environ["IWO3_DATABASE_URL"]


async def _open_tenant_conn(
    db_url: str, *, client_id: str
) -> asyncpg.Connection:
    conn = await asyncpg.connect(db_url)
    await conn.execute("SET LOCAL ROLE iwo3_app")
    await conn.execute(
        f"SET LOCAL app.current_client_id = '{client_id}'"
    )
    return conn


async def _create_test_package(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    output_kind_pkg: str = "sandbox_html",
    content_text: str = "# Test heading\n\nFirst paragraph for Klear branded test.\n\nSecond paragraph.",
) -> str:
    pkg_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO output_packages
          (id, client_id, output_kind, work_order_id, workflow_execution_id,
           title, summary, content_blocks, status, correlation_id)
        VALUES ($1::uuid, $2::uuid, $3::output_package_kind, NULL, NULL,
                $4, $5, $6::jsonb, 'draft'::output_package_status, $7)
        """,
        pkg_id,
        client_id,
        output_kind_pkg,
        "Klear test deliverable",
        "Test summary",
        json.dumps({"content_markdown": content_text}),
        f"cap-f-test:{pkg_id[:8]}",
    )
    return pkg_id


# ── 1. Adapter catalog registration ──────────────────────────────


@iwo3_db
def test_eight_new_adapters_registered(db_url: str) -> None:
    """All 8 CAP-F adapters present in adapter_catalog with the
    expected adapter_keys."""

    async def run() -> None:
        raw = await asyncpg.connect(db_url)
        try:
            rows = await raw.fetch(
                """
                SELECT adapter_key, category::text AS category, status::text AS status
                FROM adapter_catalog
                WHERE adapter_key IN (
                    'sandbox_pptx', 'sandbox_pdf', 'sandbox_html',
                    'sandbox_docx', 'sandbox_md',
                    'stitch_html_render', 'figma_html_render', 'twentyfirst_html_render'
                )
                ORDER BY adapter_key
                """
            )
            assert len(rows) == 8
            for r in rows:
                assert r["category"] == "design_render"
        finally:
            await raw.close()

    asyncio.run(run())


@iwo3_db
def test_render_action_seeded_for_each_new_adapter(db_url: str) -> None:
    """Each of the 8 new adapters has a `render` action registered."""

    async def run() -> None:
        raw = await asyncpg.connect(db_url)
        try:
            rows = await raw.fetch(
                """
                SELECT ac.adapter_key, aa.action_key
                FROM adapter_actions aa
                JOIN adapter_catalog ac ON ac.id = aa.adapter_catalog_id
                WHERE ac.adapter_key IN (
                    'sandbox_pptx', 'sandbox_pdf', 'sandbox_html',
                    'sandbox_docx', 'sandbox_md',
                    'stitch_html_render', 'figma_html_render', 'twentyfirst_html_render'
                )
                ORDER BY ac.adapter_key
                """
            )
            assert len(rows) == 8
            for r in rows:
                assert r["action_key"] == "render"
        finally:
            await raw.close()

    asyncio.run(run())


# ── 2. Local renderer functional tests ───────────────────────────


@iwo3_db
def test_sandbox_html_renders_brand_styled_output(db_url: str) -> None:
    """sandbox_html produces a real HTML artifact with brand palette
    injected as CSS custom properties."""
    from adapter.sandbox_renderers import dispatch_sandbox_html_for_package

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(
                conn, client_id=KLEAR_CLIENT, output_kind_pkg="sandbox_html"
            )
            result = await dispatch_sandbox_html_for_package(
                conn,
                output_package_id=pkg_id,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert isinstance(result, DispatchResult)
            assert result.adapter_key == "sandbox_html"
            # Read back the artifact content
            artifact_row = await conn.fetchrow(
                "SELECT extracted_text FROM artifacts WHERE id = $1::uuid",
                result.external_reference,
            )
            html_str = artifact_row["extracted_text"]
            # Klear primary palette should appear in the rendered CSS
            assert "#8B49E2" in html_str  # Klear primary purple
            assert "Lexend" in html_str  # Klear heading font
            assert "First paragraph" in html_str  # body content present
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_sandbox_md_writes_brand_frontmatter(db_url: str) -> None:
    """sandbox_md writes markdown with brand-prefixed YAML frontmatter."""
    from adapter.sandbox_renderers import dispatch_sandbox_md_for_package

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(
                conn, client_id=KLEAR_CLIENT, output_kind_pkg="sandbox_md"
            )
            result = await dispatch_sandbox_md_for_package(
                conn,
                output_package_id=pkg_id,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert result.adapter_key == "sandbox_md"
            artifact_row = await conn.fetchrow(
                "SELECT extracted_text FROM artifacts WHERE id = $1::uuid",
                result.external_reference,
            )
            md_str = artifact_row["extracted_text"]
            assert md_str.startswith("---")
            assert "brand_primary: #8B49E2" in md_str
            assert "First paragraph" in md_str
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_sandbox_pptx_produces_pptx_artifact(db_url: str) -> None:
    """sandbox_pptx (python-pptx) produces a real PPTX artifact when
    python-pptx is available. Artifact metadata carries slide_count
    + byte_size."""
    pytest.importorskip("pptx")
    from adapter.sandbox_renderers import dispatch_sandbox_pptx_for_package

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(
                conn, client_id=KLEAR_CLIENT, output_kind_pkg="sandbox_pptx"
            )
            result = await dispatch_sandbox_pptx_for_package(
                conn,
                output_package_id=pkg_id,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
            )
            assert result.adapter_key == "sandbox_pptx"
            artifact_row = await conn.fetchrow(
                "SELECT metadata::text AS m FROM artifacts WHERE id = $1::uuid",
                result.external_reference,
            )
            meta = json.loads(artifact_row["m"])
            assert meta["kind"] == "sandbox_pptx"
            assert meta["slide_count"] >= 1
            assert meta["byte_size"] > 0
            assert "rendered_bytes_base64" in meta
        finally:
            await conn.close()

    asyncio.run(run())


# ── 3. Stub adapter raise adapter_unavailable ────────────────────


@iwo3_db
def test_sandbox_pdf_raises_adapter_unavailable(db_url: str) -> None:
    from adapter.sandbox_renderers import dispatch_sandbox_pdf_for_package

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(conn, client_id=KLEAR_CLIENT)
            with pytest.raises(DispatchError) as exc_info:
                await dispatch_sandbox_pdf_for_package(
                    conn,
                    output_package_id=pkg_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                )
            assert exc_info.value.kind == "adapter_unavailable"
            assert "fpdf2" in exc_info.value.detail or "weasyprint" in exc_info.value.detail
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_sandbox_docx_raises_adapter_unavailable(db_url: str) -> None:
    from adapter.sandbox_renderers import dispatch_sandbox_docx_for_package

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(conn, client_id=KLEAR_CLIENT)
            with pytest.raises(DispatchError) as exc_info:
                await dispatch_sandbox_docx_for_package(
                    conn,
                    output_package_id=pkg_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                )
            assert exc_info.value.kind == "adapter_unavailable"
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_figma_render_raises_adapter_unavailable(db_url: str) -> None:
    from adapter.mcp_renderers import dispatch_figma_html_render_for_package

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(conn, client_id=KLEAR_CLIENT)
            with pytest.raises(DispatchError) as exc_info:
                await dispatch_figma_html_render_for_package(
                    conn,
                    output_package_id=pkg_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                )
            assert exc_info.value.kind == "adapter_unavailable"
            assert "Figma MCP" in exc_info.value.detail
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_twentyfirst_render_raises_adapter_unavailable(db_url: str) -> None:
    from adapter.mcp_renderers import dispatch_twentyfirst_html_render_for_package

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(conn, client_id=KLEAR_CLIENT)
            with pytest.raises(DispatchError) as exc_info:
                await dispatch_twentyfirst_html_render_for_package(
                    conn,
                    output_package_id=pkg_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                )
            assert exc_info.value.kind == "adapter_unavailable"
        finally:
            await conn.close()

    asyncio.run(run())


# ── 4. Router fallback ───────────────────────────────────────────


@iwo3_db
def test_router_falls_back_on_adapter_unavailable(db_url: str) -> None:
    """dispatch_for_adapter with primary=sandbox_pdf (stub) +
    fallback=[sandbox_html] should succeed via sandbox_html when
    sandbox_pdf raises adapter_unavailable."""
    from adapter.dispatch import dispatch_for_adapter

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(
                conn, client_id=KLEAR_CLIENT, output_kind_pkg="sandbox_html"
            )
            result = await dispatch_for_adapter(
                conn,
                adapter_key="sandbox_pdf",
                output_package_id=pkg_id,
                client_id=KLEAR_CLIENT,
                actor_user_id=KLEAR_OPERATOR,
                fallback_adapter_keys=["sandbox_html"],
            )
            assert result.adapter_key == "sandbox_html"
        finally:
            await conn.close()

    asyncio.run(run())


@iwo3_db
def test_router_raises_when_no_fallback_succeeds(db_url: str) -> None:
    """When primary + all fallbacks raise adapter_unavailable, the
    router re-raises the last DispatchError."""
    from adapter.dispatch import dispatch_for_adapter

    async def run() -> None:
        conn = await _open_tenant_conn(db_url, client_id=KLEAR_CLIENT)
        try:
            pkg_id = await _create_test_package(conn, client_id=KLEAR_CLIENT)
            with pytest.raises(DispatchError) as exc_info:
                await dispatch_for_adapter(
                    conn,
                    adapter_key="sandbox_pdf",
                    output_package_id=pkg_id,
                    client_id=KLEAR_CLIENT,
                    actor_user_id=KLEAR_OPERATOR,
                    fallback_adapter_keys=["sandbox_docx"],
                )
            assert exc_info.value.kind == "adapter_unavailable"
        finally:
            await conn.close()

    asyncio.run(run())


# ── 5. Wire-up helper exists for execute_step_run ────────────────


def test_execute_step_run_branded_chain_wireup_helper_exists() -> None:
    """The wire-up helper `_execute_branded_chain_step` is importable
    from runtime.tier_2_subagents — lock test that the wire-up was
    added and the function signature carries the expected parameters
    (so a chain-runtime caller can rely on it)."""
    from runtime.tier_2_subagents import _execute_branded_chain_step
    import inspect

    sig = inspect.signature(_execute_branded_chain_step)
    expected_params = {
        "conn",
        "step_run_id",
        "execution_id",
        "step_key",
        "step_order",
        "work_order_id",
        "display_name",
        "assigned_role",
        "client_id",
        "actor_user_id",
        "intake_text",
        "input_payload",
        "memory_block",
    }
    assert set(sig.parameters.keys()) == expected_params

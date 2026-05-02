"""Loop Eta Worker F — handler smoke tests for the 3 document/rendering
runnable tools (``pdf_extract_text``, ``markdown_to_pptx``,
``gamma_render``).

These are pure handler-level tests: they bypass ``execute_tool()`` so
no DB connection or audit row is required. The Gamma test mocks
``adapter.dispatch.dispatch_gamma_for_package`` outright — the live-DB
audit + idempotence behaviour is already covered by
``test_adapter_dispatch.py``."""

from __future__ import annotations

import asyncio
import base64
import io

import httpx
import pytest

from runtime.tools.document_rendering import (
    DOCUMENT_RENDERING_TOOLS,
    _gamma_render,
    _markdown_to_pptx,
    _pdf_extract_text,
    _is_safe_url,
)


# A hand-rolled minimal PDF carrying a single text object. Keeps the
# fixture surface self-contained so we don't have to ship a binary
# under ``tests/fixtures/``.
_MINIMAL_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]"
    b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 44>>stream\n"
    b"BT /F1 24 Tf 100 700 Td (Hello PDF World) Tj ET\n"
    b"endstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n"
    b"0000000054 00000 n \n0000000101 00000 n \n0000000192 00000 n \n"
    b"0000000281 00000 n \ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n338\n%%EOF"
)


def test_registry_shape_exposes_three_runnable_tools() -> None:
    """The exported registry must list exactly the three tools the
    catalog seed expects, each with a callable handler. Convergence
    merges this dict into ``aiden_tools.TOOL_REGISTRY`` verbatim."""
    keys = set(DOCUMENT_RENDERING_TOOLS.keys())
    assert keys == {"pdf_extract_text", "markdown_to_pptx", "gamma_render"}
    for tool in DOCUMENT_RENDERING_TOOLS.values():
        assert callable(tool.handler)
        assert tool.args_schema.get("type") == "object"


def test_pdf_extract_text_handler_smokes() -> None:
    """Smoke: handler fetches a URL via httpx, hands the body to
    ``pypdf``, and returns text + char_count > 0. The URL is mocked
    so no network is touched."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_MINIMAL_PDF_BYTES,
            headers={"content-type": "application/pdf"},
        )

    transport = httpx.MockTransport(_handler)

    async def _go() -> None:
        result = await _pdf_extract_text(
            None,  # type: ignore[arg-type]  # handler ignores conn
            {
                "url": "https://example.com/test.pdf",
                "_transport": transport,
            },
            client_id="00000000-0000-4000-8000-00000000c001",
        )
        assert result["url"] == "https://example.com/test.pdf"
        assert result["page_count"] == 1
        assert result["char_count"] > 0
        assert "Hello PDF World" in result["text"]

    asyncio.run(_go())


def test_pdf_extract_text_rejects_unsafe_urls() -> None:
    """SSRF guard: ``file://`` and private-IP literals must be refused
    before any network IO happens. Catches the obvious foot-guns
    until a shared SSRF helper lands."""
    assert not _is_safe_url("file:///etc/passwd")
    assert not _is_safe_url("http://127.0.0.1/a.pdf")
    assert not _is_safe_url("http://10.0.0.1/a.pdf")
    assert not _is_safe_url("http://192.168.1.1/a.pdf")
    assert not _is_safe_url("http://169.254.169.254/a.pdf")
    assert not _is_safe_url("gopher://example.com/")
    assert _is_safe_url("https://example.com/x.pdf")
    assert _is_safe_url("http://example.com/x.pdf")


def test_markdown_to_pptx_handler_returns_b64_pptx() -> None:
    """Smoke: 3-section markdown → 3-slide deck. The base64 payload
    must decode to a ZIP (PPTX is OOXML zip; signature ``PK\\x03\\x04``)."""

    md = (
        "# Deck Title\n\n"
        "## Slide One\n"
        "- bullet a\n"
        "- bullet b\n\n"
        "## Slide Two\n"
        "Some body text here.\n\n"
        "## Slide Three\n"
        "* bullet c\n"
    )

    async def _go() -> None:
        result = await _markdown_to_pptx(
            None,  # type: ignore[arg-type]
            {"markdown": md, "title": "Smoke Deck"},
            client_id="00000000-0000-4000-8000-00000000c001",
        )
        # 1 prelude slide ("Deck Title") + 3 H2 slides = 4 sections.
        assert result["slide_count"] == 4
        assert result["title"] == "Smoke Deck"
        raw = base64.b64decode(result["pptx_bytes_b64"])
        assert raw[:4] == b"PK\x03\x04"  # ZIP / OOXML signature
        # Round-trip via python-pptx to confirm the deck is well-formed.
        from pptx import Presentation  # type: ignore[import-not-found]

        deck = Presentation(io.BytesIO(raw))
        assert len(deck.slides) == 4

    asyncio.run(_go())


def test_markdown_to_pptx_rejects_empty_markdown() -> None:
    """Empty / whitespace-only markdown must raise ``args_invalid``
    instead of producing an empty deck."""
    from runtime.aiden_tools import ToolExecutionError

    async def _go() -> None:
        with pytest.raises(ToolExecutionError) as exc:
            await _markdown_to_pptx(
                None,  # type: ignore[arg-type]
                {"markdown": "   \n  \n"},
                client_id="00000000-0000-4000-8000-00000000c001",
            )
        assert exc.value.kind == "args_invalid"

    asyncio.run(_go())


def test_gamma_render_handler_smokes_via_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``adapter.dispatch.dispatch_gamma_for_package`` and assert
    the handler hands back the expected envelope. The live-DB path is
    already exercised by ``test_adapter_dispatch.py``; this test pins
    the wrapper shape only."""
    from adapter import dispatch as dispatch_mod
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class _FakeResult:
        handoff_id: str = "fake-handoff-001"
        output_package_id: str = "fake-package-001"
        external_reference: str = "gen_abc123"
        gamma_url: str | None = "https://gamma.app/test/gen_abc123"
        adapter_key: str = "gamma"

    async def _fake_dispatch(
        conn,
        *,
        output_package_id,
        client_id,
        actor_user_id,
        transport=None,
    ):
        # Confirm the handler is forwarding the right kwargs.
        assert output_package_id == "fake-package-001"
        assert client_id == "00000000-0000-4000-8000-00000000c001"
        assert actor_user_id == "agent_system"
        return _FakeResult()

    monkeypatch.setattr(
        dispatch_mod, "dispatch_gamma_for_package", _fake_dispatch
    )

    async def _go() -> None:
        result = await _gamma_render(
            None,  # type: ignore[arg-type]
            {"output_package_id": "fake-package-001"},
            client_id="00000000-0000-4000-8000-00000000c001",
        )
        assert result["handoff_id"] == "fake-handoff-001"
        assert result["external_reference"] == "gen_abc123"
        assert result["status"] == "submitted"
        assert result["gamma_url"] == "https://gamma.app/test/gen_abc123"
        assert result["output_package_id"] == "fake-package-001"

    asyncio.run(_go())


def test_gamma_render_translates_dispatch_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``DispatchError`` inside the adapter must surface as a
    ``ToolExecutionError`` with the same ``kind`` so the audit row
    written by ``execute_tool()`` carries the original taxonomy."""
    from adapter import dispatch as dispatch_mod
    from runtime.aiden_tools import ToolExecutionError

    async def _fake_dispatch(*args, **kwargs):
        raise dispatch_mod.DispatchError(
            "handoff_already_exists", "fake in-flight"
        )

    monkeypatch.setattr(
        dispatch_mod, "dispatch_gamma_for_package", _fake_dispatch
    )

    async def _go() -> None:
        with pytest.raises(ToolExecutionError) as exc_info:
            await _gamma_render(
                None,  # type: ignore[arg-type]
                {"output_package_id": "fake-package-001"},
                client_id="00000000-0000-4000-8000-00000000c001",
            )
        assert exc_info.value.kind == "handoff_already_exists"

    asyncio.run(_go())

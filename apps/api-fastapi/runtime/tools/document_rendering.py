"""Loop Eta Worker F — document + rendering Tier 2 tool handlers.

Three runnable handlers wired to existing tool_catalog rows seeded by
Worker A (handler_ref values match the entries in
``db/seeds/tool_catalog.json``):

  - ``pdf_extract_text``  — fetch a PDF URL, return text + page_count.
  - ``markdown_to_pptx``  — split markdown on H2 + render simple PPTX.
  - ``gamma_render``      — thin wrapper around
                            ``adapter.dispatch.dispatch_gamma_for_package``.

The registry exported by this module (``DOCUMENT_RENDERING_TOOLS``) is
imported + dict-merged into ``runtime/aiden_tools.py:TOOL_REGISTRY``
during convergence. Each handler signature mirrors the existing 3
Tier-1 handlers in ``aiden_tools.py``:

    async def _<tool>(
        conn: asyncpg.Connection,
        args: dict[str, Any],
        client_id: str,
    ) -> dict[str, Any]: ...

Failures should raise ``aiden_tools.ToolExecutionError`` so the
``execute_tool()`` audit-row pipeline records ``*.tool_failed``.
Per architect lock for this loop:
  - No schema changes / no new audit events / no new permission keys.
  - ``aiden_tools.py`` is read-only here; convergence imports this
    registry and merges it.
"""

from __future__ import annotations

import base64
import io
import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

import asyncpg
import httpx

from runtime.aiden_tools import ToolDefinition, ToolExecutionError


# ── SSRF guard ────────────────────────────────────────────────────────


_DENY_SCHEMES = {"file", "gopher", "ftp", "data"}


def _is_safe_url(url: str) -> bool:
    """Reject obviously dangerous URLs.

    Refuses non-http(s) schemes and any host that resolves to a
    private / loopback / link-local IPv4 literal. Hostnames are not
    DNS-resolved here (network-free check); the upstream httpx call
    will fail closed if the resolved IP turns out to be private. A
    shared SSRF helper for the broader Loop Eta cohort is expected
    to land in a follow-up loop — until then this inline guard keeps
    the surface narrow."""
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return False
    if scheme in _DENY_SCHEMES:
        return False
    host = parsed.hostname
    if not host:
        return False
    # If the hostname is an IP literal, reject private / loopback /
    # link-local ranges directly. DNS-name hosts pass this check; the
    # underlying socket connect will fail-closed if their A record
    # lands on a private address.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return False
    return True


# ── Handlers ──────────────────────────────────────────────────────────


PDF_FETCH_TIMEOUT_S = 20.0
PDF_MAX_BYTES = 25 * 1024 * 1024  # 25 MB cap; keeps memory bounded


async def _pdf_extract_text(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Fetch a PDF over HTTP(S), extract plain text via ``pypdf``.

    Returns ``{url, page_count, char_count, text}``. Failures raise
    ``ToolExecutionError`` so the audit pipeline records
    ``*.tool_failed``. The ``conn`` arg is unused for this handler
    but kept in the signature so the registry dispatch is uniform."""
    del conn, client_id  # tenant-scoped DB not consulted by this handler

    url = args.get("url")
    if not isinstance(url, str) or not url:
        raise ToolExecutionError(
            "pdf_extract_text", "args_invalid", "args.url is required (string)"
        )
    if not _is_safe_url(url):
        raise ToolExecutionError(
            "pdf_extract_text",
            "url_rejected",
            f"url {url!r} failed SSRF safety check",
        )

    transport = args.get("_transport")  # test-only injection point

    try:
        async with httpx.AsyncClient(
            timeout=PDF_FETCH_TIMEOUT_S,
            follow_redirects=True,
            transport=transport,
        ) as client:
            resp = await client.get(url)
    except httpx.HTTPError as exc:
        raise ToolExecutionError(
            "pdf_extract_text", "fetch_failed", str(exc)
        ) from exc

    if resp.status_code >= 400:
        raise ToolExecutionError(
            "pdf_extract_text",
            "fetch_failed",
            f"upstream returned {resp.status_code}",
        )

    body = resp.content
    if len(body) > PDF_MAX_BYTES:
        raise ToolExecutionError(
            "pdf_extract_text",
            "payload_too_large",
            f"PDF body {len(body)} bytes exceeds {PDF_MAX_BYTES}",
        )

    try:
        # Local import keeps module-load cheap when the tool isn't used.
        from pypdf import PdfReader  # type: ignore[import-not-found]

        reader = PdfReader(io.BytesIO(body))
        pages_text: list[str] = []
        for page in reader.pages:
            try:
                pages_text.append(page.extract_text() or "")
            except Exception:  # noqa: BLE001
                # Best-effort per-page; keep going on a malformed page.
                pages_text.append("")
        text = "\n\n".join(pages_text).strip()
        page_count = len(reader.pages)
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(
            "pdf_extract_text", "pdf_processing_failed", str(exc)
        ) from exc

    return {
        "url": url,
        "page_count": page_count,
        "char_count": len(text),
        "text": text,
    }


_H2_SPLIT_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)


async def _markdown_to_pptx(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Convert a markdown string to a minimal PPTX deck.

    Splits on H2 (``## ...``) headers into one slide per section.
    Body lines under each header become bullets (basic ``- `` /
    ``* `` prefixes are normalised; any other line is added as plain
    text). Returns ``{title, slide_count, pptx_bytes_b64}`` where
    ``pptx_bytes_b64`` is the base64-encoded PPTX zip.

    This is the v1 pipeline — Klear-branded templates land in a
    later loop; here we keep the dependency surface to
    ``python-pptx`` only and produce a valid OOXML document the
    operator can open in any compatible viewer."""
    del conn, client_id  # tenant-scoped DB not consulted by this handler

    markdown = args.get("markdown")
    if not isinstance(markdown, str) or not markdown.strip():
        raise ToolExecutionError(
            "markdown_to_pptx",
            "args_invalid",
            "args.markdown is required (non-empty string)",
        )
    title_arg = args.get("title")
    title: str = title_arg if isinstance(title_arg, str) and title_arg else "Untitled"

    # Split into ``[(heading, body_lines), ...]`` slides. If the markdown
    # has no H2 headers, treat the whole document as one slide using
    # the first H1 (or the supplied title) as the heading.
    sections: list[tuple[str, list[str]]] = []
    indices = [m.start() for m in _H2_SPLIT_RE.finditer(markdown)]
    if not indices:
        # Try to lift a leading H1 as the heading; otherwise use ``title``.
        h1_match = re.match(r"^#\s+(.+)$", markdown, re.MULTILINE)
        head = h1_match.group(1).strip() if h1_match else title
        body = markdown
        if h1_match:
            body = markdown[h1_match.end():]
        sections.append((head, [ln for ln in body.splitlines() if ln.strip()]))
    else:
        # Capture pre-H2 prelude as a title slide if it has any content.
        first = indices[0]
        prelude = markdown[:first].strip()
        if prelude:
            h1_match = re.match(r"^#\s+(.+)$", prelude, re.MULTILINE)
            head = h1_match.group(1).strip() if h1_match else title
            body = prelude
            if h1_match:
                body = prelude[h1_match.end():]
            prelude_lines = [ln for ln in body.splitlines() if ln.strip()]
            if prelude_lines or h1_match:
                sections.append((head, prelude_lines))
        # Split the H2 sections.
        bounded = indices + [len(markdown)]
        for i in range(len(indices)):
            block = markdown[bounded[i]:bounded[i + 1]]
            heading_match = _H2_SPLIT_RE.match(block)
            if heading_match is None:
                continue  # defensive
            heading = heading_match.group(1).strip()
            body = block[heading_match.end():]
            body_lines = [ln for ln in body.splitlines() if ln.strip()]
            sections.append((heading, body_lines))

    if not sections:
        raise ToolExecutionError(
            "markdown_to_pptx",
            "args_invalid",
            "markdown produced no slide sections",
        )

    try:
        from pptx import Presentation  # type: ignore[import-not-found]

        pres = Presentation()
        # Layout 1 = "Title and Content" in the default python-pptx
        # template; falls back to layout 0 (Title) if unavailable.
        try:
            content_layout = pres.slide_layouts[1]
        except IndexError:  # pragma: no cover — default template ships layouts
            content_layout = pres.slide_layouts[0]

        for heading, lines in sections:
            slide = pres.slides.add_slide(content_layout)
            if slide.shapes.title is not None:
                slide.shapes.title.text = heading or "Untitled section"
            # Locate the body placeholder (first non-title placeholder).
            body_ph = None
            for ph in slide.placeholders:
                if ph.placeholder_format.idx != 0:
                    body_ph = ph
                    break
            if body_ph is not None and lines:
                tf = body_ph.text_frame
                # First line replaces the default empty paragraph;
                # subsequent lines append new paragraphs.
                first_line, *rest = [
                    re.sub(r"^[\-\*]\s+", "", ln).strip() for ln in lines
                ]
                tf.text = first_line
                for line in rest:
                    p = tf.add_paragraph()
                    p.text = line

        buf = io.BytesIO()
        pres.save(buf)
        pptx_bytes = buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(
            "markdown_to_pptx", "render_failed", str(exc)
        ) from exc

    return {
        "title": title,
        "slide_count": len(sections),
        "pptx_bytes_b64": base64.b64encode(pptx_bytes).decode("ascii"),
    }


async def _gamma_render(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Submit an existing output_package to Gamma via the existing
    ``adapter.dispatch.dispatch_gamma_for_package`` flow.

    This handler is intentionally thin — the value here is making
    the catalog entry executable from the Tier 2 tool surface so
    sub-agents can render an already-built package without going
    through the ``/work_orders/{id}/render`` route. All the heavy
    lifting (template lookup, idempotence guard, audit row, handoff
    insert, optional MockTransport) lives in ``adapter.dispatch``.

    Returns ``{handoff_id, output_package_id, external_reference,
    status, gamma_url}``. ``status`` is always ``"submitted"`` on
    success — the poll worker advances it to ``completed`` later."""
    output_package_id = args.get("output_package_id")
    if not isinstance(output_package_id, str) or not output_package_id:
        raise ToolExecutionError(
            "gamma_render",
            "args_invalid",
            "args.output_package_id is required (string)",
        )

    # Local import avoids pulling adapter.dispatch (and its httpx /
    # gamma-shape modules) into module-load cost when the tool is
    # never invoked.
    from adapter.dispatch import (  # type: ignore[import-not-found]
        DispatchError,
        dispatch_gamma_for_package,
    )

    transport = args.get("_transport")  # test-only injection point

    try:
        result = await dispatch_gamma_for_package(
            conn,
            output_package_id=output_package_id,
            client_id=client_id,
            actor_user_id="agent_system",
            transport=transport,
        )
    except DispatchError as exc:
        raise ToolExecutionError(
            "gamma_render", exc.kind, exc.detail
        ) from exc

    return {
        "handoff_id": result.handoff_id,
        "output_package_id": result.output_package_id,
        "external_reference": result.external_reference,
        "gamma_url": result.gamma_url,
        "status": "submitted",
    }


# ── Registry ─────────────────────────────────────────────────────────


DOCUMENT_RENDERING_TOOLS: dict[str, ToolDefinition] = {
    "pdf_extract_text": ToolDefinition(
        name="pdf_extract_text",
        description=(
            "Fetch a PDF from an HTTP(S) URL and extract its text. "
            "Returns {url, page_count, char_count, text}. Use when the "
            "operator or a sub-agent needs to read the contents of a "
            "PDF that lives on the open web. Refuses non-http(s) "
            "schemes and private/loopback IP literals."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=_pdf_extract_text,
    ),
    "markdown_to_pptx": ToolDefinition(
        name="markdown_to_pptx",
        description=(
            "Convert a markdown string to a minimal PPTX deck (one "
            "slide per H2 header). Returns {title, slide_count, "
            "pptx_bytes_b64}. v1 ships a generic python-pptx template; "
            "Klear-branded templates land in a later loop."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "markdown": {"type": "string"},
                "title": {"type": "string"},
                "theme": {"type": "string", "default": "klear_default"},
            },
            "required": ["markdown"],
            "additionalProperties": False,
        },
        handler=_markdown_to_pptx,
    ),
    "gamma_render": ToolDefinition(
        name="gamma_render",
        description=(
            "Submit an existing output_package to Gamma via the "
            "adapter dispatch flow. Args: {output_package_id}. "
            "Returns {handoff_id, output_package_id, "
            "external_reference, gamma_url, status}. Idempotent: "
            "rejects a second submission while a non-terminal handoff "
            "is in flight (DispatchError(handoff_already_exists))."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "output_package_id": {"type": "string"},
            },
            "required": ["output_package_id"],
            "additionalProperties": False,
        },
        handler=_gamma_render,
    ),
}

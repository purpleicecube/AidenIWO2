"""Loop Eta Worker G — Tier-2 web search + SSRF-safe scrape handlers.

Ports four IWO2 tool-executor handlers to runnable Python:
  - web_search_brave        → Brave Search API
  - web_search_perplexity   → Perplexity Sonar (AI-summarised + citations)
  - web_search_ddg          → DuckDuckGo instant answers (no API key)
  - web_scrape              → Fetch + extract text, SSRF-protected

Behavioural parity reference (do not mutate):
  /home/virgina/VS_AIDEN_IWO2/server/tool-executor.ts
    - executeBraveSearch          (lines 81-112)
    - executePerplexitySearch     (lines 159-193)
    - executeDuckDuckGoSearch     (lines 195-219)
    - executeWebScraper + isSafeUrl (lines 134-151, 318-389)

Hard locks:
  - These handlers are pure functions over (conn, args, client_id);
    auditing/leasing happens in `aiden_tools.execute_tool`.
  - `aiden_tools.py` MUST NOT be modified by this worker — convergence
    step folds `SEARCH_TOOLS` into `TOOL_REGISTRY` in a follow-up loop.
  - All outbound HTTP goes through httpx so tests can swap in a
    `MockTransport`; no `requests`, no `urllib.request`.
  - `_is_safe_url` is a pure helper that runs *before* any network
    call — keeps SSRF policy unit-testable.
"""

from __future__ import annotations

import ipaddress
import os
import re
from typing import Any
from urllib.parse import urlparse

import asyncpg
import httpx
from bs4 import BeautifulSoup

from runtime.aiden_tools import ToolDefinition, ToolExecutionError


# ── SSRF guard ───────────────────────────────────────────────────────


_BLOCKED_HOSTNAMES = frozenset(
    {
        "localhost",
        "0.0.0.0",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
    }
)
_BLOCKED_HOSTNAME_SUFFIXES = (".local", ".internal", ".localhost")
# IWO2 parity (tool-executor.ts:139-146): private + loopback + link-local
# IPv4 ranges plus IPv6 loopback / unique-local / link-local.
_BLOCKED_NETWORKS_V4 = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
)
_BLOCKED_NETWORKS_V6 = (
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),  # unique-local (covers fd00::/8)
    ipaddress.ip_network("fe80::/10"),  # link-local
)


def _is_safe_url(url: str) -> bool:
    """Return True iff `url` is a public http/https URL that's safe to
    fetch from a server-side scraper. Pure function; no I/O, no DNS.

    Rejects (BEFORE any outbound request):
      - non-http/https schemes (file://, gopher://, ftp://, ...)
      - localhost / *.local / *.internal / *.localhost / 0.0.0.0
      - private IPv4 literals (10/8, 127/8, 172.16/12, 192.168/16, 169.254/16)
      - IPv6 loopback (::1), unique-local (fc00::/7), link-local (fe80::/10)
      - empty hostname / unparseable URLs

    DNS rebinding is *not* blocked here — that requires getaddrinfo
    resolution at fetch time and pinning the connect address, which
    is out of scope for this loop. The Tier-2 runtime should add a
    socket-level guard before exposing this tool to untrusted prompts.
    """
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False
    if hostname in _BLOCKED_HOSTNAMES:
        return False
    if hostname.endswith(_BLOCKED_HOSTNAME_SUFFIXES):
        return False
    # Try to parse hostname as IP literal (strips brackets for IPv6).
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return True  # hostname is a real DNS name — allow
    if isinstance(ip, ipaddress.IPv4Address):
        for net in _BLOCKED_NETWORKS_V4:
            if ip in net:
                return False
        return True
    # IPv6
    for net6 in _BLOCKED_NETWORKS_V6:
        if ip in net6:
            return False
    return True


# ── HTTP transport seam ──────────────────────────────────────────────


def _new_client(transport: httpx.BaseTransport | None = None) -> httpx.AsyncClient:
    """Construct an httpx.AsyncClient. Tests pass a MockTransport via
    args["_transport"] so we never burn real API credits in CI."""
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(15.0, connect=10.0),
        follow_redirects=True,
        headers={
            "User-Agent": "AIDEN-IWO3/0.1 (+https://aiden-iwo.replit.app)",
        },
    )


def _pop_transport(args: dict[str, Any]) -> httpx.BaseTransport | None:
    """Tests inject `_transport` (MockTransport) via args; runtime never
    sets it. Pop so we don't accidentally serialise it into audit metadata."""
    return args.pop("_transport", None)


# ── Tool handlers ────────────────────────────────────────────────────


async def _web_search_brave(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Brave Search API — top N web results.

    IWO2 parity: tool-executor.ts:81-112. Returns shaped dict (not the
    IWO2 markdown blob) so the LLM can re-format it for the operator
    without re-parsing markdown.
    """
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not api_key:
        raise ToolExecutionError(
            "web_search_brave",
            "api_key_missing",
            "BRAVE_SEARCH_API_KEY not set",
        )
    query = str(args.get("query", "") or "").strip()
    if not query:
        raise ToolExecutionError(
            "web_search_brave", "bad_args", "query is required"
        )
    raw_max = int(args.get("max_results", 5) or 5)
    max_results = max(1, min(raw_max, 20))
    transport = _pop_transport(args)

    async with _new_client(transport=transport) as client:
        resp = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
        )
    if resp.status_code != 200:
        raise ToolExecutionError(
            "web_search_brave",
            "http_error",
            f"Brave returned {resp.status_code}: {resp.text[:200]}",
        )
    data = resp.json()
    raw = (data.get("web") or {}).get("results") or []
    results: list[dict[str, Any]] = []
    for r in raw[:max_results]:
        results.append(
            {
                "title": r.get("title") or "Untitled",
                "url": r.get("url") or "",
                "snippet": re.sub(r"<[^>]*>", "", r.get("description") or "")[
                    :300
                ],
            }
        )
    return {
        "query": query,
        "result_count": len(results),
        "results": results,
    }


async def _web_search_perplexity(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Perplexity Sonar — AI-summarised answer + citations.

    IWO2 parity: tool-executor.ts:159-193.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY")
    if not api_key:
        raise ToolExecutionError(
            "web_search_perplexity",
            "api_key_missing",
            "PERPLEXITY_API_KEY not set",
        )
    query = str(args.get("query", "") or "").strip()
    if not query:
        raise ToolExecutionError(
            "web_search_perplexity", "bad_args", "query is required"
        )
    model = str(args.get("model", "sonar") or "sonar")
    transport = _pop_transport(args)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a concise research assistant. Provide "
                    "factual, well-sourced answers with specific numbers "
                    "and citations. Never approximate or guess — only "
                    "state what sources confirm. Be direct."
                ),
            },
            {"role": "user", "content": query},
        ],
        "max_tokens": 1500,
    }
    async with _new_client(transport=transport) as client:
        resp = await client.post(
            "https://api.perplexity.ai/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
    if resp.status_code != 200:
        raise ToolExecutionError(
            "web_search_perplexity",
            "http_error",
            f"Perplexity returned {resp.status_code}: {resp.text[:200]}",
        )
    data = resp.json()
    choices = data.get("choices") or []
    answer = ""
    if choices:
        answer = ((choices[0].get("message") or {}).get("content")) or ""
    citations = data.get("citations") or []
    return {
        "query": query,
        "model": model,
        "answer": answer,
        "citations": list(citations),
    }


async def _web_search_ddg(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """DuckDuckGo instant-answer endpoint — no API key required.

    IWO2 parity: tool-executor.ts:195-219. The DDG instant-answer API
    returns terse abstracts + related-topic stubs; it's a free fallback,
    not a deep search.
    """
    query = str(args.get("query", "") or "").strip()
    if not query:
        raise ToolExecutionError(
            "web_search_ddg", "bad_args", "query is required"
        )
    transport = _pop_transport(args)

    async with _new_client(transport=transport) as client:
        resp = await client.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            },
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise ToolExecutionError(
            "web_search_ddg",
            "http_error",
            f"DuckDuckGo returned {resp.status_code}",
        )
    data = resp.json()
    related: list[dict[str, str]] = []
    for topic in (data.get("RelatedTopics") or [])[:5]:
        text = topic.get("Text") or ""
        first_url = topic.get("FirstURL") or ""
        if text and first_url:
            related.append({"text": text[:300], "url": first_url})
    instant = data.get("Answer") or data.get("AnswerType") or ""
    return {
        "query": query,
        "abstract": data.get("AbstractText") or "",
        "abstract_url": data.get("AbstractURL") or "",
        "instant_answer": instant,
        "related_topics": related,
    }


# ── Web scrape (SSRF-protected) ──────────────────────────────────────


def _extract_text_from_html(html: str) -> tuple[str, str]:
    """Return (title, body_text). Strips script/style/nav/footer first;
    collapses whitespace. Pure function — easy to unit-test."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("title")
    title = ""
    if title_el and title_el.string:
        title = re.sub(r"\s+", " ", title_el.string).strip()
    for tag_name in ("script", "style", "nav", "footer", "header", "noscript"):
        for el in soup.find_all(tag_name):
            el.decompose()
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines + lone whitespace.
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return title, text.strip()


async def _web_scrape(
    conn: asyncpg.Connection,
    args: dict[str, Any],
    client_id: str,
) -> dict[str, Any]:
    """Fetch a URL and extract main text. SSRF-protected.

    IWO2 parity: tool-executor.ts:318-389. Critical difference: SSRF
    validation runs BEFORE any network call (raises
    ToolExecutionError("ssrf_blocked", ...) and the mock transport
    never sees a request).
    """
    url = str(args.get("url", "") or "").strip()
    if not url:
        raise ToolExecutionError("web_scrape", "bad_args", "url is required")
    raw_max = int(args.get("max_chars", 10000) or 10000)
    max_chars = max(500, min(raw_max, 200_000))

    if not _is_safe_url(url):
        # IMPORTANT: raise BEFORE constructing the client so no DNS
        # lookup or connect attempt fires for blocked targets.
        raise ToolExecutionError(
            "web_scrape",
            "ssrf_blocked",
            f"refusing to fetch private/internal URL: {url}",
        )

    transport = _pop_transport(args)
    async with _new_client(transport=transport) as client:
        resp = await client.get(
            url,
            headers={
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,*/*;q=0.8"
                ),
            },
        )
    if resp.status_code != 200:
        raise ToolExecutionError(
            "web_scrape",
            "http_error",
            f"{url} returned {resp.status_code}",
        )
    html = resp.text
    title, text = _extract_text_from_html(html)
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]
    return {
        "url": url,
        "title": title,
        "char_count": len(text),
        "text": text,
        "truncated": truncated,
    }


# ── Registry ─────────────────────────────────────────────────────────


SEARCH_TOOLS: dict[str, ToolDefinition] = {
    "web_search_brave": ToolDefinition(
        name="web_search_brave",
        description=(
            "Brave Search API web search. Returns up to N ranked results "
            "(title/url/snippet). Use for general factual queries when "
            "Brave's index is preferred over Perplexity's summarisation. "
            "Requires BRAVE_SEARCH_API_KEY env var."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_web_search_brave,
    ),
    "web_search_perplexity": ToolDefinition(
        name="web_search_perplexity",
        description=(
            "Perplexity Sonar — AI-summarised search answer with citations. "
            "Best for nuanced research questions where a synthesised "
            "answer + sources is preferable to a raw result list. Requires "
            "PERPLEXITY_API_KEY env var."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "model": {"type": "string", "default": "sonar"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_web_search_perplexity,
    ),
    "web_search_ddg": ToolDefinition(
        name="web_search_ddg",
        description=(
            "DuckDuckGo instant-answer search. No API key required. "
            "Returns abstract + related topics; use as a free fallback "
            "when Brave/Perplexity are unavailable or the query is "
            "definitional."
        ),
        args_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_web_search_ddg,
    ),
    "web_scrape": ToolDefinition(
        name="web_scrape",
        description=(
            "Fetch a public URL and extract the main text. SSRF-protected: "
            "rejects private/loopback/link-local addresses + non-http(s) "
            "schemes BEFORE any network call. Truncates to max_chars "
            "(default 10000)."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {
                    "type": "integer",
                    "minimum": 500,
                    "maximum": 200000,
                    "default": 10000,
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        handler=_web_scrape,
    ),
}


# ── Source extraction (pure; no network) ─────────────────────────────
#
# The four search/scrape handlers each return a different shape. The
# chat surface needs ONE shape to render "Sources" chips under an
# answer, so normalisation lives here next to the handlers that define
# those shapes — if a handler's return shape changes, this function is
# in the same file and the same review.
#
# Pure over (tool_name, result): no conn, no I/O, unit-testable.

_WEB_SOURCE_TOOLS = frozenset(
    {"web_search_brave", "web_search_perplexity", "web_search_ddg", "web_scrape"}
)

_MAX_SOURCES = 8


def _clean_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url.startswith(("http://", "https://")):
        return ""
    return url


def extract_web_sources(
    tool_name: str, result: Any
) -> list[dict[str, str]]:
    """Normalise a search/scrape tool result into `[{title, url}]`.

    Returns `[]` for non-search tools, malformed results, or results
    carrying no usable http(s) URL — the caller renders nothing rather
    than an empty chip row. Deduped by URL, order preserved, capped at
    `_MAX_SOURCES`.
    """
    if tool_name not in _WEB_SOURCE_TOOLS or not isinstance(result, dict):
        return []

    pairs: list[tuple[str, str]] = []

    if tool_name == "web_search_brave":
        for row in result.get("results") or []:
            if isinstance(row, dict):
                pairs.append((str(row.get("title") or ""), row.get("url")))

    elif tool_name == "web_search_perplexity":
        # Sonar citations are bare URL strings; some builds return
        # {url: ...} objects. Accept both.
        for cite in result.get("citations") or []:
            if isinstance(cite, dict):
                pairs.append((str(cite.get("title") or ""), cite.get("url")))
            else:
                pairs.append(("", cite))

    elif tool_name == "web_search_ddg":
        pairs.append(("Abstract", result.get("abstract_url")))
        for topic in result.get("related_topics") or []:
            if isinstance(topic, dict):
                pairs.append((str(topic.get("text") or ""), topic.get("url")))

    elif tool_name == "web_scrape":
        pairs.append((str(result.get("title") or ""), result.get("url")))

    sources: list[dict[str, str]] = []
    seen: set[str] = set()
    for title, raw_url in pairs:
        url = _clean_url(raw_url)
        if not url or url in seen:
            continue
        seen.add(url)
        label = title.strip() or urlparse(url).netloc or url
        sources.append({"title": label[:160], "url": url})
        if len(sources) >= _MAX_SOURCES:
            break
    return sources

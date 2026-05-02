"""Loop Eta Worker G — tests for runtime.tools.search.

Every outbound HTTP request is mocked via `httpx.MockTransport` so CI
never burns real Brave / Perplexity / DuckDuckGo credits. The pattern
mirrors `test_adapter_dispatch._gamma_submit_mock_transport`.

The SSRF block test is the security-critical case: we assert the
handler raises BEFORE the mock transport receives any request.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import pytest

from runtime.aiden_tools import ToolExecutionError
from runtime.tools.search import (
    SEARCH_TOOLS,
    _extract_text_from_html,
    _is_safe_url,
    _web_scrape,
    _web_search_brave,
    _web_search_ddg,
    _web_search_perplexity,
)


# ── Helpers ──────────────────────────────────────────────────────────


class _RecordingTransport(httpx.MockTransport):
    """MockTransport that records the request count + last request so
    SSRF tests can assert the network was never touched. Overrides
    *both* sync and async dispatch entry points; httpx's `AsyncClient`
    routes through `handle_async_request`, so a sync-only override
    misses every recorded call."""

    def __init__(self, handler):  # type: ignore[no-untyped-def]
        super().__init__(handler)
        self.calls: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return super().handle_request(request)

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        self.calls.append(request)
        return await super().handle_async_request(request)


def _mock_brave_transport(num_results: int = 5) -> _RecordingTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "search.brave.com" in str(request.url), str(request.url)
        results = [
            {
                "title": f"Result {i}",
                "url": f"https://example.com/{i}",
                "description": f"<b>Snippet</b> for result {i}",
            }
            for i in range(num_results)
        ]
        return httpx.Response(200, json={"web": {"results": results}})

    return _RecordingTransport(handler)


def _mock_perplexity_transport() -> _RecordingTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "perplexity.ai" in str(request.url), str(request.url)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "Aiden IWO3 is the successor architecture "
                                "branch of AIDEN IWO2."
                            )
                        }
                    }
                ],
                "citations": [
                    "https://aiden.example/spec",
                    "https://aiden.example/runbook",
                ],
            },
        )

    return _RecordingTransport(handler)


def _mock_ddg_transport() -> _RecordingTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "duckduckgo.com" in str(request.url), str(request.url)
        return httpx.Response(
            200,
            json={
                "AbstractText": "Test abstract from DuckDuckGo.",
                "AbstractURL": "https://duckduckgo.com/?q=test",
                "Answer": "",
                "AnswerType": "",
                "RelatedTopics": [
                    {
                        "Text": "Topic one",
                        "FirstURL": "https://example.com/one",
                    },
                    {
                        "Text": "Topic two",
                        "FirstURL": "https://example.com/two",
                    },
                ],
            },
        )

    return _RecordingTransport(handler)


def _mock_scrape_transport(*, body: str, status: int = 200) -> _RecordingTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            text=body,
            headers={"content-type": "text/html; charset=utf-8"},
        )

    return _RecordingTransport(handler)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ── _is_safe_url unit tests ──────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/etc/passwd",
        "http://localhost/",
        "http://0.0.0.0/",
        "http://10.0.0.5/",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata
        "http://internal.local/",
        "http://srv.internal/",
        "http://[::1]/",
        "file:///etc/passwd",
        "gopher://evil.example/",
        "ftp://ftp.example.com/",
        "http:///no-host",
        "not a url",
    ],
)
def test_is_safe_url_blocks_dangerous(url: str) -> None:
    assert _is_safe_url(url) is False, url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "http://example.com/path?q=1",
        "https://api.brave.com/search",
        "https://duckduckgo.com/",
    ],
)
def test_is_safe_url_allows_public(url: str) -> None:
    assert _is_safe_url(url) is True, url


# ── Handler tests ────────────────────────────────────────────────────


def test_brave_search_returns_top_n(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "test-fake-key")
    transport = _mock_brave_transport(num_results=5)
    result = _run(
        _web_search_brave(
            None,  # type: ignore[arg-type]
            {"query": "iwo3 architecture", "max_results": 5, "_transport": transport},
            "00000000-0000-4000-8000-00000000c001",
        )
    )
    assert result["query"] == "iwo3 architecture"
    assert result["result_count"] == 5
    assert len(result["results"]) == 5
    first = result["results"][0]
    assert first["title"] == "Result 0"
    assert first["url"] == "https://example.com/0"
    # HTML stripped from snippet
    assert "<b>" not in first["snippet"]
    assert "Snippet" in first["snippet"]
    assert len(transport.calls) == 1


def test_brave_search_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    transport = _mock_brave_transport()
    with pytest.raises(ToolExecutionError) as exc_info:
        _run(
            _web_search_brave(
                None,  # type: ignore[arg-type]
                {"query": "x", "_transport": transport},
                "client",
            )
        )
    assert exc_info.value.kind == "api_key_missing"
    assert len(transport.calls) == 0  # never touched the network


def test_perplexity_search_returns_ai_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PERPLEXITY_API_KEY", "test-fake-key")
    transport = _mock_perplexity_transport()
    result = _run(
        _web_search_perplexity(
            None,  # type: ignore[arg-type]
            {"query": "what is aiden iwo3", "_transport": transport},
            "client",
        )
    )
    assert result["query"] == "what is aiden iwo3"
    assert result["model"] == "sonar"
    assert "successor architecture" in result["answer"]
    assert len(result["citations"]) == 2
    assert result["citations"][0].startswith("https://")
    assert len(transport.calls) == 1


def test_ddg_search_no_key_required(monkeypatch: pytest.MonkeyPatch) -> None:
    # Explicitly clear any keys to confirm DDG runs without them.
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    transport = _mock_ddg_transport()
    result = _run(
        _web_search_ddg(
            None,  # type: ignore[arg-type]
            {"query": "test", "_transport": transport},
            "client",
        )
    )
    assert result["query"] == "test"
    assert "Test abstract" in result["abstract"]
    assert len(result["related_topics"]) == 2
    assert result["related_topics"][0]["url"].startswith("https://")
    assert len(transport.calls) == 1


def test_web_scrape_blocks_localhost() -> None:
    # The transport handler asserts on call so we know if it ever fires.
    fired: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fired.append(request)
        return httpx.Response(200, text="should not happen")

    transport = httpx.MockTransport(handler)

    with pytest.raises(ToolExecutionError) as exc_info:
        _run(
            _web_scrape(
                None,  # type: ignore[arg-type]
                {
                    "url": "http://127.0.0.1:8080/etc/passwd",
                    "_transport": transport,
                },
                "client",
            )
        )
    assert exc_info.value.kind == "ssrf_blocked"
    assert "127.0.0.1" in exc_info.value.detail
    # CRITICAL: the mock transport must never have been hit.
    assert fired == []


def test_web_scrape_blocks_aws_metadata() -> None:
    """The 169.254.169.254 link-local IP is the AWS/GCP metadata
    endpoint — the canonical SSRF target. Belt-and-braces test."""
    fired: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fired.append(request)
        return httpx.Response(200, text="creds")

    transport = httpx.MockTransport(handler)
    with pytest.raises(ToolExecutionError) as exc_info:
        _run(
            _web_scrape(
                None,  # type: ignore[arg-type]
                {
                    "url": "http://169.254.169.254/latest/meta-data/",
                    "_transport": transport,
                },
                "client",
            )
        )
    assert exc_info.value.kind == "ssrf_blocked"
    assert fired == []


def test_web_scrape_extracts_text_truncates() -> None:
    body = (
        "<html><head><title>The Big Page</title></head>"
        "<body><script>var x = 1;</script>"
        "<nav>nav links</nav>"
        "<h1>Headline</h1>"
        "<p>" + ("hello world " * 5000) + "</p>"
        "<footer>copyright</footer>"
        "</body></html>"
    )
    transport = _mock_scrape_transport(body=body)
    result = _run(
        _web_scrape(
            None,  # type: ignore[arg-type]
            {
                "url": "https://example.com/big",
                "max_chars": 1000,
                "_transport": transport,
            },
            "client",
        )
    )
    assert result["url"] == "https://example.com/big"
    assert result["title"] == "The Big Page"
    assert result["truncated"] is True
    assert result["char_count"] <= 1000
    assert len(result["text"]) <= 1000
    # Script + nav + footer must be stripped
    assert "var x = 1" not in result["text"]
    assert "nav links" not in result["text"]
    assert "copyright" not in result["text"]
    # Body content survives
    assert "hello world" in result["text"]


def test_web_scrape_short_body_not_truncated() -> None:
    body = "<html><head><title>Short</title></head><body><p>Tiny body.</p></body></html>"
    transport = _mock_scrape_transport(body=body)
    result = _run(
        _web_scrape(
            None,  # type: ignore[arg-type]
            {
                "url": "https://example.com/short",
                "max_chars": 10000,
                "_transport": transport,
            },
            "client",
        )
    )
    assert result["title"] == "Short"
    assert result["truncated"] is False
    assert "Tiny body" in result["text"]
    assert result["char_count"] == len(result["text"])


# ── Registry shape ───────────────────────────────────────────────────


def test_search_tools_registry_has_four_runnable_handlers() -> None:
    assert set(SEARCH_TOOLS.keys()) == {
        "web_search_brave",
        "web_search_perplexity",
        "web_search_ddg",
        "web_scrape",
    }
    for name, td in SEARCH_TOOLS.items():
        assert td.name == name
        assert callable(td.handler)
        assert td.args_schema["type"] == "object"


def test_extract_text_from_html_strips_script_style() -> None:
    html = (
        "<html><head><title>T</title><style>.x{color:red}</style></head>"
        "<body><script>alert('xss')</script><p>Visible.</p></body></html>"
    )
    title, text = _extract_text_from_html(html)
    assert title == "T"
    assert "alert" not in text
    assert ".x{color" not in text
    assert "Visible." in text


# Quiet pytest about unused imports if linter ever runs against test file:
_ = os

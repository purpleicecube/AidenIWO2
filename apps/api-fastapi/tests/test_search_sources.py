"""Open-search surfacing — `extract_web_sources` normalisation.

The four search/scrape handlers each return a different shape. The chat
surface renders ONE shape. These tests pin the mapping for every handler
plus the malformed/hostile cases, with no network: `extract_web_sources`
is a pure function over (tool_name, result).
"""

from __future__ import annotations

# `runtime.tools.search` is imported by `runtime.aiden_tools` at module
# bottom (registry convergence). Import the parent first so the cycle
# resolves — same ordering as `test_tools_search.py`.
import runtime.aiden_tools  # noqa: F401
from runtime.tools.search import extract_web_sources


def test_brave_results_map_to_title_url() -> None:
    result = {
        "query": "sedgwick ceo",
        "result_count": 2,
        "results": [
            {"title": "Sedgwick names CEO", "url": "https://sedgwick.com/pr", "snippet": "x"},
            {"title": "Profile", "url": "https://linkedin.com/in/x", "snippet": "y"},
        ],
    }
    out = extract_web_sources("web_search_brave", result)
    assert out == [
        {"title": "Sedgwick names CEO", "url": "https://sedgwick.com/pr"},
        {"title": "Profile", "url": "https://linkedin.com/in/x"},
    ]


def test_perplexity_accepts_bare_string_citations() -> None:
    """Sonar returns bare URL strings; the title falls back to netloc so
    the chip is still readable."""
    out = extract_web_sources(
        "web_search_perplexity",
        {"answer": "…", "citations": ["https://example.com/a"]},
    )
    assert out == [{"title": "example.com", "url": "https://example.com/a"}]


def test_perplexity_accepts_object_citations() -> None:
    out = extract_web_sources(
        "web_search_perplexity",
        {"citations": [{"title": "Doc", "url": "https://example.com/b"}]},
    )
    assert out == [{"title": "Doc", "url": "https://example.com/b"}]


def test_ddg_maps_abstract_and_related() -> None:
    out = extract_web_sources(
        "web_search_ddg",
        {
            "abstract_url": "https://en.wikipedia.org/wiki/X",
            "related_topics": [{"text": "Topic A", "url": "https://duckduckgo.com/A"}],
        },
    )
    assert out == [
        {"title": "Abstract", "url": "https://en.wikipedia.org/wiki/X"},
        {"title": "Topic A", "url": "https://duckduckgo.com/A"},
    ]


def test_scrape_maps_single_page() -> None:
    out = extract_web_sources(
        "web_scrape",
        {"url": "https://example.com/p", "title": "Page", "text": "…"},
    )
    assert out == [{"title": "Page", "url": "https://example.com/p"}]


def test_non_search_tool_yields_nothing() -> None:
    """A runtime tool must not produce web-source chips."""
    assert extract_web_sources("runtime_health", {"db": "ok"}) == []


def test_malformed_result_yields_nothing() -> None:
    for bad in (None, "a string", 42, [], {"results": "not-a-list"}):
        assert extract_web_sources("web_search_brave", bad) == []


def test_non_http_urls_are_dropped() -> None:
    """No javascript:/file:/data: URLs reach a rendered link."""
    out = extract_web_sources(
        "web_search_brave",
        {
            "results": [
                {"title": "bad", "url": "javascript:alert(1)"},
                {"title": "also bad", "url": "file:///etc/passwd"},
                {"title": "good", "url": "https://ok.example"},
            ]
        },
    )
    assert out == [{"title": "good", "url": "https://ok.example"}]


def test_duplicate_urls_collapse_preserving_order() -> None:
    out = extract_web_sources(
        "web_search_brave",
        {
            "results": [
                {"title": "first", "url": "https://a.example"},
                {"title": "dupe", "url": "https://a.example"},
                {"title": "second", "url": "https://b.example"},
            ]
        },
    )
    assert [s["url"] for s in out] == ["https://a.example", "https://b.example"]
    assert out[0]["title"] == "first"


def test_source_list_is_capped() -> None:
    many = {"results": [{"title": f"r{i}", "url": f"https://e{i}.example"} for i in range(30)]}
    assert len(extract_web_sources("web_search_brave", many)) == 8


def test_missing_title_falls_back_to_netloc() -> None:
    out = extract_web_sources(
        "web_search_brave", {"results": [{"title": "", "url": "https://news.example/x"}]}
    )
    assert out == [{"title": "news.example", "url": "https://news.example/x"}]

"""Loop Iota — Memory V1 token budget allocator.

Pure functions: no DB, no I/O. Given a list of MemorySource, allocate
under the 2K token ceiling using the deterministic priority order from
types.SOURCE_PRIORITY. Truncation drops scratch first, then workspace
retrieval, then chat history. Canonical facts is never truncated; if
the canonical-facts blob alone exceeds the budget, it is truncated at
the character level (better than dropping it entirely — it is the
authoritative source).
"""

from __future__ import annotations

from typing import Optional

from .types import (
    CHARS_PER_TOKEN,
    MEMORY_BUDGET_TOKENS,
    MemorySource,
    SOURCE_PRIORITY,
)


def estimate_tokens(text: str) -> int:
    """Cheap chars/4 approximation matching tier_1_aiden's pre-flight
    budget gate. Real provider counts are logged after the call."""
    if not text:
        return 0
    # Round up so we never under-count.
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate `text` to fit within `max_tokens`. Cuts at a paragraph
    boundary if one exists in the last 20% of the truncation window so
    the LLM sees coherent prose, otherwise hard-cuts at the char limit.
    """
    if max_tokens <= 0 or not text:
        return ""
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    # Look for a paragraph boundary in the last 20% of the window.
    window_start = int(max_chars * 0.8)
    last_pp = cut.rfind("\n\n", window_start)
    if last_pp != -1:
        return cut[:last_pp].rstrip() + "\n\n[...truncated]"
    return cut.rstrip() + " [...truncated]"


def allocate(
    sources: list[MemorySource],
    budget: int = MEMORY_BUDGET_TOKENS,
) -> tuple[list[MemorySource], list[str]]:
    """Allocate `sources` under `budget`, returning (kept, truncated_kinds).

    Algorithm:
      1. Sort by SOURCE_PRIORITY (canonical_facts first).
      2. Walk in order. If adding the next source fits, keep verbatim.
         If it doesn't fit but the source is canonical_facts, truncate
         it to whatever fits (and record the truncation).
      3. For any non-canonical source that doesn't fit, truncate it to
         the remaining budget if any tokens remain; otherwise drop the
         source entirely (record truncation/drop).
      4. Walks within a single kind preserve input order — caller is
         responsible for ranking within a kind (e.g. chat history newest
         last; workspace retrieval highest-score first).
    """
    by_priority = sorted(
        sources, key=lambda s: (SOURCE_PRIORITY.get(s.kind, 99))
    )
    kept: list[MemorySource] = []
    truncated_kinds: set[str] = set()
    remaining = budget

    for src in by_priority:
        if remaining <= 0:
            truncated_kinds.add(src.kind)
            continue
        if src.tokens <= remaining:
            kept.append(src)
            remaining -= src.tokens
            continue
        # Doesn't fit. Decide truncate vs drop.
        if src.kind == "canonical_facts":
            # Never drop canonical_facts. Truncate to remaining.
            new_text = truncate_to_tokens(src.text, remaining)
            new_tokens = estimate_tokens(new_text)
            kept.append(
                MemorySource(
                    kind=src.kind,
                    client_id=src.client_id,
                    record_id=src.record_id,
                    text=new_text,
                    tokens=new_tokens,
                    owner_user_id=src.owner_user_id,
                    metadata={**src.metadata, "truncated": True},
                )
            )
            truncated_kinds.add(src.kind)
            remaining -= new_tokens
            continue
        # Non-canonical source that doesn't fit. Try to keep something.
        if remaining >= 32:  # below this it's not worth a partial chunk
            new_text = truncate_to_tokens(src.text, remaining)
            new_tokens = estimate_tokens(new_text)
            kept.append(
                MemorySource(
                    kind=src.kind,
                    client_id=src.client_id,
                    record_id=src.record_id,
                    text=new_text,
                    tokens=new_tokens,
                    owner_user_id=src.owner_user_id,
                    metadata={**src.metadata, "truncated": True},
                )
            )
            remaining -= new_tokens
        truncated_kinds.add(src.kind)

    return kept, sorted(truncated_kinds)


_GROUNDING_RULES_PREAMBLE = """## GROUNDING RULES
- Use ONLY the facts, data, metrics, and quotes found in the sources below.
- Do NOT invent or extrapolate numbers, statistics, or claims absent from the source content.
- If the sources do not contain specific data needed, say so explicitly rather than fabricating.
- When citing a source, reference its filename or path so the operator can verify."""


def _format_citation_line(src: MemorySource) -> str:
    """One line per kept source for the end-of-block CITATIONS index.

    Format:  `[<short_id>] <kind> — <filename or label> (<score or revision>)`

    The short_id is the first 8 chars of `record_id` plus the kind
    prefix so operators can match a citation back to its section.
    """
    short_id = (src.record_id or "")[:8] or "?"
    fn = src.metadata.get("filename")
    if not fn:
        if src.kind == "canonical_facts":
            fn = f"canonical_facts (rev {src.metadata.get('revision', '?')})"
        elif src.kind == "folder_listing":
            fn = src.metadata.get("root_path") or "folder_listing"
        elif src.kind == "chat_history":
            fn = f"chat_session ({src.metadata.get('turn_count', '?')} turns)"
        else:
            fn = "(unnamed)"
    score = src.metadata.get("score")
    score_label = (
        f" score={score:.2f}"
        if isinstance(score, float) and src.kind not in {"canonical_facts", "chat_history", "folder_listing"}
        else ""
    )
    return f"- [{short_id}] {src.kind} — {fn}{score_label}"


def render_block(sources: list[MemorySource]) -> str:
    """Concatenate kept sources into the final memory block string.

    Loop Kappa render order (matches SOURCE_PRIORITY):
        ## GROUNDING RULES (preamble — anti-hallucination posture)
        ## CANONICAL FACTS (authoritative)
        ## PATH-TARGETED FILES
        ## FOLDER LISTING
        ## FILENAME MATCHES
        ## WORKSPACE GROUNDING (tsquery)
        ## RECENT CHAT HISTORY
        ## OPERATOR SCRATCH
        ## CITATIONS (one line per kept source)

    Empty bundle returns empty string.
    """
    if not sources:
        return ""
    by_priority = sorted(
        sources, key=lambda s: (SOURCE_PRIORITY.get(s.kind, 99))
    )
    sections: dict[str, list[MemorySource]] = {}
    for src in by_priority:
        sections.setdefault(src.kind, []).append(src)

    parts: list[str] = ["[MEMORY CONTEXT — tenant-validated]"]
    parts.append("")
    parts.append(_GROUNDING_RULES_PREAMBLE)

    if "canonical_facts" in sections:
        parts.append("\n## CANONICAL FACTS (authoritative)")
        for src in sections["canonical_facts"]:
            parts.append(src.text.rstrip())

    if "path_targeted" in sections:
        parts.append("\n## PATH-TARGETED FILES")
        for src in sections["path_targeted"]:
            fn = src.metadata.get("filename") or "(unnamed)"
            folder = src.metadata.get("folder_path") or ""
            label = f"{folder}/{fn}" if folder else fn
            parts.append(f"\n### {label}")
            parts.append(src.text.rstrip())

    if "folder_listing" in sections:
        parts.append("\n## FOLDER LISTING")
        for src in sections["folder_listing"]:
            parts.append(src.text.rstrip())

    if "filename_match" in sections:
        parts.append("\n## FILENAME MATCHES")
        for src in sections["filename_match"]:
            fn = src.metadata.get("filename") or "(unnamed)"
            parts.append(f"\n### {fn}")
            parts.append(src.text.rstrip())

    if "workspace_retrieval" in sections:
        parts.append("\n## WORKSPACE GROUNDING")
        for src in sections["workspace_retrieval"]:
            fn = src.metadata.get("filename") or "(unnamed)"
            score = src.metadata.get("score")
            score_label = f" (score={score:.2f})" if isinstance(score, float) else ""
            parts.append(f"\n### {fn}{score_label}")
            parts.append(src.text.rstrip())

    if "chat_history" in sections:
        parts.append("\n## RECENT CHAT HISTORY")
        for src in sections["chat_history"]:
            parts.append(src.text.rstrip())

    if "scratch_retrieval" in sections:
        parts.append("\n## OPERATOR SCRATCH")
        for src in sections["scratch_retrieval"]:
            fn = src.metadata.get("filename") or "(unnamed)"
            score = src.metadata.get("score")
            score_label = f" (score={score:.2f})" if isinstance(score, float) else ""
            parts.append(f"\n### {fn}{score_label}")
            parts.append(src.text.rstrip())

    # End-of-block citation index. Lists every kept source by short id
    # + kind + filename so the LLM can cite verifiably.
    parts.append("\n## CITATIONS")
    for src in by_priority:
        parts.append(_format_citation_line(src))

    parts.append("\n[END MEMORY CONTEXT]")
    return "\n".join(parts)

"""Loop Iota — Memory V1 deterministic source assembly.

One composite asyncpg query that pulls every memory source in a single
DB round-trip. Per scope §D2 + performance budget P0 #1.

CTE structure:
  client_row     — clients row for memory_enabled + canonical_facts_*
  recent_chat    — operator's chat_sessions row (most recent N turns)
  workspace_hits — top-N artifacts matching tsquery, scored
  scratch_hits   — top-N artifacts under operator's scratch subtree
                   matching tsquery (only when scratch intent regex
                   matched; otherwise CTE returns empty)

Every CTE carries explicit `client_id = $1` predicates (firewall Layer
3 belt + RLS hard wall).

Top-N is RETRIEVAL_TOP_N (=3). Search uses `plainto_tsquery('english', $)`
against the GIN-indexed `extracted_text_tsv` column added by migration
0025.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

import asyncpg

from . import cache
from .budget import estimate_tokens
from .types import (
    CHAT_HISTORY_TURNS,
    RETRIEVAL_TOP_N,
    MemorySource,
)


# Operator scratch retrieval gate. Per scope §D Phase ι.3 + firewall
# package §"strict rules": owner-scoped only, regex-only, no LLM
# classifier. Common ways operators reference their private scratch.
_SCRATCH_INTENT_RE = re.compile(
    r"\bmy\s+(?:scratch|notes?|drafts?|memos?|files?|workspace)\b",
    re.IGNORECASE,
)


def _intent_matches_scratch(intake_text: str) -> bool:
    return bool(_SCRATCH_INTENT_RE.search(intake_text))


def _build_tsquery_from_intake(intake_text: str) -> Optional[str]:
    """Build a plainto_tsquery-safe term string from the intake text.

    Strategy: keep alpha tokens length >=3 from the first 200 chars.
    Drop common stopwords. Cap at 8 terms. Returns None if no useful
    terms (caller skips retrieval).
    """
    head = (intake_text or "")[:200].lower()
    raw = re.findall(r"[a-z][a-z0-9]{2,}", head)
    stop = {
        "the", "and", "but", "for", "with", "this", "that", "from", "into",
        "what", "when", "where", "why", "how", "are", "you", "your", "our",
        "have", "has", "can", "could", "should", "would", "will", "any",
        "tell", "give", "show", "find", "make", "build", "want", "need",
        "tier", "deck", "pdf", "html",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for t in raw:
        if t in stop or t in seen:
            continue
        seen.add(t)
        terms.append(t)
        if len(terms) >= 8:
            break
    if not terms:
        return None
    return " ".join(terms)


async def fetch_memory_inputs(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    user_id: str,
    intake_text: str,
) -> dict:
    """Run the composite query, return raw rows for the builder to
    transform into MemorySource objects. Single DB round-trip.

    Returns a dict with keys:
      - client: dict | None        the clients row
      - chat: dict | None          the chat_sessions row (or None if absent)
      - workspace: list[dict]      top-N artifact matches (tenant-scoped)
      - scratch: list[dict]        top-N scratch matches (tenant + owner-scoped),
                                   empty when intent didn't match
    """
    tsquery_terms = _build_tsquery_from_intake(intake_text)
    do_workspace = tsquery_terms is not None
    do_scratch = do_workspace and _intent_matches_scratch(intake_text)

    # The composite query. CTEs that wouldn't run (no tsquery) still
    # appear but yield zero rows because we pass NULL for the terms.
    sql = """
        WITH
        client_row AS (
            SELECT id::text AS id,
                   memory_enabled,
                   canonical_facts_blob,
                   canonical_facts_revision
            FROM clients
            WHERE id = $1::uuid
        ),
        recent_chat AS (
            SELECT id::text          AS id,
                   user_id::text     AS user_id,
                   client_id::text   AS client_id,
                   messages,
                   updated_at
            FROM chat_sessions
            WHERE client_id = $1::uuid
              AND user_id = $2::uuid
        ),
        workspace_hits AS (
            SELECT a.id::text                          AS id,
                   a.client_id::text                   AS client_id,
                   a.filename                          AS filename,
                   a.workspace_folder_id::text         AS workspace_folder_id,
                   substring(coalesce(a.extracted_text, '') FROM 1 FOR 2400) AS excerpt,
                   ts_rank_cd(a.extracted_text_tsv,
                              plainto_tsquery('english', $3)) AS score
            FROM artifacts a
            WHERE $3::text IS NOT NULL
              AND $4::boolean = true
              AND a.client_id = $1::uuid
              AND a.extracted_text IS NOT NULL
              AND a.extracted_text_tsv @@ plainto_tsquery('english', $3)
              AND NOT EXISTS (
                  SELECT 1 FROM workspace_folders wf
                  WHERE wf.id = a.workspace_folder_id
                    AND wf.client_id = $1::uuid
                    AND wf.owner_user_id IS NOT NULL
              )
            ORDER BY score DESC
            LIMIT $5::int
        ),
        scratch_hits AS (
            SELECT a.id::text                          AS id,
                   a.client_id::text                   AS client_id,
                   wf.owner_user_id::text              AS owner_user_id,
                   a.filename                          AS filename,
                   wf.name                             AS folder_name,
                   substring(coalesce(a.extracted_text, '') FROM 1 FOR 2400) AS excerpt,
                   ts_rank_cd(a.extracted_text_tsv,
                              plainto_tsquery('english', $3)) AS score
            FROM artifacts a
            JOIN workspace_folders wf
              ON wf.id = a.workspace_folder_id
            WHERE $3::text IS NOT NULL
              AND $6::boolean = true
              AND a.client_id = $1::uuid
              AND wf.client_id = $1::uuid
              AND wf.owner_user_id = $2::uuid
              AND a.extracted_text IS NOT NULL
              AND a.extracted_text_tsv @@ plainto_tsquery('english', $3)
            ORDER BY score DESC
            LIMIT $5::int
        )
        SELECT
            (SELECT row_to_json(c) FROM client_row c)              AS client_json,
            (SELECT row_to_json(r) FROM recent_chat r)             AS chat_json,
            COALESCE(
                (SELECT json_agg(w ORDER BY w.score DESC) FROM workspace_hits w),
                '[]'::json
            )                                                       AS workspace_json,
            COALESCE(
                (SELECT json_agg(s ORDER BY s.score DESC) FROM scratch_hits s),
                '[]'::json
            )                                                       AS scratch_json
    """

    row = await conn.fetchrow(
        sql,
        client_id,
        user_id,
        tsquery_terms,
        do_workspace,
        RETRIEVAL_TOP_N,
        do_scratch,
    )

    def _maybe_json(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return default
        return value

    return {
        "client": _maybe_json(row["client_json"], None) if row else None,
        "chat": _maybe_json(row["chat_json"], None) if row else None,
        "workspace": _maybe_json(row["workspace_json"], []) if row else [],
        "scratch": _maybe_json(row["scratch_json"], []) if row else [],
    }


def _format_chat_turn(turn: dict) -> Optional[str]:
    """Format one chat_sessions message for the memory block. Returns
    None if the turn shape is unrecognised (drop silently)."""
    if not isinstance(turn, dict):
        return None
    role = turn.get("role") or turn.get("author") or turn.get("speaker")
    content = (
        turn.get("content")
        or turn.get("text")
        or turn.get("message")
        or turn.get("body")
    )
    if not content:
        return None
    if isinstance(content, dict):
        # Aiden assistant_reply turns may carry a dict shape.
        content = content.get("message") or content.get("headline") or ""
    if not isinstance(content, str) or not content.strip():
        return None
    role_label = (role or "operator").lower()
    return f"- {role_label}: {content.strip()[:600]}"


def assemble_sources(
    inputs: dict,
    *,
    client_id: str,
    user_id: str,
) -> tuple[list[MemorySource], dict]:
    """Transform raw inputs into MemorySource list. Returns (sources, summary).

    The summary dict carries non-source signals the caller might want
    in audit metadata: cache_hits[], canonical_revision, etc.
    """
    sources: list[MemorySource] = []
    cache_hits: list[str] = []

    client_row = inputs.get("client") or {}
    revision = int(client_row.get("canonical_facts_revision") or 0)

    # Canonical facts: prefer cache; fall back to DB blob; cache the blob.
    blob: Optional[str] = cache.get_canonical_facts(client_id, revision)
    if blob is not None:
        cache_hits.append("canonical_facts")
    else:
        blob = client_row.get("canonical_facts_blob")
        if blob:
            cache.put_canonical_facts(client_id, revision, blob)

    if blob and blob.strip():
        sources.append(
            MemorySource(
                kind="canonical_facts",
                client_id=client_id,
                record_id=f"{client_id}:rev{revision}",
                text=blob.strip(),
                tokens=estimate_tokens(blob),
                owner_user_id=None,
                metadata={"revision": revision, "cache_hit": "canonical_facts" in cache_hits},
            )
        )

    # Chat history.
    chat_row = inputs.get("chat")
    if chat_row and isinstance(chat_row.get("messages"), list):
        msgs = chat_row["messages"]
        # Take the last CHAT_HISTORY_TURNS turns. Older turns drop first.
        recent = msgs[-CHAT_HISTORY_TURNS:]
        formatted_lines: list[str] = []
        for turn in recent:
            formatted = _format_chat_turn(turn)
            if formatted:
                formatted_lines.append(formatted)
        if formatted_lines:
            text = "\n".join(formatted_lines)
            sources.append(
                MemorySource(
                    kind="chat_history",
                    client_id=chat_row["client_id"],
                    record_id=chat_row["id"],
                    text=text,
                    tokens=estimate_tokens(text),
                    owner_user_id=user_id,
                    metadata={
                        "turn_count": len(formatted_lines),
                        "session_id": chat_row["id"],
                    },
                )
            )

    # Workspace retrieval.
    for hit in inputs.get("workspace", []) or []:
        excerpt = (hit.get("excerpt") or "").strip()
        if not excerpt:
            continue
        sources.append(
            MemorySource(
                kind="workspace_retrieval",
                client_id=hit["client_id"],
                record_id=hit["id"],
                text=excerpt,
                tokens=estimate_tokens(excerpt),
                owner_user_id=None,
                metadata={
                    "filename": hit.get("filename"),
                    "score": float(hit.get("score") or 0.0),
                    "workspace_folder_id": hit.get("workspace_folder_id"),
                },
            )
        )

    # Scratch retrieval (already gated on owner_user_id by the SQL JOIN
    # but the validator will also assert it).
    for hit in inputs.get("scratch", []) or []:
        excerpt = (hit.get("excerpt") or "").strip()
        if not excerpt:
            continue
        sources.append(
            MemorySource(
                kind="scratch_retrieval",
                client_id=hit["client_id"],
                record_id=hit["id"],
                text=excerpt,
                tokens=estimate_tokens(excerpt),
                owner_user_id=hit.get("owner_user_id"),
                metadata={
                    "filename": hit.get("filename"),
                    "folder_name": hit.get("folder_name"),
                    "score": float(hit.get("score") or 0.0),
                },
            )
        )

    summary = {
        "cache_hits": cache_hits,
        "canonical_revision": revision,
        "memory_enabled_per_tenant": bool(client_row.get("memory_enabled", True)),
    }
    return sources, summary

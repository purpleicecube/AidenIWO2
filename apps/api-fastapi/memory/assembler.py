"""Loop Iota — Memory V1 deterministic source assembly.
   Loop Kappa — extended for path / filename / folder-listing intent.

One composite asyncpg query that pulls every memory source in a single
DB round-trip. Per scope §D2 + performance budget P0 #1.

CTE structure (Loop Iota):
  client_row     — clients row for memory_enabled + canonical_facts_*
  recent_chat    — operator's chat_sessions row (most recent N turns)
  workspace_hits — top-N artifacts matching tsquery, scored
  scratch_hits   — top-N artifacts under operator's scratch subtree
                   matching tsquery (only when scratch intent regex
                   matched; otherwise CTE returns empty)

CTE additions (Loop Kappa):
  folder_paths    — recursive CTE building full path for every
                    workspace folder under the active tenant
  matched_folders — folders whose full path or terminal segment matches
                    one of the operator's parsed `paths[]`
  path_hits       — artifacts directly under a matched folder, score 1.0
  filename_hits   — artifacts whose `filename ILIKE` any operator-named
                    term, score 0.7 (parity with IWO2 keyword + filename
                    overlap)

Every CTE carries explicit `client_id = $1` predicates (firewall Layer
3 belt + RLS hard wall).

Folder listing (`MemorySource(kind="folder_listing")`) is synthesized
in Python from a small follow-up query when `wants_folder_listing` is
true. Structural traversal data is awkward to express as scored
retrieval — keeping it Python-side preserves the assembler's
"all sources are scored hits" mental model.

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
from .intent_parser import ContextIntent
from .types import (
    CHAT_HISTORY_TURNS,
    FOLDER_LISTING_MAX_FILES,
    FOLDER_LISTING_MAX_SUBFOLDERS,
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


def _path_terminals(paths: list[str]) -> list[str]:
    """Last `/`-segment of each path. Empty paths skipped."""
    out: list[str] = []
    for p in paths:
        if not p:
            continue
        seg = p.rstrip("/").split("/")[-1]
        if seg and seg not in out:
            out.append(seg)
    return out


async def fetch_memory_inputs(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    user_id: str,
    intake_text: str,
    intent: Optional[ContextIntent] = None,
) -> dict:
    """Run the composite query, return raw rows for the builder to
    transform into MemorySource objects. Single DB round-trip for the
    main bundle; one optional follow-up when `wants_folder_listing`.

    Returns a dict with keys:
      - client: dict | None        the clients row
      - chat: dict | None          the chat_sessions row (or None if absent)
      - workspace: list[dict]      top-N artifact matches (tenant-scoped)
      - scratch: list[dict]        top-N scratch matches (tenant + owner-scoped)
      - path_hits: list[dict]      artifacts under operator-named folder paths
      - filename_hits: list[dict]  artifacts whose filename matches an operator term
      - folder_listing: dict | None  {root_path, subfolders[], files[]}
    """
    intent = intent or ContextIntent()
    tsquery_terms = _build_tsquery_from_intake(intake_text)
    do_workspace = tsquery_terms is not None
    do_scratch = do_workspace and _intent_matches_scratch(intake_text)

    paths_list = list(intent.paths)
    path_terminals = _path_terminals(paths_list)
    do_path_hits = bool(paths_list)

    filename_list = list(intent.filename_terms)
    do_filename_hits = bool(filename_list)

    # The composite query. CTEs that wouldn't run (no tsquery, no
    # paths, no filenames) still appear but yield zero rows because we
    # pass NULL/empty arrays for their inputs.
    sql = """
        WITH RECURSIVE
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
        ),
        folder_paths AS (
            SELECT id, name::text AS name,
                   parent_folder_id, 0 AS depth,
                   name::text AS full_path
            FROM workspace_folders
            WHERE client_id = $1::uuid
              AND parent_folder_id IS NULL
              AND deleted_at IS NULL
            UNION ALL
            SELECT wf.id, wf.name::text,
                   wf.parent_folder_id, fp.depth + 1,
                   (fp.full_path || '/' || wf.name)::text
            FROM workspace_folders wf
            JOIN folder_paths fp ON wf.parent_folder_id = fp.id
            WHERE wf.client_id = $1::uuid
              AND wf.deleted_at IS NULL
              AND fp.depth < 8
        ),
        matched_folders AS (
            SELECT fp.id, fp.full_path, fp.name
            FROM folder_paths fp
            WHERE $7::boolean = true
              AND (
                  fp.full_path = ANY($8::text[])
                  OR fp.name = ANY($9::text[])
              )
        ),
        path_hits AS (
            SELECT a.id::text                  AS id,
                   a.client_id::text           AS client_id,
                   a.filename                  AS filename,
                   a.workspace_folder_id::text AS workspace_folder_id,
                   mf.full_path                AS folder_path,
                   substring(coalesce(a.extracted_text, '') FROM 1 FOR 2400) AS excerpt
            FROM artifacts a
            JOIN matched_folders mf ON a.workspace_folder_id = mf.id
            WHERE a.client_id = $1::uuid
              AND NOT EXISTS (
                  SELECT 1 FROM workspace_folders wf
                  WHERE wf.id = a.workspace_folder_id
                    AND wf.client_id = $1::uuid
                    AND wf.owner_user_id IS NOT NULL
              )
            ORDER BY mf.full_path, a.filename
            LIMIT $5::int
        ),
        filename_hits AS (
            SELECT a.id::text                  AS id,
                   a.client_id::text           AS client_id,
                   a.filename                  AS filename,
                   a.workspace_folder_id::text AS workspace_folder_id,
                   substring(coalesce(a.extracted_text, '') FROM 1 FOR 2400) AS excerpt
            FROM artifacts a
            WHERE $10::boolean = true
              AND a.client_id = $1::uuid
              AND a.filename ILIKE ANY(
                  SELECT '%' || term || '%'
                  FROM unnest($11::text[]) AS term
              )
              AND NOT EXISTS (
                  SELECT 1 FROM workspace_folders wf
                  WHERE wf.id = a.workspace_folder_id
                    AND wf.client_id = $1::uuid
                    AND wf.owner_user_id IS NOT NULL
              )
            ORDER BY a.filename
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
            )                                                       AS scratch_json,
            COALESCE(
                (SELECT json_agg(p) FROM path_hits p),
                '[]'::json
            )                                                       AS path_hits_json,
            COALESCE(
                (SELECT json_agg(f) FROM filename_hits f),
                '[]'::json
            )                                                       AS filename_hits_json
    """

    row = await conn.fetchrow(
        sql,
        client_id,                   # $1
        user_id,                     # $2
        tsquery_terms,               # $3
        do_workspace,                # $4
        RETRIEVAL_TOP_N,             # $5
        do_scratch,                  # $6
        do_path_hits,                # $7
        paths_list,                  # $8
        path_terminals,              # $9
        do_filename_hits,            # $10
        filename_list,               # $11
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

    out = {
        "client": _maybe_json(row["client_json"], None) if row else None,
        "chat": _maybe_json(row["chat_json"], None) if row else None,
        "workspace": _maybe_json(row["workspace_json"], []) if row else [],
        "scratch": _maybe_json(row["scratch_json"], []) if row else [],
        "path_hits": _maybe_json(row["path_hits_json"], []) if row else [],
        "filename_hits": _maybe_json(row["filename_hits_json"], []) if row else [],
        "folder_listing": None,
    }

    # Optional follow-up: if operator wants a folder listing AND we
    # have at least one matched path, fetch the structural directory
    # data for the FIRST matched path. Multiple folder listings would
    # blow the token budget; pick the most specific (longest path).
    if intent.wants_folder_listing and paths_list:
        out["folder_listing"] = await _fetch_folder_listing(
            conn,
            client_id=client_id,
            paths=paths_list,
        )

    return out


async def _fetch_folder_listing(
    conn: asyncpg.Connection,
    *,
    client_id: str,
    paths: list[str],
) -> Optional[dict]:
    """Return a structural directory map for the most specific matched
    path, capped at FOLDER_LISTING_MAX_SUBFOLDERS subfolders +
    FOLDER_LISTING_MAX_FILES files. Returns None if no path matched.

    Output shape:
        {
          "root_path": "04_Resources/Demo_Content",
          "subfolders": [{"name": "...", "file_count": N}, ...],
          "files":      [{"filename": "...", "extracted_size": N}, ...],
          "subfolder_truncated": bool,
          "file_truncated": bool,
        }
    """
    path_terminals = _path_terminals(paths)
    sql = """
        WITH RECURSIVE folder_paths AS (
            SELECT id, name::text AS name,
                   parent_folder_id, 0 AS depth,
                   name::text AS full_path
            FROM workspace_folders
            WHERE client_id = $1::uuid
              AND parent_folder_id IS NULL
              AND deleted_at IS NULL
            UNION ALL
            SELECT wf.id, wf.name::text,
                   wf.parent_folder_id, fp.depth + 1,
                   (fp.full_path || '/' || wf.name)::text
            FROM workspace_folders wf
            JOIN folder_paths fp ON wf.parent_folder_id = fp.id
            WHERE wf.client_id = $1::uuid
              AND wf.deleted_at IS NULL
              AND fp.depth < 8
        ),
        matched AS (
            SELECT id, full_path, name
            FROM folder_paths
            WHERE full_path = ANY($2::text[])
               OR name = ANY($3::text[])
            -- Pick most specific: longest full_path wins.
            ORDER BY length(full_path) DESC
            LIMIT 1
        )
        SELECT m.id::text          AS root_id,
               m.full_path         AS root_path,
               COALESCE(
                   (
                       SELECT json_agg(sub)
                       FROM (
                           SELECT wf.name::text                     AS name,
                                  (
                                      SELECT count(*)::int
                                      FROM artifacts ax
                                      WHERE ax.workspace_folder_id = wf.id
                                        AND ax.client_id = $1::uuid
                                  ) AS file_count
                           FROM workspace_folders wf
                           WHERE wf.parent_folder_id = m.id
                             AND wf.client_id = $1::uuid
                             AND wf.deleted_at IS NULL
                           ORDER BY wf.name
                           LIMIT $4::int + 1
                       ) sub
                   ),
                   '[]'::json
               )                   AS subfolders_json,
               COALESCE(
                   (
                       SELECT json_agg(f)
                       FROM (
                           SELECT a.filename::text                  AS filename,
                                  COALESCE(length(a.extracted_text), 0) AS extracted_size
                           FROM artifacts a
                           WHERE a.workspace_folder_id = m.id
                             AND a.client_id = $1::uuid
                           ORDER BY a.filename
                           LIMIT $5::int + 1
                       ) f
                   ),
                   '[]'::json
               )                   AS files_json
        FROM matched m
    """
    row = await conn.fetchrow(
        sql,
        client_id,
        paths,
        path_terminals,
        FOLDER_LISTING_MAX_SUBFOLDERS,
        FOLDER_LISTING_MAX_FILES,
    )
    if not row:
        return None

    def _maybe_json(value: Any, default: Any) -> Any:
        if value is None:
            return default
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return default
        return value

    subs = _maybe_json(row["subfolders_json"], [])
    files = _maybe_json(row["files_json"], [])
    sub_truncated = len(subs) > FOLDER_LISTING_MAX_SUBFOLDERS
    file_truncated = len(files) > FOLDER_LISTING_MAX_FILES
    if sub_truncated:
        subs = subs[:FOLDER_LISTING_MAX_SUBFOLDERS]
    if file_truncated:
        files = files[:FOLDER_LISTING_MAX_FILES]

    return {
        "root_id": row["root_id"],
        "root_path": row["root_path"],
        "subfolders": subs,
        "files": files,
        "subfolder_truncated": sub_truncated,
        "file_truncated": file_truncated,
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


def _render_folder_listing_text(listing: dict) -> str:
    """Render the structural directory map as a markdown block. Format
    matches IWO2's `buildFolderListing()` verbatim so operators see
    consistent output across products.
    """
    lines: list[str] = []
    lines.append(f"# Folder: {listing['root_path']}")
    lines.append("")
    subs = listing.get("subfolders") or []
    files = listing.get("files") or []
    if subs:
        lines.append(f"## Subfolders ({len(subs)})")
        for sub in subs:
            count = sub.get("file_count") or 0
            count_label = f" ({count} files)" if count else ""
            lines.append(f"- **{sub.get('name', '?')}**{count_label}")
        if listing.get("subfolder_truncated"):
            lines.append(f"- ... [truncated; cap={FOLDER_LISTING_MAX_SUBFOLDERS}]")
        lines.append("")
    if files:
        lines.append(f"## Files ({len(files)})")
        for f in files:
            size = f.get("extracted_size") or 0
            size_label = f" ({size // 1024}KB)" if size >= 1024 else ""
            lines.append(f"- {f.get('filename', '?')}{size_label}")
        if listing.get("file_truncated"):
            lines.append(f"- ... [truncated; cap={FOLDER_LISTING_MAX_FILES}]")
        lines.append("")
    return "\n".join(lines).rstrip()


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

    # Loop Kappa — path-targeted hits (score 1.0 implicit).
    seen_artifact_ids: set[str] = set()
    for hit in inputs.get("path_hits", []) or []:
        excerpt = (hit.get("excerpt") or "").strip()
        if not excerpt or hit["id"] in seen_artifact_ids:
            continue
        seen_artifact_ids.add(hit["id"])
        sources.append(
            MemorySource(
                kind="path_targeted",
                client_id=hit["client_id"],
                record_id=hit["id"],
                text=excerpt,
                tokens=estimate_tokens(excerpt),
                owner_user_id=None,
                metadata={
                    "filename": hit.get("filename"),
                    "folder_path": hit.get("folder_path"),
                    "workspace_folder_id": hit.get("workspace_folder_id"),
                    "score": 1.0,
                    "match_kind": "path_targeted",
                },
            )
        )

    # Loop Kappa — folder listing synthesized source.
    listing = inputs.get("folder_listing")
    if listing and (listing.get("subfolders") or listing.get("files")):
        text = _render_folder_listing_text(listing)
        if text:
            sources.append(
                MemorySource(
                    kind="folder_listing",
                    client_id=client_id,
                    record_id=f"folder:{listing.get('root_id', '')}",
                    text=text,
                    tokens=estimate_tokens(text),
                    owner_user_id=None,
                    metadata={
                        "root_path": listing.get("root_path"),
                        "subfolder_count": len(listing.get("subfolders") or []),
                        "file_count": len(listing.get("files") or []),
                        "truncated": bool(
                            listing.get("subfolder_truncated")
                            or listing.get("file_truncated")
                        ),
                    },
                )
            )

    # Loop Kappa — filename hits (score 0.7 implicit). Skip artifacts
    # already surfaced via path_hits to avoid double-counting.
    for hit in inputs.get("filename_hits", []) or []:
        if hit["id"] in seen_artifact_ids:
            continue
        excerpt = (hit.get("excerpt") or "").strip()
        if not excerpt:
            continue
        seen_artifact_ids.add(hit["id"])
        sources.append(
            MemorySource(
                kind="filename_match",
                client_id=hit["client_id"],
                record_id=hit["id"],
                text=excerpt,
                tokens=estimate_tokens(excerpt),
                owner_user_id=None,
                metadata={
                    "filename": hit.get("filename"),
                    "workspace_folder_id": hit.get("workspace_folder_id"),
                    "score": 0.7,
                    "match_kind": "filename_match",
                },
            )
        )

    # Workspace tsquery retrieval — skip artifacts already surfaced.
    for hit in inputs.get("workspace", []) or []:
        if hit["id"] in seen_artifact_ids:
            continue
        excerpt = (hit.get("excerpt") or "").strip()
        if not excerpt:
            continue
        seen_artifact_ids.add(hit["id"])
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
                    "match_kind": "tsquery",
                },
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

"""Loop Mu — Memory V3 ChromaDB vector store wrapper.

Tenant-scoped semantic retrieval. **Index time, not query time** —
each tenant gets its own ChromaDB collection (`tenant_<client_id>`),
so queries can never accidentally surface another tenant's vectors.
This satisfies the V3 firewall constraint locked in ADR-031
§"Cache namespace isolation": no global-then-filter retrieval.

Pattern adopted from DigiFLOW (`WS021_KlearMarketing/06_KlearOpen/
klearopen-app/kg_engine.py`) — same ChromaDB PersistentClient
posture, same default embedding (`all-MiniLM-L6-v2` via Chroma's
bundled `DefaultEmbeddingFunction`), same cosine similarity space,
same chunk-size (~500 tokens with 50-token overlap).

Adaptations for IWO3:
  - Per-tenant collections instead of per-KG (DigiFLOW concept).
    `tenant_<client_id>` is the index-time tenancy boundary.
  - No external API keys — bundled embedding model is local.
  - Storage path is `.local/chroma/` at the repo root; matches
    the `.local/skills/` convention from MegaLoop Theta. Hosted
    Railway will need a persistent volume; documented in ADR-034.
  - Env-level kill switch `IWO3_SEMANTIC_RETRIEVAL_ENABLED` (matches
    the `IWO3_MEMORY_INJECTION_ENABLED` Iota pattern).

Imports are deferred (`import chromadb` inside the helper
functions) so the rest of the memory module loads cleanly when
chromadb is unavailable — V3 is opt-in for environments that
don't yet ship the dep.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Storage location. Mirrors `.local/skills/` from MegaLoop Theta.
# Hosted: requires persistent volume on Railway (see ADR-034 §"Hosted
# rollout"). Local-dev: created on first use.
def _chroma_dir() -> Path:
    # Resolve relative to the repo root (apps/api-fastapi/.. → repo).
    here = Path(__file__).resolve().parent
    repo_root = here.parents[2]
    return repo_root / ".local" / "chroma"


_ENV_KILL_SWITCH = "IWO3_SEMANTIC_RETRIEVAL_ENABLED"


def env_semantic_enabled() -> bool:
    """Env-level kill switch for V3 semantic retrieval. Default ON;
    set to "false" / "0" to bypass at the env layer regardless of
    per-tenant `clients.memory_enabled`.
    """
    raw = os.environ.get(_ENV_KILL_SWITCH)
    if raw is None:
        return True
    return raw.strip().lower() not in {"false", "0", "no", "off"}


def collection_name_for_tenant(client_id: str) -> str:
    """Stable, deterministic per-tenant collection name. The
    `tenant_` prefix + uuid form is the index-time tenancy boundary
    — queries against `tenant_A` cannot see `tenant_B` vectors.
    """
    return f"tenant_{client_id}"


def _get_chroma_client():
    """Get or create persistent ChromaDB client. Returns None if
    chromadb is unavailable — caller must check.
    """
    try:
        import chromadb
    except ImportError:
        logger.warning(
            "vector_store: chromadb is not installed; semantic "
            "retrieval is unavailable. Install via `uv add chromadb`."
        )
        return None
    chroma_dir = _chroma_dir()
    chroma_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(chroma_dir))


def get_or_create_tenant_collection(client_id: str):
    """Return the per-tenant Chroma collection. Cosine-space; uses
    Chroma's default embedding model (all-MiniLM-L6-v2; ~22MB,
    bundled). Returns None if chromadb is unavailable.
    """
    client = _get_chroma_client()
    if client is None:
        return None
    return client.get_or_create_collection(
        name=collection_name_for_tenant(client_id),
        metadata={"hnsw:space": "cosine"},
    )


def get_tenant_collection_or_none(client_id: str):
    """Read-side helper — returns None if the collection does not yet
    exist for this tenant (no indexed artifacts), without raising.
    """
    client = _get_chroma_client()
    if client is None:
        return None
    try:
        return client.get_collection(name=collection_name_for_tenant(client_id))
    except Exception:
        return None


def delete_tenant_collection(client_id: str) -> bool:
    """Delete the entire tenant collection. Used by ops/admin paths
    for tenant offboarding or full re-index. Returns True on success.
    """
    client = _get_chroma_client()
    if client is None:
        return False
    try:
        client.delete_collection(name=collection_name_for_tenant(client_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "delete_tenant_collection failed for client_id=%s: %s",
            client_id,
            exc,
        )
        return False


def chunk_text_for_vectors(
    text: str,
    chunk_size_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[str]:
    """DigiFLOW-parity chunker. Splits text into ~500-token chunks
    with 50-token overlap. Token approximation: 1 token ≈ 4 chars.
    """
    if not text:
        return []
    char_size = chunk_size_tokens * 4
    char_overlap = overlap_tokens * 4
    if len(text) <= char_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + char_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - char_overlap
    return chunks


def index_artifact_for_tenant(
    *,
    client_id: str,
    artifact_id: str,
    filename: Optional[str],
    text: str,
    workspace_folder_id: Optional[str] = None,
) -> int:
    """Index one artifact's extracted_text into the tenant
    collection. Returns the number of chunks stored, or 0 if
    chromadb is unavailable / text is empty.

    Idempotent — uses `upsert` so re-indexing the same artifact
    overwrites prior chunks for that artifact.
    """
    if not text or not text.strip():
        return 0
    collection = get_or_create_tenant_collection(client_id)
    if collection is None:
        return 0
    chunks = chunk_text_for_vectors(text)
    if not chunks:
        return 0
    ids = [f"{artifact_id}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "artifact_id": artifact_id,
            "filename": filename or "(unnamed)",
            "chunk_idx": i,
            "client_id": client_id,
            "workspace_folder_id": workspace_folder_id or "",
        }
        for i in range(len(chunks))
    ]
    try:
        collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "index_artifact_for_tenant: upsert failed for "
            "client_id=%s artifact_id=%s: %s",
            client_id,
            artifact_id,
            exc,
        )
        return 0
    return len(chunks)


def remove_artifact_from_tenant(
    *,
    client_id: str,
    artifact_id: str,
) -> int:
    """Delete every chunk for an artifact from the tenant collection.
    Returns the number of chunks removed (or 0 if collection absent).
    """
    collection = get_tenant_collection_or_none(client_id)
    if collection is None:
        return 0
    try:
        result = collection.get(where={"artifact_id": artifact_id})
        ids = result.get("ids") if isinstance(result, dict) else None
        if not ids:
            return 0
        collection.delete(ids=ids)
        return len(ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "remove_artifact_from_tenant: delete failed for "
            "client_id=%s artifact_id=%s: %s",
            client_id,
            artifact_id,
            exc,
        )
        return 0


def semantic_search_for_tenant(
    *,
    client_id: str,
    query: str,
    top_k: int = 3,
) -> list[dict]:
    """Run a semantic search against the tenant's collection.

    Returns a list of `{score, text, filename, artifact_id,
    workspace_folder_id, chunk_idx}` dicts, ordered by descending
    relevance (cosine similarity, mapped to score = 1 - distance).

    Returns empty list if chromadb is unavailable, the collection
    doesn't exist for this tenant (no indexed artifacts yet), or
    the query string is empty.
    """
    if not query or not query.strip():
        return []
    collection = get_tenant_collection_or_none(client_id)
    if collection is None:
        return []
    try:
        results = collection.query(
            query_texts=[query],
            n_results=top_k,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "semantic_search_for_tenant: query failed for "
            "client_id=%s: %s",
            client_id,
            exc,
        )
        return []
    docs = (results.get("documents") or [[]])[0] or []
    metas = (results.get("metadatas") or [[]])[0] or []
    dists = (results.get("distances") or [[]])[0] or []
    out: list[dict] = []
    for doc, meta, dist in zip(docs, metas, dists):
        if not doc:
            continue
        meta = meta or {}
        # Defensive: confirm meta.client_id matches active tenant.
        # The collection is already tenant-scoped; this is the
        # firewall belt analogous to ADR-031 Layer 4 validation.
        meta_client_id = meta.get("client_id")
        if meta_client_id and meta_client_id != client_id:
            logger.warning(
                "semantic_search_for_tenant: cross-tenant chunk found "
                "in collection — client_id=%s, chunk client_id=%s. "
                "Skipping. This indicates a corruption — investigate.",
                client_id,
                meta_client_id,
            )
            continue
        out.append({
            "score": 1.0 - float(dist) if dist is not None else 0.0,
            "text": doc,
            "filename": meta.get("filename") or "(unnamed)",
            "artifact_id": meta.get("artifact_id") or "",
            "workspace_folder_id": meta.get("workspace_folder_id") or "",
            "chunk_idx": int(meta.get("chunk_idx") or 0),
        })
    return out

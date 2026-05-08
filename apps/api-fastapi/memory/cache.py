"""Loop Iota — Memory V1 in-process LRU caches (firewall Layer 5).

Two caches:
  - canonical_facts cache, keyed (client_id, revision)
  - scratch retrieval cache, keyed (client_id, user_id, terms_hash)

Cache keys MUST include `client_id`. Operator-private caches MUST
additionally include `user_id`. Bundles assembled by
`memory_context_builder` are never cached across requests — the bundle
itself is per-HTTP-request scope. Only the upstream blobs are cached.

Caches are FastAPI-process-local. Each Railway / local replica has its
own cache; that's fine because:
  - canonical_facts cache is keyed on (client_id, revision); a workspace
    write bumps the revision so even stale replicas miss-then-load on
    the next chat turn after the write.
  - scratch cache TTL is short (60s) and operator scratch changes
    rarely mid-conversation.

A future loop may add Redis if multi-replica coherence becomes a
concern, but per the firewall package "no global cache" is mandatory:
any shared cache would also need to namespace keys by client_id.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from threading import Lock
from typing import Optional


class _LruCache:
    """Tiny LRU. ~50 lines of Python beats pulling in cachetools."""

    def __init__(self, max_entries: int = 256, ttl_seconds: Optional[int] = None):
        self._cache: "OrderedDict[tuple, tuple[float, str]]" = OrderedDict()
        self._lock = Lock()
        self._max = max_entries
        self._ttl = ttl_seconds

    def get(self, key: tuple) -> Optional[str]:
        with self._lock:
            if key not in self._cache:
                return None
            inserted_at, value = self._cache[key]
            if self._ttl is not None and (time.monotonic() - inserted_at) > self._ttl:
                del self._cache[key]
                return None
            # Touch — move to MRU end.
            self._cache.move_to_end(key)
            return value

    def set(self, key: tuple, value: str) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (time.monotonic(), value)
            if len(self._cache) > self._max:
                self._cache.popitem(last=False)

    def invalidate_prefix(self, prefix: tuple) -> int:
        """Drop every key whose tuple starts with `prefix`.

        Used by the workspace write hook when a tenant's
        canonical_facts_revision changes — invalidate every revision
        for that tenant rather than relying on revision-counter
        monotonicity alone.
        """
        with self._lock:
            to_delete = [k for k in self._cache if k[: len(prefix)] == prefix]
            for k in to_delete:
                del self._cache[k]
            return len(to_delete)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


# Canonical facts: long-lived (no TTL), bumped via revision counter.
_canonical_facts_cache = _LruCache(max_entries=128, ttl_seconds=None)

# Scratch terms: short TTL (60s) — operator scratch can change mid-flight
# and the lookup key includes a terms_hash so cache hits are
# query-specific.
_scratch_cache = _LruCache(max_entries=512, ttl_seconds=60)


def _make_canonical_key(client_id: str, revision: int) -> tuple:
    return (client_id, "canonical_facts", revision)


def _make_scratch_key(client_id: str, user_id: str, terms_hash: str) -> tuple:
    return (client_id, user_id, "scratch", terms_hash)


def hash_terms(terms: str) -> str:
    return hashlib.sha256(terms.encode("utf-8")).hexdigest()[:16]


def get_canonical_facts(client_id: str, revision: int) -> Optional[str]:
    return _canonical_facts_cache.get(_make_canonical_key(client_id, revision))


def put_canonical_facts(client_id: str, revision: int, blob: str) -> None:
    _canonical_facts_cache.set(_make_canonical_key(client_id, revision), blob)


def invalidate_canonical_facts(client_id: str) -> int:
    """Invalidate every cached revision for `client_id`. Called by the
    workspace write hook on `canonical_facts_revision` bump. Returns
    the number of cache entries dropped (informational)."""
    return _canonical_facts_cache.invalidate_prefix((client_id, "canonical_facts"))


def get_scratch_match(
    client_id: str, user_id: str, terms_hash: str
) -> Optional[str]:
    return _scratch_cache.get(_make_scratch_key(client_id, user_id, terms_hash))


def put_scratch_match(
    client_id: str, user_id: str, terms_hash: str, payload: str
) -> None:
    _scratch_cache.set(_make_scratch_key(client_id, user_id, terms_hash), payload)


def clear_all_caches() -> None:
    """Test-only escape hatch. Production has no use case."""
    _canonical_facts_cache.clear()
    _scratch_cache.clear()

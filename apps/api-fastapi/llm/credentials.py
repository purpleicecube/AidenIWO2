"""Loop 9 Phase 9.3 — env-injected LLM credential resolution.

Same `credential_ref:env:NAME` discipline as `adapter_credentials`
(IWO3_LOOP_8_3_CODEX_DECISIONS §Q2). Raw API keys never leave the
runtime environment; the DB only ever holds the placeholder ref.
"""

from __future__ import annotations

import os
import re
from typing import Optional


_REF_RE = re.compile(r"^credential_ref:env:([A-Za-z0-9_]+)$")


class LlmCredentialError(Exception):
    """Raised when a credential_ref cannot be resolved to a usable value."""


def env_var_from_credential_ref(ref: str) -> Optional[str]:
    """Parse `credential_ref:env:NAME` → "NAME". Returns None on mismatch."""
    m = _REF_RE.match(ref)
    return m.group(1) if m else None


def resolve_credential(
    ref: str, env: Optional[dict[str, str]] = None
) -> str:
    """Resolve a `credential_ref:env:NAME` to the runtime secret value.

    Raises `LlmCredentialError` when the ref shape is wrong or the env
    var is unset / empty. Defaults to `os.environ`; tests pass an
    isolated dict.
    """
    env_map = env if env is not None else os.environ
    name = env_var_from_credential_ref(ref)
    if not name:
        raise LlmCredentialError(
            f"credential_ref must match credential_ref:env:NAME (got {ref!r})"
        )
    value = env_map.get(name)
    if not value:
        raise LlmCredentialError(f"env var {name} is not set or empty")
    return value

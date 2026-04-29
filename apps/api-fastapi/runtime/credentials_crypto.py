"""MegaLoop Beta-1.5 phase 2 / Q15 — encrypted-at-rest credential storage.

Architect Q15 lock (path B): libsodium app-side encryption. The DB stores
the ciphertext; the runtime holds the master key in `IWO3_CRYPTO_MASTER_KEY`
and derives the per-tenant key inside the process. Raw plaintext never
touches the DB and never appears in logs.

Algorithm: NaCl SecretBox (XSalsa20-Poly1305 authenticated encryption).
Tag: ``libsodium-secretbox-v1``. Each ciphertext is `nonce(24) || box(...)`.

Master-key envelope:
  IWO3_CRYPTO_MASTER_KEY = hex(32-bytes) | b64(32-bytes)
The runtime derives a per-tenant key via HKDF-SHA256 with `info =
"iwo3.adapter_credentials.{client_id}"` so a per-tenant compromise
isolates blast radius.

Offline-sandbox caveat (R-045 carry-forward):
  pynacl is not installable in the offline sandbox we develop in. The
  module degrades gracefully — `is_available()` returns False and any
  encrypt/decrypt call raises `CryptoUnavailable`. Operators on a
  networked host run `cd apps/api-fastapi && uv add pynacl` once;
  module starts working immediately. The R-034 pattern.

Key recovery:
  Loss of `IWO3_CRYPTO_MASTER_KEY` makes every encrypted credential
  unrecoverable. There is no backdoor. Operator runbook documents
  rotation: new key → re-encrypt credentials in a brief downtime
  window → swap env var. Documented in BETA_1_5_PHASE_2 record §Q15.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Optional


_ALGO_TAG = "libsodium-secretbox-v1"
_MASTER_KEY_ENV = "IWO3_CRYPTO_MASTER_KEY"
_KEY_BYTES = 32  # SecretBox key size
_NONCE_BYTES = 24  # SecretBox nonce size

try:
    from nacl import secret as _nacl_secret  # type: ignore[import-not-found]
    from nacl import utils as _nacl_utils  # type: ignore[import-not-found]
    _NACL_AVAILABLE = True
except Exception:  # noqa: BLE001 — optional dep
    _nacl_secret = None
    _nacl_utils = None
    _NACL_AVAILABLE = False


class CryptoUnavailable(RuntimeError):
    """Raised when an encrypt/decrypt call is made and either pynacl is
    not importable or `IWO3_CRYPTO_MASTER_KEY` is unset/malformed."""


class CryptoCorrupt(RuntimeError):
    """Raised when ciphertext fails the Poly1305 MAC. Treated as a
    tampering / wrong-key signal — never fall through to plaintext."""


def algo_tag() -> str:
    return _ALGO_TAG


def is_available() -> bool:
    """True iff pynacl is importable AND a usable master key is set.

    Callers (dispatch path, ad-hoc probes) can use this without
    triggering a full encrypt. A False return means dispatch falls back
    to env-injection (the Beta-1 default), not that the runtime breaks.
    """
    if not _NACL_AVAILABLE:
        return False
    try:
        _resolve_master_key()
    except CryptoUnavailable:
        return False
    return True


def _resolve_master_key() -> bytes:
    raw = os.environ.get(_MASTER_KEY_ENV, "").strip()
    if not raw:
        raise CryptoUnavailable(
            f"{_MASTER_KEY_ENV} is not set. Generate with "
            "`python -c 'import secrets; print(secrets.token_hex(32))'` "
            "and set it in the runtime environment."
        )
    # Try hex (64 chars) then base64 (44 chars).
    if len(raw) == 64:
        try:
            key = bytes.fromhex(raw)
        except ValueError as exc:
            raise CryptoUnavailable(
                f"{_MASTER_KEY_ENV} is 64 chars but not valid hex: {exc}"
            )
    else:
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise CryptoUnavailable(
                f"{_MASTER_KEY_ENV} must be hex(64) or base64(44); "
                f"decode failed: {exc}"
            )
    if len(key) != _KEY_BYTES:
        raise CryptoUnavailable(
            f"{_MASTER_KEY_ENV} must decode to {_KEY_BYTES} bytes "
            f"(got {len(key)})"
        )
    return key


def _derive_tenant_key(master: bytes, client_id: str) -> bytes:
    """HKDF-SHA256 expand to 32 bytes scoped by client_id. Pure stdlib —
    independent of pynacl so the derivation is testable without the
    optional dep."""
    info = f"iwo3.adapter_credentials.{client_id}".encode("utf-8")
    # HKDF-Expand with PRK = master (we treat the master as already a
    # PRK; HKDF-Extract step is skipped because the master is uniformly
    # random by construction).
    t = b""
    okm = b""
    counter = 1
    while len(okm) < _KEY_BYTES:
        t = hmac.new(master, t + info + bytes([counter]), hashlib.sha256).digest()
        okm += t
        counter += 1
    return okm[:_KEY_BYTES]


def encrypt_credential(plaintext: str, *, client_id: str) -> bytes:
    """Encrypt a raw credential for storage. Returns
    ``nonce(24) || ciphertext_with_tag(...)`` as raw bytes; caller
    persists into ``adapter_credentials.encrypted_value BYTEA``.

    Raises ``CryptoUnavailable`` if pynacl is not installed or the
    master key is unset/malformed.
    """
    if not _NACL_AVAILABLE or _nacl_secret is None or _nacl_utils is None:
        raise CryptoUnavailable(
            "pynacl is not installed in this runtime. Run "
            "`cd apps/api-fastapi && uv add pynacl` then restart."
        )
    master = _resolve_master_key()
    tenant_key = _derive_tenant_key(master, client_id)
    box = _nacl_secret.SecretBox(tenant_key)
    nonce = _nacl_utils.random(_NONCE_BYTES)
    ct = box.encrypt(plaintext.encode("utf-8"), nonce)
    # nacl's encrypt() returns nonce||ciphertext already; we re-wrap as
    # bytes() for clarity and so callers do not need to know the nacl
    # internal Box object shape.
    return bytes(ct)


def decrypt_credential(blob: bytes, *, client_id: str) -> str:
    """Inverse of ``encrypt_credential``. Raises ``CryptoUnavailable``
    on missing dep / key, ``CryptoCorrupt`` on MAC failure (wrong key,
    truncated, or tampered ciphertext)."""
    if not _NACL_AVAILABLE or _nacl_secret is None:
        raise CryptoUnavailable(
            "pynacl is not installed in this runtime."
        )
    if len(blob) <= _NONCE_BYTES:
        raise CryptoCorrupt(
            f"ciphertext too short ({len(blob)} bytes); expected "
            f"more than {_NONCE_BYTES}"
        )
    master = _resolve_master_key()
    tenant_key = _derive_tenant_key(master, client_id)
    box = _nacl_secret.SecretBox(tenant_key)
    try:
        plaintext = box.decrypt(blob)
    except Exception as exc:  # noqa: BLE001 — nacl's CryptoError
        raise CryptoCorrupt(f"SecretBox.decrypt failed: {exc}")
    return plaintext.decode("utf-8")


def resolve_encrypted_or_env(
    *,
    client_id: str,
    encrypted_value: Optional[bytes],
    credential_ref: str,
    env: Optional[dict[str, str]] = None,
) -> str:
    """Two-tier resolution: encrypted blob (preferred when present) →
    env-var fallback (the Beta-1 path).

    Beta-1 default keeps env-injection as the source of truth; Beta-1.5
    phase 2 introduces the encrypted column as an additive option. A
    row may have BOTH (blob is canonical, env var stays for emergency
    rollback) or just one. The Q15 migration path is gradual: operator
    encrypts existing creds via the rotation runbook; the env var
    remains usable until the operator removes it.

    Raises ``CryptoUnavailable`` only when the encrypted path was
    requested but cannot be served. Falls through to env-injection
    otherwise — never silently downgrades.
    """
    if encrypted_value is not None and len(encrypted_value) > 0:
        return decrypt_credential(encrypted_value, client_id=client_id)
    # Defer to the env-injection helper; we keep this module loose-
    # coupled to llm.credentials by re-implementing the trivial
    # resolution here. Same semantics: credential_ref:env:NAME → env.
    from llm.credentials import resolve_credential

    return resolve_credential(credential_ref, env=env)

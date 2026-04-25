"""MegaLoop Beta-1 ε.3 / Q2 — stdlib-only HMAC-SHA256 signed tokens.

The architect locked Q2 = "custom signed JWT with short TTL +
refresh". The offline sandbox has no pyjwt / python-jose / nacl
available, so we implement the JWT shape with stdlib `hmac` + `hashlib`
+ `base64` + `json` + `secrets`. This is industry-standard JWT-HS256
in the format `header.payload.signature` with constant-time signature
verification.

When PyPI is reachable, an operator may swap this module for a
mature lib by leaving the Public API surface (`encode`, `decode`,
`SigningKey`, `TokenError`) intact. The drop-in pattern matches
how Loop δ wired streamlit-sortables: code path stays the same;
implementation can upgrade later.

Threat model (Beta-1 posture):
  - HS256 with a 32-byte secret. No key rotation in Beta-1; secret
    rotation lands in ε.5 alongside encrypted-at-rest credentials.
  - Constant-time signature comparison via `hmac.compare_digest`.
  - Replay protection by `exp` (expiry) only. No JTI revocation list
    in Beta-1; sessions revoke at TTL boundary.
  - Refresh tokens are separate JWTs with longer TTL + a different
    `typ` claim ("refresh" vs "access").
  - Header is fixed `{"alg":"HS256","typ":"JWT"}`. Algorithm
    confusion (alg=none) attacks are impossible because the verifier
    rejects any header that doesn't match this fixed shape.

Token shape:
  HEADER.b64url(json({"alg":"HS256","typ":"JWT"}))
  PAYLOAD.b64url(json(claims))
  SIGNATURE.b64url(hmac_sha256(key, HEADER + "." + PAYLOAD))

Standard claims used:
  sub  — user_id
  cid  — client_id (tenant)
  iat  — issued at (unix seconds)
  exp  — expires at (unix seconds)
  typ  — "access" | "refresh"
  jti  — random token id (for log correlation only; not revoked)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Optional


_HEADER = b'{"alg":"HS256","typ":"JWT"}'
_HEADER_B64 = base64.urlsafe_b64encode(_HEADER).rstrip(b"=")

DEFAULT_ACCESS_TTL_SECONDS = 15 * 60  # 15 minutes
DEFAULT_REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days
SIGNING_KEY_ENV_VAR = "IWO3_JWT_SIGNING_KEY"


class TokenError(Exception):
    """Anything that goes wrong with a token. Caller maps to 401."""

    def __init__(self, kind: str, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def _b64url_encode(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def _b64url_decode(data: bytes) -> bytes:
    pad = b"=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _resolve_signing_key(
    explicit: Optional[str] = None, *, env: Optional[dict[str, str]] = None
) -> bytes:
    """Return the HMAC signing key as raw bytes. Accept an explicit
    key for tests; otherwise read from env. The env value can be
    raw text (encoded utf-8) or hex; either is accepted as-long-as
    >=32 bytes. We don't try to be clever with derivation here."""
    if explicit:
        raw = explicit.encode("utf-8") if isinstance(explicit, str) else explicit
    else:
        env_map = env if env is not None else os.environ
        v = env_map.get(SIGNING_KEY_ENV_VAR, "")
        if not v:
            raise TokenError(
                "signing_key_missing",
                f"env var {SIGNING_KEY_ENV_VAR} must be set with a "
                f">=32-byte secret",
            )
        raw = v.encode("utf-8")
    if len(raw) < 32:
        raise TokenError(
            "signing_key_too_short",
            f"need >=32 bytes; got {len(raw)}",
        )
    return raw


def encode(
    *,
    user_id: str,
    client_id: str,
    typ: str = "access",
    ttl_seconds: Optional[int] = None,
    extra: Optional[dict[str, Any]] = None,
    signing_key: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
    now: Optional[int] = None,
) -> str:
    """Encode a JWT-shape access or refresh token. Returns the dot-
    joined string."""
    if typ not in ("access", "refresh"):
        raise TokenError("bad_typ", typ)
    if ttl_seconds is None:
        ttl_seconds = (
            DEFAULT_ACCESS_TTL_SECONDS
            if typ == "access"
            else DEFAULT_REFRESH_TTL_SECONDS
        )
    iat = int(now if now is not None else time.time())
    exp = iat + ttl_seconds

    claims: dict[str, Any] = {
        "sub": user_id,
        "cid": client_id,
        "iat": iat,
        "exp": exp,
        "typ": typ,
        "jti": secrets.token_urlsafe(16),
    }
    if extra:
        claims.update(extra)

    key = _resolve_signing_key(signing_key, env=env)
    payload_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = _HEADER_B64 + b"." + payload_b64
    sig = hmac.new(key, signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return (signing_input + b"." + sig_b64).decode("ascii")


def decode(
    token: str,
    *,
    expected_typ: Optional[str] = None,
    signing_key: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
    now: Optional[int] = None,
    leeway_seconds: int = 5,
) -> dict[str, Any]:
    """Decode + verify. Returns the claims dict. Raises TokenError
    with a stable `kind` for the caller to map to a 401."""
    if not token or token.count(".") != 2:
        raise TokenError("malformed", "expected three dot-separated parts")
    header_b64, payload_b64, sig_b64 = token.encode("ascii").split(b".", 2)
    if header_b64 != _HEADER_B64:
        raise TokenError("bad_header", "only HS256 / JWT supported")

    key = _resolve_signing_key(signing_key, env=env)
    expected_sig = hmac.new(
        key, header_b64 + b"." + payload_b64, hashlib.sha256
    ).digest()
    actual_sig = _b64url_decode(sig_b64)
    if not hmac.compare_digest(actual_sig, expected_sig):
        raise TokenError("bad_signature")

    try:
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise TokenError("bad_payload", str(e))
    if not isinstance(claims, dict):
        raise TokenError("bad_payload", "not a JSON object")

    cur = int(now if now is not None else time.time())
    exp = claims.get("exp")
    if not isinstance(exp, int):
        raise TokenError("missing_exp")
    if cur > exp + leeway_seconds:
        raise TokenError("expired", f"exp={exp}, now={cur}")

    if expected_typ and claims.get("typ") != expected_typ:
        raise TokenError(
            "typ_mismatch",
            f"expected {expected_typ}, got {claims.get('typ')}",
        )

    for required in ("sub", "cid", "iat", "typ"):
        if required not in claims:
            raise TokenError("missing_claim", required)

    return claims

# IWO3 Risk Register v0.3.0 (final)

Date: 2026-04-25
Predecessor: `RISK_REGISTER_v0.3.0_partial.md` (Beta-1 ε.10 closeout).
Closeout: MegaLoop Beta-1 + Beta-1.5 phase 1 (ε.5) + Beta-1.5 phase 2 — completed Production Posture baseline at `iwo3/main @ 805a139`.

## Posture statement

Beta-1 + Beta-1.5 phase 1 + Beta-1.5 phase 2 together form the **completed Production Posture baseline**. All 12 must-have architect Q's (Q1–Q12) ship end-to-end; Q13/Q14 are deferred-as-locked (Slack adapter to Beta-2); Q4 is deferred-as-locked. Q15 has a code path with graceful offline fallback awaiting one operator command (`uv add pynacl` + `IWO3_CRYPTO_MASTER_KEY`) to retire R-045 finally.

## Active risks (post-Beta-1.5 phase 2)

### R-022 [S2] Telegram offset persistence in-process — **carry**

Bounded post-β.5 idempotency hardening; Beta-1 / Beta-1.5 did not invest. Beta-1.5 ε.5's webhook → dispatch path further reduces relevance: production traffic flows through `POST /webhook/telegram`, not the long-poll worker.

### R-023 [S2] Auth-code consume on bypass connection — **carry**

Architectural by design (cross-tenant lookup before bind). Annotated. No Beta change.

### R-030 [S3] display_name backfill heuristic — **carry**

Cosmetic. New tenants seeded explicitly post-δ.

### R-034 [operational caveat] Drag-drop dep activation — **carry, strict wording**

Per CODEX 2026-04-25: carried operational caveat, **not** a completed drag-drop parity item. Stays visible until literal drag-drop verified active on a networked host via `cd apps/console-streamlit && uv sync`. Wording unchanged.

### R-037 [S2] Auth signing-key rotation operational complexity — **carry**

Q2 production auth uses `IWO3_JWT_SIGNING_KEY` env. Rotating the key invalidates all outstanding access + refresh tokens; operators must communicate ahead of rotation or accept brief unavailability.

**Mitigation:** Beta-2 phase 0 candidate — operator runbook (issue new key with grace period; rotate workers; revoke old key). For now, key rotation = mass logout — defensible for pilot posture.

### R-039 [S2] Webhook HMAC secret leak — **carry, telemetry now real**

Q3 webhook ingress relies on `IWO3_WEBHOOK_HMAC_<TENANT>` env-side secret + 5-min replay window. Leak = arbitrary signed inbound traffic for that tenant until the operator rotates.

**Mitigation:** Replay window (5 min on signed-timestamp path), constant-time signature compare, telemetry via `webhook.signature_invalid` audit on bad attempts. ε.5 fix made the audit row real (was inert pre-ε.5). Beta-2 may add a Telegram-side native secret rotation runbook.

### R-044 [S3] Login route bypasses tenant-scoped connection — **carry**

Architectural exception: `/auth/login` looks up users by email **before** the tenant is established. The lookup runs on a bypass conn and resolves `client_memberships` for the chosen `client_id`.

**Mitigation:** Single 401 response for all failure modes (`{"error":"invalid_credentials"}`) — no email-existence oracle. Audit `auth.login_failed` rows show the attempted email + tenant for forensics.

### R-045 [S2] Encrypted-at-rest credentials — **mitigated** (was deferred)

Q15 code path shipped at Beta-1.5 phase 2: `runtime/credentials_crypto.py` (NaCl SecretBox + per-tenant HKDF-SHA256), migration 0018 adds `encrypted_value (bytea) + encryption_algo + encrypted_at` triplet on `adapter_credentials`, `resolve_encrypted_or_env` prefers blob and falls through to env-injection (never silently downgrades). The module imports cleanly without pynacl; encrypt/decrypt raise `CryptoUnavailable` with operator-actionable message.

**Final retire condition:** operator activates on a networked host with `cd apps/api-fastapi && uv add pynacl` + sets `IWO3_CRYPTO_MASTER_KEY` (32-byte hex(64) or base64(44)). Same R-034 pattern — one operator command. Recommend Beta-2 phase 0 covers the retire + ADR-030 (Q15 architecture).

### R-038 [S2] Encryption-key derivation single-point-of-failure — **mitigating** (was dormant)

Activated alongside R-045 mitigation. Lost `IWO3_CRYPTO_MASTER_KEY` = unrecoverable encrypted credentials. The HKDF-SHA256 per-tenant derivation scopes blast radius (a tenant-key compromise doesn't unlock other tenants), but master-key loss has no recovery path.

**Mitigation:** Operator runbook documents rotation in a brief downtime window (new master key → re-encrypt credentials → swap env var). Documented in `runtime/credentials_crypto.py` docstring + `IWO3_MEGALOOP_BETA_1_5_PHASE_2_RECORD_v0.1.0.md` § Q15.

## Retired in Beta-1 + Beta-1.5 (11 risks)

| Risk | Closed by |
|---|---|
| R-021 (S1) | Q1 per-tenant LLM ceiling override (backend ε.3 + UI editor phase 2) |
| R-024 (S2) | `/health/channels` surfaces resolution status to the operator |
| R-026 (S3) | Q5 RBAC granularity |
| R-027 (S3) | Q5 RBAC granularity |
| R-028 (S3) | Q2 production auth (stdlib HMAC-SHA256 JWT + PBKDF2 passwords) |
| R-029 (S2) | Q5 RBAC granularity |
| R-031 (S3) | **Full retire at phase 2** — UI tail closed: chat persistence, ceiling editor, persona library, scratch UI all live |
| R-032 (S3) | Q7 `chat_sessions` backend (ε.2) + Streamlit hydrate/persist (phase 2) |
| R-033 (S3) | Q8 server-side WO idempotency (chat:* correlation 409) |
| R-035 (S3) | Q9 workspace content fetch endpoint |
| R-036 (S3) | Q10 workspace hard-delete (folder cascade + file remove) |
| R-046 (NEW + retired) | Architect-flagged ε.5 gaps: webhook dispatch, signature_invalid audit, scratch isolation |

## Cardinality summary

- **Active:** 9 (R-022, R-023, R-030, R-034, R-037, R-038, R-039, R-044, R-045)
- **Retired this loop:** 12 (10 from Beta-1, 1 from ε.5, R-031 fully retired in phase 2)
- **State changes this loop:** R-045 deferred → mitigated; R-038 dormant → mitigating
- **Final retire condition outstanding:** R-045 (one operator command)

## Process notes

- This is the **final** v0.3.0 register; v0.3.0_partial superseded.
- v0.4.0 expected at MegaLoop Beta-2 (Capability Expansion) closeout. Beta-2 phase 0 should cover R-045 final retire + ADR-030 (Q15 crypto architecture).
- R-034 stays carried until operator confirms drag-drop on a networked host. Independent of R-045.

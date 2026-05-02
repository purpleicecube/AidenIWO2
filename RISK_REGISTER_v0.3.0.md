# IWO3 Risk Register v0.3.0 (final)

Date: 2026-04-25
Predecessor: `RISK_REGISTER_v0.3.0_partial.md` (Beta-1 ε.10 closeout).
Closeout: MegaLoop Beta-1 + Beta-1.5 phase 1 (ε.5) + Beta-1.5 phase 2 — completed Production Posture baseline at `iwo3/main @ 805a139`.

## Posture statement

Beta-1 + Beta-1.5 phase 1 + Beta-1.5 phase 2 together form the **completed Production Posture baseline**. All 12 must-have architect Q's (Q1–Q12) ship end-to-end; Q13/Q14 are deferred-as-locked (Slack adapter to Beta-2); Q4 is deferred-as-locked. Q15 **retired 2026-04-29** (A4 working-version activation): pynacl 1.6.2 installed, `IWO3_CRYPTO_MASTER_KEY` set in `apps/api-fastapi/.env` (master-key copy of record at `VS_PDOE/+8PGITHUB/00_Secrets/iwo3_crypto_master_key.txt`), `is_available()` True, encrypt/decrypt round-trip + per-tenant HKDF isolation verified.

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

### R-038 [S2] Encryption-key derivation single-point-of-failure — **mitigating**

Activated in earnest by R-045 retire (2026-04-29). Lost `IWO3_CRYPTO_MASTER_KEY` = unrecoverable encrypted credentials. The HKDF-SHA256 per-tenant derivation scopes blast radius (a tenant-key compromise doesn't unlock other tenants), but master-key loss has no recovery path.

**Mitigation:** Master-key copy of record stored at `VS_PDOE/+8PGITHUB/00_Secrets/iwo3_crypto_master_key.txt` (gitignored, chmod 600). Operator must back up off-machine (password manager, encrypted USB, or paper in a safe) — the on-machine copy is not a backup. Operator runbook documents rotation in a brief downtime window (new master key → re-encrypt credentials → swap env var). Documented in `runtime/credentials_crypto.py` docstring + `IWO3_MEGALOOP_BETA_1_5_PHASE_2_RECORD_v0.1.0.md` § Q15.

## Retired in Beta-1 + Beta-1.5 (12 risks)

| Risk | Closed by |
| --- | --- |
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
| R-045 (S2) | **Retired 2026-04-29 (A4 working-version activation):** `uv add pynacl` (1.6.2 installed); `IWO3_CRYPTO_MASTER_KEY` set in `/home/virgina/VS_AIDEN_IWO3/.env` (master-key copy of record at `VS_PDOE/+8PGITHUB/00_Secrets/iwo3_crypto_master_key.txt`); FastAPI restarted on :5500 with `--env-file`; standalone verification confirms `is_available()` True, encrypt → 71-byte blob, decrypt round-trip OK, cross-tenant decrypt fails with `CryptoCorrupt` (HKDF isolation enforced). |
| R-049 (S2 — NEW + retired same day) | **Latent Loop 9 watchdog first-poll bug discovered + fixed during Beta-2 phase 0.2 smoke (2026-05-01).** `adapter/gamma_poll.py:_load_handoff_for_poll` selected `last_poll_at` but not `created_at`; on a fresh handoff `last_poll_at IS NULL` falls back to `datetime.fromtimestamp(0, tz=utc)` so `elapsed = now - epoch_zero ≈ 5.3B seconds`, triggering `stale=true` on the FIRST tick of EVERY new handoff. **Net effect**: every fresh handoff was watchdog-expired before its first real poll attempt; Loop 9 production code was never auto-completing the loop via the poll worker — only via direct `POST /output_handoffs/{id}/poll`. **Fix**: select `h.created_at` in `_load_handoff_for_poll`, fall back to `created_at` instead of epoch-zero (`apps/api-fastapi/adapter/gamma_poll.py:250`). **Verification**: Test PDF GAMMA WO `8af691d4-…` and Phase 0.2 smoke `94099396-…` both auto-completed end-to-end after the fix; poll worker logs show `tick complete — {'completed': N}` instead of `{'watchdog_expired': N}`. **Latency**: bug existed on `iwo3/main` since Loop 9 Phase 9.4 (`8a56236`); fix is forward-only on `iwo3/main` (no IWO2 backport — bug is IWO3-native). |

## Cardinality summary

- **Active:** 8 (R-022, R-023, R-030, R-034, R-037, R-038, R-039, R-044)
- **Retired this loop:** 13 (10 from Beta-1, 1 from ε.5, R-031 fully retired in phase 2, R-045 retired post-phase-2 on 2026-04-29)
- **State changes this loop:** R-045 deferred → mitigated → **retired**; R-038 dormant → mitigating
- **Final retire condition outstanding:** none

## Process notes

- This is the **final** v0.3.0 register; v0.3.0_partial superseded.
- v0.4.0 expected at MegaLoop Beta-2 (Capability Expansion) closeout. Beta-2 phase 0 may still cover ADR-030 (Q15 crypto architecture documentation); R-045 final retire is no longer a Beta-2 prerequisite.
- R-034 stays carried until operator confirms drag-drop on a networked host. Independent of R-045.

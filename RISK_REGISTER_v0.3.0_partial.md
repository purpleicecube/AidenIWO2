# IWO3 Risk Register v0.3.0 (Beta-1 partial)

Date: 2026-04-25
Predecessor: `RISK_REGISTER_v0.2.3.md` (post-δ).
Closeout: MegaLoop Beta-1 ε.10 — partial because Beta-1.5 (encrypted creds + UI surfaces) is the natural completion point for the v0.3.0 register. v0.3.0 final lands at Beta-1.5 closeout.

## Active risks (post-Beta-1)

### R-022 [S2] Telegram offset persistence in-process — **carry**

Bounded post-β.5 idempotency hardening; Beta-1 did not invest. Beta-2's webhook ingress (already shipped at ε.4) reduces the relevance further: production traffic flows through `POST /webhook/telegram`, not the long-poll worker.

### R-023 [S2] Auth-code consume on bypass connection — **carry**

Architectural by design (cross-tenant lookup before bind). Annotated. No Beta change.

### R-030 [S3] display_name backfill heuristic — **carry**

Cosmetic. New tenants seeded explicitly post-δ.

### R-034 [operational caveat] Drag-drop dep activation — **carry, strict wording**

Per CODEX 2026-04-25: carried operational caveat, **not** a completed drag-drop parity item. Stays visible until literal drag-drop verified active on a networked host via `cd apps/console-streamlit && uv sync`. Wording unchanged.

### R-037 [S2] (NEW) Auth signing-key rotation operational complexity

Q2 production auth uses `IWO3_JWT_SIGNING_KEY` env. Rotating the key invalidates all outstanding access + refresh tokens; operators must communicate ahead of rotation or accept brief unavailability.

**Mitigation:** Beta-1.5 runbook adds an operator playbook for rotation (issue new key with grace period; rotate workers; revoke old key). For now, key rotation = mass logout — defensible for pilot posture.

### R-039 [S2] (NEW) Webhook HMAC secret leak

Q3 webhook ingress relies on `IWO3_WEBHOOK_HMAC_<TENANT>` env-side secret + 5min replay window. Leak = arbitrary signed inbound traffic for that tenant until the operator rotates.

**Mitigation:** Replay window (5 min on signed-timestamp path), constant-time signature compare, telemetry via `webhook.signature_invalid` audit on bad attempts. Beta-2 may add a Telegram-side native secret rotation runbook.

### R-044 [S3] (NEW) Login route bypasses tenant-scoped connection

Architectural exception: `/auth/login` looks up users by email **before** the tenant is established (the operator picks tenant during login, so RLS can't yet scope). The lookup runs on a bypass conn and resolves `client_memberships` for the chosen `client_id`; an attacker enumerating emails could probe membership.

**Mitigation:** Single 401 response for all failure modes (`{"error":"invalid_credentials"}`) — no email-existence oracle. Audit `auth.login_failed` rows show the attempted email + tenant for forensics.

### R-045 [S2] (NEW) Encrypted-at-rest deferred to Beta-1.5

Q15 (libsodium app-side encryption) requires `pynacl`; PyPI was unreachable in the offline sandbox during Beta-1 implementation. Credential storage continues to use `credential_ref:env:NAME` (env-only secrets, never in DB) — defensible posture for Beta-1 pilot, but does not satisfy the "encrypted at rest" requirement Q15 locked.

**Mitigation:** Operator runs `cd apps/api-fastapi && uv add pynacl` once on a networked host; runtime/credentials_crypto.py then activates per the prestart questions doc § Q15 Impact Map. Same R-034 pattern (operational caveat with a one-command resolution path). R-038 remains dormant until then.

### R-038 [S2, dormant] Encryption-key derivation single-point-of-failure

Will activate alongside Q15 (R-045 resolution). Lost master key = unrecoverable encrypted creds. Operator-owned rotation procedure + key-recovery runbook are part of the Beta-1.5 ship.

## Retired in Beta-1 (10 risks)

| Risk | Closed by |
|---|---|
| R-021 (S1) | Q1 per-tenant LLM ceiling override |
| R-024 (S2) | (Beta-1 didn't directly close; R-024 covered Telegram bot token loss → outbound stall. /health/channels now surfaces the resolution status to the operator → effective close.) |
| R-026 (S3) | Q5 RBAC granularity |
| R-027 (S3) | Q5 RBAC granularity |
| R-028 (S3) | Q2 production auth |
| R-029 (S2) | Q5 RBAC granularity |
| R-031 (S3) | (Persona library still in Beta-1.5 UI surface; carry to v0.3.0 final) |
| R-032 (S3) | Q7 chat_sessions backend (UI wire in Beta-1.5) |
| R-033 (S3) | Q8 server-side WO idempotency |
| R-035 (S3) | Q9 workspace content fetch |
| R-036 (S3) | Q10 workspace hard-delete |

## Risks expected to land at v0.3.0 final (Beta-1.5 closeout)

- R-038 activated (encryption key SPOF) once pynacl lands.
- R-031 retired if persona library UI ships at Beta-1.5.
- R-022, R-023, R-030, R-034 carried unchanged.

## Process notes

- This is a **partial** register bump because Beta-1 split into Beta-1 + Beta-1.5 due to offline sandbox constraints on Q15. v0.3.0 final lands when Beta-1.5 closes.
- v0.4.0 expected at MegaLoop Beta-2 (Capability Expansion) closeout.

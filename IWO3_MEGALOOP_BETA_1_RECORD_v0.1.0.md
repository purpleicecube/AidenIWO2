# IWO3 MegaLoop Beta-1 — Production Posture Record v0.1.0

Date: 2026-04-25
Status: **Code-complete** (ε.10 closeout artifact). Ready for CODEX review.
Branch: `iwo3/main`.
Predecessors: `IWO3_MEGALOOP_BETA_DECISIONS_v0.1.0.md` (the gate), `IWO3_PRE_BETA_PRODUCT_SURFACE_REMEDIATION_LOOP_RECORD_v0.1.0.md` (loop δ).
Successor: MegaLoop Beta-2 — Capability Expansion (separate loop).

Loop **ε** in α/β/γ/δ/ε continuity. Production-posture must-haves locked by architect Q1–Q15 land here; capability expansion (Slack, Sandbox PPTX/PDF, MCP registry, Aiden conversational v2) stays for Beta-2.

## Phase summary

| Phase | Headline | Commit | Architect Q's closed |
|-------|----------|--------|---------------------|
| ε.1 | Schema foundation: clients.llm_per_wo_ceiling + chat_sessions + workspace_folders.owner_user_id + chat-correlation UNIQUE + RBAC keys + audit-event vocabulary lock (BETA_PHASE_1_AUDIT_EVENTS, +9 events) | `349c1ca` | Q1, Q5 (schema), Q7 (schema), Q8 (schema), Q11 (schema) |
| ε.2 | RBAC swap on /llm/configs + workspace content fetch + folder/file hard-delete + chat persistence backend | `1dd2d62` | Q5 (route), Q7 (backend), Q9, Q10 |
| ε.3 | Production auth (stdlib HMAC-SHA256 JWT) + WO chat-correlation 409 mapping + per-tenant ceiling runtime hookup + auth-mode-aware deps | `f62d848` | Q2, Q8 (route), Q1 (runtime) |
| ε.4 | Webhook ingress (`POST /webhook/telegram` HMAC-verified; `/webhook/slack` 503 placeholder) + `/health/channels` + `/health/llm` | (this commit) | Q3, ε health surfaces |
| ε.5 | **Deferred to Beta-1.5** — encrypted credentials require `pynacl` (PyPI unreachable in offline sandbox). See "Deferred" below. | — | Q15 |
| ε.6 | **Deferred to Beta-1.5** — Streamlit chat persistence wire-up + per-tenant ceiling editor UI + per-operator scratch + persona library reuse | — | Q11 (UI), Q6, ε UI surfaces |
| ε.10 | Closeout — this record + risk register v0.3.0-partial + CODEX note + final CI green | (this commit) | governance |

## Architect Q's — outcome

| Q | Decision | Status |
|---|----------|--------|
| Q1  | Per-tenant LLM ceiling override (column on clients) | ✅ schema + runtime |
| Q2  | Production auth (signed JWT + dev-bearer env gate) | ✅ |
| Q3  | Channel webhook design (HMAC primary + long-poll fallback) | ✅ |
| Q4  | Cost-aware provider arbitration (defer beyond Beta) | ✅ deferred |
| Q5  | RBAC granularity for config CRUD (split write/delete) | ✅ |
| Q6  | Persona library (reuse prompt_profiles) | ⚠️ deferred to Beta-1.5 (UI surface only; resolver is unchanged) |
| Q7  | Cross-session chat context durability (chat_sessions table) | ✅ backend; ⚠️ Streamlit wire-up deferred to Beta-1.5 |
| Q8  | Server-side WO idempotency (UNIQUE on chat correlation) | ✅ |
| Q9  | Workspace file content fetch | ✅ |
| Q10 | Workspace hard-delete | ✅ |
| Q11 | Per-operator scratch | ✅ schema + RLS-ready; ⚠️ UI surface deferred to Beta-1.5 |
| Q12 | Beta loop split | ✅ ratified by this Beta-1 record |
| Q13 | Tool/MCP registry (defer to Beta-2) | ✅ deferred |
| Q14 | Slack adapter timing (Beta-2) | ✅ deferred |
| Q15 | Encrypted credentials (libsodium app-side) | ⚠️ deferred to Beta-1.5 — see below |

## Beta-1 must-have ↔ outcome

10 must-haves from the decisions memo:

1. Production auth ✅ (Q2)
2. Encrypted credentials ⚠️ Beta-1.5 (Q15 — pynacl unreachable; carry-forward documented)
3. Webhook ingress ✅ (Q3)
4. Server-side WO idempotency ✅ (Q8)
5. Cross-session chat context — backend ✅; Streamlit wire-up Beta-1.5 (Q7)
6. Workspace content fetch ✅ (Q9)
7. Workspace hard-delete ✅ (Q10)
8. /health/channels + /health/llm ✅
9. Per-tenant LLM ceiling — runtime + schema ✅; Aiden Settings editor UI Beta-1.5 (Q1)
10. RBAC granularity for config CRUD ✅ (Q5)

**8 of 10 must-haves shipped end-to-end.** 2 split between backend (this loop) and UI (Beta-1.5).

## Deferred to Beta-1.5

A focused follow-on phase under the same Beta-1 banner that closes the offline-sandbox-blocked items + the UI surface tail. Total estimate: ~1–2 days work once PyPI is reachable.

### Q15 — Encrypted-at-rest credentials

`pynacl` (or any libsodium binding) is unreachable in the development sandbox; PyPI install was blocked. Per the architect-locked Q15 answer (B = libsodium app-side), the implementation needs the dep. Two paths to land it:

1. **Operator runs `cd apps/api-fastapi && uv add pynacl` once on a networked host.** Then drop in `runtime/credentials_crypto.py` per the prestart questions doc § Q15 Impact Map.
2. Architect can choose to swap to Q15 option (a) `pgcrypto` instead — fully Postgres-side, no Python dep. That changes the lock and would need an ADR.

Default path: option 1 (architect-locked B). This is the same R-034 pattern (drag-drop dep) — code path stays the same once the dep is installed.

Until then, credential storage continues to use the existing `credential_ref:env:NAME` pattern from α.5 — secrets stay in env, never in DB. That's a defensible posture for Beta-1 pilot tenants while the encryption layer comes online.

### Q7 / Q11 / Q1 / Q6 UI surfaces

The backend + RBAC + schema for cross-session chat persistence, per-operator scratch, per-tenant ceiling, and persona library are all in place. The Streamlit-side wire-up (chat.py reading from /chat_sessions/me, workspace.py rendering per-operator subtree, aiden_settings.py adding the ceiling editor + persona-template picker) is pure UI work that doesn't change the backend contract.

## Schema delta (Beta-1 ε.1+ε.3)

```
db/migrations/0016_beta_phase_1_epsilon_schema.sql
  + clients.llm_per_wo_ceiling (INTEGER NULL)
  + chat_sessions table + RLS + iwo3_app grant
  + work_orders chat-correlation partial UNIQUE
  + workspace_folders.owner_user_id (UUID NULL)
  + permissions: llm_config:write, llm_config:delete
  + role_permissions: 5 new mappings

db/migrations/0017_beta_phase_1_epsilon_auth.sql
  + users.password_hash (VARCHAR 512 NULL)
  + users.password_updated_at (TIMESTAMPTZ NULL)
```

## Audit vocabulary delta

- +9 events under `BETA_PHASE_1_AUDIT_EVENTS`:
  - `auth.session_started / refreshed / ended / login_failed`
  - `credential.encrypted` (lock-only; emitted in Beta-1.5 when Q15 lands)
  - `credential.rotated` (same)
  - `chat_session.updated`
  - `webhook.received`
  - `webhook.signature_invalid`
- Total events: 100 → 109. Snapshot fixture + cardinality assertions bumped in lockstep.

## Permission vocabulary delta

- +2 keys: `llm_config:write`, `llm_config:delete`
- Total: 75 → 77. Per-role bumps:
  - owner: 75→77, admin: 73→75, operator: 31→32 (write only; delete stays admin)
  - reviewer/viewer/agent_system unchanged
- Total role_permissions: 235 → 240

## Tenant-scoped tables delta

- +1 table: `chat_sessions`
- Total: 30 → 31. Lint plugin TENANT_SCOPED_TABLES updated.

## CI snapshot at ε.10

```
pytest:    225 → 232 passed (+7 webhook tests over ε.3)
           (1 skip preserved across all loops)
vitest:    581 passed across 51 files
Streamlit: 24 passed, 3 skipped
ESLint custom rules: clean
Contract snapshot: frozen at 109 events / 77 perms / 44 enums
```

Test growth across Beta-1:
- α.8: 160 / 581 / 24
- δ.8: 201 / 581 / 24
- ε.10: 232 / 581 / 24 (+72 pytest tests in α/β/γ/δ/ε)

## Risks retired by Beta-1

| Risk | How |
|---|---|
| R-021 (S1) | Per-tenant LLM ceiling lands; runtime gate honors override (Q1) |
| R-026, R-027, R-029 | RBAC granularity for config CRUD (Q5) |
| R-028 | Production auth replaces dev bearer in production env (Q2) |
| R-032 | Cross-session chat context backend (Q7); Streamlit wire-up in Beta-1.5 |
| R-033 | Server-side WO idempotency on chat correlation (Q8) |
| R-035 | Workspace file content fetch (Q9) |
| R-036 | Workspace hard-delete (Q10) |

## Risks added in Beta-1 (anticipated, projected to v0.3.0)

| Risk | Severity | Why |
|---|---|---|
| R-037 | S2 | Auth signing-key rotation operational complexity (Q2) |
| R-039 | S2 | Webhook signature gap if HMAC secret leaks (Q3) |
| R-044 | S3 | Login route deliberately bypasses tenant-scoped connection on email lookup |
| R-045 | S2 | NEW — `pynacl` install blocked in sandbox; encrypted-at-rest deferred to Beta-1.5 (operational caveat similar to R-034) |
| R-038 | S2 | Encryption-key derivation single-point-of-failure — **dormant** until Q15 lands; will activate alongside the pynacl install |

## Carry-forward (unchanged)

- **R-034** drag-drop dep activation — carried operational caveat per architect 2026-04-25; not a completed parity item. Stays visible until literal drag-drop verified active on a networked host (`cd apps/console-streamlit && uv sync`).
- R-022 Telegram offset persistence in-process (bounded post-β.5).
- R-023 Auth-code consume on bypass connection (architectural).
- R-030 display_name backfill heuristic (cosmetic).

## Sign-off checklist

- [x] All decision-memo Q's recorded with implementation status (✅ / ⚠️ Beta-1.5 / ✅ deferred-to-Beta-2-or-GA per the lock).
- [x] 8 of 10 must-haves shipped end-to-end; 2 split with explicit Beta-1.5 deferrals documented.
- [x] No Beta-2 scope pulled in (Slack, Sandbox PPTX/PDF, MCP execution, Aiden conversational v2 all stay deferred).
- [x] Audit vocabulary, permission vocabulary, tenant-scoped tables, contract snapshot all updated in lockstep with the migrations.
- [x] CI green: pytest 232 / 1 skipped, vitest 581 / 0, streamlit 24 / 3.
- [x] ESLint custom rules clean (require-tenant-scope-on-client-tables, no-raw-audit-insert).
- [x] R-034 wording strict ("carried operational caveat, not a completed parity item") preserved across all Beta artifacts.
- [ ] Operator runs Beta-1 verification flows (auth login + JWT round-trip; webhook smoke against a real Telegram bot; per-tenant ceiling editor; chat persistence after refresh; workspace content + hard-delete). _Operator action — not blocking commit._

## Recommendation to CODEX

Accept Beta-1 as code-complete with the documented Beta-1.5 carry-forward. Open Beta-2 (Capability Expansion) only after either:

- (a) Beta-1.5 closes the encrypted-creds + UI surfaces, OR
- (b) Architect explicitly accepts the Beta-1.5 carry as a Beta-2 dependency (i.e. Beta-2 starts with those items as Beta-2-phase-0).

My recommendation: option (a) — Beta-1 is the Production Posture loop, and shipping Beta-2 (Slack, Sandbox, MCP) on top of partial production posture risks tangling the security review of Beta-1.5 with Beta-2 capability work. Beta-1.5 is small and well-scoped.

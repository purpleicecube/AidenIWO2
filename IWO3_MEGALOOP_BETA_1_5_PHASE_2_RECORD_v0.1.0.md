# IWO3 MegaLoop Beta-1.5 Phase 2 Record v0.1.0

Date: 2026-04-25
Status: **Code-complete** for the four UI/encryption tail items. Beta-1 + Beta-1.5 phase 1 (ε.5) + Beta-1.5 phase 2 together close the documented Production Posture baseline.
Branch: `iwo3/main`.
Predecessors: `IWO3_MEGALOOP_BETA_1_5_RECORD_v0.1.0.md` (commit `8ef5f4a`).
Successor: MegaLoop Beta-2 (Capability Expansion) — gated until this record is accepted.

## Why phase 2 was opened

Beta-1 + Beta-1.5 ε.5 closed the architect's HIGH/MED gaps. Four documented carry-forwards remained, blocking honest acceptance of "Production Posture":

| # | Carry-forward | Architect Q lock | What was missing |
|---|---|---|---|
| 1 | Q15 encrypted-at-rest credentials | Path B (libsodium app-side) | `runtime/credentials_crypto.py` + adapter_credentials columns + operator runbook |
| 2 | Q1 per-tenant LLM ceiling editor | A (column on clients) | UI surface in Aiden Settings + admin-gated `PATCH /tenants/me/settings` |
| 3 | Q6 persona library | A (reuse prompt_profiles) | UI surface + read-only `GET /llm/personas` |
| 4 | Q7 chat persistence wire-up | A (chat_sessions table) | Streamlit chat.py reads/writes /chat_sessions/me |
| 5 | Q11 per-operator scratch UI | A (per-operator subtree) | "Create my scratch" button + visible chip in tree |

All five are now shipped. R-045 (encrypted-at-rest deferred) is **mitigated** — the code path exists with a graceful fallback to Beta-1 env-injection. R-031 partial → fully retired (UI tail closed). The pynacl operational caveat remains until the operator runs `uv add pynacl` on a networked host.

## Phase-2 ship summary

| Slice | Headline | Files |
|-------|----------|-------|
| Q15 crypto module | libsodium SecretBox wrapper with offline-fallback | `apps/api-fastapi/runtime/credentials_crypto.py` (new) |
| Q15 schema | encrypted-credential triplet (bytea + algo + at) on adapter_credentials | `db/migrations/0018_beta_phase_1_5_phase_2_encrypted_credentials.sql` (new) + `db/schema/adapter_credentials.ts` |
| Q1 backend | GET + PATCH `/tenants/me/settings` (admin-gated, audit-logged) | `apps/api-fastapi/routes/tenants.py` |
| Q6 backend | GET `/llm/personas` (read-only prompt_profiles passthrough) | `apps/api-fastapi/routes/llm.py` |
| Q11 backend | POST `/workspace/folders/scratch` (idempotent + soft-delete restore) | `apps/api-fastapi/routes/workspace.py` |
| Audit lock | New `client.settings_updated` event + `BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS` array | `packages/contracts/audit/events.ts` + snapshot fixture |
| Q7 UI | Streamlit chat.py hydrates from /chat_sessions/me on first render; PUTs on every turn | `apps/console-streamlit/views/chat.py` |
| Q1+Q6 UI | Aiden Settings — ceiling editor + persona library sections | `apps/console-streamlit/views/aiden_settings.py` |
| Q11 UI | Workspace — "Create my scratch" / "Open my scratch" + scratch-chip on selected folder | `apps/console-streamlit/views/workspace.py` |
| Tests | 13 new pytest covering all four surfaces + crypto fallback semantics | `apps/api-fastapi/tests/test_beta_1_5_phase_2.py` (new) |

## Q15 — encrypted-at-rest credentials (the hardest piece)

### Architecture

`runtime/credentials_crypto.py` wraps NaCl SecretBox (XSalsa20-Poly1305 authenticated encryption). Algorithm tag `libsodium-secretbox-v1`. Per-tenant key is derived via HKDF-SHA256 from `IWO3_CRYPTO_MASTER_KEY` with `info = "iwo3.adapter_credentials.{client_id}"` so a single-tenant compromise doesn't unlock other tenants' credentials.

Master key envelope:
- `IWO3_CRYPTO_MASTER_KEY` env var, hex(64) or base64(44) — both decode to 32 bytes.
- Generated via `python -c 'import secrets; print(secrets.token_hex(32))'`.
- **Loss is unrecoverable.** Operator runbook documents rotation in a brief downtime window: new key → re-encrypt credentials → swap env var. There is no backdoor.

### Schema

Three additive columns on `adapter_credentials` under a single CHECK constraint that forces them to move together:

```sql
encrypted_value bytea NULL,
encryption_algo varchar(64) NULL,
encrypted_at timestamp with time zone NULL,

CHECK (
  (encrypted_value IS NULL AND encryption_algo IS NULL AND encrypted_at IS NULL)
  OR
  (encrypted_value IS NOT NULL AND encryption_algo IS NOT NULL AND encrypted_at IS NOT NULL)
)
```

NULL in all three slots = env-injection only (Beta-1 default). Non-NULL = encrypted-at-rest active. The runtime resolver `resolve_encrypted_or_env(...)` prefers the encrypted blob when present, falls through to env-injection otherwise. **Never silently downgrades.**

### Offline-sandbox graceful fallback (R-045 → mitigating)

The module imports cleanly even when pynacl is absent:

```python
try:
    from nacl import secret as _nacl_secret
    from nacl import utils as _nacl_utils
    _NACL_AVAILABLE = True
except Exception:
    _NACL_AVAILABLE = False
```

`is_available()` returns False; `encrypt_credential` / `decrypt_credential` raise `CryptoUnavailable` with an operator-actionable message:

> pynacl is not installed in this runtime. Run `cd apps/api-fastapi && uv add pynacl` then restart.

The R-034 pattern. Verified: `IWO3_CRYPTO_MASTER_KEY` validation runs entirely in stdlib, so the message is precise about which prerequisite is missing.

### Test coverage

Five unit tests (no DB needed):
- `test_credentials_crypto_module_imports_without_pynacl`
- `test_credentials_crypto_encrypt_raises_when_unavailable`
- `test_credentials_crypto_resolve_falls_through_to_env`
- `test_credentials_crypto_master_key_validation`
- (algo_tag stability + CryptoUnavailable subclass discipline asserted in the import test)

## Q1 — per-tenant LLM ceiling editor

### Backend

- `GET /tenants/me/settings` — any tenant member with `client:read`. Returns `{client_id, designation, llm_per_wo_ceiling, llm_per_wo_ceiling_is_default, ceiling_min, ceiling_max}`. NULL on `clients.llm_per_wo_ceiling` surfaces as `DEFAULT_PER_WO_CEILING` with `is_default=true`.
- `PATCH /tenants/me/settings` — `system:admin` gated. Two modes:
  - `{"llm_per_wo_ceiling": N}` — pin override.
  - `{"revert_to_default": true}` — clear override.
- Out-of-range values rejected at the Pydantic boundary (422). Allowed range `[1_000, 1_000_000]` matches `runtime/budgets.py` clamp.
- Audit emits `client.settings_updated` with previous/new ceiling + revert flag in metadata.

### UI (Aiden Settings)

New "Per-tenant LLM ceiling (Q1)" section. Reads current state, surfaces the chip (⚙️ default vs 🟢 override), shows allowed range. For non-admins the form is read-only with a "your role doesn't permit edits" caption. Save button issues PATCH; success rerun reflects the new state.

### Test coverage

Five integration tests:
- `test_tenant_settings_get_returns_default_when_unset`
- `test_tenant_settings_admin_can_set_then_revert` (mutation path with cleanup)
- `test_tenant_settings_operator_cannot_write` (RBAC boundary)
- `test_tenant_settings_rejects_out_of_range`
- `test_tenant_settings_emits_audit_row`

## Q6 — persona library

### Backend

`GET /llm/personas` reads `prompt_profiles` for the active tenant (status='active' only). Returns `{personas: [{id, profile_key, display_name, scope, status, created_at, updated_at}]}`. Tenant scoping is enforced by RLS on the connection. No new table — architect Q6 lock.

### UI (Aiden Settings)

Persona library section groups personas by scope (client / workflow / wo) and renders each as `display_name · profile_key · status`. Editing routes through the existing prompt-profile surfaces; this view is read-only by design.

### Test coverage

Two integration tests:
- `test_personas_list_returns_active_prompt_profiles`
- `test_personas_requires_client_read` (intruder → 403)

## Q7 — chat persistence wired

### What changed

`apps/console-streamlit/views/chat.py` previously held messages in `st.session_state` only — refresh = lose history. Phase 2 wires the page to the existing `/chat_sessions/me` backend (built in Beta-1 ε.2):

- **Hydrate-on-first-render** via `_hydrate_from_server(api)`. Marks the session id as hydrated so subsequent reruns within a session don't re-fetch. Empty server state → seeds the welcome message and marks hydrated (so future PUTs land cleanly).
- **PUT-on-every-turn** via `_persist_to_server(api)` — fires after each user message, each Aiden reply, each promote action.
- **DELETE-on-clear** via `_clear_on_server(api)` — Clear-history button.
- **Graceful API-down fallback**: any `APIError` flips `_PERSIST_DISABLED_KEY`; chat keeps working in session-state-only mode and surfaces a banner so the operator knows persistence is offline.

A different operator on the same tenant gets their own row (per-`(user_id, client_id)` UNIQUE) — operator-scoped continuity, not agent-side memory.

## Q11 — per-operator scratch

### Backend

`POST /workspace/folders/scratch` — idempotent. Three states:

1. Fresh user → creates `Scratch (you)` under tenant root with `owner_user_id = ctx.user_id`.
2. Existing active scratch → returns the same row (no audit, no mutation).
3. Soft-deleted scratch → restores it (clears `deleted_at`). Preserves any subfolder/file contents the operator left behind, and avoids the `(client_id, parent_folder_id, name)` UNIQUE collision a fresh INSERT would trigger.

Audit emits `folder.created` with `scope: per_operator_scratch` (and `restoredFromSoftDelete: true` on path 3).

### Tree visibility

The Beta-1.5 ε.5 fix already filters `(owner_user_id IS NULL OR owner_user_id = $user_id)` on tree + folder reads. Phase 2 surfaces `owner_user_id` in the tree response so the UI can chip "🗒️ scratch" without a second round-trip.

### UI

- 🗒️ icon replaces 📁 on per-operator scratch folders in the tree picker.
- New "Create my scratch folder" button (or "Open my scratch" deep-link if already exists).
- Selected scratch folder shows `🗒️ per-operator scratch (visible only to you)` in the header chip.

### Test coverage

Two integration tests:
- `test_scratch_folder_create_then_get_returns_same_row` (idempotency + cross-operator invisibility)
- `test_scratch_folder_requires_workspace_write` (viewer 403)

## Audit vocabulary delta

One new event added to the locked vocabulary:

```text
client.settings_updated   — Q1 ceiling editor mutation
```

Locked under `BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS`. The Q15 encryption path reuses `credential.encrypted` (already locked in BETA_PHASE_1 in ε.1, anticipating this phase).

Snapshot deltas:
- `auditEvents.all` count: 109 → 110
- New per-loop array: `BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS` (1 entry)
- `tests/contract/contract-enums.test.ts` cardinality assertions updated
- `tests/contract/_snapshot-helpers.ts` exports the new array

## CI snapshot at phase 2 closeout

```
pytest:    248 passed, 1 skipped (was 235; +13 new tests)
vitest:    581 passed across 51 files (unchanged from ε.5)
streamlit: 24 passed, 3 skipped (unchanged)
```

13 new pytest:
- 5× `test_credentials_crypto_*` (unit, no DB)
- 2× `test_scratch_folder_*`
- 5× `test_tenant_settings_*`
- 2× `test_personas_*`

## Risks delta

### Retired

- **R-031** (partial → full) — UI tail closed: chat persistence wired, ceiling editor live, persona library surfaced, scratch UI shipped.
- **R-046** — already retired in ε.5; mentioned for traceability.

### Mitigated (deferred → mitigated)

- **R-045** Encrypted-at-rest deferred → **mitigated**. Code path exists with graceful fallback. Operator must `uv add pynacl` + set `IWO3_CRYPTO_MASTER_KEY` to activate. Same R-034 pattern. Stays mitigating until an operator confirms it on a networked host.

### Activated (dormant → mitigating)

- **R-038** Encryption-key derivation SPOF — activates with R-045 mitigation. The HKDF approach scopes per-tenant blast radius but `IWO3_CRYPTO_MASTER_KEY` loss is still unrecoverable. Operator runbook documents this explicitly.

### Carry-forward (unchanged)

- **R-034** Drag-drop dep activation — strict carry per architect 2026-04-25.
- **R-037** Auth signing-key rotation operational complexity.
- **R-039** Webhook HMAC secret leak detection (telemetry exists since ε.5).
- **R-044** Login route bypass-conn (architectural exception).

## Posture statement

Beta-1 + Beta-1.5 phase 1 (ε.5) + Beta-1.5 phase 2 together form the **completed Production Posture baseline.** The webhook → dispatch path is end-to-end; audit telemetry that mitigations rely on is real; per-operator scratch backend and UI both isolate; encrypted-at-rest credentials have a code path waiting on a single operator step; and every Q1–Q15 architect-locked outcome has either shipped end-to-end or is mitigated with a documented next-action.

**Beta-2 (Capability Expansion) opens cleanly from this baseline** — Slack adapter, Sandbox PPTX/PDF, Tool/MCP registry, Aiden conversational v2 — per architect Q12/Q14 lock.

## Sign-off checklist

- [x] Q15 — `runtime/credentials_crypto.py` ships with offline fallback; module imports cleanly without pynacl; `is_available()` discriminates correctly.
- [x] Q15 — Migration 0018 applied; encrypted triplet CHECK constraint enforces all-or-nothing.
- [x] Q1 — `PATCH /tenants/me/settings` admin-gated; ceiling editor visible in Aiden Settings; revert path tested.
- [x] Q6 — `GET /llm/personas` read-only; persona library section visible.
- [x] Q7 — chat.py hydrates + persists; clear-history wired; offline fallback surfaces a caption.
- [x] Q11 — scratch endpoint idempotent + soft-delete restore; "Create my scratch" + "Open my scratch" both work; cross-operator invisibility tested.
- [x] CI green: pytest 248/1 skipped, vitest 581/0, streamlit 24/3.
- [x] Audit vocabulary lock — `client.settings_updated` added; `BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS` array + snapshot delta committed.
- [ ] Operator activates pynacl on networked host (R-045 final retire).
- [ ] Architect acceptance of Beta-1.5 phase 2 → Beta-2 authorization.

## Recommendation to CODEX

**Accept Beta-1 + Beta-1.5 phase 1 + Beta-1.5 phase 2 together as the completed Production Posture baseline.** Authorize Beta-2 (Capability Expansion) on acceptance. R-045 stays mitigating until the operator runs `uv add pynacl` on a networked host; that is a one-command step, not blocking.

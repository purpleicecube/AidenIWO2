# IWO3 MegaLoop Beta-1.5 — Architect-Flagged Gap Fixes Record v0.1.0

Date: 2026-04-25
Status: **Code-complete** for the three architect-identified gaps. Beta-1 + Beta-1.5 together now form the credible Production Posture baseline.
Branch: `iwo3/main`.
Predecessors: `IWO3_MEGALOOP_BETA_1_RECORD_v0.1.0.md` (commits `4dfeee5`→`c0f23e6`).
Successor: Beta-1.5 phase 2 (encrypted creds + UI surfaces) when PyPI is reachable; then MegaLoop Beta-2.

## Why Beta-1.5 was opened

CODEX review of `c0f23e6` flagged three gaps where the Beta-1 record overstated the shipped state:

1. **HIGH** — `POST /webhook/telegram` verified the signature and emitted `webhook.received` but did **not** hand the parsed update into the inbound/intent pipeline. Operators disabling the long-poll worker (the documented production posture) would have accepted inbound traffic and silently dropped it.
2. **MED** — `webhook.signature_invalid` was locked in vocabulary + counted in the audit-event totals, but the route's 401 path raised without writing an audit row, so the telemetry that R-039 mitigation relied on did not exist at runtime.
3. **MED** — Q11 per-operator scratch was claimed as "schema + RLS-ready" but the workspace tree + folder-contents queries did not filter by `owner_user_id`. The schema column existed; the read paths ignored it.

All three are now fixed. This record documents the fixes, the test coverage for each, and the corrected status carry-forward into Beta-2 scoping.

## Phase summary

| Phase | Headline | Where |
|-------|----------|-------|
| ε.5 fix #1 | Webhook → real dispatch pipeline | `routes/webhooks.py` (full rewrite) + `workers/telegram_worker.py` (public alias `process_telegram_update`) |
| ε.5 fix #2 | `webhook.signature_invalid` audit emission | `routes/webhooks.py` `_resolve_tenant_and_audit` |
| ε.5 fix #3 | `owner_user_id` filter in workspace reads | `routes/workspace.py` (tree + folder contents + 404 on foreign scratch) |
| ε.5 closeout | This record + corrected Beta-1 status notes | governance |

## Fix #1 — Webhook → real dispatch (HIGH)

**Before:** verified payloads logged `webhook.received` and parsed best-effort, then returned 200. No `record_inbound_message`, no `dispatch_intent`, no outbound queue. Production traffic disappeared.

**After:**
- `workers/telegram_worker.py` exposes `process_telegram_update` as a public alias for the existing `_process_update` helper. Same dispatch path the long-poll worker uses.
- `routes/webhooks.py` constructs a per-request `TelegramAdapter` for the resolved tenant and calls `process_telegram_update(get_db_pool(), adapter, parsed_update)`.
- The pipeline runs identically whether the inbound came from the worker or the webhook: `record_inbound_message` → `dispatch_intent` → `queue_outbound_message` → `mark_inbound_processed` (or `mark_outbound_attempt_failed` on Telegram-side failure). Both `/start` cross-tenant binding and bound-chat dispatch work.
- Webhook-layer exceptions inside the pipeline are caught + logged; the inbound is durably persisted (β.5 idempotency hardening guarantees no double-write on Telegram retries), so the route returns 200 to keep Telegram from re-firing. `mark_inbound_failed` runs inside `process_telegram_update` on the failure path.

**Architect impact:** Operators can now set `IWO3_TELEGRAM_WORKER_DISABLED=true` in production — the documented Beta-1 posture — without losing inbound processing. Q3 truly closes.

## Fix #2 — `webhook.signature_invalid` audit emission (MED)

**Before:** the locked vocabulary contained the event but the 401 path re-raised without writing it. R-039 mitigation ("telemetry via webhook.signature_invalid audit on bad attempts") was inert.

**After:**
- `_resolve_tenant_and_audit` (replacing the ε.4 `_resolve_tenant_for_webhook`) walks active tenants and, for every tenant with a configured webhook secret that did **not** match the inbound signature, opens a tenant-scoped tx and writes one `webhook.signature_invalid` audit row. Metadata records the rejection reason (`hmac_bad_sig` / `hmac_bad_timestamp` / `hmac_expired_timestamp` / `none`), the body byte count, and which signature header was present.
- Operators see attack pressure per-tenant — useful even when the rejection cause is identical across tenants.
- Audit failures are logged at warn level but don't block the 401 (the security primary is the rejection itself; telemetry is best-effort).

**Test coverage:** `test_webhook_signature_invalid_emits_audit` queries `action_audit_log` directly before and after the failed POST, asserting at least one new row. The pre-fix code would have left the count unchanged.

## Fix #3 — `owner_user_id` filter (MED)

**Before:** the schema comment claimed per-operator scratch was "visible only to the named user via route-layer filter", but `GET /workspace/tree` and `GET /workspace/folders/{id}` both read every folder + every file regardless of `owner_user_id`. A second operator on the same tenant would see — and be able to deep-link into — the first operator's scratch folders.

**After:**
- `GET /workspace/tree`: folders filtered with `WHERE deleted_at IS NULL AND (owner_user_id IS NULL OR owner_user_id = $user_id)`. Files joined to their parent folder and filtered by the same predicate.
- `GET /workspace/folders/{id}`: foreign-scratch access returns 404 (matches the existing not-found contract; doesn't leak existence). Children + files filtered by the same predicate.
- `_ensure_folder_exists` returns `owner_user_id` so the route can make the foreign-scratch decision.
- Tenant-shared folders (the seeded `/` root + `Outputs/`) have `owner_user_id IS NULL` and remain visible to every tenant member with `workspace:read`.

**Test coverage:** `test_per_operator_scratch_folder_isolation_in_tree` directly inserts two scratch folders (one for owner, one for operator), then asserts each user's `/workspace/tree` shows only their own scratch + tenant-shared folders, and that a `GET /workspace/folders/<foreign-scratch>` returns 404 for the non-owner. Cleanup at end of test.

## CI snapshot at ε.5 closeout

```
pytest:    232 → 235 passed (+3 new tests; 1 skip preserved)
vitest:    581 passed across 51 files
Streamlit: 24 passed, 3 skipped
```

The +3 new tests:
- `test_webhook_signature_invalid_emits_audit`
- `test_webhook_dispatches_unbound_chat_to_pipeline`
- `test_per_operator_scratch_folder_isolation_in_tree`

## Corrected Beta-1 status

The Beta-1 record (`IWO3_MEGALOOP_BETA_1_RECORD_v0.1.0.md`) overstated three Q outcomes. With ε.5 fixes the corrected status is:

| Q | Pre-ε.5 record claim | True post-ε.5 status |
|---|---|---|
| Q3 (webhook ingress) | ✅ shipped | ✅ shipped — webhook dispatches into pipeline |
| Q11 (per-operator scratch) | ✅ schema + RLS-ready, UI deferred | ✅ schema + read-path filter, UI still deferred |
| `webhook.signature_invalid` audit | counted as locked-and-emitted | ✅ now actually emitted |

R-039 mitigation is now substantive (telemetry exists). R-046 — the gap risks themselves — gets logged in v0.3.0-partial as **retired in this same loop** so the audit trail stays clean.

## Risks delta

### Retired in ε.5

- **R-046 (NEW + retired same-loop)** — the architect-flagged set of three gaps in `c0f23e6`. Logged for traceability; closed by ε.5 fixes #1/#2/#3.

### Carry-forward into Beta-1.5 phase 2 (unchanged)

- **R-045** Encrypted-at-rest deferred — pynacl install still blocked in offline sandbox.
- **R-031 partial / Q1/Q6/Q7/Q11 UI** — Streamlit-side surfaces still in carry.
- **R-034** Drag-drop dep activation — strict carry per architect 2026-04-25.

### Posture statement

Beta-1 + Beta-1.5 ε.5 together form the **credible Production Posture baseline**. The webhook → dispatch path is closed end-to-end; the audit telemetry that mitigations rely on is real; and per-operator scratch backend isolation matches what the schema comment claims. Beta-1.5 phase 2 (encryption + UI surfaces) remains the natural completion point for v0.3.0 final, but the architect's three High/Medium gaps no longer block honest acceptance of Beta-1.

## Sign-off checklist

- [x] Fix #1 (HIGH) — webhook routes verified payloads through `process_telegram_update`; operators can disable long-poll worker without dropping inbound.
- [x] Fix #2 (MED) — `webhook.signature_invalid` audit emitted on every 401 path; test asserts the audit side-effect.
- [x] Fix #3 (MED) — `owner_user_id` filter on tree + folder-contents reads; cross-operator isolation tested.
- [x] CI green: pytest 235 / 1 skipped, vitest 581 / 0, streamlit 24 / 3.
- [x] Beta-1 status notes corrected here; the prior record stays as-is (architect explicitly accepted `c0f23e6` as the baseline; this record is the delta).
- [ ] Operator F2 verification (Beta-1.5 phase 2 still required for the UI tail + encrypted creds).

## Recommendation to CODEX

Accept Beta-1 + Beta-1.5 ε.5 together as the **credible Production Posture baseline.** Open Beta-1.5 phase 2 next (encrypted creds via pynacl + Streamlit UI surfaces) when PyPI is reachable. Hold Beta-2 until phase 2 lands per the original handback recommendation.

# IWO3 Pre-Beta Gap Closure — CODEX Architect Dev Review Report v0.1.0

Date: 2026-04-24
Author: Implementation team (Claude Opus 4.7).
Audience: CODEX architect.
Purpose: Single document the architect reads to confirm the gap closure loop satisfied the directive, and to surface the open architectural questions that block scoping MegaLoop Beta.

## Executive summary

The Pre-Beta Gap Closure Loop closed the truth gaps the architect named in the directive. IWO3 now offers:

- a real end-to-end runtime path reachable from the browser (operator clicks "Run Aiden + Tier 2" on a WO and Tier 1 → Tier 1.5/Tier 2 → output_package fires inline);
- a real Telegram operating surface (worker active in lifespan; /start binding, intent dispatch, outbound delivery, last_seen_at all wired);
- browser-side CRUD for the sub-agent roster (provider/model/base URL/system prompt/enabled/display_name/description editable, plus New + Disable);
- corrected channel idempotency scope (cross-chat collisions cannot alias rows);
- truthful credential state surfacing without leaking secrets.

**No Beta items were pulled into scope.** The directive's "EXPLICITLY DEFERRED TO MEGALOOP BETA" list is intact.

## Acceptance criteria — verification

The directive's 13 numbered criteria all carry ✅ in the closeout record:

```
#1  Browser → real runtime (Tier 1 → 1.5 → 2 → output_package → handoff)
#2  Telegram inbound reaches real runtime
#3  /start CODE end-to-end
#4  Outbound replies via outbox/send path
#5  Channel dedup chat-scoped
#6  Edit provider/model/base URL/system prompt/enabled
#7  Browser CRUD without DB-only edits
#8  Truthful credential state without raw secrets
#9  Sub-agent metadata model v1 used by UI
#10 Connection test still works post-edit
#11 Browser no longer "read-only admin-lite"
#12 Documentation reflects new truth
#13 CI green; no regressions
```

Detailed mapping in `IWO3_PRE_BETA_GAP_CLOSURE_RECORD_v0.1.0.md` § "Acceptance criteria — outcome".

## What changed

### New runtime surface
- `POST /work_orders/{id}/dispatch` runs Aiden Tier 1 against the WO's title+description and routes the decision (`work_order_brief` → Tier 2 + output_package; `workflow_brief` → PM Tier 1.5 instantiation; `clarification` → return question without DB writes).
- `POST /workflows/{execution_id}/run_next_step` advances one pending step_run inline.
- `workers/telegram_worker.py` lifespan task drains every Telegram-bound tenant on a 10s tick (`IWO3_TELEGRAM_WORKER_DISABLED=true` to opt out).

### CRUD parity v1
- `POST /llm/configs`, `PATCH /llm/configs/{id}`, `DELETE /llm/configs/{id}` (admin-gated, audit-logged).
- Sub-Agents page rewritten to support Edit / Test / Disable per row + a "New sub-agent" form.
- Aiden Settings inline editor for the Tier 1 row + Test Connection button.
- Work Orders detail expander gets a "Run Aiden + Tier 2" button.

### Schema delta
- Migration 0012: `llm_configs.display_name` (NOT NULL with backfill) + `description`.
- Migration 0013: `channel_messages_inbound_external_uniq` widened to include `external_chat_id`.

### ADRs
- ADR-025 (LLM config CRUD model)
- ADR-026 (sub-agent metadata model v1)
- ADR-027 (Telegram runtime worker)
- ADR-028 (channel idempotency scope correction)

### Risk register
- v0.2.0 → v0.2.1.
- 4 Alpha risks retired (Tier 2 dispatch transport seam; Telegram theoretical; channel cross-chat collision; read-only admin-lite).
- 3 new Pre-Beta risks added (R-029 system:admin-only RBAC on config CRUD; R-030 heuristic display_name backfill; R-031 no persona library yet).
- R-022 Telegram offset persistence downgraded S1 → S2 thanks to the corrected idempotency scope.

## Quality gates

- **Lint:** `require-tenant-scope-on-client-tables` + `no-raw-audit-insert` clean. No new bypass-rls-explain annotations beyond the pre-existing channel-layer + workflow_step_runs ones.
- **Contract snapshot:** `tests/fixtures/contract-enums.snapshot.json` updated for the 3 new audit events. Snapshot freeze test green.
- **TS/Python parity:** `_snapshot-helpers.ts` carries `PRE_BETA_PHASE_2_AUDIT_EVENTS`; the Python audit writer side uses the same string keys directly.
- **No new RBAC keys.** Per ADR-025 § 2 we chose `system:admin` over a fresh `llm_config:*` family. Permission cardinality stays at 72; role-permission rows stay at 223.

## Final test posture

```
pytest:    185 passed, 1 skipped, 3 warnings
vitest:    581 passed across 51 test files
Streamlit: 24 passed, 3 skipped
```

(Up from 160 / 1 / 24 at α.8 — +25 new pytest tests across β.2/β.3/β.4/β.5.)

## Operator path forward

`IWO3_PRE_BETA_F2_ADDENDUM_v0.1.0.md` adds 4 new verification flows on top of the 9 Alpha flows. All 13 must carry ✅ before declaring the loop operator-verified.

## Open architect questions (carried from α.8 review report, refined)

These four still block scoping MegaLoop Beta:

1. **Per-tenant LLM ceiling override schema:** column on `clients`, separate `llm_quotas` table, or operator-policy registry? β.2 would have folded a per-tenant override into the same CRUD surface, but doing so without architect input would have invented schema. (ADR-028 candidate.)

2. **Beta auth choice:** Replit OAuth, custom signed JWT, or external (Auth0 / WorkOS)? Pre-Beta closure left R-028 (dev bearer in prod) untouched per Stage A § D4 lock. (ADR-029 candidate.)

3. **Channel webhook endpoint design:** path-based per-tenant secret, or one endpoint with `update_id` cross-reference? β.4 deliberately chose long-poll for Alpha posture; Beta needs the architect's call here. (ADR-030 candidate.)

4. **Cost-aware provider arbitration:** static per-role priority, or dynamic based on per-tenant cost budget? Tied to question #1.

Two new architect questions emerging from this loop:

5. **RBAC granularity for config CRUD.** R-029 captures the trade-off: `system:admin` is the only gate today. For external pilot tenants in Beta, do we add `llm_config:create/update/delete` keys or accept the broader `system:admin` scope? Trade-off: vocabulary growth (3 keys, ~12 role rows) vs operator-workflow separation.

6. **Persona library / template profiles.** R-031 captures the "every new sub-agent starts from a blank prompt" friction. Does Beta carry persona templates per role (with versioning), or remain prompt-by-hand? Tied to whether prompt_profile machinery from Loop 2 should hold sub-agent-default prompts.

## Recommendation

Approve β.7 closeout. The Pre-Beta acceptance bar is met; CI is green; deferrals are recorded; the open architect questions are the right ones to discuss before Beta scoping.

The next forward action is: operator runs the F2 verification (9 Alpha + 4 Pre-Beta flows). Once green, MegaLoop Beta can scope around the six open architect questions above.

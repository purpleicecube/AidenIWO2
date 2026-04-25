# IWO3 MegaLoop Beta — Risk Alignment Note v0.1.0

Date: 2026-04-25
Status: Draft for CODEX review (optional but recommended companion). Post-architect-feedback edit applied 2026-04-25.

## Edit history

- **2026-04-25 — post-architect-feedback audit:** verified R-032 stays under "Retire" (Beta-1 must-have Q7 closes it). The earlier scope-proposal §E listed R-032 under both "retire" and "carry forward"; that has been corrected in the proposal. This note's R-032 entry was already correct and required no change. R-034 wording verified strict ("carried operational caveat, not a completed drag-drop parity item") and consistent across all four package artifacts.
Predecessor risk register: `RISK_REGISTER_v0.2.3.md` (post-δ).
Target risk register: `RISK_REGISTER_v0.3.0.md` (post-Beta).

This note maps every active risk in v0.2.3 against Beta scope so CODEX can see clearly which risks Beta intends to retire vs carry forward, and what the risk register will look like at Beta close.

## Active risks (v0.2.3) — Beta disposition

| Risk | Severity | Title | Beta disposition | Why |
|---|---|---|---|---|
| R-021 | S1 | Per-WO LLM ceiling at call-time | **Retire** | Beta must-have "Per-tenant LLM ceiling overrides" (Q1) closes this; per-call gate gets per-tenant value, monitor-only afterwards |
| R-022 | S2 | Telegram offset persistence is in-process | **Carry** | Bounded post-β.5 idempotency; Beta does not invest unless a real failure surfaces |
| R-023 | S2 | Auth-code consume on bypass connection | **Carry** | Architectural by design (cross-tenant lookup); annotated; no Beta need |
| R-024 | S2 | Telegram bot token loss → outbound stall | **Retire** | Beta must-have `/health/channels` makes resolution visible to operator |
| R-025 | S2 | Workflow launch deferred from chat | **Retire (partial)** | Cross-session chat context (Q7) gives chat the same Open-Workflow deep-link path browser has; full chat-driven workflow instantiation remains GA |
| R-026 | S3 | RBAC granularity carried decision | **Retire** | Beta must-have "RBAC granularity for config CRUD" (Q5) takes a side either way; carry-forward becomes ADR-decided not open-question |
| R-027 | S3 | Tier 2 dispatch transport seam | retired in γ | n/a |
| R-028 | S3 | Dev bearer auth in production | **Retire** | Beta must-have "Production auth" (Q2) closes this |
| R-029 | S2 | `system:admin` only RBAC gate on llm_config CRUD | **Retire** | Same as R-026 above |
| R-030 | S3 | display_name backfill heuristic | **Carry** | Cosmetic; new tenants seeded explicitly post-δ |
| R-031 | S3 | No persona library | **Retire if Beta should-have ships** (Q6) | Otherwise carry to GA |
| R-032 | S3 | Chat context in-process Streamlit session state | **Retire** | Beta must-have "Cross-session chat context durability" (Q7) closes this |
| R-033 | S3 | Client-side idempotency only | **Retire** | Beta must-have "Server-side WO idempotency" (Q8) closes this |
| **R-034** | **operational caveat** | **Drag-drop dep activation** | **Carry — visible until literal drag-drop activated on networked host** | Per CODEX 2026-04-25 — "must remain visible until literal drag-drop is live, not just code-wired" |
| R-035 | S3 | Workspace file content not fetchable | **Retire** | Beta must-have "Workspace file content fetch route" (Q9) closes this |
| R-036 | S3 | Soft-deleted workspace folders accumulate | **Retire** | Beta must-have "Workspace hard-delete model" (Q10) closes this |

## Anticipated v0.3.0 risk register — projected shape

Assuming Beta executes per the proposal:

### Retired in Beta (10 risks)
R-021, R-024, R-025 (partial), R-026, R-028, R-029, R-031 (if persona library ships), R-032, R-033, R-035, R-036.

### Carried into v0.3.0 (3 risks + caveat)
- R-022 Telegram offset (Beta non-essential)
- R-023 Auth-code bypass connection (architectural)
- R-030 display_name heuristic (cosmetic)
- **R-034 drag-drop dep — operational caveat, NOT consumed by Beta**

### New risks anticipated by Beta (provisional)
Beta will introduce its own risks; these are projected and will be locked at Beta closeout:

| Provisional ID | Severity (est.) | Anticipated risk |
|---|---|---|
| R-037 | S2 | Production auth secret rotation operational complexity (depends on Q2 choice) |
| R-038 | S2 | Encrypted-at-rest key derivation: a lost runtime secret means lost provider keys (depends on Q15 choice) |
| R-039 | S2 | Webhook signature verification gap if HMAC secret leaks |
| R-040 | S3 | Slack adapter rate-limit posture different from Telegram (per-bot vs per-workspace) |
| R-041 | S3 | Sandbox PPTX/PDF library version drift between dev and prod |
| R-042 | S3 | MCP registry shape may need backwards-incompatible updates when execution lands post-Beta |
| R-043 | S2 | Cross-session chat history grows unbounded; retention policy needed |

These are speculative until Beta locks the answers to Q2/Q3/Q15 and the implementation surfaces actual failure modes.

## Carry-forward visibility for R-034

Per CODEX directive 2026-04-25:

> R-034 drag-drop activation caveat — accepted operational caveat, not a blocker to Beta opening, **must remain visible until literal drag-drop is live, not just code-wired**.

Implementation plan for visibility:

1. R-034 stays in the Beta closeout risk register (`RISK_REGISTER_v0.3.0.md`) with the same severity ("operational caveat") and same wording.
2. The Beta record explicitly notes R-034 status under "carried forward (not consumed)".
3. The first time `streamlit-sortables` is verified active on a networked host and an operator confirms literal drag-drop works, R-034 retires in a follow-up risk register bump (v0.3.0.1 or v0.3.1).
4. Beta closeout artifacts include a one-line "drag-drop verification status" check; if still ⚠️, the line stays in the GA scoping packet.

This is a 30-second operator action (`cd apps/console-streamlit && uv sync` followed by a browser smoke-test) — not a sustained engineering item.

## Signal to CODEX

Beta's risk profile is **net-positive**: 10 retires + 3 carry + 1 caveat. New Beta-introduced risks are projected to be lower-severity than those retired (most S2/S3, no fresh S1).

The biggest residual concern is **R-038 (encrypted-at-rest key derivation)**: a misconfigured runtime secret could brick provider access for a tenant. Mitigation depends on Q15's choice — option (b) libsodium with operator-owned secret rotation is recommended, with a clear runbook entry on key recovery.

This note is companion to the Beta scope proposal; CODEX may treat it as advisory or fold it into the prestart decision memo.

# ADR-020 — Live adapter dual gate, env-injected credentials, async polling, non-Gamma symmetry

Date: 2026-04-25
Status: Accepted (Loop 9)
Predecessors: ADR-012 (output packages + adapter registry), ADR-014 (RBAC permission model), ADR-015 (RLS enforcement + tenant context).
Companions: `IWO3_LOOP_8_3_CODEX_DECISIONS_v0.1.0.md` (locked Q1–Q5), `IWO3_LOOP_9_SCOPE_PROPOSAL_v0.1.0.md`, `LOOP_9_RECORD.md`.

## Context

Loop 3 Phase 3.4 proved the `AdapterContract` end-to-end with a Gamma test-double. Loop 9 ships the first real outbound dispatch path (Gamma live render). Three things needed to land together for that to be safe and accurate:

1. A pre-dispatch authorization gate that cannot be bypassed by either an environment misconfiguration OR an operator skipping confirmation.
2. A credential posture that lets us iterate quickly without ever risking raw API keys at rest in the database, fixtures, logs, or commit history.
3. An async-polling model that does not let healthy long-running renders look like failures, and a watchdog that fires only on stale polls or true terminal failures.

Sandbox PPTX/PDF lands next (Loop 10). Whatever shape we settle on for Gamma must work for Sandbox (and later Figma / Stitch / Claude Design / email / CRM) without reshaping the runtime contract.

## Decision

### 1. Dual first-live-invocation gate

Two independent legs, both must pass for any live dispatch:

**Leg A — environmental kill-switch**

- Each live adapter declares a `envFlagName` in its `AdapterDescription` (e.g. `"GAMMA_LIVE_ENABLED"`).
- The dispatcher reads `process.env[envFlagName]` and short-circuits unless the value is the literal string `"true"`. Any other value (including unset, empty, `"1"`, `"True"`) is treated as false. Audit row: `adapter_dispatch.live_disabled`.
- Adapters with `isLive: true` and a missing `envFlagName` fail-closed with the same audit.

**Leg B — operator first-invocation confirmation**

- `adapter_credentials` carries `first_invocation_confirmed_at` and `first_invocation_confirmed_by_user_id`. NULL means "never approved for live dispatch."
- An admin (`adapter_credential:rotate` permission, owner / admin roles only — Loop 4 §Q2) flips this via `POST /adapter_credentials/{id}/confirm_first_invocation`. The route is idempotent — a second confirmation is a no-op without writing a duplicate audit row.
- Audit row on first confirmation: `adapter_credential.first_invocation_confirmed`.
- Dispatcher refusal when the timestamp is NULL: audit `adapter_dispatch.first_invocation_pending`.

**Why two gates rather than one**

- Leg A is the "we forgot to flip the breaker after restoring from backup" defence. It survives operator changes, replays, restored DBs.
- Leg B is the "we explicitly chose to send the first live request" defence. It survives env-flag-everywhere misconfigurations and demands a deliberate human action.
- Either gate alone could be gamed; both together require an environment misconfiguration AND an operator misclick to leak.

Candidate review (Loop 6) is **deliberately not used here**. Candidate review governs *artifact choice* (operator picks one of N rendered candidates); the dual gate governs *outbound-service authorization*. Mixing them would conflate content quality approval with network-egress approval.

### 2. Credential posture — env-injected at runtime, DB ref-only

- `adapter_credentials.credential_ref` holds the literal string `credential_ref:env:NAME`. Nothing else.
- Raw API keys live exclusively in `process.env[NAME]` at runtime. They never persist to:
  - Database rows
  - Seed JSON
  - Audit log metadata (writer redacts; tests assert)
  - Error responses (FastAPI dep middleware redacts)
  - Commit history (gitleaks CI scans on every push; rule allowlists `credential_ref:` placeholders only)
- The dispatcher resolves `credential_ref` to the env value at I/O time. If the ref shape is wrong or the env var is unset, the adapter raises `GammaAdapterError(kind="credential_invalid")` and the dispatcher emits `adapter_dispatch.credential_invalid`. The DB row is never modified by a bad runtime resolution.
- Secret-at-rest in DB is **explicitly out of scope for Loop 9**. If we want it later (HSM-backed cells, external secret manager handle, etc.), it ships as its own approved hardening slice with explicit encryption/key-management design.

### 3. Async polling on the handoff, not on the WO

- Once a live dispatch submit succeeds and the adapter's `fetchResult` returns `status="unknown"` (still rendering), the dispatcher leaves the handoff in `submitted` and the parent WO in `processing`. New `pending_poll` `DispatchResult` variant signals this.
- Per-poll metadata lives on `output_handoffs`: `last_poll_status`, `last_poll_at`, `poll_count`. Each poll attempt increments the count + timestamps the row.
- `pollHandoffStatus` (TS) and `poll_gamma_handoff` (Python mirror) are the canonical advance functions. They run inside the caller's transaction and emit phase-locked audit events:
  - Successful poll → `adapter_dispatch.completed` + handoff status `completed`.
  - Terminal adapter failure → `adapter_dispatch.failed` + handoff status `failed`.
  - Still pending → `adapter_dispatch.polling` + handoff stays `submitted`.
- WO state never bounces during healthy rendering. WO transitions are reserved for terminal handoff outcomes (cascade is out of scope for Phase 9.4 — handled by the Loop 6 transition helper from the calling layer).

### 4. Watchdog policy

- Each adapter action carries an optional `adapter_actions.poll_timeout_seconds` (Phase 9.1 schema). Default 600s (10 minutes) when null.
- Watchdog fires when:
  - `now - last_poll_at > poll_timeout_seconds` (stale poll), OR
  - `pollHandoffStatus` is invoked with `forceStaleWatchdog: true` (test / scheduled-job override), OR
  - The adapter returns a true terminal failure (mapped to `adapter_dispatch.failed` directly, not via watchdog).
- Stale-poll watchdog audit: `adapter_dispatch.watchdog_expired_stale_poll`. Handoff transitions to `failed`; `last_poll_status = "watchdog_expired"`.
- Healthy long renders inside the timeout window do NOT trigger the watchdog. The Phase 9.4 integration test asserts this with a 3-poll-then-success sequence.

### 5. Non-Gamma adapter symmetry

The above design is **adapter-agnostic** by construction:

- `AdapterContract` is unchanged from ADR-012; the only extension is the optional `isLive` + `envFlagName` flags on `AdapterDescription` (Phase 9.1).
- The dispatcher has zero Gamma-specific code. It reads `adapter.describe()` for the gate inputs.
- The Python poll mirror is currently Gamma-specific (`poll_gamma_handoff`) but will generalise to a registry pattern when the second live adapter (Sandbox PPTX/PDF in Loop 10) lands.
- `output_kind` enum already covers 11 values across all planned adapter categories (Loop 3 Phase 3.2). No new values were added in Loop 9.
- Sandbox PPTX/PDF can register against the same `AdapterContract` interface, declare `isLive: false` (since it's local-only) or `isLive: true` with its own `envFlagName`, populate the same handoff poll-state columns, and surface in Design Lab via `/adapter_status/sandbox_pptx` (an `ADAPTER_ENV_FLAGS` map entry) without touching the runtime.

## Consequences

**Positive**

- Live Gamma dispatch is now safe to enable per-tenant via two independent admin actions (env flag + first-invocation confirm). Either left undone keeps the system fully test-doubled.
- Forensic trail: every dispatch attempt — refused, submitted, polling, completed, failed, watchdog-expired — produces a single audit row with phase-locked vocabulary. Replaying audit by handoff_id reconstructs the full lifecycle.
- Sandbox PPTX/PDF (Loop 10) requires zero contract changes. It registers + seeds + ships.
- Python and TS share the same poll decision tree via `gamma_request_shape.py` parser parity, so the FastAPI poll path and the future TS scheduled job stay consistent.

**Negative / accepted**

- Dispatcher gating is now ~80 lines of inline switch logic. Acceptable; a dedicated gating module would obscure the lifecycle that's currently easy to read.
- Watchdog uses wall-clock subtraction (`now - last_poll_at`) per row. Cheap at the row level but the queue scan (poll all `submitted` handoffs older than threshold) belongs to a future scheduled-job slice — not Phase 9.4.
- The Python poll mirror is currently Gamma-specific. Generalising this to a `(adapter_key) → poll function` registry is small but deferred to Loop 10.

## Out of scope (deferred)

- Encrypted-at-rest credentials in DB (separate hardening slice).
- Scheduled poll-job that walks all pending handoffs every N seconds (cron / worker — Loop 10+).
- Sandbox PPTX/PDF adapter — Loop 10.
- Live LLM adapter wiring through the same dual-gate pattern — Loop 10+ once LLM Foundation (Phase 9.3) connects to the Tier 1 / Tier 2 call paths.
- Cascade from terminal handoff outcomes to WO state transitions via Loop 6 helpers — caller-orchestrated; not encoded inside `pollHandoffStatus` to keep responsibilities sharp.

## References

- IWO3_LOOP_8_3_CODEX_DECISIONS §Q1 (dual gate locked), §Q2 (credential posture locked), §Q3 (poll/watchdog semantics locked), §Q4 (non-Gamma symmetry guardrail), §Q5 (Phase 9.0 placement).
- IWO3_LOOP_9_SCOPE_PROPOSAL §3.2 (Phase 9.1 credential + gating), §3.3 (Phase 9.2 GammaLiveAdapter), §3.4 (Phase 9.4 async polling), §3.5 (Phase 9.5 closeout).
- LOOP_9_RECORD.md — full phase ship history with commit hashes + CI runs.
- Migrations: `0007_loop9_phase1_credential_gating.sql`, `0009_loop9_phase4_async_polling.sql`.
- Audit vocabulary additions: `LOOP_9_PHASE_1_AUDIT_EVENTS` (4), `LOOP_9_PHASE_2_AUDIT_EVENTS` (2), `LOOP_9_PHASE_4_AUDIT_EVENTS` (2). Total Loop-9 audit additions: 8 events. (LLM Foundation events in `LOOP_9_PHASE_3_AUDIT_EVENTS` are governed by Loop 9.3 and not by this ADR.)

---

## Changelog

| Date | Changes |
| --- | --- |
| 2026-04-25 | Initial ADR-020 written at Loop 9 closeout. Documents Phase 9.1 + 9.2 + 9.4 + 9.5 design. Phase 9.3 LLM Foundation is referenced but governed by future LLM-runtime ADR. |

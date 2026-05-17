/**
 * Sandbox-Hosted-In-App β.0 — acceptance state machine constants.
 *
 * Vocabulary-only file. Per the β.0 brief: define schema + contracts
 * + permissions + audit vocab + ADR. **No transition logic, no
 * helpers, no dispatcher.** The transition validator + per-state
 * helpers belong to β.1+ (mirrors the Loop 6 Phase 6.1 → 6.2 split
 * where 6.1 was constants-only and 6.2 wired the helpers).
 *
 * Authority:
 *   - ADR-036 (sandbox β-line state machine + enforcement edge)
 *   - CODEX β.0 brief disposition (WS024 baseline `edce652`)
 *   - D-B2 (V1 state vocabulary; pass/fail in test evidence, not
 *     in the state machine)
 *   - D-B6 (per-action gating; no per-filetype permissions in V1)
 *   - D-B7 (acceptance gates dispatch, not output-package creation)
 *
 * DB-side mirror: `sandbox_sessions.acceptance_state` CHECK
 * constraint (migration 0033) enforces the same string set. Adding
 * a new state requires updating both surfaces in lockstep.
 *
 * Python parity: not required in β.0 (FastAPI doesn't yet host
 * sandbox routes — the canonical sandbox surface is the Node side).
 * If/when the β.1+ slices add FastAPI sandbox routes, mirror this
 * file into `apps/api-fastapi/contracts/sandbox_state_machines.py`
 * with a byte-for-byte parity test, following the wo-wf precedent.
 */

import { AUDIT_EVENTS } from "../audit/events";

// ── Acceptance state vocabulary (D-B2) ───────────────────────────────
//
// 7 states. Lifecycle:
//   uploaded → evaluating → tested → under_review → accepted
//                                                 ↘ rejected → reopened → uploaded
//
// Mirrors `sandbox_sessions.acceptance_state` CHECK constraint in
// migration 0033.

export const SANDBOX_ACCEPTANCE_STATES = [
  "uploaded",
  "evaluating",
  "tested",
  "under_review",
  "accepted",
  "rejected",
  "reopened",
] as const;

export type SandboxAcceptanceState = (typeof SANDBOX_ACCEPTANCE_STATES)[number];

// Terminal states. Acceptance gates downstream dispatch (D-B7) on
// `accepted`; `rejected` is a terminal "no" that must `reopened` to
// re-enter the workflow.
export const SANDBOX_TERMINAL_STATES = ["accepted", "rejected"] as const;
export type SandboxTerminalState = (typeof SANDBOX_TERMINAL_STATES)[number];

// ── Transition table ─────────────────────────────────────────────────
//
// Same `TransitionSpec` shape used by `packages/contracts/wo-wf/
// state_machines.ts` so future β.1 helpers can re-use the existing
// `describeTransition`/`requirePermission` patterns without inventing
// new ones. β.0 only registers the shape — no validator/dispatcher
// imports here.
//
// 7 transitions covering the full acceptance flow:
//   1. uploaded → evaluating         (sandbox:evaluate, sandbox.evaluated)
//   2. evaluating → tested           (sandbox:test, sandbox.tested)
//   3. tested → under_review         (sandbox:review, sandbox.under_review)
//   4. under_review → accepted       (sandbox:accept, sandbox.accepted)
//   5. under_review → rejected       (sandbox:accept, sandbox.rejected)
//   6. rejected → reopened           (sandbox:evaluate, sandbox.reopened)
//   7. reopened → evaluating         (sandbox:evaluate, sandbox.evaluated)
//
// Notes:
//   - rejection is gated on `sandbox:accept` (same gate as acceptance)
//     because both are terminal acceptance-authority decisions; the
//     gate name reflects the privilege tier, not the verb. The
//     audit event distinguishes them. β.1+ may surface a separate
//     `sandbox:reject` permission if operator review shows the
//     coupling is too tight — captured as an OPEN_NOTE in ADR-036.
//   - `reopened` re-enters the flow at `evaluating` (transition 7),
//     not at `uploaded`, because the artifact bytes haven't changed.
//     If the operator wants to upload a fresh artifact, that's a
//     new session, not a reopen.

export interface SandboxTransitionSpec {
  readonly from: SandboxAcceptanceState;
  readonly to: SandboxAcceptanceState;
  readonly requires: readonly string[];
  readonly event: string;
}

export const SANDBOX_SESSION_TRANSITIONS: readonly SandboxTransitionSpec[] = [
  {
    from: "uploaded",
    to: "evaluating",
    requires: ["sandbox:evaluate"],
    event: AUDIT_EVENTS.SANDBOX_EVALUATED,
  },
  {
    from: "evaluating",
    to: "tested",
    requires: ["sandbox:test"],
    event: AUDIT_EVENTS.SANDBOX_TESTED,
  },
  {
    from: "tested",
    to: "under_review",
    requires: ["sandbox:review"],
    event: AUDIT_EVENTS.SANDBOX_UNDER_REVIEW,
  },
  {
    from: "under_review",
    to: "accepted",
    requires: ["sandbox:accept"],
    event: AUDIT_EVENTS.SANDBOX_ACCEPTED,
  },
  {
    from: "under_review",
    to: "rejected",
    requires: ["sandbox:accept"],
    event: AUDIT_EVENTS.SANDBOX_REJECTED,
  },
  {
    from: "rejected",
    to: "reopened",
    requires: ["sandbox:evaluate"],
    event: AUDIT_EVENTS.SANDBOX_REOPENED,
  },
  {
    from: "reopened",
    to: "evaluating",
    requires: ["sandbox:evaluate"],
    event: AUDIT_EVENTS.SANDBOX_EVALUATED,
  },
] as const;

// ── Enforcement edge (D-B7) ──────────────────────────────────────────
//
// Per D-B7, downstream pipeline progression is gated on a sandbox
// session reaching the `accepted` state. Specifically: an
// `output_packages` row that references a `sandbox_session_id` MUST
// have the referenced session in `acceptance_state = 'accepted'`
// before `output_handoffs` will dispatch.
//
// The enforcement lives in the dispatch helper (β.1+), not at
// output_package creation time — creation, review, and acceptance
// can happen in any order; only the handoff dispatch is blocked.
// Block error code: `409 sandbox_not_accepted`.
//
// β.0 records the contract here; β.1+ wires it.

export const SANDBOX_DISPATCH_GATE_ERROR_CODE = "sandbox_not_accepted" as const;

// ── Permission keys used by the state machine ────────────────────────
//
// Exported for tests + future helpers so the per-loop addition list
// is colocated with the state machine that consumes them.

export const SANDBOX_BETA_0_PERMISSION_KEYS = [
  "sandbox:evaluate",
  "sandbox:test",
  "sandbox:review",
  "sandbox:accept",
] as const;

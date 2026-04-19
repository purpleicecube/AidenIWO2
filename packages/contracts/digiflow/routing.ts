/**
 * Loop 3 Phase 3 — DigiFLOW deterministic routing (TypeScript canonical).
 *
 * Decides whether an intake packet becomes a one-time Work Order, a
 * repeatable Workflow (template), or is flagged `needs_clarification`
 * for human review. Byte-identical output required from the Python
 * mirror at `apps/api-fastapi/digiflow/intake.py`. The parity contract
 * test (`tests/contract/digiflow-routing-parity.test.ts`) enforces.
 *
 * Rules (CODEX response packet §2):
 *   1. If `requested_execution_mode` is `wo` or `wf`, honor it.
 *   2. If `recurrence.kind` is present and not `once`, route WF.
 *   3. If there is at least one `desired_outputs[]` entry and no
 *      recurrence, route WO (one output = single package; many
 *      outputs = WO with multiple output packages — still one run).
 *   4. If multiple phases, reusable steps, or other structural
 *      indicators of repeat work present → WF. (Phase 3.3 uses a
 *      conservative "recurrence is the only WF trigger in auto mode"
 *      rule; Phase 3.4 / Loop 6 may add more signals, each locked in
 *      a follow-up ADR amendment.)
 *   5. Ambiguous (no outputs, no explicit mode, no recurrence) →
 *      `needs_clarification`.
 *
 * The algorithm MUST be side-effect-free and deterministic: no clock,
 * no RNG, no network, no DB. Given the same packet, returns the same
 * decision.
 */

import type { DigiFlowIntakePacket } from "./intake";

export type RouteKind = "wo" | "wf" | "needs_clarification";

export interface RouteDecision {
  kind: RouteKind;
  rationale: string;
}

export function routeIntake(
  packet: Pick<
    DigiFlowIntakePacket,
    "requested_execution_mode" | "recurrence" | "desired_outputs"
  >
): RouteDecision {
  const mode = packet.requested_execution_mode ?? "auto";

  if (mode === "wo") {
    return {
      kind: "wo",
      rationale: "requested_execution_mode='wo' — explicit override",
    };
  }
  if (mode === "wf") {
    return {
      kind: "wf",
      rationale: "requested_execution_mode='wf' — explicit override",
    };
  }

  // mode === "auto" — decide from signals.
  const recurrenceKind = packet.recurrence?.kind;
  const hasRecurrence = !!recurrenceKind && recurrenceKind !== "once";

  if (hasRecurrence) {
    return {
      kind: "wf",
      rationale: `recurrence.kind='${recurrenceKind}' → repeatable workflow`,
    };
  }

  const outputs = packet.desired_outputs ?? [];
  if (outputs.length === 1) {
    return {
      kind: "wo",
      rationale: "single one-time output, no recurrence",
    };
  }
  if (outputs.length > 1) {
    return {
      kind: "wo",
      rationale: `${outputs.length} one-time outputs, single run → WO with multiple output packages`,
    };
  }

  return {
    kind: "needs_clarification",
    rationale:
      "ambiguous — no desired_outputs, no recurrence, no explicit execution mode",
  };
}

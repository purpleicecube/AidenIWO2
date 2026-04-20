/**
 * Loop 6 Phase 6.3 — candidate-review operator flow.
 *
 * Builds on the Phase 3.2 minimal candidate shape (ADR-012,
 * `output_handoffs.candidate_status` + `candidate_group_id`). When an
 * adapter produces N candidates (gamma produces multiple decks from
 * one package, or email adapter drafts several send variants), the
 * handoffs are grouped via `candidate_group_id` and carry
 * `candidate_status = 'candidate'`. A reviewer then picks one with
 * `selectCandidate` (losers auto-reject) or vetoes a single one with
 * `rejectCandidate` (no effect on the group state).
 *
 * Permission gates (locked in Phase 4.1 vocabulary):
 *   - `output_candidate:select` for `selectCandidate`
 *   - `output_candidate:reject` for `rejectCandidate`
 * Neither operator nor agent_system holds these by default (§Q2
 * revised grants) — candidate review is reviewer-only.
 *
 * Events emitted (from the Loop 3 Phase 2 vocabulary, not new):
 *   - `output_candidate.selected`  on the selected handoff
 *   - `output_candidate.rejected`  on every auto-rejected sibling
 *                                   (from a successful select) or on
 *                                   the directly-rejected handoff
 *                                   (from `rejectCandidate`)
 *   - `output_package.validated`   on the parent package when a
 *                                   candidate is selected (the winning
 *                                   candidate is validated content).
 *
 * `output_package.delivered` is NOT emitted here — delivery is the
 * dispatcher's job (Loop 3 Phase 4.2 adapter registry). Candidate
 * review validates the choice; delivery happens after the adapter
 * relays the selected handoff's payload.
 */

import type { PoolClient } from "pg";

import { AUDIT_EVENTS } from "../audit/events";
import { writeAuditRow } from "../audit/writer";
import { requirePermission } from "../authz/require_permission";

export class CandidateNotEligible extends Error {
  readonly handoffId: string;
  readonly currentStatus: string;

  constructor(opts: { handoffId: string; currentStatus: string }) {
    super(
      `CandidateNotEligible: handoff ${opts.handoffId} has candidate_status='${opts.currentStatus}', not 'candidate'`
    );
    this.name = "CandidateNotEligible";
    this.handoffId = opts.handoffId;
    this.currentStatus = opts.currentStatus;
  }
}

export class CandidateHandoffNotFound extends Error {
  constructor(opts: { handoffId: string; clientId: string }) {
    super(
      `CandidateHandoffNotFound: handoff ${opts.handoffId} not found in client ${opts.clientId}`
    );
    this.name = "CandidateHandoffNotFound";
  }
}

interface HandoffRow {
  id: string;
  client_id: string;
  output_package_id: string | null;
  candidate_group_id: string | null;
  candidate_status: string;
}

async function loadHandoff(
  client: PoolClient,
  handoffId: string,
  clientId: string
): Promise<HandoffRow> {
  const { rows } = await client.query<HandoffRow>(
    `SELECT id, client_id, output_package_id, candidate_group_id, candidate_status
     FROM output_handoffs
     WHERE id = $1 AND client_id = $2`,
    [handoffId, clientId]
  );
  if (rows.length === 0) {
    throw new CandidateHandoffNotFound({ handoffId, clientId });
  }
  return rows[0];
}

export interface SelectCandidateInput {
  handoffId: string;
  clientId: string;
  actorUserId: string;
  reason?: string;
}

export interface SelectCandidateResult {
  selectedHandoffId: string;
  rejectedSiblingIds: readonly string[];
  packageValidated: string | null;
}

/**
 * Select a candidate handoff. Auto-rejects every sibling in the same
 * `candidate_group_id`, validates the parent output_package, and
 * writes audit rows for each side effect inside the caller's
 * transaction.
 */
export async function selectCandidate(
  client: PoolClient,
  input: SelectCandidateInput
): Promise<SelectCandidateResult> {
  const auditMetadata: Record<string, unknown> = {
    reason: input.reason ?? null,
  };

  await requirePermission(client, {
    userId: input.actorUserId,
    clientId: input.clientId,
    permission: "output_candidate:select",
    targetType: "output_handoff",
    targetId: input.handoffId,
    metadata: auditMetadata,
  });

  const handoff = await loadHandoff(client, input.handoffId, input.clientId);
  if (handoff.candidate_status !== "candidate") {
    throw new CandidateNotEligible({
      handoffId: input.handoffId,
      currentStatus: handoff.candidate_status,
    });
  }

  // Mark the winner selected.
  await client.query(
    `UPDATE output_handoffs
     SET candidate_status = 'selected',
         selected_at = now(),
         selected_by_user_id = $1,
         updated_at = now()
     WHERE id = $2 AND client_id = $3`,
    [input.actorUserId, input.handoffId, input.clientId]
  );

  // Auto-reject any sibling in the same candidate_group_id that is
  // still in candidate state. Skip when no group (single-candidate
  // select — unusual but legal).
  const rejectedSiblingIds: string[] = [];
  if (handoff.candidate_group_id) {
    const { rows: siblings } = await client.query<{ id: string }>(
      `UPDATE output_handoffs
       SET candidate_status = 'rejected', updated_at = now()
       WHERE candidate_group_id = $1
         AND id <> $2
         AND candidate_status = 'candidate'
         AND client_id = $3
       RETURNING id`,
      [handoff.candidate_group_id, input.handoffId, input.clientId]
    );
    rejectedSiblingIds.push(...siblings.map((r) => r.id));
  }

  // Validate the parent package.
  let packageValidated: string | null = null;
  if (handoff.output_package_id) {
    await client.query(
      `UPDATE output_packages
       SET status = 'validated', updated_at = now()
       WHERE id = $1 AND client_id = $2
         AND status NOT IN ('delivered', 'cancelled')`,
      [handoff.output_package_id, input.clientId]
    );
    packageValidated = handoff.output_package_id;
  }

  // Audit: selected, rejected siblings, package validated.
  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId,
    event: AUDIT_EVENTS.OUTPUT_CANDIDATE_SELECTED,
    targetType: "output_handoff",
    targetId: input.handoffId,
    metadata: {
      ...auditMetadata,
      candidate_group_id: handoff.candidate_group_id,
      output_package_id: handoff.output_package_id,
      rejected_siblings: rejectedSiblingIds,
    },
  });
  for (const siblingId of rejectedSiblingIds) {
    await writeAuditRow(client, {
      clientId: input.clientId,
      actorUserId: input.actorUserId,
      event: AUDIT_EVENTS.OUTPUT_CANDIDATE_REJECTED,
      targetType: "output_handoff",
      targetId: siblingId,
      metadata: {
        reason: "auto_rejected_by_sibling_selection",
        selected_sibling: input.handoffId,
        candidate_group_id: handoff.candidate_group_id,
      },
    });
  }
  if (packageValidated) {
    await writeAuditRow(client, {
      clientId: input.clientId,
      actorUserId: input.actorUserId,
      event: AUDIT_EVENTS.OUTPUT_PACKAGE_VALIDATED,
      targetType: "output_package",
      targetId: packageValidated,
      metadata: {
        reason: "candidate_selected",
        selected_handoff: input.handoffId,
      },
    });
  }

  return {
    selectedHandoffId: input.handoffId,
    rejectedSiblingIds,
    packageValidated,
  };
}

export interface RejectCandidateInput {
  handoffId: string;
  clientId: string;
  actorUserId: string;
  reason?: string;
}

/**
 * Reject a single candidate handoff. Does NOT touch siblings or the
 * parent package — a reviewer can reject one candidate in a group
 * while still deliberating on the others.
 */
export async function rejectCandidate(
  client: PoolClient,
  input: RejectCandidateInput
): Promise<{ rejectedHandoffId: string }> {
  const auditMetadata: Record<string, unknown> = {
    reason: input.reason ?? null,
  };

  await requirePermission(client, {
    userId: input.actorUserId,
    clientId: input.clientId,
    permission: "output_candidate:reject",
    targetType: "output_handoff",
    targetId: input.handoffId,
    metadata: auditMetadata,
  });

  const handoff = await loadHandoff(client, input.handoffId, input.clientId);
  if (handoff.candidate_status !== "candidate") {
    throw new CandidateNotEligible({
      handoffId: input.handoffId,
      currentStatus: handoff.candidate_status,
    });
  }

  await client.query(
    `UPDATE output_handoffs
     SET candidate_status = 'rejected', updated_at = now()
     WHERE id = $1 AND client_id = $2`,
    [input.handoffId, input.clientId]
  );

  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId,
    event: AUDIT_EVENTS.OUTPUT_CANDIDATE_REJECTED,
    targetType: "output_handoff",
    targetId: input.handoffId,
    metadata: {
      ...auditMetadata,
      candidate_group_id: handoff.candidate_group_id,
    },
  });

  return { rejectedHandoffId: input.handoffId };
}

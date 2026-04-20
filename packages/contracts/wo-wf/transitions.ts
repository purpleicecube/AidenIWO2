/**
 * Loop 6 Phase 6.2 — lifecycle transition helpers.
 *
 * Runtime entry points for WO / WF / execution / step-run state
 * changes. Each helper:
 *
 *   1. Loads the current row + tenant-scopes the lookup by `client_id`.
 *   2. Calls `describeTransition(...)` against the Phase 6.1 tables.
 *      Illegal transitions throw `IllegalTransition` — nothing touches
 *      the DB in that branch.
 *   3. For each permission in `spec.requires` calls `requirePermission`
 *      — missing permissions throw `PermissionDenied` and write an
 *      `authz.denied` audit row (ADR-014). Every gate runs under the
 *      caller's transaction.
 *   4. Updates the row's `status` column (tenant-scoped WHERE).
 *   5. If `spec.requiresCycle`, opens a new `execution_cycles` row for
 *      WO-scoped machines (work_order only; workflow_execution's
 *      `requiresCycle` flag is currently documentation for Loop 9+
 *      orchestration — see R-009 in the CODEX log).
 *   6. Writes exactly one audit row using the transition's declared
 *      event name with `{machine, from, to, reason, cycleId?}` metadata.
 *
 * Helper semantics:
 *
 *   - `transitionWorkOrder` / `transitionWorkflow` /
 *     `transitionWorkflowExecution` / `transitionWorkflowStepRun` are
 *     the general-purpose state-change entry points. They pick the
 *     FIRST matching spec from the state-machine table, so
 *     processing → blocked resolves to the "regular block" spec with
 *     `work_order.blocked` event (NOT the watchdog one).
 *
 *   - `watchdogExpireWorkOrder` is a dedicated helper for the
 *     watchdog path (processing → blocked with
 *     `work_order.watchdog_expired` event + cycle row). Exposed
 *     separately so a future Loop-9 watchdog job calls it
 *     unambiguously; manual operator blocks continue to use
 *     `transitionWorkOrder`.
 *
 * Loop 6 intentionally does NOT ship a scheduled watchdog job —
 * Darrel's approved default (§Q1) says helper-only in Loop 6; the
 * scheduler lands in Loop 9.
 */

import type { PoolClient } from "pg";

import { AUDIT_EVENTS } from "../audit/events";
import { writeAuditRow } from "../audit/writer";
import { requirePermission } from "../authz/require_permission";
import {
  describeTransition,
  STATE_MACHINES,
  type StateMachineKey,
  type TransitionSpec,
} from "./state_machines";

// ── Error types ───────────────────────────────────────────────────────

export class IllegalTransition extends Error {
  readonly machine: StateMachineKey;
  readonly from: string;
  readonly to: string;
  readonly code: "unknown_from" | "illegal_transition";

  constructor(opts: {
    machine: StateMachineKey;
    from: string;
    to: string;
    code: "unknown_from" | "illegal_transition";
  }) {
    super(
      `IllegalTransition on ${opts.machine}: ${opts.from} → ${opts.to} (${opts.code})`
    );
    this.name = "IllegalTransition";
    this.machine = opts.machine;
    this.from = opts.from;
    this.to = opts.to;
    this.code = opts.code;
  }
}

export class RowNotFound extends Error {
  readonly table: string;
  readonly id: string;
  readonly clientId: string;

  constructor(opts: { table: string; id: string; clientId: string }) {
    super(
      `RowNotFound: ${opts.table} id=${opts.id} client_id=${opts.clientId}`
    );
    this.name = "RowNotFound";
    this.table = opts.table;
    this.id = opts.id;
    this.clientId = opts.clientId;
  }
}

// ── Shared transition plumbing ────────────────────────────────────────

interface TransitionContext {
  machine: StateMachineKey;
  /** Resolved transition spec from the Phase 6.1 table. */
  spec: TransitionSpec;
  /** from-status (current row value). */
  from: string;
  /** Target status (caller-provided). */
  to: string;
}

async function loadStatus(
  client: PoolClient,
  table: string,
  id: string,
  clientId: string
): Promise<string> {
  const { rows } = await client.query<{ status: string }>(
    `SELECT status FROM ${table} WHERE id = $1 AND client_id = $2`,
    [id, clientId]
  );
  if (rows.length === 0) {
    throw new RowNotFound({ table, id, clientId });
  }
  return rows[0].status;
}

/**
 * Nested tables (workflow_templates, workflow_step_runs) do not carry
 * `client_id` directly. Callers supply the client_id explicitly; this
 * helper looks up status via the table's own id column and trusts the
 * caller's tenant claim (which the audit row + RLS will double-check).
 */
async function loadStatusWithoutClientFilter(
  client: PoolClient,
  table: string,
  id: string
): Promise<string> {
  const { rows } = await client.query<{ status: string }>(
    `SELECT status FROM ${table} WHERE id = $1`,
    [id]
  );
  if (rows.length === 0) {
    throw new RowNotFound({ table, id, clientId: "(nested — not on table)" });
  }
  return rows[0].status;
}

function pickFirstSpec(
  machine: StateMachineKey,
  from: string,
  to: string
): TransitionSpec {
  const r = describeTransition(machine, from, to);
  if (!r.ok) {
    throw new IllegalTransition({ machine, from, to, code: r.reason });
  }
  return r.spec;
}

async function requireAllPermissions(
  client: PoolClient,
  input: {
    actorUserId: string;
    clientId: string;
    permissions: readonly string[];
    targetType: string;
    targetId: string;
    auditMetadata: Record<string, unknown>;
  }
): Promise<void> {
  for (const permission of input.permissions) {
    await requirePermission(client, {
      userId: input.actorUserId,
      clientId: input.clientId,
      permission,
      targetType: input.targetType,
      targetId: input.targetId,
      metadata: input.auditMetadata,
    });
  }
}

async function insertExecutionCycle(
  client: PoolClient,
  input: {
    clientId: string;
    workOrderId: string;
    trigger:
      | "new"
      | "retry"
      | "reopen"
      | "unblock"
      | "watchdog"
      | "admin_repair"
      | "candidate_request_more";
    initiatedByUserId: string | null;
    reason: string | null;
    metadata: Record<string, unknown>;
  }
): Promise<string> {
  // Compute next cycle_number + pick prior_cycle_id from the newest
  // existing cycle for this WO. Unique on (work_order_id, cycle_number)
  // prevents races — a concurrent insert would fail the uniq constraint
  // and the caller's transaction rolls back.
  const priorRes = await client.query<{
    id: string;
    cycle_number: number;
  }>(
    `SELECT id, cycle_number
     FROM execution_cycles
     WHERE work_order_id = $1 AND client_id = $2
     ORDER BY cycle_number DESC
     LIMIT 1`,
    [input.workOrderId, input.clientId]
  );
  const nextCycleNumber =
    priorRes.rows.length > 0 ? priorRes.rows[0].cycle_number + 1 : 1;
  const priorCycleId = priorRes.rows[0]?.id ?? null;

  const { rows } = await client.query<{ id: string }>(
    `INSERT INTO execution_cycles
       (client_id, work_order_id, cycle_number, trigger,
        initiated_by_user_id, reason, prior_cycle_id, metadata)
     VALUES ($1, $2, $3, $4::execution_cycle_trigger, $5, $6, $7, $8)
     RETURNING id`,
    [
      input.clientId,
      input.workOrderId,
      nextCycleNumber,
      input.trigger,
      input.initiatedByUserId,
      input.reason,
      priorCycleId,
      JSON.stringify(input.metadata),
    ]
  );
  return rows[0].id;
}

// ── Public helpers ────────────────────────────────────────────────────

export interface TransitionWorkOrderInput {
  workOrderId: string;
  clientId: string;
  actorUserId: string;
  to: string;
  reason?: string;
}

export interface TransitionResult {
  from: string;
  to: string;
  event: string;
  cycleId?: string;
}

export async function transitionWorkOrder(
  client: PoolClient,
  input: TransitionWorkOrderInput
): Promise<TransitionResult> {
  const from = await loadStatus(
    client,
    "work_orders",
    input.workOrderId,
    input.clientId
  );
  const spec = pickFirstSpec("work_order", from, input.to);

  const auditMetadata: Record<string, unknown> = {
    machine: "work_order",
    from,
    to: input.to,
    reason: input.reason ?? null,
  };

  await requireAllPermissions(client, {
    actorUserId: input.actorUserId,
    clientId: input.clientId,
    permissions: spec.requires,
    targetType: "work_order",
    targetId: input.workOrderId,
    auditMetadata,
  });

  await client.query(
    `UPDATE work_orders
     SET status = $1, updated_at = now()
     WHERE id = $2 AND client_id = $3`,
    [input.to, input.workOrderId, input.clientId]
  );

  let cycleId: string | undefined;
  if (spec.requiresCycle) {
    // First-match semantics mean this is the reopen path
    // (work_order.reopened). The watchdog path has its own helper.
    cycleId = await insertExecutionCycle(client, {
      clientId: input.clientId,
      workOrderId: input.workOrderId,
      trigger: "reopen",
      initiatedByUserId: input.actorUserId,
      reason: input.reason ?? null,
      metadata: { from, to: input.to, event: spec.event },
    });
    auditMetadata.cycleId = cycleId;
  }

  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId,
    event: spec.event,
    targetType: "work_order",
    targetId: input.workOrderId,
    metadata: auditMetadata,
  });

  return { from, to: input.to, event: spec.event, cycleId };
}

export interface WatchdogExpireInput {
  workOrderId: string;
  clientId: string;
  /** agent_system actor id — used for audit + cycle lineage. */
  actorUserId: string;
  reason: string;
}

/**
 * Watchdog path — marks a processing WO blocked with the
 * `work_order.watchdog_expired` audit event + writes a cycle row
 * (trigger=watchdog) recording the timer breach. Callers are
 * responsible for firing this only against WOs they've decided are
 * stale; Loop 9+ orchestration adds the scheduled job that invokes it.
 */
export async function watchdogExpireWorkOrder(
  client: PoolClient,
  input: WatchdogExpireInput
): Promise<TransitionResult> {
  const from = await loadStatus(
    client,
    "work_orders",
    input.workOrderId,
    input.clientId
  );
  if (from !== "processing") {
    throw new IllegalTransition({
      machine: "work_order",
      from,
      to: "blocked",
      code: "illegal_transition",
    });
  }

  // Pick the watchdog-specific spec (not the first match).
  const spec = STATE_MACHINES.work_order.find(
    (t) =>
      t.from === "processing" &&
      t.to === "blocked" &&
      t.event === AUDIT_EVENTS.WORK_ORDER_WATCHDOG_EXPIRED
  );
  if (!spec) {
    // Defensive: state_machines table was tampered with between phases.
    throw new Error("watchdog transition spec missing from work_order table");
  }

  const auditMetadata: Record<string, unknown> = {
    machine: "work_order",
    from,
    to: "blocked",
    reason: input.reason,
    trigger: "watchdog",
  };

  await requireAllPermissions(client, {
    actorUserId: input.actorUserId,
    clientId: input.clientId,
    permissions: spec.requires,
    targetType: "work_order",
    targetId: input.workOrderId,
    auditMetadata,
  });

  await client.query(
    `UPDATE work_orders
     SET status = 'blocked', updated_at = now()
     WHERE id = $1 AND client_id = $2`,
    [input.workOrderId, input.clientId]
  );

  const cycleId = await insertExecutionCycle(client, {
    clientId: input.clientId,
    workOrderId: input.workOrderId,
    trigger: "watchdog",
    initiatedByUserId: input.actorUserId,
    reason: input.reason,
    metadata: { from, to: "blocked", event: spec.event },
  });
  auditMetadata.cycleId = cycleId;

  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId,
    event: spec.event,
    targetType: "work_order",
    targetId: input.workOrderId,
    metadata: auditMetadata,
  });

  return { from, to: "blocked", event: spec.event, cycleId };
}

export interface TransitionWorkflowInput {
  workflowId: string;
  clientId: string;
  actorUserId: string;
  to: string;
  reason?: string;
}

export async function transitionWorkflow(
  client: PoolClient,
  input: TransitionWorkflowInput
): Promise<TransitionResult> {
  const from = await loadStatus(
    client,
    "workflows",
    input.workflowId,
    input.clientId
  );
  const spec = pickFirstSpec("workflow", from, input.to);

  const auditMetadata: Record<string, unknown> = {
    machine: "workflow",
    from,
    to: input.to,
    reason: input.reason ?? null,
  };

  await requireAllPermissions(client, {
    actorUserId: input.actorUserId,
    clientId: input.clientId,
    permissions: spec.requires,
    targetType: "workflow",
    targetId: input.workflowId,
    auditMetadata,
  });

  await client.query(
    `UPDATE workflows
     SET status = $1, updated_at = now()
     WHERE id = $2 AND client_id = $3`,
    [input.to, input.workflowId, input.clientId]
  );

  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId,
    event: spec.event,
    targetType: "workflow",
    targetId: input.workflowId,
    metadata: auditMetadata,
  });

  return { from, to: input.to, event: spec.event };
}

export interface TransitionWorkflowExecutionInput {
  executionId: string;
  clientId: string;
  actorUserId: string;
  to: string;
  reason?: string;
}

export async function transitionWorkflowExecution(
  client: PoolClient,
  input: TransitionWorkflowExecutionInput
): Promise<TransitionResult> {
  const from = await loadStatus(
    client,
    "workflow_executions",
    input.executionId,
    input.clientId
  );
  const spec = pickFirstSpec("workflow_execution", from, input.to);

  const auditMetadata: Record<string, unknown> = {
    machine: "workflow_execution",
    from,
    to: input.to,
    reason: input.reason ?? null,
  };

  await requireAllPermissions(client, {
    actorUserId: input.actorUserId,
    clientId: input.clientId,
    permissions: spec.requires,
    targetType: "workflow_execution",
    targetId: input.executionId,
    auditMetadata,
  });

  await client.query(
    `UPDATE workflow_executions
     SET status = $1, updated_at = now()
     WHERE id = $2 AND client_id = $3`,
    [input.to, input.executionId, input.clientId]
  );

  // NOTE: `requiresCycle` on the failed → running spec is documentation
  // for a future Loop 9 orchestration helper; execution_cycles is
  // WO-scoped today so Phase 6.2 does not open a cycle row here.
  // See R-009 in IWO3_OVERNIGHT_DEV_RESOLUTION_LOG for rationale.

  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId,
    event: spec.event,
    targetType: "workflow_execution",
    targetId: input.executionId,
    metadata: auditMetadata,
  });

  return { from, to: input.to, event: spec.event };
}

export interface TransitionWorkflowStepRunInput {
  stepRunId: string;
  clientId: string;
  actorUserId: string;
  to: string;
  reason?: string;
}

/**
 * workflow_step_runs does not carry a direct `client_id` column (the
 * tenant is derived via workflow_executions → client_id; see
 * migration 0006 RLS policy). The helper accepts `clientId` from the
 * caller for audit + authz purposes. RLS on `workflow_step_runs`
 * enforces the real tenant boundary on the UPDATE via the nested
 * EXISTS policy.
 */
export async function transitionWorkflowStepRun(
  client: PoolClient,
  input: TransitionWorkflowStepRunInput
): Promise<TransitionResult> {
  const from = await loadStatusWithoutClientFilter(
    client,
    "workflow_step_runs",
    input.stepRunId
  );
  const spec = pickFirstSpec("workflow_step_run", from, input.to);

  const auditMetadata: Record<string, unknown> = {
    machine: "workflow_step_run",
    from,
    to: input.to,
    reason: input.reason ?? null,
  };

  await requireAllPermissions(client, {
    actorUserId: input.actorUserId,
    clientId: input.clientId,
    permissions: spec.requires,
    targetType: "workflow_step_run",
    targetId: input.stepRunId,
    auditMetadata,
  });

  // lint:bypass-rls-explain="workflow_step_runs has no direct client_id column; tenant isolation is enforced via the RLS EXISTS policy against workflow_executions (migration 0006) + the caller's requirePermission gate above. The UPDATE is PK-scoped (id is globally unique) and RLS refuses to update a row whose parent workflow_execution.client_id does not match current_setting('app.current_client_id')."
  await client.query(
    `UPDATE workflow_step_runs
     SET status = $1, updated_at = now()
     WHERE id = $2`,
    [input.to, input.stepRunId]
  );

  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId,
    event: spec.event,
    targetType: "workflow_step_run",
    targetId: input.stepRunId,
    metadata: auditMetadata,
  });

  return { from, to: input.to, event: spec.event };
}

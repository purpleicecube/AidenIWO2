import { describe, it, expect, afterAll, beforeEach, beforeAll } from "vitest";
import { Pool } from "pg";

import {
  transitionWorkOrder,
  transitionWorkflow,
  watchdogExpireWorkOrder,
  IllegalTransition,
  RowNotFound,
} from "../../packages/contracts/wo-wf/transitions";
import { PermissionDenied } from "../../packages/contracts/authz/require_permission";
import { AUDIT_EVENTS } from "../../packages/contracts/audit/events";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";
const FFAI = "00000000-0000-4000-8000-00000000c002";

const KLEAR_OWNER = "00000000-0000-4000-8000-000001000001";
const KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002";
const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";
const KLEAR_REVIEWER = "00000000-0000-4000-8000-000001000004";
const KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005";
const KLEAR_AGENT = "00000000-0000-4000-8000-000001000006";

// Dedicated Loop 6 test WOs — separate from the seeded WOs that
// Loop 3's `tenant-execution-cycle-isolation.test.ts` exercises in
// parallel. Using our own WOs keeps cycle_number accounting clean and
// avoids race conditions on the shared seed rows.
const KLEAR_TEST_WO = "00000000-0000-4000-8000-000060060001";
const FFAI_TEST_WO = "00000000-0000-4000-8000-000060060002";
const KLEAR_WORKFLOW = "00000000-0000-4000-8000-000070000001";

// Helpers that run on the iwo3 superuser connection (bypasses RLS) so
// each test starts from a known state without fighting the policy layer.
async function resetWoStatus(
  pool: Pool,
  woId: string,
  status: string
): Promise<void> {
  await pool.query(
    `UPDATE work_orders SET status = $1, updated_at = now() WHERE id = $2`,
    [status, woId]
  );
}

async function resetWorkflowStatus(
  pool: Pool,
  wfId: string,
  status: string
): Promise<void> {
  await pool.query(
    `UPDATE workflows SET status = $1, updated_at = now() WHERE id = $2`,
    [status, wfId]
  );
}

async function clearTransitionArtifacts(pool: Pool): Promise<void> {
  await pool.query(
    `DELETE FROM execution_cycles WHERE work_order_id = ANY($1)`,
    [[KLEAR_TEST_WO, FFAI_TEST_WO]]
  );
  await pool.query(
    `DELETE FROM action_audit_log
     WHERE target_id = ANY($1)
        OR (metadata->>'machine' = 'workflow' AND target_id = $2)`,
    [[KLEAR_TEST_WO, FFAI_TEST_WO], KLEAR_WORKFLOW]
  );
  await resetWoStatus(pool, KLEAR_TEST_WO, "pending");
  await resetWoStatus(pool, FFAI_TEST_WO, "pending");
  await resetWorkflowStatus(pool, KLEAR_WORKFLOW, "active");
}

async function ensureTestWorkOrders(pool: Pool): Promise<void> {
  // Loop 6-owned WOs — inserted once per test-file run; deleted in
  // afterAll. Using UPSERT so reruns are idempotent across vitest
  // watch restarts.
  for (const [id, clientId, userId] of [
    [KLEAR_TEST_WO, KLEAR, KLEAR_ADMIN],
    [FFAI_TEST_WO, FFAI, "00000000-0000-4000-8000-000002000002"],
  ] as const) {
    await pool.query(
      `INSERT INTO work_orders
         (id, client_id, title, type, priority, status, submitted_by_user_id, correlation_id)
       VALUES ($1, $2, 'Loop 6 transition-test WO', 'content_brief',
               'medium', 'pending', $3, 'loop-6-test')
       ON CONFLICT (id) DO UPDATE SET status = 'pending', updated_at = now()`,
      [id, clientId, userId]
    );
  }
}

async function dropTestWorkOrders(pool: Pool): Promise<void> {
  await pool.query(`DELETE FROM execution_cycles WHERE work_order_id = ANY($1)`, [
    [KLEAR_TEST_WO, FFAI_TEST_WO],
  ]);
  await pool.query(`DELETE FROM work_orders WHERE id = ANY($1)`, [
    [KLEAR_TEST_WO, FFAI_TEST_WO],
  ]);
}

describeIwo3("Loop 6 Phase 6.2 — transitionWorkOrder", () => {
  const pool = new Pool({ connectionString: url });

  beforeAll(async () => {
    await ensureTestWorkOrders(pool);
  });

  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    await clearTransitionArtifacts(pool);
  });

  it("operator moves pending → processing; status updates + audit row lands", async () => {
    const c = await pool.connect();
    let result;
    try {
      await c.query("BEGIN");
      result = await transitionWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_OPERATOR,
        to: "processing",
        reason: "start of work",
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(result.from).toBe("pending");
    expect(result.to).toBe("processing");
    expect(result.event).toBe(AUDIT_EVENTS.WORK_ORDER_TRANSITIONED);
    expect(result.cycleId).toBeUndefined();

    const { rows: status } = await pool.query(
      `SELECT status FROM work_orders WHERE id = $1`,
      [KLEAR_TEST_WO]
    );
    expect(status[0].status).toBe("processing");

    const { rows: audits } = await pool.query<{
      action: string;
      actor_user_id: string;
      metadata: { machine: string; from: string; to: string; reason: string };
    }>(
      `SELECT action, actor_user_id, metadata FROM action_audit_log
       WHERE target_id = $1 AND metadata->>'machine' = 'work_order'
       ORDER BY created_at DESC LIMIT 1`,
      [KLEAR_TEST_WO]
    );
    expect(audits[0].action).toBe(AUDIT_EVENTS.WORK_ORDER_TRANSITIONED);
    expect(audits[0].actor_user_id).toBe(KLEAR_OPERATOR);
    expect(audits[0].metadata.from).toBe("pending");
    expect(audits[0].metadata.to).toBe("processing");
    expect(audits[0].metadata.reason).toBe("start of work");
  });

  it("viewer is rejected with PermissionDenied; no status change; authz.denied row lands", async () => {
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await transitionWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_VIEWER,
        to: "processing",
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(PermissionDenied);

    const { rows: status } = await pool.query(
      `SELECT status FROM work_orders WHERE id = $1`,
      [KLEAR_TEST_WO]
    );
    expect(status[0].status).toBe("pending");

    const { rows: denied } = await pool.query(
      `SELECT id FROM action_audit_log
       WHERE action = 'authz.denied'
         AND target_id = $1
         AND metadata->>'machine' = 'work_order'`,
      [KLEAR_TEST_WO]
    );
    expect(denied.length).toBeGreaterThanOrEqual(1);
  });

  it("illegal transition (pending → completed) throws before any DB write", async () => {
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await transitionWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_OPERATOR,
        to: "completed",
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(IllegalTransition);
    if (caught instanceof IllegalTransition) {
      expect(caught.code).toBe("illegal_transition");
    }
    const { rows } = await pool.query(
      `SELECT status FROM work_orders WHERE id = $1`,
      [KLEAR_TEST_WO]
    );
    expect(rows[0].status).toBe("pending");
  });

  it("cross-tenant transition fails with RowNotFound (tenant-scoped lookup)", async () => {
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await transitionWorkOrder(c, {
        workOrderId: FFAI_TEST_WO, // FFAI WO
        clientId: KLEAR, // claimed Klear tenant
        actorUserId: KLEAR_OPERATOR,
        to: "processing",
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(RowNotFound);
  });

  it("reopen from completed → processing requires BOTH execution_cycle:reopen AND work_order:update + opens a cycle row", async () => {
    await resetWoStatus(pool, KLEAR_TEST_WO, "completed");

    const c = await pool.connect();
    let result;
    try {
      await c.query("BEGIN");
      result = await transitionWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_OWNER, // owner holds both perms
        to: "processing",
        reason: "client wants a redraft",
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(result.event).toBe(AUDIT_EVENTS.WORK_ORDER_REOPENED);
    expect(result.cycleId).toBeTypeOf("string");

    const { rows: cycles } = await pool.query<{
      trigger: string;
      cycle_number: number;
      prior_cycle_id: string | null;
    }>(
      `SELECT trigger, cycle_number, prior_cycle_id
       FROM execution_cycles WHERE id = $1`,
      [result.cycleId]
    );
    expect(cycles[0].trigger).toBe("reopen");
    expect(cycles[0].cycle_number).toBe(1);
    expect(cycles[0].prior_cycle_id).toBeNull();
  });

  it("reviewer attempting reopen is denied — lacks execution_cycle:reopen", async () => {
    // NB: operator has both execution_cycle:reopen AND work_order:update
    // in the §Q2 grant set, so operators CAN reopen. The deny demonstration
    // needs a role that lacks the first permission. Reviewer lacks both.
    await resetWoStatus(pool, KLEAR_TEST_WO, "completed");
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await transitionWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_REVIEWER,
        to: "processing",
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(PermissionDenied);
    if (caught instanceof PermissionDenied) {
      expect(caught.permission).toBe("execution_cycle:reopen");
    }
  });

  it("operator cancels a pending WO with work_order:cancel; emits work_order.cancelled", async () => {
    const c = await pool.connect();
    let result;
    try {
      await c.query("BEGIN");
      result = await transitionWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_OPERATOR,
        to: "cancelled",
        reason: "customer pulled the ask",
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(result.event).toBe(AUDIT_EVENTS.WORK_ORDER_CANCELLED);
  });

  it("block path emits work_order.blocked; unblock path emits work_order.unblocked", async () => {
    await resetWoStatus(pool, KLEAR_TEST_WO, "processing");

    const c1 = await pool.connect();
    let blockResult, unblockResult;
    try {
      await c1.query("BEGIN");
      blockResult = await transitionWorkOrder(c1, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_OPERATOR,
        to: "blocked",
        reason: "waiting on stakeholder input",
      });
      await c1.query("COMMIT");
    } finally {
      c1.release();
    }
    expect(blockResult.event).toBe(AUDIT_EVENTS.WORK_ORDER_BLOCKED);

    const c2 = await pool.connect();
    try {
      await c2.query("BEGIN");
      unblockResult = await transitionWorkOrder(c2, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_OPERATOR,
        to: "processing",
        reason: "stakeholder replied",
      });
      await c2.query("COMMIT");
    } finally {
      c2.release();
    }
    expect(unblockResult.event).toBe(AUDIT_EVENTS.WORK_ORDER_UNBLOCKED);
  });
});

describeIwo3("Loop 6 Phase 6.2 — watchdogExpireWorkOrder", () => {
  const pool = new Pool({ connectionString: url });

  beforeAll(async () => {
    await ensureTestWorkOrders(pool);
  });

  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    await clearTransitionArtifacts(pool);
  });

  it("marks a processing WO blocked with watchdog_expired event + cycle (trigger=watchdog)", async () => {
    await resetWoStatus(pool, KLEAR_TEST_WO, "processing");

    const c = await pool.connect();
    let result;
    try {
      await c.query("BEGIN");
      result = await watchdogExpireWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_AGENT,
        reason: "no heartbeat for 15 minutes",
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(result.event).toBe(AUDIT_EVENTS.WORK_ORDER_WATCHDOG_EXPIRED);
    expect(result.cycleId).toBeTypeOf("string");

    const { rows: cycles } = await pool.query<{
      trigger: string;
      reason: string;
    }>(`SELECT trigger, reason FROM execution_cycles WHERE id = $1`, [
      result.cycleId,
    ]);
    expect(cycles[0].trigger).toBe("watchdog");
    expect(cycles[0].reason).toBe("no heartbeat for 15 minutes");

    const { rows: audit } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE target_id = $1 AND action = $2
       ORDER BY created_at DESC LIMIT 1`,
      [KLEAR_TEST_WO, AUDIT_EVENTS.WORK_ORDER_WATCHDOG_EXPIRED]
    );
    expect(audit.length).toBe(1);
  });

  it("watchdog on a non-processing WO throws IllegalTransition", async () => {
    await resetWoStatus(pool, KLEAR_TEST_WO, "blocked");
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await watchdogExpireWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_AGENT,
        reason: "test",
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(IllegalTransition);
  });

  it("reviewer cannot invoke watchdog — lacks work_order:update", async () => {
    await resetWoStatus(pool, KLEAR_TEST_WO, "processing");
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await watchdogExpireWorkOrder(c, {
        workOrderId: KLEAR_TEST_WO,
        clientId: KLEAR,
        actorUserId: KLEAR_REVIEWER,
        reason: "test",
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(PermissionDenied);
  });
});

describeIwo3("Loop 6 Phase 6.2 — transitionWorkflow", () => {
  const pool = new Pool({ connectionString: url });

  beforeAll(async () => {
    await ensureTestWorkOrders(pool);
  });

  afterAll(async () => {
    await dropTestWorkOrders(pool);
    await pool.end();
  });

  beforeEach(async () => {
    await clearTransitionArtifacts(pool);
  });

  it("active → paused emits workflow.paused", async () => {
    const c = await pool.connect();
    let r;
    try {
      await c.query("BEGIN");
      r = await transitionWorkflow(c, {
        workflowId: KLEAR_WORKFLOW,
        clientId: KLEAR,
        actorUserId: KLEAR_ADMIN,
        to: "paused",
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(r.event).toBe(AUDIT_EVENTS.WORKFLOW_PAUSED);
  });

  it("archived is terminal — cannot transition out", async () => {
    await resetWorkflowStatus(pool, KLEAR_WORKFLOW, "archived");
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await transitionWorkflow(c, {
        workflowId: KLEAR_WORKFLOW,
        clientId: KLEAR,
        actorUserId: KLEAR_ADMIN,
        to: "active",
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(IllegalTransition);
  });
});

/**
 * Loop 9 Phase 9.4 (scope §3.4) — async polling integration.
 *
 * Scenarios:
 *   1. Submit with unknown response → dispatch returns `pending_poll`,
 *      handoff stays `submitted`, poll_count=1.
 *   2. Subsequent pollHandoffStatus with unknown → stays pending, poll_count++.
 *   3. pollHandoffStatus with success → handoff completed, WO can advance.
 *   4. pollHandoffStatus with failed → handoff failed + audit.
 *   5. Stale poll (forceStaleWatchdog) → handoff failed + watchdog_expired audit.
 *
 * Uses a minimal `FakeLivePollingAdapter` that lets tests script the
 * fetchResult sequence without an HTTP mock. Isolates registry/audit
 * from the real Gamma client.
 */

import {
  describe,
  it,
  expect,
  afterAll,
  beforeEach,
  afterEach,
} from "vitest";
import { Pool } from "pg";

import {
  __registerAdapterForTest,
  dispatchToAdapter,
  pollHandoffStatus,
} from "../../packages/contracts/adapter/registry";
import { gammaTestDouble } from "../../packages/adapters/gamma/adapter";
import type {
  AdapterContract,
  AdapterDescription,
  AdapterExecutionResult,
  AdapterPollContext,
  AdapterPollResult,
  AdapterSubmissionContext,
  AdapterSubmissionResult,
  AdapterValidationResult,
} from "../../packages/contracts/adapter/types";
import type { OutputPackage } from "../../db/schema/output_packages";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001";
const KLEAR_WO = "00000000-0000-4000-8000-000060000001";
const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";
const KLEAR_PPTX_TEMPLATE = "00000000-0000-4000-8000-000010000001";


class FakeLivePollingAdapter implements AdapterContract {
  readonly adapterKey = "gamma";
  private submissions = new Map<string, { ref: string; index: number }>();
  private readonly plan: AdapterExecutionResult["status"][];

  constructor(plan: AdapterExecutionResult["status"][]) {
    this.plan = plan.slice();
  }

  describe(): AdapterDescription {
    return {
      adapterKey: "gamma",
      contractVersion: "v0",
      supportedOutputKinds: ["gamma_pptx", "gamma_pdf"],
      supportedActions: ["generate", "render_from_template"],
      isLive: true,
      envFlagName: "GAMMA_LIVE_ENABLED",
    };
  }

  validatePackage(_pkg: OutputPackage): AdapterValidationResult {
    return { ok: true, errors: [] };
  }

  async submit(
    pkg: OutputPackage,
    _ctx: AdapterSubmissionContext
  ): Promise<AdapterSubmissionResult> {
    const ref = `fake-live-${pkg.id.slice(0, 8)}`;
    this.submissions.set(ref, { ref, index: 0 });
    return {
      externalReference: ref,
      externalDestination: "gamma://fake-live",
      handoffPayloadRef: `memory://fake-live/${ref}`,
    };
  }

  async pollStatus(
    externalReference: string,
    _ctx?: AdapterPollContext
  ): Promise<AdapterPollResult> {
    const sub = this.submissions.get(externalReference);
    const idx = sub?.index ?? 0;
    const kind = this.plan[Math.min(idx, this.plan.length - 1)];
    return {
      externalReference,
      status:
        kind === "success"
          ? "completed"
          : kind === "failed"
          ? "failed"
          : "running",
    };
  }

  async fetchResult(
    externalReference: string,
    _ctx?: AdapterPollContext
  ): Promise<AdapterExecutionResult> {
    const sub = this.submissions.get(externalReference);
    if (!sub) {
      return {
        externalReference,
        status: "failed",
        errorMessage: "unknown reference",
      };
    }
    const kind = this.plan[Math.min(sub.index, this.plan.length - 1)];
    sub.index += 1;
    if (kind === "success") {
      return {
        externalReference,
        status: "success",
        payloadRef: `https://export.gamma.app/${externalReference}.pptx`,
      };
    }
    if (kind === "failed") {
      return {
        externalReference,
        status: "failed",
        errorMessage: "adapter reported terminal failure",
      };
    }
    // Phase 9.4 introduces `unknown` as the pending-poll signal.
    return {
      externalReference,
      status: "unknown",
      metadata: { adapter: "fake-live-polling" },
    };
  }
}


async function ensureCredential(pool: Pool): Promise<void> {
  const { rows } = await pool.query<{ id: string }>(
    "SELECT id FROM adapter_catalog WHERE adapter_key = 'gamma'"
  );
  const catalogId = rows[0].id;
  await pool.query(
    "DELETE FROM adapter_credentials WHERE client_id = $1 AND adapter_catalog_id = $2",
    [KLEAR_CLIENT, catalogId]
  );
  await pool.query(
    `INSERT INTO adapter_credentials
       (client_id, adapter_catalog_id, credential_ref, status,
        first_invocation_confirmed_at, first_invocation_confirmed_by_user_id)
     VALUES ($1, $2, 'credential_ref:env:GAMMA_LIVE_TEST_KEY', 'active',
             now(), $3)`,
    [KLEAR_CLIENT, catalogId, KLEAR_OPERATOR]
  );
}


async function insertOutputPackage(pool: Pool): Promise<OutputPackage> {
  const { rows } = await pool.query<{ id: string }>(
    `INSERT INTO output_packages
       (client_id, work_order_id, output_kind, title, content_blocks,
        template_profile_id, created_by_user_id, provenance)
     VALUES ($1, $2, 'gamma_pptx', 'Phase 9.4 async test',
             $3::jsonb, $4, $5, '{"test":"async"}'::jsonb)
     RETURNING id`,
    [
      KLEAR_CLIENT,
      KLEAR_WO,
      JSON.stringify({ prompt: "render" }),
      KLEAR_PPTX_TEMPLATE,
      KLEAR_OPERATOR,
    ]
  );
  return {
    id: rows[0].id,
    schemaVersion: "v0",
    clientId: KLEAR_CLIENT,
    workOrderId: KLEAR_WO,
    workflowExecutionId: null,
    outputKind: "gamma_pptx",
    title: "Phase 9.4 async test",
    summary: null,
    status: "draft",
    priority: "medium",
    contentBlocks: { prompt: "render" },
    assetRefs: null,
    templateProfileId: KLEAR_PPTX_TEMPLATE,
    renderPolicy: null,
    destinationTargets: null,
    approvalPolicy: null,
    complianceNotes: null,
    provenance: { test: "async" },
    correlationId: null,
    createdByUserId: KLEAR_OPERATOR,
    dueAt: null,
    createdAt: new Date(),
    updatedAt: new Date(),
  } as OutputPackage;
}


async function readHandoffState(
  pool: Pool,
  handoffId: string
): Promise<{
  status: string;
  last_poll_status: string | null;
  poll_count: number;
  result_payload_ref: string | null;
}> {
  const { rows } = await pool.query<{
    status: string;
    last_poll_status: string | null;
    poll_count: number;
    result_payload_ref: string | null;
  }>(
    `SELECT status::text AS status, last_poll_status,
            poll_count, result_payload_ref
       FROM output_handoffs
      WHERE id = $1`,
    [handoffId]
  );
  return rows[0];
}


async function latestHandoffAudit(
  pool: Pool,
  handoffId: string
): Promise<{ action: string; metadata: Record<string, unknown> } | null> {
  const { rows } = await pool.query<{
    action: string;
    metadata: Record<string, unknown>;
  }>(
    `SELECT action, metadata
       FROM action_audit_log
      WHERE metadata->>'handoffId' = $1
         OR target_id = $1
      ORDER BY id DESC
      LIMIT 1`,
    [handoffId]
  );
  return rows[0] ?? null;
}


describeIwo3(
  "Loop 9 Phase 9.4 — async polling dispatcher + pollHandoffStatus",
  () => {
    const pool = new Pool({ connectionString: url });

    beforeEach(async () => {
      await ensureCredential(pool);
      process.env.GAMMA_LIVE_ENABLED = "true";
      process.env.GAMMA_LIVE_TEST_KEY = "test";
    });

    afterEach(() => {
      __registerAdapterForTest("gamma", gammaTestDouble);
      delete process.env.GAMMA_LIVE_ENABLED;
      delete process.env.GAMMA_LIVE_TEST_KEY;
    });

    afterAll(async () => {
      await pool.end();
    });

    it("dispatch returns pending_poll when adapter's fetchResult is unknown", async () => {
      __registerAdapterForTest(
        "gamma",
        new FakeLivePollingAdapter(["unknown", "unknown", "success"])
      );
      const pkg = await insertOutputPackage(pool);
      const client = await pool.connect();
      try {
        await client.query("BEGIN");
        const result = await dispatchToAdapter(client, {
          clientId: KLEAR_CLIENT,
          adapterKey: "gamma",
          actionKey: "render_from_template",
          outputPackage: pkg,
          actorUserId: KLEAR_OPERATOR,
          workOrderId: KLEAR_WO,
        });
        await client.query("COMMIT");
        expect(result.status).toBe("pending_poll");
        if (result.status !== "pending_poll") throw new Error("narrowing");
        const state = await readHandoffState(pool, result.handoffId);
        expect(state.status).toBe("submitted");
        expect(state.last_poll_status).toBe("pending");
        expect(state.poll_count).toBe(1);
      } finally {
        client.release();
      }
    });

    it("poll sequence: pending → pending → completed advances without watchdog", async () => {
      const adapter = new FakeLivePollingAdapter([
        "unknown",
        "unknown",
        "unknown",
        "success",
      ]);
      __registerAdapterForTest("gamma", adapter);
      const pkg = await insertOutputPackage(pool);

      // Initial dispatch — first poll is inline during submit.
      const client1 = await pool.connect();
      let handoffId = "";
      try {
        await client1.query("BEGIN");
        const r = await dispatchToAdapter(client1, {
          clientId: KLEAR_CLIENT,
          adapterKey: "gamma",
          actionKey: "render_from_template",
          outputPackage: pkg,
          actorUserId: KLEAR_OPERATOR,
          workOrderId: KLEAR_WO,
        });
        expect(r.status).toBe("pending_poll");
        if (r.status === "pending_poll") handoffId = r.handoffId;
        await client1.query("COMMIT");
      } finally {
        client1.release();
      }

      // Poll #2 — still pending.
      const client2 = await pool.connect();
      try {
        await client2.query("BEGIN");
        const p2 = await pollHandoffStatus(client2, {
          handoffId,
          clientId: KLEAR_CLIENT,
          actorUserId: KLEAR_OPERATOR,
        });
        expect(p2.status).toBe("pending");
        await client2.query("COMMIT");
      } finally {
        client2.release();
      }

      // Poll #3 — still pending.
      const client3 = await pool.connect();
      try {
        await client3.query("BEGIN");
        const p3 = await pollHandoffStatus(client3, {
          handoffId,
          clientId: KLEAR_CLIENT,
          actorUserId: KLEAR_OPERATOR,
        });
        expect(p3.status).toBe("pending");
        await client3.query("COMMIT");
      } finally {
        client3.release();
      }

      // Poll #4 — adapter returns success; handoff completes.
      const client4 = await pool.connect();
      try {
        await client4.query("BEGIN");
        const p4 = await pollHandoffStatus(client4, {
          handoffId,
          clientId: KLEAR_CLIENT,
          actorUserId: KLEAR_OPERATOR,
        });
        expect(p4.status).toBe("completed");
        await client4.query("COMMIT");
      } finally {
        client4.release();
      }

      const final = await readHandoffState(pool, handoffId);
      expect(final.status).toBe("completed");
      expect(final.last_poll_status).toBe("completed");
      expect(final.poll_count).toBeGreaterThanOrEqual(4);
      expect(final.result_payload_ref).toContain(".pptx");
    });

    it("stale poll (forceStaleWatchdog) fires watchdog_expired_stale_poll audit", async () => {
      __registerAdapterForTest(
        "gamma",
        new FakeLivePollingAdapter(["unknown"])
      );
      const pkg = await insertOutputPackage(pool);

      // Submit + first (inline) poll — still pending.
      const client1 = await pool.connect();
      let handoffId = "";
      try {
        await client1.query("BEGIN");
        const r = await dispatchToAdapter(client1, {
          clientId: KLEAR_CLIENT,
          adapterKey: "gamma",
          actionKey: "render_from_template",
          outputPackage: pkg,
          actorUserId: KLEAR_OPERATOR,
          workOrderId: KLEAR_WO,
        });
        if (r.status === "pending_poll") handoffId = r.handoffId;
        await client1.query("COMMIT");
      } finally {
        client1.release();
      }

      // Force-stale poll.
      const client2 = await pool.connect();
      try {
        await client2.query("BEGIN");
        const p = await pollHandoffStatus(client2, {
          handoffId,
          clientId: KLEAR_CLIENT,
          actorUserId: KLEAR_OPERATOR,
          forceStaleWatchdog: true,
        });
        expect(p.status).toBe("watchdog_expired");
        await client2.query("COMMIT");
      } finally {
        client2.release();
      }

      const state = await readHandoffState(pool, handoffId);
      expect(state.status).toBe("failed");
      expect(state.last_poll_status).toBe("watchdog_expired");

      const audit = await latestHandoffAudit(pool, handoffId);
      expect(audit?.action).toBe(
        "adapter_dispatch.watchdog_expired_stale_poll"
      );
      expect(audit?.metadata["forced"]).toBe(true);
    });

    it("terminal adapter failure surfaces as failed without watchdog", async () => {
      __registerAdapterForTest(
        "gamma",
        new FakeLivePollingAdapter(["unknown", "failed"])
      );
      const pkg = await insertOutputPackage(pool);

      const client1 = await pool.connect();
      let handoffId = "";
      try {
        await client1.query("BEGIN");
        const r = await dispatchToAdapter(client1, {
          clientId: KLEAR_CLIENT,
          adapterKey: "gamma",
          actionKey: "render_from_template",
          outputPackage: pkg,
          actorUserId: KLEAR_OPERATOR,
          workOrderId: KLEAR_WO,
        });
        if (r.status === "pending_poll") handoffId = r.handoffId;
        await client1.query("COMMIT");
      } finally {
        client1.release();
      }

      const client2 = await pool.connect();
      try {
        await client2.query("BEGIN");
        const p = await pollHandoffStatus(client2, {
          handoffId,
          clientId: KLEAR_CLIENT,
          actorUserId: KLEAR_OPERATOR,
        });
        expect(p.status).toBe("failed");
        await client2.query("COMMIT");
      } finally {
        client2.release();
      }

      const state = await readHandoffState(pool, handoffId);
      expect(state.status).toBe("failed");
      expect(state.last_poll_status).toBe("failed");

      const audit = await latestHandoffAudit(pool, handoffId);
      expect(audit?.action).toBe("adapter_dispatch.failed");
    });

    it("poll rejects non-submitted handoffs as not_pollable", async () => {
      const adapter = new FakeLivePollingAdapter(["success"]);
      __registerAdapterForTest("gamma", adapter);
      const pkg = await insertOutputPackage(pool);

      // Dispatch → completes immediately (plan[0]=success).
      const client1 = await pool.connect();
      let handoffId = "";
      try {
        await client1.query("BEGIN");
        const r = await dispatchToAdapter(client1, {
          clientId: KLEAR_CLIENT,
          adapterKey: "gamma",
          actionKey: "render_from_template",
          outputPackage: pkg,
          actorUserId: KLEAR_OPERATOR,
          workOrderId: KLEAR_WO,
        });
        expect(r.status).toBe("completed");
        if (r.status === "completed") handoffId = r.handoffId;
        await client1.query("COMMIT");
      } finally {
        client1.release();
      }

      // Trying to poll a completed handoff returns not_pollable.
      const client2 = await pool.connect();
      try {
        await client2.query("BEGIN");
        const p = await pollHandoffStatus(client2, {
          handoffId,
          clientId: KLEAR_CLIENT,
          actorUserId: KLEAR_OPERATOR,
        });
        expect(p.status).toBe("handoff_not_pollable");
        await client2.query("COMMIT");
      } finally {
        client2.release();
      }
    });
  }
);

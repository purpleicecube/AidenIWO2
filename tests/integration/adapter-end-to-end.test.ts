import { describe, it, expect, beforeEach, afterAll } from "vitest";
import { Pool } from "pg";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { dispatchToAdapter } from "../../packages/contracts/adapter/registry";
import { gammaTestDouble } from "../../packages/adapters/gamma/adapter";
import { AUDIT_EVENTS } from "../../packages/contracts/audit/events";
import { validateIntakePacket } from "../../packages/contracts/digiflow/intake";
import { routeIntake } from "../../packages/contracts/digiflow/routing";
import type { OutputPackage } from "../../db/schema/output_packages";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001";
const KLEAR_WO = "00000000-0000-4000-8000-000060000001";
const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";
const KLEAR_PPTX_TEMPLATE = "00000000-0000-4000-8000-000010000001";

// Helper: compose a minimal Gamma output package for the Klear WO.
// Returns a camelCased OutputPackage — pg returns snake_case rows, but the
// adapter contract (and the registry) read camelCase fields.
async function insertOutputPackage(
  pool: Pool,
  overrides: Partial<OutputPackage> = {}
): Promise<OutputPackage> {
  const { rows } = await pool.query<{
    id: string;
    client_id: string;
    work_order_id: string | null;
    output_kind: string;
    title: string;
    content_blocks: unknown;
    template_profile_id: string | null;
    created_by_user_id: string | null;
    schema_version: string;
    status: string;
    priority: string;
    correlation_id: string | null;
    created_at: string;
    updated_at: string;
  }>(
    `INSERT INTO output_packages
       (client_id, work_order_id, output_kind, title, content_blocks,
        template_profile_id, created_by_user_id, provenance)
     VALUES ($1, $2, $3::output_package_kind, $4, $5::jsonb, $6, $7, $8::jsonb)
     RETURNING id, client_id, work_order_id, output_kind, title,
               content_blocks, template_profile_id, created_by_user_id,
               schema_version, status, priority, correlation_id,
               created_at, updated_at`,
    [
      KLEAR_CLIENT,
      KLEAR_WO,
      overrides.outputKind ?? "gamma_pptx",
      overrides.title ?? "Klear RMIS one-pager",
      JSON.stringify(
        overrides.contentBlocks ?? {
          sections: [
            { title: "Intro", body: "Why RMIS matters." },
            { title: "Results", body: "Q1 RMIS numbers." },
          ],
        }
      ),
      overrides.templateProfileId ?? KLEAR_PPTX_TEMPLATE,
      KLEAR_OPERATOR,
      JSON.stringify({ test_marker: "adapter-end-to-end" }),
    ]
  );
  const r = rows[0];
  return {
    id: r.id,
    schemaVersion: r.schema_version,
    clientId: r.client_id,
    workOrderId: r.work_order_id,
    workflowExecutionId: null,
    outputKind: r.output_kind as OutputPackage["outputKind"],
    title: r.title,
    summary: null,
    status: r.status as OutputPackage["status"],
    priority: r.priority as OutputPackage["priority"],
    contentBlocks: r.content_blocks,
    assetRefs: null,
    templateProfileId: r.template_profile_id,
    renderPolicy: null,
    destinationTargets: null,
    approvalPolicy: null,
    complianceNotes: null,
    provenance: null,
    correlationId: r.correlation_id,
    createdByUserId: r.created_by_user_id,
    dueAt: null,
    createdAt: new Date(r.created_at),
    updatedAt: new Date(r.updated_at),
  } as OutputPackage;
}

describeIwo3("Loop 3 Phase 4 — adapter registry end-to-end", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    gammaTestDouble.__reset();
    // Clean Phase-4 artifacts. external_execution_results cascades from
    // output_handoffs; output_packages are marked via provenance.
    await pool.query(
      `DELETE FROM output_handoffs
       WHERE metadata->>'dispatched_by' = 'registry.dispatch'`
    );
    await pool.query(
      `DELETE FROM output_packages
       WHERE provenance->>'test_marker' = 'adapter-end-to-end'`
    );
    await pool.query(
      `DELETE FROM action_audit_log
       WHERE metadata->>'adapterKey' = 'gamma'
          OR metadata->>'adapterKey' = 'email_campaign'
          OR metadata->>'adapterKey' = 'crm'`
    );
  });

  it("happy path: gamma.render_from_template → handoff + result + audit chain", async () => {
    const pkg = await insertOutputPackage(pool);

    const client = await pool.connect();
    let dispatch;
    try {
      await client.query("BEGIN");
      dispatch = await dispatchToAdapter(client, {
        clientId: KLEAR_CLIENT,
        adapterKey: "gamma",
        actionKey: "render_from_template",
        outputPackage: pkg,
        actorUserId: KLEAR_OPERATOR,
        workOrderId: KLEAR_WO,
        correlationId: "e2e-happy-path-001",
      });
      await client.query("COMMIT");
    } finally {
      client.release();
    }

    expect(dispatch.status).toBe("completed");
    if (dispatch.status !== "completed") throw new Error("expected completed");

    // Handoff row with all 13 CODEX §5 provenance fields populated (or
    // nullable where appropriate).
    const { rows: handoffs } = await pool.query<{
      client_id: string;
      work_order_id: string;
      output_package_id: string;
      adapter_catalog_id: string;
      template_profile_id: string;
      external_destination: string;
      external_reference: string;
      status: string;
      result_payload_ref: string;
    }>(
      `SELECT client_id, work_order_id, output_package_id, adapter_catalog_id,
              template_profile_id, external_destination, external_reference,
              status, result_payload_ref
       FROM output_handoffs WHERE id = $1`,
      [dispatch.handoffId]
    );
    expect(handoffs).toHaveLength(1);
    const h = handoffs[0];
    expect(h.client_id).toBe(KLEAR_CLIENT);
    expect(h.work_order_id).toBe(KLEAR_WO);
    expect(h.output_package_id).toBe(pkg.id);
    expect(h.adapter_catalog_id).not.toBeNull();
    expect(h.template_profile_id).toBe(KLEAR_PPTX_TEMPLATE);
    expect(h.external_destination).toBe("gamma://test-double");
    expect(h.external_reference).toMatch(/^gamma-double-/);
    expect(h.status).toBe("completed");
    expect(h.result_payload_ref).toMatch(/^memory:\/\/gamma\//);

    // External execution results row
    const { rows: results } = await pool.query<{
      status: string;
      payload_ref: string;
    }>(
      `SELECT status, payload_ref FROM external_execution_results
       WHERE output_handoff_id = $1`,
      [dispatch.handoffId]
    );
    expect(results).toHaveLength(1);
    expect(results[0].status).toBe("success");

    // Audit chain: initiated → submitted → completed, all tenant-scoped
    const { rows: audits } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE client_id = $1
         AND metadata->>'outputPackageId' = $2
       ORDER BY id`,
      [KLEAR_CLIENT, pkg.id]
    );
    const events = audits.map((r) => r.action);
    expect(events).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_INITIATED);
    expect(events).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_SUBMITTED);
    expect(events).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_COMPLETED);
  });

  it("policy-disallowed path: crm.create_record rejected without a handoff", async () => {
    const pkg = await insertOutputPackage(pool, {
      outputKind: "crm_mutation",
      title: "CRM create-record attempt",
    });

    const client = await pool.connect();
    let dispatch;
    try {
      await client.query("BEGIN");
      dispatch = await dispatchToAdapter(client, {
        clientId: KLEAR_CLIENT,
        adapterKey: "crm",
        actionKey: "create_record",
        outputPackage: pkg,
        actorUserId: KLEAR_OPERATOR,
      });
      await client.query("COMMIT");
    } finally {
      client.release();
    }

    expect(dispatch.status).toBe("rejected_policy");

    // No handoff row for this package
    const { rows: handoffs } = await pool.query(
      `SELECT id FROM output_handoffs WHERE output_package_id = $1`,
      [pkg.id]
    );
    expect(handoffs).toHaveLength(0);

    // Audit: initiated + policy_rejected, but NOT submitted or completed
    const { rows: audits } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE client_id = $1
         AND metadata->>'outputPackageId' = $2
       ORDER BY id`,
      [KLEAR_CLIENT, pkg.id]
    );
    const events = audits.map((r) => r.action);
    expect(events).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_INITIATED);
    expect(events).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_POLICY_REJECTED);
    expect(events).not.toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_SUBMITTED);
    expect(events).not.toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_COMPLETED);
  });

  it("approval-required path without approvalRef: email.send stops before submit", async () => {
    const pkg = await insertOutputPackage(pool, {
      outputKind: "email_campaign",
      title: "Klear April campaign",
    });

    const client = await pool.connect();
    let dispatch;
    try {
      await client.query("BEGIN");
      dispatch = await dispatchToAdapter(client, {
        clientId: KLEAR_CLIENT,
        adapterKey: "email_campaign",
        actionKey: "send",
        outputPackage: pkg,
        actorUserId: KLEAR_OPERATOR,
      });
      await client.query("COMMIT");
    } finally {
      client.release();
    }

    expect(dispatch.status).toBe("approval_required");

    const { rows: handoffs } = await pool.query(
      `SELECT id FROM output_handoffs WHERE output_package_id = $1`,
      [pkg.id]
    );
    expect(handoffs).toHaveLength(0);

    const { rows: audits } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE client_id = $1
         AND metadata->>'outputPackageId' = $2
       ORDER BY id`,
      [KLEAR_CLIENT, pkg.id]
    );
    const events = audits.map((r) => r.action);
    expect(events).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_APPROVAL_REQUIRED);
    expect(events).not.toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_SUBMITTED);
  });

  it("invalid package: gamma rejects wrong output_kind at validate step", async () => {
    const pkg = await insertOutputPackage(pool, {
      outputKind: "drive_upload",
      title: "Drive upload routed to Gamma by mistake",
    });

    const client = await pool.connect();
    let dispatch;
    try {
      await client.query("BEGIN");
      dispatch = await dispatchToAdapter(client, {
        clientId: KLEAR_CLIENT,
        adapterKey: "gamma",
        actionKey: "generate",
        outputPackage: pkg,
      });
      await client.query("COMMIT");
    } finally {
      client.release();
    }

    expect(dispatch.status).toBe("package_invalid");
    if (dispatch.status === "package_invalid") {
      expect(dispatch.errors.join(" ")).toMatch(/not supported by gamma/);
    }

    const { rows: audits } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE client_id = $1
         AND metadata->>'outputPackageId' = $2
       ORDER BY id`,
      [KLEAR_CLIENT, pkg.id]
    );
    const events = audits.map((r) => r.action);
    expect(events).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_PACKAGE_INVALID);
    expect(events).not.toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_SUBMITTED);
  });

  it("full demonstrator: DigiFLOW intake → route → WO-sourced package → dispatch → handoff", async () => {
    // 1. Load a DigiFLOW fixture (single-output auto mode → WO route).
    const fixturePath = resolve(
      __dirname,
      "../fixtures/digiflow/input-04-auto-single-output.json"
    );
    const packet = JSON.parse(readFileSync(fixturePath, "utf-8"));

    // 2. Validate + route. (Intake packet is tenant = Klear.)
    const validation = validateIntakePacket(packet);
    expect(validation.valid).toBe(true);
    const decision = routeIntake(packet);
    expect(decision.kind).toBe("wo");

    // 3. For the demonstrator we reuse the seeded Klear WO rather than
    //    creating a new one (Loop 6 is the natural home for the full
    //    intake→WO persistence; Phase 3.4 proves the end-to-end contract).
    //    Compose a package that reflects the intake's first output kind.
    const firstOutput = packet.desired_outputs[0];
    const pkg = await insertOutputPackage(pool, {
      outputKind: firstOutput.output_kind,
      title: packet.title,
    });

    // 4. Dispatch via registry.
    const client = await pool.connect();
    let dispatch;
    try {
      await client.query("BEGIN");
      dispatch = await dispatchToAdapter(client, {
        clientId: KLEAR_CLIENT,
        adapterKey: "gamma",
        actionKey: "render_from_template",
        outputPackage: pkg,
        actorUserId: KLEAR_OPERATOR,
        workOrderId: KLEAR_WO,
        correlationId: packet.id,
      });
      await client.query("COMMIT");
    } finally {
      client.release();
    }

    // 5. Verify the full chain landed.
    expect(dispatch.status).toBe("completed");

    const { rows: handoffs } = await pool.query<{
      correlation_id: string;
      external_reference: string;
    }>(
      `SELECT correlation_id, external_reference
       FROM output_handoffs
       WHERE output_package_id = $1`,
      [pkg.id]
    );
    expect(handoffs).toHaveLength(1);
    expect(handoffs[0].correlation_id).toBe(packet.id);
    expect(handoffs[0].external_reference).toMatch(/^gamma-double-/);

    const { rows: events } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE client_id = $1
         AND metadata->>'outputPackageId' = $2
       ORDER BY id`,
      [KLEAR_CLIENT, pkg.id]
    );
    const names = events.map((e) => e.action);
    expect(names).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_INITIATED);
    expect(names).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_SUBMITTED);
    expect(names).toContain(AUDIT_EVENTS.ADAPTER_DISPATCH_COMPLETED);
  });
});

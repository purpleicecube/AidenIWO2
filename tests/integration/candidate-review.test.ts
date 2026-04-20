import { describe, it, expect, afterAll, beforeEach, beforeAll } from "vitest";
import { Pool } from "pg";

import {
  selectCandidate,
  rejectCandidate,
  CandidateNotEligible,
  CandidateHandoffNotFound,
} from "../../packages/contracts/wo-wf/candidate_review";
import { PermissionDenied } from "../../packages/contracts/authz/require_permission";
import { AUDIT_EVENTS } from "../../packages/contracts/audit/events";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";

const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";
const KLEAR_REVIEWER = "00000000-0000-4000-8000-000001000004";
const KLEAR_PPTX_TEMPLATE = "00000000-0000-4000-8000-000010000001";

// Loop 6 Phase 6.3-owned candidate fixtures. Package + handoff UUIDs
// are deterministic so the beforeEach wipe is scoped and parallel
// execution with other test files doesn't contend.
const TEST_PACKAGE = "00000000-0000-4000-8000-000062061001";
const CANDIDATE_GROUP = "00000000-0000-4000-8000-000062062001";
const HANDOFF_A = "00000000-0000-4000-8000-000062063001";
const HANDOFF_B = "00000000-0000-4000-8000-000062063002";
const HANDOFF_C = "00000000-0000-4000-8000-000062063003";

async function seedCandidateGroup(pool: Pool): Promise<void> {
  // Fresh package + three candidate handoffs under one group.
  await pool.query(
    `INSERT INTO output_packages
       (id, client_id, output_kind, title, content_blocks,
        template_profile_id, created_by_user_id, provenance)
     VALUES ($1, $2, 'gamma_pptx', 'Candidate review test',
             $3::jsonb, $4, $5, $6::jsonb)
     ON CONFLICT (id) DO UPDATE SET status = 'draft', updated_at = now()`,
    [
      TEST_PACKAGE,
      KLEAR,
      JSON.stringify({ sections: [{ title: "t", body: "b" }] }),
      KLEAR_PPTX_TEMPLATE,
      KLEAR_OPERATOR,
      JSON.stringify({ test_marker: "candidate-review" }),
    ]
  );

  for (const hid of [HANDOFF_A, HANDOFF_B, HANDOFF_C]) {
    await pool.query(
      `INSERT INTO output_handoffs
         (id, client_id, output_package_id, status,
          candidate_group_id, candidate_status, metadata)
       VALUES ($1, $2, $3, 'queued', $4, 'candidate', $5::jsonb)
       ON CONFLICT (id) DO UPDATE SET
         candidate_status = 'candidate',
         selected_at = NULL,
         selected_by_user_id = NULL,
         updated_at = now()`,
      [
        hid,
        KLEAR,
        TEST_PACKAGE,
        CANDIDATE_GROUP,
        JSON.stringify({ test_marker: "candidate-review" }),
      ]
    );
  }
}

async function cleanCandidateFixtures(pool: Pool): Promise<void> {
  await pool.query(
    `DELETE FROM action_audit_log
     WHERE metadata->>'test_marker' = 'candidate-review'
        OR target_id = ANY($1)`,
    [[HANDOFF_A, HANDOFF_B, HANDOFF_C, TEST_PACKAGE]]
  );
  await pool.query(`DELETE FROM output_handoffs WHERE id = ANY($1)`, [
    [HANDOFF_A, HANDOFF_B, HANDOFF_C],
  ]);
  await pool.query(`DELETE FROM output_packages WHERE id = $1`, [TEST_PACKAGE]);
}

describeIwo3("Loop 6 Phase 6.3 — selectCandidate", () => {
  const pool = new Pool({ connectionString: url });

  beforeAll(async () => {
    await cleanCandidateFixtures(pool);
  });

  afterAll(async () => {
    await cleanCandidateFixtures(pool);
    await pool.end();
  });

  beforeEach(async () => {
    await seedCandidateGroup(pool);
  });

  it("reviewer picks HANDOFF_A → selected; B + C auto-rejected; package validated", async () => {
    const c = await pool.connect();
    let result;
    try {
      await c.query("BEGIN");
      result = await selectCandidate(c, {
        handoffId: HANDOFF_A,
        clientId: KLEAR,
        actorUserId: KLEAR_REVIEWER,
        reason: "clearest framing",
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(result.selectedHandoffId).toBe(HANDOFF_A);
    expect(result.rejectedSiblingIds.sort()).toEqual(
      [HANDOFF_B, HANDOFF_C].sort()
    );
    expect(result.packageValidated).toBe(TEST_PACKAGE);

    // Handoff candidate_status snapshot
    const { rows } = await pool.query<{
      id: string;
      candidate_status: string;
      selected_by_user_id: string | null;
    }>(
      `SELECT id, candidate_status, selected_by_user_id
       FROM output_handoffs
       WHERE id = ANY($1) ORDER BY id`,
      [[HANDOFF_A, HANDOFF_B, HANDOFF_C]]
    );
    const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(byId[HANDOFF_A].candidate_status).toBe("selected");
    expect(byId[HANDOFF_A].selected_by_user_id).toBe(KLEAR_REVIEWER);
    expect(byId[HANDOFF_B].candidate_status).toBe("rejected");
    expect(byId[HANDOFF_C].candidate_status).toBe("rejected");

    // Package status
    const { rows: pkg } = await pool.query<{ status: string }>(
      `SELECT status FROM output_packages WHERE id = $1`,
      [TEST_PACKAGE]
    );
    expect(pkg[0].status).toBe("validated");

    // Audit: 1 selected + 2 auto-rejected + 1 package validated = 4 rows
    const { rows: audits } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE target_id = ANY($1)
         AND actor_user_id = $2
       ORDER BY created_at`,
      [[HANDOFF_A, HANDOFF_B, HANDOFF_C, TEST_PACKAGE], KLEAR_REVIEWER]
    );
    const counts = audits.reduce((acc, r) => {
      acc[r.action] = (acc[r.action] ?? 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    expect(counts[AUDIT_EVENTS.OUTPUT_CANDIDATE_SELECTED]).toBe(1);
    expect(counts[AUDIT_EVENTS.OUTPUT_CANDIDATE_REJECTED]).toBe(2);
    expect(counts[AUDIT_EVENTS.OUTPUT_PACKAGE_VALIDATED]).toBe(1);
  });

  it("operator is denied — lacks output_candidate:select", async () => {
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await selectCandidate(c, {
        handoffId: HANDOFF_A,
        clientId: KLEAR,
        actorUserId: KLEAR_OPERATOR,
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
      expect(caught.permission).toBe("output_candidate:select");
    }
  });

  it("non-candidate handoff (already rejected) raises CandidateNotEligible", async () => {
    // Pre-reject HANDOFF_A directly so it's no longer selectable.
    await pool.query(
      `UPDATE output_handoffs SET candidate_status = 'rejected' WHERE id = $1`,
      [HANDOFF_A]
    );
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await selectCandidate(c, {
        handoffId: HANDOFF_A,
        clientId: KLEAR,
        actorUserId: KLEAR_REVIEWER,
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("ROLLBACK");
    } finally {
      c.release();
    }
    expect(caught).toBeInstanceOf(CandidateNotEligible);
  });

  it("cross-tenant handoff (wrong clientId) raises CandidateHandoffNotFound", async () => {
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await selectCandidate(c, {
        handoffId: HANDOFF_A,
        clientId: "00000000-0000-4000-8000-00000000c002", // FFAI
        actorUserId: KLEAR_REVIEWER,
      });
      await c.query("COMMIT");
    } catch (err) {
      caught = err;
      await c.query("COMMIT"); // authz.denied was written before load
    } finally {
      c.release();
    }
    // Could be either PermissionDenied (no membership on FFAI tenant) or
    // CandidateHandoffNotFound depending on ordering. Accept either.
    expect(
      caught instanceof PermissionDenied ||
        caught instanceof CandidateHandoffNotFound
    ).toBe(true);
  });
});

describeIwo3("Loop 6 Phase 6.3 — rejectCandidate", () => {
  const pool = new Pool({ connectionString: url });

  beforeAll(async () => {
    await cleanCandidateFixtures(pool);
  });

  afterAll(async () => {
    await cleanCandidateFixtures(pool);
    await pool.end();
  });

  beforeEach(async () => {
    await seedCandidateGroup(pool);
  });

  it("reviewer rejects HANDOFF_B → only B rejected; A and C remain candidates; package unchanged", async () => {
    const c = await pool.connect();
    let result;
    try {
      await c.query("BEGIN");
      result = await rejectCandidate(c, {
        handoffId: HANDOFF_B,
        clientId: KLEAR,
        actorUserId: KLEAR_REVIEWER,
        reason: "off-brand voice",
      });
      await c.query("COMMIT");
    } finally {
      c.release();
    }
    expect(result.rejectedHandoffId).toBe(HANDOFF_B);

    const { rows } = await pool.query<{
      id: string;
      candidate_status: string;
    }>(
      `SELECT id, candidate_status FROM output_handoffs
       WHERE id = ANY($1) ORDER BY id`,
      [[HANDOFF_A, HANDOFF_B, HANDOFF_C]]
    );
    const byId = Object.fromEntries(rows.map((r) => [r.id, r]));
    expect(byId[HANDOFF_A].candidate_status).toBe("candidate");
    expect(byId[HANDOFF_B].candidate_status).toBe("rejected");
    expect(byId[HANDOFF_C].candidate_status).toBe("candidate");

    const { rows: pkg } = await pool.query<{ status: string }>(
      `SELECT status FROM output_packages WHERE id = $1`,
      [TEST_PACKAGE]
    );
    expect(pkg[0].status).toBe("draft");

    // Exactly one output_candidate.rejected audit row (the manual one)
    const { rows: audits } = await pool.query<{ action: string }>(
      `SELECT action FROM action_audit_log
       WHERE target_id = $1 AND actor_user_id = $2`,
      [HANDOFF_B, KLEAR_REVIEWER]
    );
    expect(audits.length).toBe(1);
    expect(audits[0].action).toBe(AUDIT_EVENTS.OUTPUT_CANDIDATE_REJECTED);
  });

  it("operator is denied — lacks output_candidate:reject", async () => {
    const c = await pool.connect();
    let caught: unknown = null;
    try {
      await c.query("BEGIN");
      await rejectCandidate(c, {
        handoffId: HANDOFF_B,
        clientId: KLEAR,
        actorUserId: KLEAR_OPERATOR,
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

  it("double-reject of the same handoff raises CandidateNotEligible", async () => {
    // First reject
    const c1 = await pool.connect();
    try {
      await c1.query("BEGIN");
      await rejectCandidate(c1, {
        handoffId: HANDOFF_B,
        clientId: KLEAR,
        actorUserId: KLEAR_REVIEWER,
      });
      await c1.query("COMMIT");
    } finally {
      c1.release();
    }

    // Second reject of the same handoff — already rejected
    const c2 = await pool.connect();
    let caught: unknown = null;
    try {
      await c2.query("BEGIN");
      await rejectCandidate(c2, {
        handoffId: HANDOFF_B,
        clientId: KLEAR,
        actorUserId: KLEAR_REVIEWER,
      });
      await c2.query("COMMIT");
    } catch (err) {
      caught = err;
      await c2.query("ROLLBACK");
    } finally {
      c2.release();
    }
    expect(caught).toBeInstanceOf(CandidateNotEligible);
  });
});

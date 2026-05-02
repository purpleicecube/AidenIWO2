import { describe, it, expect, afterAll, beforeEach } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const INTRUDER = "intruder@dev.local";

const KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001";
const FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002";
const KLEAR_WO = "00000000-0000-4000-8000-000060000001";
const FFAI_WO = "00000000-0000-4000-8000-000060000002";
const KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002";
const FFAI_ADMIN = "00000000-0000-4000-8000-000002000002";

const LIST_CYCLES_FOR_USER = `
  SELECT ec.id, ec.cycle_number, ec.trigger::text AS trigger, c.designation
  FROM execution_cycles ec
  JOIN clients c ON c.id = ec.client_id
  JOIN client_memberships m ON m.client_id = ec.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, ec.started_at
`;

describeIwo3("Loop 3 Phase 1 — tenant execution-cycle isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    // Clean Phase-1 test rows + any leftover cycles on the WO IDs this
    // test owns (Beta-2 phase 0.2 introduced the auto_dispatch worker
    // that may have created untagged rows on these WOs in earlier runs).
    await pool.query(
      `DELETE FROM execution_cycles
        WHERE metadata->>'test_marker' = 'wo-execution-cycle-isolation'
           OR work_order_id IN ($1::uuid, $2::uuid)`,
      [KLEAR_WO, FFAI_WO]
    );
  });

  it("rows visible only to members of the owning tenant", async () => {
    // Seed one cycle per tenant.
    await pool.query(
      `INSERT INTO execution_cycles (client_id, work_order_id, cycle_number, trigger, initiated_by_user_id, reason, metadata)
       VALUES ($1, $2, $3, 'new', $4, $5, $6)`,
      [
        KLEAR_CLIENT,
        KLEAR_WO,
        1,
        KLEAR_ADMIN,
        "Initial attempt",
        JSON.stringify({ test_marker: "wo-execution-cycle-isolation", tenant: "klear" }),
      ]
    );
    await pool.query(
      `INSERT INTO execution_cycles (client_id, work_order_id, cycle_number, trigger, initiated_by_user_id, reason, metadata)
       VALUES ($1, $2, $3, 'new', $4, $5, $6)`,
      [
        FFAI_CLIENT,
        FFAI_WO,
        1,
        FFAI_ADMIN,
        "Initial attempt",
        JSON.stringify({ test_marker: "wo-execution-cycle-isolation", tenant: "ffai" }),
      ]
    );

    const { rows: klearView } = await pool.query<{
      trigger: string;
      designation: string;
    }>(LIST_CYCLES_FOR_USER, [OPERATOR_KLEAR]);
    expect(klearView).toHaveLength(1);
    expect(klearView[0].designation).toBe("IWO | Klear.ai");

    const { rows: ffaiView } = await pool.query<{
      trigger: string;
      designation: string;
    }>(LIST_CYCLES_FOR_USER, [OPERATOR_FFAI]);
    expect(ffaiView).toHaveLength(1);
    expect(ffaiView[0].designation).toBe("IWO | FreedomForge.AI");

    const { rows: intruderView } = await pool.query(LIST_CYCLES_FOR_USER, [
      INTRUDER,
    ]);
    expect(intruderView).toHaveLength(0);
  });

  it("cycle_number is unique per work_order", async () => {
    await pool.query(
      `INSERT INTO execution_cycles (client_id, work_order_id, cycle_number, trigger, metadata)
       VALUES ($1, $2, $3, 'new', $4)`,
      [
        KLEAR_CLIENT,
        KLEAR_WO,
        1,
        JSON.stringify({ test_marker: "wo-execution-cycle-isolation", step: "first" }),
      ]
    );
    await expect(
      pool.query(
        `INSERT INTO execution_cycles (client_id, work_order_id, cycle_number, trigger, metadata)
         VALUES ($1, $2, $3, 'retry', $4)`,
        [
          KLEAR_CLIENT,
          KLEAR_WO,
          1,
          JSON.stringify({ test_marker: "wo-execution-cycle-isolation", step: "dupe" }),
        ]
      )
    ).rejects.toThrow();
  });

  it("prior_cycle_id lineage stays tenant-scoped by reference", async () => {
    const first = await pool.query<{ id: string }>(
      `INSERT INTO execution_cycles (client_id, work_order_id, cycle_number, trigger, metadata)
       VALUES ($1, $2, $3, 'new', $4)
       RETURNING id`,
      [
        KLEAR_CLIENT,
        KLEAR_WO,
        1,
        JSON.stringify({ test_marker: "wo-execution-cycle-isolation", step: "first" }),
      ]
    );
    const retry = await pool.query<{ id: string; prior_cycle_id: string }>(
      `INSERT INTO execution_cycles (client_id, work_order_id, cycle_number, trigger, prior_cycle_id, metadata)
       VALUES ($1, $2, $3, 'retry', $4, $5)
       RETURNING id, prior_cycle_id`,
      [
        KLEAR_CLIENT,
        KLEAR_WO,
        2,
        first.rows[0].id,
        JSON.stringify({ test_marker: "wo-execution-cycle-isolation", step: "retry" }),
      ]
    );
    expect(retry.rows[0].prior_cycle_id).toBe(first.rows[0].id);
  });
});

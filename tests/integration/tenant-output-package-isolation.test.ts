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
const KLEAR_USER = "00000000-0000-4000-8000-000001000003";
const FFAI_USER = "00000000-0000-4000-8000-000002000003";

const LIST_OUTPUT_PACKAGES_FOR_USER = `
  SELECT op.id, op.title, op.output_kind, c.designation
  FROM output_packages op
  JOIN clients c ON c.id = op.client_id
  JOIN client_memberships m ON m.client_id = op.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, op.created_at
`;

const READ_PKG_FOR_USER = `
  SELECT op.id
  FROM output_packages op
  JOIN client_memberships m ON m.client_id = op.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1 AND op.id = $2
`;

describeIwo3("Loop 3 Phase 2 — tenant output_package isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  beforeEach(async () => {
    await pool.query(
      `DELETE FROM output_packages WHERE provenance->>'test_marker' = 'tenant-output-package'`
    );
  });

  it("rows are isolated by client_id", async () => {
    const klearPkg = await pool.query<{ id: string }>(
      `INSERT INTO output_packages
         (client_id, work_order_id, output_kind, title, content_blocks,
          created_by_user_id, provenance)
       VALUES ($1, $2, 'gamma_pptx', 'Klear RMIS deck',
         $3::jsonb, $4, $5::jsonb)
       RETURNING id`,
      [
        KLEAR_CLIENT,
        KLEAR_WO,
        JSON.stringify({ slides: [] }),
        KLEAR_USER,
        JSON.stringify({ test_marker: "tenant-output-package", tenant: "klear" }),
      ]
    );
    const ffaiPkg = await pool.query<{ id: string }>(
      `INSERT INTO output_packages
         (client_id, work_order_id, output_kind, title, content_blocks,
          created_by_user_id, provenance)
       VALUES ($1, $2, 'gamma_pdf', 'FFAI bench report',
         $3::jsonb, $4, $5::jsonb)
       RETURNING id`,
      [
        FFAI_CLIENT,
        FFAI_WO,
        JSON.stringify({ slides: [] }),
        FFAI_USER,
        JSON.stringify({ test_marker: "tenant-output-package", tenant: "ffai" }),
      ]
    );

    const { rows: klearView } = await pool.query<{ designation: string }>(
      LIST_OUTPUT_PACKAGES_FOR_USER,
      [OPERATOR_KLEAR]
    );
    expect(klearView.map((r) => r.designation)).toEqual(["IWO | Klear.ai"]);

    const { rows: ffaiView } = await pool.query<{ designation: string }>(
      LIST_OUTPUT_PACKAGES_FOR_USER,
      [OPERATOR_FFAI]
    );
    expect(ffaiView.map((r) => r.designation)).toEqual([
      "IWO | FreedomForge.AI",
    ]);

    const { rows: intruderView } = await pool.query(
      LIST_OUTPUT_PACKAGES_FOR_USER,
      [INTRUDER]
    );
    expect(intruderView).toHaveLength(0);

    // Cross-tenant read-by-id returns zero rows.
    const { rows: klearTriesFfai } = await pool.query(READ_PKG_FOR_USER, [
      OPERATOR_KLEAR,
      ffaiPkg.rows[0].id,
    ]);
    expect(klearTriesFfai).toHaveLength(0);

    const { rows: ffaiTriesKlear } = await pool.query(READ_PKG_FOR_USER, [
      OPERATOR_FFAI,
      klearPkg.rows[0].id,
    ]);
    expect(ffaiTriesKlear).toHaveLength(0);
  });
});

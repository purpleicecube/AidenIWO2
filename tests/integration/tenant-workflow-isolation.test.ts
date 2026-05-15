import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const OPERATOR_KLEAR = "operator_klear@dev.local";
const OPERATOR_FFAI = "operator_ffai@dev.local";
const SUPER = "super@dev.local";
const INTRUDER = "intruder@dev.local";

const LIST_WORKFLOWS_FOR_USER = `
  SELECT wf.key, wf.display_name, c.designation
  FROM workflows wf
  JOIN clients c ON c.id = wf.client_id
  JOIN client_memberships m ON m.client_id = wf.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, wf.key
`;

// Workflow templates are tenant-scoped transitively through their workflow.
const LIST_TEMPLATES_FOR_USER = `
  SELECT wt.id, wt.version, wf.key AS workflow_key, c.designation
  FROM workflow_templates wt
  JOIN workflows wf ON wf.id = wt.workflow_id
  JOIN clients c ON c.id = wf.client_id
  JOIN client_memberships m ON m.client_id = wf.client_id AND m.status = 'active'
  JOIN users u ON u.id = m.user_id AND u.status = 'active'
  WHERE u.email = $1
  ORDER BY c.designation, wf.key, wt.version
`;

describeIwo3("Loop 3 Phase 1 — tenant workflow isolation", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  // Loop CAP-C / Φ.4 added 8 branded chain workflows per tenant
  // (cap_branded_*). Counts updated below to reflect the new floor.
  // Tenant isolation invariant unchanged — operators still see only
  // their own tenant's workflows.
  const KLEAR_WORKFLOW_KEYS = [
    "cap_branded_docx",
    "cap_branded_html",
    "cap_branded_html_21st",
    "cap_branded_html_figma",
    "cap_branded_html_stitch",
    "cap_branded_md",
    "cap_branded_pdf",
    "cap_branded_pptx",
    "weekly_marketing_brief",
  ];
  const FFAI_WORKFLOW_KEYS = [
    "bench_report_v1",
    "cap_branded_docx",
    "cap_branded_html",
    "cap_branded_html_21st",
    "cap_branded_html_figma",
    "cap_branded_html_stitch",
    "cap_branded_md",
    "cap_branded_pdf",
    "cap_branded_pptx",
  ];

  it("Klear Operator sees only Klear workflows (CAP-C: 1 legacy + 8 branded chains)", async () => {
    const { rows } = await pool.query<{ key: string }>(LIST_WORKFLOWS_FOR_USER, [
      OPERATOR_KLEAR,
    ]);
    expect(rows.map((r) => r.key).sort()).toEqual(KLEAR_WORKFLOW_KEYS);
  });

  it("FFAI Operator sees only FFAI workflows (CAP-C: 1 legacy + 8 branded chain mirrors)", async () => {
    const { rows } = await pool.query<{ key: string }>(LIST_WORKFLOWS_FOR_USER, [
      OPERATOR_FFAI,
    ]);
    expect(rows.map((r) => r.key).sort()).toEqual(FFAI_WORKFLOW_KEYS);
  });

  it("super (owner on both) sees both tenants' workflows (18 total post-CAP-C)", async () => {
    const { rows } = await pool.query<{ key: string }>(LIST_WORKFLOWS_FOR_USER, [
      SUPER,
    ]);
    expect(rows).toHaveLength(KLEAR_WORKFLOW_KEYS.length + FFAI_WORKFLOW_KEYS.length);
  });

  it("intruder sees zero workflows", async () => {
    const { rows } = await pool.query(LIST_WORKFLOWS_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });

  it("Klear Operator sees only Klear workflow templates — tenant scope transitive (CAP-C: 9 = 1 legacy + 8 branded chain v1)", async () => {
    const { rows } = await pool.query<{
      workflow_key: string;
      version: string;
      designation: string;
    }>(LIST_TEMPLATES_FOR_USER, [OPERATOR_KLEAR]);
    expect(rows).toHaveLength(KLEAR_WORKFLOW_KEYS.length);
    for (const r of rows) {
      expect(r.designation).toBe("IWO | Klear.ai");
      expect(r.version).toBe("1");
    }
  });

  it("intruder sees zero workflow templates", async () => {
    const { rows } = await pool.query(LIST_TEMPLATES_FOR_USER, [INTRUDER]);
    expect(rows).toHaveLength(0);
  });
});

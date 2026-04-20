import { describe, it, expect } from "vitest";

import {
  scanForRawAuditInsert,
  isPathAllowlistedForAuditInsert,
} from "../../tools/eslint-plugin-iwo3/rules/no-raw-audit-insert";

describe("Loop 4 Phase 4 — no-raw-audit-insert rule", () => {
  it("flags a raw INSERT in a handler file", () => {
    const src = `
      async function doSomething() {
        await pool.query(
          \`INSERT INTO action_audit_log (client_id, action) VALUES ($1, $2)\`
        );
      }
    `;
    const findings = scanForRawAuditInsert("server/handlers/foo.ts", src);
    expect(findings).toHaveLength(1);
    expect(findings[0].rule).toBe("no-raw-audit-insert");
    expect(findings[0].line).toBe(4);
  });

  it("is case-insensitive (catches `insert into action_audit_log`)", () => {
    const src = `const sql = \`insert into action_audit_log ...\`;`;
    const findings = scanForRawAuditInsert("packages/contracts/foo.ts", src);
    expect(findings).toHaveLength(1);
  });

  it("allows raw INSERT in the canonical writer", () => {
    const src = `
      export async function writeAuditRow(c, r) {
        await c.query(\`INSERT INTO action_audit_log (client_id) VALUES ($1)\`);
      }
    `;
    expect(
      scanForRawAuditInsert("packages/contracts/audit/writer.ts", src)
    ).toEqual([]);
  });

  it("allows raw INSERT inside migrations/", () => {
    const src = `INSERT INTO action_audit_log (id, client_id, created_at) VALUES (...);`;
    expect(
      scanForRawAuditInsert(
        "db/migrations/0002_partition_action_audit_log.sql",
        src
      )
    ).toEqual([]);
  });

  it("allows raw INSERT in audit-partition integration test", () => {
    const src = `
      await c.query(\`INSERT INTO action_audit_log (client_id, action) VALUES ($1, $2)\`);
    `;
    expect(
      scanForRawAuditInsert(
        "tests/integration/audit-partition.test.ts",
        src
      )
    ).toEqual([]);
  });

  it("does not fire on unrelated SQL (no action_audit_log table)", () => {
    const src = `
      await pool.query(\`INSERT INTO work_orders (client_id) VALUES ($1)\`);
      await pool.query(\`SELECT * FROM action_audit_log WHERE id = $1\`);
    `;
    expect(
      scanForRawAuditInsert("packages/contracts/audit/foo.ts", src)
    ).toEqual([]);
  });

  it("isPathAllowlistedForAuditInsert matches prefix-style entries", () => {
    expect(isPathAllowlistedForAuditInsert("db/migrations/0002_x.sql")).toBe(
      true
    );
    expect(
      isPathAllowlistedForAuditInsert("packages/contracts/audit/writer.ts")
    ).toBe(true);
    expect(
      isPathAllowlistedForAuditInsert("tests/integration/audit-partition.test.ts")
    ).toBe(true);
    expect(isPathAllowlistedForAuditInsert("server/routes/foo.ts")).toBe(false);
  });
});

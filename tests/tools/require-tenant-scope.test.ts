import { describe, it, expect } from "vitest";

import {
  scanForUnscopedTenantQuery,
  isPathAllowlistedForScopeRule,
  TENANT_SCOPED_TABLES,
} from "../../tools/eslint-plugin-iwo3/rules/require-tenant-scope-on-client-tables";

describe("Loop 4 Phase 4 — require-tenant-scope-on-client-tables rule", () => {
  it("passes when the query has an explicit client_id predicate", () => {
    const src = `
      const { rows } = await pool.query(
        \`SELECT id, title FROM work_orders WHERE client_id = $1\`,
        [clientId]
      );
    `;
    expect(
      scanForUnscopedTenantQuery("packages/contracts/some-handler.ts", src)
    ).toEqual([]);
  });

  it("flags a SELECT on a tenant table without scope", () => {
    const src = `
      const { rows } = await pool.query(\`SELECT id FROM work_orders\`);
    `;
    const findings = scanForUnscopedTenantQuery(
      "packages/contracts/runtime-handler.ts",
      src
    );
    expect(findings).toHaveLength(1);
    expect(findings[0].rule).toBe("require-tenant-scope-on-client-tables");
    expect(findings[0].message).toContain("work_orders");
  });

  it("flags an UPDATE on a tenant table without scope", () => {
    const src = `
      await pool.query(\`UPDATE output_packages SET status = 'submitted'\`);
    `;
    const findings = scanForUnscopedTenantQuery(
      "packages/contracts/runtime-handler.ts",
      src
    );
    expect(findings).toHaveLength(1);
  });

  it("flags a DELETE on a tenant table without scope", () => {
    const src = `
      await pool.query(\`DELETE FROM artifacts\`);
    `;
    const findings = scanForUnscopedTenantQuery(
      "packages/contracts/runtime-handler.ts",
      src
    );
    expect(findings).toHaveLength(1);
  });

  it("passes when the query is inside withTenantContext", () => {
    const src = `
      await withTenantContext(pool, { clientId }, async (c) => {
        const { rows } = await c.query(\`SELECT id FROM work_orders\`);
        return rows;
      });
    `;
    expect(
      scanForUnscopedTenantQuery(
        "packages/contracts/some-runtime.ts",
        src
      )
    ).toEqual([]);
  });

  it("passes when the line immediately above has a lint:bypass annotation", () => {
    const src = `
      // lint:bypass-rls-explain="admin cross-tenant list for ops dashboard"
      const { rows } = await adminPool.query(\`SELECT id FROM work_orders\`);
    `;
    expect(
      scanForUnscopedTenantQuery(
        "packages/contracts/admin-tools.ts",
        src
      )
    ).toEqual([]);
  });

  it("does not fire on tenant-agnostic tables (adapter_catalog)", () => {
    const src = `
      const { rows } = await pool.query(\`SELECT id FROM adapter_catalog\`);
    `;
    expect(
      scanForUnscopedTenantQuery("packages/contracts/foo.ts", src)
    ).toEqual([]);
  });

  it("returns multiple findings for multiple unscoped tenant-table queries", () => {
    const src = `
      await pool.query(\`SELECT id FROM work_orders\`);
      await pool.query(\`SELECT id FROM output_packages\`);
      await pool.query(\`UPDATE artifacts SET extracted_text = 'x'\`);
    `;
    const findings = scanForUnscopedTenantQuery(
      "packages/contracts/runtime-handler.ts",
      src
    );
    expect(findings.length).toBeGreaterThanOrEqual(3);
  });

  it("allowlists db/ paths (raw SQL migrations + schema + seeds)", () => {
    expect(isPathAllowlistedForScopeRule("db/migrations/0003_x.sql")).toBe(
      true
    );
    expect(isPathAllowlistedForScopeRule("db/schema/work_orders.ts")).toBe(
      true
    );
    expect(isPathAllowlistedForScopeRule("db/seeds/work_orders.json")).toBe(
      true
    );
  });

  it("allowlists tests/integration/ + tests/contract/ + tests/tools/", () => {
    expect(
      isPathAllowlistedForScopeRule("tests/integration/foo.test.ts")
    ).toBe(true);
    expect(isPathAllowlistedForScopeRule("tests/contract/bar.test.ts")).toBe(
      true
    );
    expect(isPathAllowlistedForScopeRule("tests/tools/baz.test.ts")).toBe(
      true
    );
  });

  it("allowlists seed-loader + manifest-populate", () => {
    expect(
      isPathAllowlistedForScopeRule("infra/local/seed-loader.ts")
    ).toBe(true);
    expect(
      isPathAllowlistedForScopeRule("infra/local/manifest-populate.ts")
    ).toBe(true);
  });

  it("does not allowlist generic packages/ or apps/ paths", () => {
    expect(
      isPathAllowlistedForScopeRule("packages/contracts/foo.ts")
    ).toBe(false);
    expect(
      isPathAllowlistedForScopeRule("apps/api-fastapi/handlers/foo.py")
    ).toBe(false);
  });

  it("covers all 29 tenant-scoped tables (+3 from MegaLoop Alpha α.5 channel layer)", () => {
    expect(TENANT_SCOPED_TABLES).toHaveLength(29);
    // Spot-check two from each category
    expect(TENANT_SCOPED_TABLES).toContain("work_orders"); // direct
    expect(TENANT_SCOPED_TABLES).toContain("workflow_templates"); // nested
    expect(TENANT_SCOPED_TABLES).toContain("clients"); // special
    expect(TENANT_SCOPED_TABLES).toContain("users"); // special
    expect(TENANT_SCOPED_TABLES).toContain("permission_grants"); // Loop 4
    expect(TENANT_SCOPED_TABLES).toContain("llm_configs"); // Loop 9 Phase 9.3
    // Tenant-agnostic tables MUST NOT be in the list
    expect(TENANT_SCOPED_TABLES).not.toContain("permissions");
    expect(TENANT_SCOPED_TABLES).not.toContain("role_permissions");
    expect(TENANT_SCOPED_TABLES).not.toContain("adapter_catalog");
    expect(TENANT_SCOPED_TABLES).not.toContain("adapter_actions");
    expect(TENANT_SCOPED_TABLES).not.toContain("migration_source_manifest");
  });
});

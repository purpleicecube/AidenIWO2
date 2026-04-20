/**
 * Loop 4 Phase 4 — lint rule: forbid unscoped SELECT / UPDATE / DELETE
 * against tenant-scoped tables.
 *
 * A query is considered SCOPED when any of the following holds in the
 * surrounding context (typically within 12 lines above or below the
 * offending SQL line):
 *
 *   1. The query text itself contains a `client_id` predicate
 *      (e.g. `WHERE client_id = $1` or `ON c.client_id = ...`).
 *   2. The query is embedded inside a `withTenantContext(` or
 *      `useTenantContext(` call — RLS will enforce isolation via the
 *      Loop 4 Phase 3 Postgres policies.
 *   3. The line carries an explicit escape annotation
 *      `// lint:bypass-rls-explain="<reason>"` immediately above the
 *      query — used for admin / audit / diagnostic tooling that
 *      legitimately crosses tenants. Required for PR review.
 *
 * The discretionary-implementation note on the standalone-vs-ESLint
 * tradeoff lives in no-raw-audit-insert.ts.
 */

import type { LintFinding } from "./no-raw-audit-insert";

const RULE_ID = "require-tenant-scope-on-client-tables";

export const TENANT_SCOPED_TABLES: readonly string[] = [
  "clients",
  "users",
  "client_memberships",
  "template_profiles",
  "prompt_profiles",
  "prompt_profile_versions",
  "prompt_rendered_snapshots",
  "repository_bindings",
  "data_source_bindings",
  "artifacts",
  "action_audit_log",
  "work_orders",
  "workflows",
  "workflow_templates",
  "workflow_template_steps",
  "workflow_executions",
  "workflow_step_runs",
  "execution_cycles",
  "client_adapter_configs",
  "adapter_action_policies",
  "adapter_credentials",
  "output_packages",
  "output_handoffs",
  "external_execution_results",
  "permission_grants",
];

// Paths where tenant-scope queries are exempt:
//  - Raw SQL migrations and schema DDL files.
//  - Seed loaders + manifest populator (run as iwo3 superuser,
//    administrative bootstrap).
//  - Test files under tests/integration + tests/contract; they
//    legitimately cross tenants to prove isolation.
//  - Lint plugin source and its tests (contains the tables list by
//    nature).
export const SCOPE_RULE_ALLOWLIST: readonly string[] = [
  "db/", // schemas, migrations, seeds
  "infra/local/seed-loader.ts",
  "infra/local/manifest-populate.ts",
  "infra/local/apply-migrations.ts",
  "tests/integration/",
  "tests/contract/",
  "tests/fixtures/",
  "tests/tools/",
  "tools/eslint-plugin-iwo3/",
  "apps/api-fastapi/alembic/",
];

export function isPathAllowlistedForScopeRule(relPath: string): boolean {
  for (const entry of SCOPE_RULE_ALLOWLIST) {
    if (entry.endsWith("/")) {
      if (relPath.startsWith(entry)) return true;
    } else if (relPath === entry) {
      return true;
    }
  }
  return false;
}

// Match a SQL DML statement that touches one of the tenant tables.
// Captures the command (SELECT/UPDATE/DELETE) + table name. Case-insens.
function buildDMLPattern(): RegExp {
  const tableAlt = TENANT_SCOPED_TABLES.map((t) => `\\b${t}\\b`).join("|");
  // Matches "SELECT … FROM <table>" / "UPDATE <table>" / "DELETE FROM <table>"
  const pattern = new RegExp(
    "(?:" +
      "select\\b[\\s\\S]{0,200}?\\bfrom\\s+[\"']?(" +
      tableAlt +
      ")[\"']?" +
      "|" +
      "update\\s+[\"']?(" +
      tableAlt +
      ")[\"']?" +
      "|" +
      "delete\\s+from\\s+[\"']?(" +
      tableAlt +
      ")[\"']?" +
      ")",
    "i"
  );
  return pattern;
}

const DML_PATTERN = buildDMLPattern();

const CLIENT_ID_PREDICATE = /\bclient_id\b/i;
const WITH_TENANT_CONTEXT = /\b(?:withTenantContext|useTenantContext)\s*\(/;
const BYPASS_ANNOTATION = /lint:\s*bypass-rls-explain\s*=/i;

// Per-match context window. Look at the current line + surrounding N lines
// for any of the scope-proving hooks.
const CONTEXT_WINDOW_LINES = 12;

function hasScopeProof(
  allLines: readonly string[],
  matchLineIdx: number
): boolean {
  const start = Math.max(0, matchLineIdx - CONTEXT_WINDOW_LINES);
  const end = Math.min(
    allLines.length - 1,
    matchLineIdx + CONTEXT_WINDOW_LINES
  );
  for (let i = start; i <= end; i++) {
    const line = allLines[i];
    if (CLIENT_ID_PREDICATE.test(line)) return true;
    if (WITH_TENANT_CONTEXT.test(line)) return true;
    if (BYPASS_ANNOTATION.test(line)) return true;
  }
  return false;
}

export function scanForUnscopedTenantQuery(
  relPath: string,
  source: string
): LintFinding[] {
  if (isPathAllowlistedForScopeRule(relPath)) return [];

  const findings: LintFinding[] = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(DML_PATTERN);
    if (!m) continue;
    const table = m[1] ?? m[2] ?? m[3] ?? "<unknown>";

    if (hasScopeProof(lines, i)) continue;

    findings.push({
      filePath: relPath,
      line: i + 1,
      column: (m.index ?? 0) + 1,
      rule: RULE_ID,
      message:
        `Query against tenant-scoped table '${table}' is missing a ` +
        "`client_id` predicate and is not inside `withTenantContext`. " +
        "Either add the predicate, wrap in `withTenantContext(...)`, " +
        "or annotate with `// lint:bypass-rls-explain=\"<reason>\"` if " +
        "this is an intentional cross-tenant admin query.",
      snippet: lines[i].trim().slice(0, 80),
    });
  }
  return findings;
}

export const REQUIRE_TENANT_SCOPE_RULE = {
  id: RULE_ID,
  scan: scanForUnscopedTenantQuery,
  isAllowlistedPath: isPathAllowlistedForScopeRule,
  tables: TENANT_SCOPED_TABLES,
} as const;

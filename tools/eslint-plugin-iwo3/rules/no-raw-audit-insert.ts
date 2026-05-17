/**
 * Loop 4 Phase 4 — lint rule: forbid raw `INSERT INTO action_audit_log`
 * outside the canonical writer at `packages/contracts/audit/writer.ts`.
 *
 * Discretionary note (see IWO3_OVERNIGHT_DEV_RESOLUTION_LOG R-005):
 * The repo has no pre-existing ESLint toolchain. To stay within the
 * Phase 4.4 scope (tooling + cleanup, not a toolchain overhaul), this
 * rule is implemented as a standalone text-scanning function instead
 * of an ESLint plugin rule. It is invoked by:
 *   - Vitest unit tests with source fixtures
 *   - The CI lint CLI at `tools/eslint-plugin-iwo3/lint.ts`
 * If a future loop adds ESLint, wrapping this function as an ESLint
 * rule is a trivial adapter — the core detection logic stays put.
 */

export interface LintFinding {
  filePath: string;
  line: number;
  column: number;
  rule: string;
  message: string;
  snippet: string;
}

const RULE_ID = "no-raw-audit-insert";

// Paths where raw `INSERT INTO action_audit_log` is legitimate:
//  - The canonical writer itself.
//  - Raw SQL migration files (DDL + one-time partitioning data copy).
//  - Test files that exercise the writer via direct INSERT for partition
//    routing verification (audit-partition.test.ts).
// Keep this list tight — adding a new allowlisted path is an
// architectural deviation that CODEX should review.
export const AUDIT_WRITE_ALLOWLIST: readonly string[] = [
  "packages/contracts/audit/writer.ts",
  "apps/api-fastapi/authz/audit_writer.py", // Loop 7 Phase 7.1 Python mirror
  "db/migrations/", // any file under migrations/
  "tests/integration/audit-partition.test.ts",
  "tools/eslint-plugin-iwo3/", // rule text itself contains the pattern
  "tests/tools/", // rule unit tests contain the pattern in fixtures
  "apps/api-fastapi/tests/", // pytest fixtures seed audit rows directly to assert dispatch + AEP routing behavior
];

const INSERT_PATTERN = /insert\s+into\s+[\"']?action_audit_log[\"']?/i;

export function isPathAllowlistedForAuditInsert(relPath: string): boolean {
  for (const entry of AUDIT_WRITE_ALLOWLIST) {
    if (entry.endsWith("/")) {
      if (relPath.startsWith(entry)) return true;
    } else if (relPath === entry) {
      return true;
    }
  }
  return false;
}

export function scanForRawAuditInsert(
  relPath: string,
  source: string
): LintFinding[] {
  if (isPathAllowlistedForAuditInsert(relPath)) return [];

  const findings: LintFinding[] = [];
  const lines = source.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = line.match(INSERT_PATTERN);
    if (m) {
      findings.push({
        filePath: relPath,
        line: i + 1,
        column: (m.index ?? 0) + 1,
        rule: RULE_ID,
        message:
          "Raw `INSERT INTO action_audit_log` is forbidden outside " +
          "`packages/contracts/audit/writer.ts`. Use `writeAuditRow()` " +
          "so every audit row carries the standard shape + metadata.",
        snippet: line.trim().slice(0, 80),
      });
    }
  }
  return findings;
}

export const NO_RAW_AUDIT_INSERT_RULE = {
  id: RULE_ID,
  scan: scanForRawAuditInsert,
  isAllowlistedPath: isPathAllowlistedForAuditInsert,
} as const;

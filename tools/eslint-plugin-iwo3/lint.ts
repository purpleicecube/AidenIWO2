/**
 * Loop 4 Phase 4 — standalone lint CLI for IWO3 rules.
 *
 * Walks the IWO3-owned source tree, runs both rules against each file,
 * reports findings to stdout, exits 1 on any finding. Invoked by the
 * CI baseline-check script.
 *
 * Scope (per IWO3_LOOP_4_APPROVAL_DECISIONS §Q6 `b`):
 *   - Lints IWO3-owned paths only: packages/, apps/, db/, infra/, tests/, tools/
 *   - Explicitly skips IWO2-parity paths: server/, client/, shared/, script/
 *     (a separate backport pass may bring IWO2 code into compliance later)
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, relative, join } from "node:path";

import {
  scanForRawAuditInsert,
  type LintFinding,
} from "./rules/no-raw-audit-insert";
import { scanForUnscopedTenantQuery } from "./rules/require-tenant-scope-on-client-tables";

const REPO_ROOT = resolve(__dirname, "..", "..");

const IWO3_OWNED_ROOTS: readonly string[] = [
  "packages",
  "apps",
  "db",
  "infra",
  "tests",
  "tools",
];

// File extensions we scan for SQL-in-source patterns.
const SCAN_EXTS = new Set([".ts", ".tsx", ".js", ".mjs", ".cjs", ".py", ".sql"]);

// Directories to skip mid-walk.
const SKIP_DIR_NAMES = new Set([
  "node_modules",
  "__pycache__",
  ".pytest_cache",
  "dist",
  "build",
  ".venv",
  "venv",
]);

function walk(dir: string, acc: string[]): void {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return;
  }
  for (const entry of entries) {
    if (SKIP_DIR_NAMES.has(entry)) continue;
    const full = join(dir, entry);
    let st;
    try {
      st = statSync(full);
    } catch {
      continue;
    }
    if (st.isDirectory()) {
      walk(full, acc);
    } else if (st.isFile()) {
      const ext = "." + entry.split(".").pop();
      if (SCAN_EXTS.has(ext)) acc.push(full);
    }
  }
}

export function collectIwo3SourceFiles(): string[] {
  const files: string[] = [];
  for (const root of IWO3_OWNED_ROOTS) {
    const dir = resolve(REPO_ROOT, root);
    walk(dir, files);
  }
  return files;
}

export function lintRepo(): LintFinding[] {
  const findings: LintFinding[] = [];
  for (const file of collectIwo3SourceFiles()) {
    const rel = relative(REPO_ROOT, file);
    let src: string;
    try {
      src = readFileSync(file, "utf-8");
    } catch {
      continue;
    }
    findings.push(...scanForRawAuditInsert(rel, src));
    findings.push(...scanForUnscopedTenantQuery(rel, src));
  }
  return findings;
}

function formatFinding(f: LintFinding): string {
  return `${f.filePath}:${f.line}:${f.column}  [${f.rule}] ${f.message}\n    → ${f.snippet}`;
}

if (
  typeof require !== "undefined" &&
  require.main === module &&
  process.argv[1] &&
  process.argv[1].includes("lint")
) {
  const findings = lintRepo();
  if (findings.length === 0) {
    console.log(`[iwo3-lint] CLEAN — 0 findings across IWO3-owned paths.`);
    process.exit(0);
  }
  for (const f of findings) {
    console.error(formatFinding(f));
  }
  console.error(`\n[iwo3-lint] ${findings.length} finding(s).`);
  process.exit(1);
}

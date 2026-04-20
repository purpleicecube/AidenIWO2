import { describe, it, expect } from "vitest";

import { lintRepo } from "../../tools/eslint-plugin-iwo3/lint";

describe("Loop 4 Phase 4 — IWO3-owned repo is lint-clean", () => {
  it("lintRepo() returns zero findings on IWO3-owned paths", () => {
    const findings = lintRepo();
    if (findings.length > 0) {
      const report = findings
        .map(
          (f) =>
            `${f.filePath}:${f.line}:${f.column}  [${f.rule}] ${f.message}\n    → ${f.snippet}`
        )
        .join("\n");
      throw new Error(
        `Expected IWO3-owned paths to be lint-clean. Got ${findings.length} finding(s):\n${report}`
      );
    }
    expect(findings).toHaveLength(0);
  });
});

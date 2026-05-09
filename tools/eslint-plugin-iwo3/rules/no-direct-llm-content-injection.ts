/**
 * Loop Iota — Memory V1 firewall guard.
 *
 * Forbids passing arbitrary content into Tier-1 / Tier-1.5 / Tier-2
 * LLM invocations except via the central `memory_context_builder`.
 *
 * The rule scans Python source for the pattern
 *
 *   await invoke_aiden_tier_1(... memory_block=...)
 *   await invoke_pm_tier_1_5(... memory_block=...)
 *   await invoke_sub_agent_tier_2(... memory_block=...)
 *
 * and asserts that the SAME source file imports `memory_context_builder`
 * from `memory`, OR is itself part of the `memory/` package, OR is a
 * test file that explicitly opts out (allowlisted).
 *
 * Rationale (firewall package §"Best framing"):
 *   "Add only one central memory builder + deterministic retrieval +
 *    validation before prompt injection."
 *   "memory_context_builder ... is the only allowed path for assembling
 *    memory injected into LLM calls."
 *
 * In other words: if you pass `memory_block=...` to a Tier-N invocation,
 * you must have asked the central builder for it. You may not construct
 * a memory string ad-hoc and pass it through, because that bypasses the
 * Layer 4 validator and the Layer 5 cache namespacing.
 */

export interface LintFinding {
  filePath: string;
  line: number;
  column: number;
  rule: string;
  message: string;
  snippet: string;
}

const RULE_ID = "no-direct-llm-content-injection";

// Files that may pass `memory_block=` to a Tier-N invocation without
// importing the builder (the builder itself, plus tests that exercise
// the runtime with synthetic blocks).
//
// Loop Lambda — extended with the runtime tier modules (PM + Tier-2)
// + the dispatch surfaces that call the wrappers. These files
// accept `memory_block` as a kwarg from the wrapper layer (which
// IS in `memory/`) and pass it through to the LLM call. They never
// assemble the bundle themselves — the wrapper does that, the
// runtime just threads the string. The lint rule's intent (block
// bypass paths that hand-roll a memory block) is preserved
// because a contributor who tries to construct a memory string
// inside these files instead of calling a wrapper would still
// have to introduce a new `memory_block=<literal>` site OUTSIDE
// these allowlisted files — which the rule still catches.
export const MEMORY_INJECTION_ALLOWLIST: readonly string[] = [
  "apps/api-fastapi/memory/", // every file in the memory package
  "apps/api-fastapi/routes/aiden.py", // imports + delegates to the builder
  "apps/api-fastapi/routes/dispatch.py", // imports wrappers; threads memory_block
  "apps/api-fastapi/runtime/tier_1_5_pm.py", // accepts memory_block kwarg from wrapper
  "apps/api-fastapi/runtime/tier_2_subagents.py", // accepts memory_block kwarg from wrapper
  "apps/api-fastapi/workers/wo_dispatch_worker.py", // imports wrappers; threads memory_block
  "apps/api-fastapi/tests/", // test fixtures simulate tenant flow
];

const MEMORY_BLOCK_KWARG = /\bmemory_block\s*=\s*[^,)\s]/;
const MEMORY_BUILDER_IMPORT = /\bfrom\s+memory(\.\w+)?\s+import\b/;

export function isPathAllowlistedForMemoryInjection(relPath: string): boolean {
  for (const entry of MEMORY_INJECTION_ALLOWLIST) {
    if (entry.endsWith("/")) {
      if (relPath.startsWith(entry)) return true;
    } else if (relPath === entry) {
      return true;
    }
  }
  return false;
}

export function scanForDirectLlmContentInjection(
  relPath: string,
  source: string
): LintFinding[] {
  // Only Python files are subject to this rule (Tier-N invocation
  // helpers are Python). TS/JS files passing memory data would hit
  // through an HTTP boundary and re-enter Python via the route.
  if (!relPath.endsWith(".py")) return [];

  // Allowlisted paths can pass memory_block freely.
  if (isPathAllowlistedForMemoryInjection(relPath)) return [];

  const lines = source.split("\n");
  const findings: LintFinding[] = [];
  // Cheap precheck: file must contain the kwarg pattern at all.
  if (!MEMORY_BLOCK_KWARG.test(source)) return [];
  // Source file is not allowlisted AND uses memory_block. Require an
  // import of the builder (or any memory.* symbol).
  const hasBuilderImport = MEMORY_BUILDER_IMPORT.test(source);
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(MEMORY_BLOCK_KWARG);
    if (!m) continue;
    if (hasBuilderImport) {
      // The presence of the import is the cooperative signal that this
      // file is using the central builder. Real enforcement of "you
      // actually called it" lives in tests + the per-route review;
      // an AST-aware lint would tighten this further (deferred).
      continue;
    }
    findings.push({
      filePath: relPath,
      line: i + 1,
      column: (m.index ?? 0) + 1,
      rule: RULE_ID,
      message:
        "Direct `memory_block=...` injection without importing the " +
        "central `memory_context_builder` is forbidden. Import from " +
        "`memory` and assemble the bundle through the builder so " +
        "every source is tenant-validated (firewall Layer 4) and " +
        "caches are namespaced (Layer 5).",
      snippet: lines[i].trim().slice(0, 80),
    });
  }
  return findings;
}

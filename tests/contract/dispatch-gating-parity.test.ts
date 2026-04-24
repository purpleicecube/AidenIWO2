/**
 * Loop 9 Phase 9.1 — TS / Python parity for the live-dispatch gate.
 *
 * Spawns the Python CLI with each fixture's input on stdin and diffs
 * the resulting JSON against the TS canonical's output. Same rhythm as
 * `prompt-resolver-parity.test.ts` and `digiflow-routing-parity.test.ts`.
 */

import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";

import { decideLiveGate } from "../../packages/contracts/adapter/dispatch_gating";
import type {
  LiveGateInput,
} from "../../packages/contracts/adapter/dispatch_gating";

const FIXTURES_DIR = resolve(__dirname, "../fixtures/dispatch-gating");
const API_FASTAPI_DIR = resolve(__dirname, "../../apps/api-fastapi");
const PYTHON_BIN = process.env.IWO3_PYTHON_BIN ?? "python3";

function runPythonGate(
  input: unknown
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const result = spawnSync(
    PYTHON_BIN,
    ["-m", "adapter.dispatch_gating_cli"],
    {
      cwd: API_FASTAPI_DIR,
      input: JSON.stringify(input),
      encoding: "utf-8",
    }
  );
  if (result.error) {
    return { ok: false, error: `spawn failed: ${result.error.message}` };
  }
  if (result.status === 0) {
    try {
      return { ok: true, value: JSON.parse(result.stdout) };
    } catch {
      return { ok: false, error: `could not parse stdout: ${result.stdout}` };
    }
  }
  return {
    ok: false,
    error: result.stderr.trim() || `exit ${result.status}`,
  };
}

function pythonAvailable(): boolean {
  const check = spawnSync(PYTHON_BIN, ["--version"], { encoding: "utf-8" });
  return check.status === 0;
}

const describeIfPython = pythonAvailable() ? describe : describe.skip;

describeIfPython("decideLiveGate — TS / Python parity", () => {
  const fixtureFiles = readdirSync(FIXTURES_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort();

  expect(fixtureFiles.length, "expected 8 parity fixtures").toBe(8);

  for (const file of fixtureFiles) {
    it(`parity: ${file}`, () => {
      const input = JSON.parse(
        readFileSync(join(FIXTURES_DIR, file), "utf-8")
      ) as LiveGateInput;

      const tsOut = decideLiveGate(input);
      const py = runPythonGate(input);

      if (!py.ok) {
        throw new Error(`Python gate failed for ${file}: ${py.error}`);
      }
      // Both impls return either { allow: true } or
      // { allow: false, reason, detail }. JSON.stringify gives a stable
      // deterministic byte form for comparison.
      expect(JSON.stringify(py.value)).toBe(JSON.stringify(tsOut));
    });
  }
});

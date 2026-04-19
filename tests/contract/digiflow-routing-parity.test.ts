import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";

import { routeIntake } from "../../packages/contracts/digiflow/routing";

const FIXTURES_DIR = resolve(__dirname, "../fixtures/digiflow");
const API_FASTAPI_DIR = resolve(__dirname, "../../apps/api-fastapi");
const PYTHON_BIN = process.env.IWO3_PYTHON_BIN ?? "python3";

function runPythonRouter(packet: unknown):
  | { ok: true; value: { kind: string; rationale: string } }
  | { ok: false; error: string } {
  const result = spawnSync(PYTHON_BIN, ["-m", "digiflow.intake_cli"], {
    cwd: API_FASTAPI_DIR,
    input: JSON.stringify(packet),
    encoding: "utf-8",
  });
  if (result.error) {
    return { ok: false, error: `spawn failed: ${result.error.message}` };
  }
  if (result.status === 0) {
    try {
      return { ok: true, value: JSON.parse(result.stdout) };
    } catch {
      return { ok: false, error: `bad stdout: ${result.stdout}` };
    }
  }
  return { ok: false, error: result.stderr.trim() || `exit ${result.status}` };
}

function pythonAvailable(): boolean {
  return spawnSync(PYTHON_BIN, ["--version"], { encoding: "utf-8" }).status === 0;
}

const describeIfPython = pythonAvailable() ? describe : describe.skip;

describeIfPython("DigiFLOW routing TS / Python parity", () => {
  const fixtureFiles = readdirSync(FIXTURES_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort();

  expect(fixtureFiles.length, "expected 6 routing fixtures").toBe(6);

  for (const file of fixtureFiles) {
    it(`parity: ${file}`, () => {
      const packet = JSON.parse(readFileSync(join(FIXTURES_DIR, file), "utf-8"));

      const tsDecision = routeIntake(packet);
      const pyResult = runPythonRouter(packet);

      if (!pyResult.ok) {
        throw new Error(
          `Python router failed for ${file}: ${pyResult.error}`
        );
      }

      expect(pyResult.value.kind, `kind mismatch on ${file}`).toBe(
        tsDecision.kind
      );
      expect(pyResult.value.rationale, `rationale mismatch on ${file}`).toBe(
        tsDecision.rationale
      );
    });
  }

  // Additional expected-kind assertions to make the intent explicit —
  // these double-check that the routing rules are behaving as designed,
  // independent of parity.
  const EXPECTED_KINDS: Record<string, string> = {
    "input-01-explicit-wo.json": "wo",
    "input-02-explicit-wf.json": "wf",
    "input-03-auto-recurrence-weekly.json": "wf",
    "input-04-auto-single-output.json": "wo",
    "input-05-auto-multiple-outputs.json": "wo",
    "input-06-ambiguous-no-outputs.json": "wo",
  };

  for (const file of fixtureFiles) {
    it(`expected kind holds: ${file} → ${EXPECTED_KINDS[file]}`, () => {
      const packet = JSON.parse(readFileSync(join(FIXTURES_DIR, file), "utf-8"));
      const decision = routeIntake(packet);
      expect(decision.kind).toBe(EXPECTED_KINDS[file]);
    });
  }
});

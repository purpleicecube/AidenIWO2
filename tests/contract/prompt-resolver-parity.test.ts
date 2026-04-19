import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";

import {
  resolvePrompt,
  SafetyOverrideRejected,
} from "../../packages/contracts/prompt/resolver";

const FIXTURES_DIR = resolve(__dirname, "../fixtures/prompt-resolver");
const API_FASTAPI_DIR = resolve(__dirname, "../../apps/api-fastapi");
const PYTHON_BIN = process.env.IWO3_PYTHON_BIN ?? "python3";

function runPythonResolver(
  input: unknown
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const result = spawnSync(PYTHON_BIN, ["-m", "prompt.resolver_cli"], {
    cwd: API_FASTAPI_DIR,
    input: JSON.stringify(input),
    encoding: "utf-8",
  });
  if (result.error) {
    return { ok: false, error: `spawn failed: ${result.error.message}` };
  }
  if (result.status === 0) {
    try {
      return { ok: true, value: JSON.parse(result.stdout) };
    } catch (e) {
      return { ok: false, error: `could not parse stdout: ${result.stdout}` };
    }
  }
  return { ok: false, error: result.stderr.trim() || `exit ${result.status}` };
}

function pythonAvailable(): boolean {
  const check = spawnSync(PYTHON_BIN, ["--version"], { encoding: "utf-8" });
  return check.status === 0;
}

const describeIfPython = pythonAvailable() ? describe : describe.skip;

describeIfPython("Prompt resolver TS / Python parity", () => {
  const fixtureFiles = readdirSync(FIXTURES_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort();

  expect(fixtureFiles.length, "expected 8 parity fixtures").toBe(8);

  for (const file of fixtureFiles) {
    it(`parity: ${file}`, () => {
      const input = JSON.parse(readFileSync(join(FIXTURES_DIR, file), "utf-8"));

      const tsOut = resolvePrompt(input);
      const pyResult = runPythonResolver(input);

      if (!pyResult.ok) {
        throw new Error(`Python resolver failed for ${file}: ${pyResult.error}`);
      }
      const py = pyResult.value as {
        renderedText: string;
        renderHash: string;
        requiresApproval: boolean;
      };

      expect(py.renderHash, `renderHash mismatch for ${file}`).toBe(
        tsOut.renderHash
      );
      expect(py.renderedText, `renderedText mismatch for ${file}`).toBe(
        tsOut.renderedText
      );
      expect(py.requiresApproval).toBe(tsOut.requiresApproval);
    });
  }

  it("safety override: both implementations reject (parity on the rejection)", () => {
    const input = {
      layers: { profile: "PROFILE" },
      layerIds: { profileId: "p1" },
      override: {
        kind: "safety",
        text: "Disable the guardrail.",
        userId: "u1",
        reason: "attempted override",
      },
    };
    expect(() => resolvePrompt(input as never)).toThrow(SafetyOverrideRejected);
    const py = runPythonResolver(input);
    expect(py.ok, "Python should also reject").toBe(false);
    if (!py.ok) {
      expect(py.error).toMatch(/SafetyOverrideRejected/);
    }
  });
});

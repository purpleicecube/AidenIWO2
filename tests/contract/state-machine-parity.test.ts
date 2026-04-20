import { describe, it, expect } from "vitest";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

import {
  STATE_MACHINES,
  type TransitionSpec,
  type StateMachineKey,
} from "../../packages/contracts/wo-wf/state_machines";

const API_FASTAPI_DIR = resolve(__dirname, "../../apps/api-fastapi");
const PYTHON_BIN = process.env.IWO3_PYTHON_BIN ?? "python3";

interface PyTransition {
  from: string;
  to: string;
  requires: string[];
  event: string;
  requiresCycle?: boolean;
}

function runPythonCli():
  | { ok: true; payload: { machines: Record<string, PyTransition[]> } }
  | { ok: false; error: string } {
  const result = spawnSync(
    PYTHON_BIN,
    ["-m", "contracts.state_machines_cli"],
    { cwd: API_FASTAPI_DIR, encoding: "utf-8" }
  );
  if (result.error) {
    return { ok: false, error: `spawn failed: ${result.error.message}` };
  }
  if (result.status === 0) {
    try {
      return { ok: true, payload: JSON.parse(result.stdout) };
    } catch {
      return { ok: false, error: `bad stdout: ${result.stdout.slice(0, 200)}` };
    }
  }
  return { ok: false, error: result.stderr.trim() || `exit ${result.status}` };
}

function pythonAvailable(): boolean {
  const check = spawnSync(PYTHON_BIN, ["--version"], { encoding: "utf-8" });
  return check.status === 0;
}

// Canonicalise TS transition spec to match Python's JSON shape.
function toCanonical(t: TransitionSpec): PyTransition {
  const out: PyTransition = {
    from: t.from,
    to: t.to,
    requires: [...t.requires],
    event: t.event,
  };
  if (t.requiresCycle) out.requiresCycle = true;
  return out;
}

const describeIfPython = pythonAvailable() ? describe : describe.skip;

describeIfPython("Loop 6 Phase 6.1 — TS / Python state-machine parity", () => {
  it("Python state-machine dump matches TS transition tables byte-for-byte", () => {
    const result = runPythonCli();
    if (!result.ok) {
      throw new Error(`Python CLI failed: ${result.error}`);
    }
    const py = result.payload.machines;

    const tsNames = Object.keys(STATE_MACHINES).sort();
    const pyNames = Object.keys(py).sort();
    expect(pyNames, "state-machine name set differs").toEqual(tsNames);

    for (const name of tsNames as StateMachineKey[]) {
      const tsCanon = STATE_MACHINES[name].map(toCanonical);
      expect(
        py[name],
        `transitions for '${name}' differ between TS canonical and Python mirror`
      ).toEqual(tsCanon);
    }
  });

  it("total transition count is stable (locked at Loop 6 Phase 6.1)", () => {
    const result = runPythonCli();
    if (!result.ok) throw new Error(result.error);
    const total = Object.values(result.payload.machines).reduce(
      (n, arr) => n + arr.length,
      0
    );
    // 21 WO + 4 WF + 6 WF-exec + 5 step-run = 36 total.
    expect(total).toBe(36);
  });
});

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";

import type { ContractSnapshot } from "./_snapshot-helpers";

const SNAPSHOT_PATH = resolve(
  __dirname,
  "../fixtures/contract-enums.snapshot.json"
);
const API_FASTAPI_DIR = resolve(__dirname, "../../apps/api-fastapi");
const PYTHON_BIN = process.env.IWO3_PYTHON_BIN ?? "python3";

function runPythonEnumDump():
  | { ok: true; payload: { enums: Record<string, string[]> } }
  | { ok: false; error: string } {
  const result = spawnSync(PYTHON_BIN, ["-m", "contracts.enum_dump"], {
    cwd: API_FASTAPI_DIR,
    encoding: "utf-8",
  });
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

const describeIfPython = pythonAvailable() ? describe : describe.skip;

describeIfPython("Loop 5 Phase 5.2 — TS / Python enum parity", () => {
  const snap = JSON.parse(
    readFileSync(SNAPSHOT_PATH, "utf-8")
  ) as ContractSnapshot;

  it("Python enum dump matches the TS snapshot byte-for-byte", () => {
    const result = runPythonEnumDump();
    if (!result.ok) {
      throw new Error(`Python enum CLI failed: ${result.error}`);
    }
    const py = result.payload.enums;
    const snapEnums = snap.dbEnums;

    const pyNames = new Set(Object.keys(py));
    const snapNames = new Set(Object.keys(snapEnums));

    expect(
      [...pyNames].sort(),
      "enum name set differs between Python mirror and TS snapshot"
    ).toEqual([...snapNames].sort());

    for (const name of snapNames) {
      expect(
        py[name],
        `values for enum '${name}' differ between Python mirror and TS snapshot`
      ).toEqual(snapEnums[name]);
    }
  });

  it("Python enum count matches expected Loop 1-4 baseline (39)", () => {
    const result = runPythonEnumDump();
    if (!result.ok) throw new Error(result.error);
    expect(Object.keys(result.payload.enums).length).toBe(39);
  });
});

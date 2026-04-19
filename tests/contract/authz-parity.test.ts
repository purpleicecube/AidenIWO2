import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";

import {
  checkPermissionDecide,
  type PermissionDecision,
} from "../../packages/contracts/authz/check_permission";

const FIXTURES_DIR = resolve(__dirname, "../fixtures/authz");
const API_FASTAPI_DIR = resolve(__dirname, "../../apps/api-fastapi");
const PYTHON_BIN = process.env.IWO3_PYTHON_BIN ?? "python3";

interface Fixture {
  note?: string;
  role: string | null;
  rolePermissions: string[];
  userGrants: { permissionKey: string; grantType: "allow" | "deny" }[];
  permission: string;
  knownPermissions?: string[];
  expected: PermissionDecision;
}

function runPythonCli(
  input: unknown
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const result = spawnSync(PYTHON_BIN, ["-m", "authz.check_permission_cli"], {
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
    } catch {
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

describeIfPython("Loop 4 Phase 2 — authz TS / Python parity", () => {
  const fixtureFiles = readdirSync(FIXTURES_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort();

  expect(fixtureFiles.length, "expected 8 parity fixtures").toBe(8);

  for (const file of fixtureFiles) {
    it(`parity: ${file}`, () => {
      const fx = JSON.parse(readFileSync(join(FIXTURES_DIR, file), "utf-8")) as Fixture;

      const tsDecision = checkPermissionDecide({
        role: fx.role,
        rolePermissions: fx.rolePermissions,
        userGrants: fx.userGrants,
        permission: fx.permission,
        knownPermissions: fx.knownPermissions
          ? new Set(fx.knownPermissions)
          : undefined,
      });

      const pyInput = {
        role: fx.role,
        rolePermissions: fx.rolePermissions,
        userGrants: fx.userGrants,
        permission: fx.permission,
        ...(fx.knownPermissions
          ? { knownPermissions: fx.knownPermissions }
          : {}),
      };
      const pyResult = runPythonCli(pyInput);
      if (!pyResult.ok) {
        throw new Error(`Python CLI failed for ${file}: ${pyResult.error}`);
      }
      const py = pyResult.value as PermissionDecision;

      // TS and Python must agree byte-for-byte.
      expect(py.allowed, `allowed mismatch for ${file}`).toBe(tsDecision.allowed);
      expect(py.reason, `reason mismatch for ${file}`).toBe(tsDecision.reason);
      expect(py.role, `role mismatch for ${file}`).toBe(tsDecision.role);

      // Both must match the fixture's declared expectation.
      expect(tsDecision).toEqual(fx.expected);
      expect(py).toEqual(fx.expected);
    });
  }
});

/**
 * Loop 9 Phase 9.2 — TS / Python parity for Gamma request-shape.
 *
 * Fixtures live in `tests/fixtures/gamma-request-shape/` and carry an
 * envelope `{ op, input, generationId? }`. The test runs each fixture
 * through both the TS canonical and the Python mirror (via the CLI in
 * `apps/api-fastapi/adapter/gamma_request_shape_cli.py`) and diffs the
 * resulting JSON byte-for-byte.
 *
 * Supported ops:
 *   build_request  — OutputPackage → Gamma API payload
 *   parse_submit   — Gamma 200 response → {generationId, gammaUrl}
 *   parse_poll     — Gamma poll response → AdapterPollResult-shaped
 */

import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { spawnSync } from "node:child_process";

import {
  buildGammaRequestBody,
  parseGammaPollResponse,
  parseGammaSubmitResponse,
} from "../../packages/adapters/gamma/request_shape";

const FIXTURES_DIR = resolve(__dirname, "../fixtures/gamma-request-shape");
const API_FASTAPI_DIR = resolve(__dirname, "../../apps/api-fastapi");
const PYTHON_BIN = process.env.IWO3_PYTHON_BIN ?? "python3";

interface Envelope {
  op: "build_request" | "parse_submit" | "parse_poll";
  input: Record<string, unknown>;
  generationId?: string;
}

function runPythonCli(envelope: Envelope):
  | { ok: true; value: unknown }
  | { ok: false; error: string } {
  const result = spawnSync(
    PYTHON_BIN,
    ["-m", "adapter.gamma_request_shape_cli"],
    {
      cwd: API_FASTAPI_DIR,
      input: JSON.stringify(envelope),
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

function runTsOp(envelope: Envelope): unknown {
  if (envelope.op === "build_request") {
    const inp = envelope.input as Record<string, unknown>;
    const shape = buildGammaRequestBody({
      outputKind: inp["outputKind"] as string,
      title: inp["title"] as string,
      summary: (inp["summary"] as string | null) ?? null,
      contentBlocks:
        (inp["contentBlocks"] as Record<string, unknown>) ?? {},
      templateExternalRef:
        (inp["templateExternalRef"] as string | null) ?? null,
    });
    return {
      endpoint: shape.endpoint,
      mode: shape.mode,
      exportAs: shape.exportAs,
      body: shape.body,
    };
  }
  if (envelope.op === "parse_submit") {
    const parsed = parseGammaSubmitResponse(envelope.input);
    return { generationId: parsed.generationId, gammaUrl: parsed.gammaUrl };
  }
  if (envelope.op === "parse_poll") {
    const parsed = parseGammaPollResponse(
      envelope.generationId as string,
      envelope.input
    );
    return {
      generationId: parsed.generationId,
      status: parsed.status,
      progress: parsed.progress ?? null,
      exportUrls: parsed.exportUrls,
      gammaUrl: parsed.gammaUrl,
      errorMessage: parsed.errorMessage,
    };
  }
  throw new Error(`unknown op: ${envelope.op}`);
}

function pythonAvailable(): boolean {
  const check = spawnSync(PYTHON_BIN, ["--version"], { encoding: "utf-8" });
  return check.status === 0;
}

const describeIfPython = pythonAvailable() ? describe : describe.skip;

describeIfPython("Gamma request-shape — TS / Python parity", () => {
  const fixtureFiles = readdirSync(FIXTURES_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort();

  expect(fixtureFiles.length, "expected 9 fixtures").toBe(9);

  for (const file of fixtureFiles) {
    it(`parity: ${file}`, () => {
      const envelope = JSON.parse(
        readFileSync(join(FIXTURES_DIR, file), "utf-8")
      ) as Envelope;

      const tsOut = runTsOp(envelope);
      const py = runPythonCli(envelope);
      if (!py.ok) {
        throw new Error(`python cli failed for ${file}: ${py.error}`);
      }
      expect(JSON.stringify(py.value)).toBe(JSON.stringify(tsOut));
    });
  }
});

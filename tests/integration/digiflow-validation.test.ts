import { describe, it, expect } from "vitest";

import {
  validateIntakePacket,
  type DigiFlowIntakePacket,
} from "../../packages/contracts/digiflow/intake";

function validPacket(): Record<string, unknown> {
  return {
    id: "intake-test-001",
    schema_version: "v0",
    source_system: "digiflow",
    client_designation: "IWO | Klear.ai",
    requester: { kind: "user", email: "operator_klear@dev.local" },
    title: "Test",
    objective: "Test objective",
    requested_execution_mode: "auto",
    desired_outputs: [{ output_kind: "gamma_pptx" }],
  };
}

describe("Loop 3 Phase 3 — DigiFLOW intake validation (TS Zod)", () => {
  it("accepts a minimal valid packet", () => {
    const result = validateIntakePacket(validPacket());
    expect(result.valid).toBe(true);
    if (result.valid) {
      const p: DigiFlowIntakePacket = result.packet;
      expect(p.intake_type).toBe("content"); // default applied
      expect(p.priority).toBe("medium"); // default applied
    }
  });

  it("rejects packet missing both client_id and client_designation", () => {
    const bad = validPacket();
    delete (bad as Record<string, unknown>).client_designation;
    const result = validateIntakePacket(bad);
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => /client_designation|client_id/.test(e))).toBe(true);
    }
  });

  it("accepts packet with client_id only", () => {
    const ok = validPacket();
    delete (ok as Record<string, unknown>).client_designation;
    (ok as Record<string, unknown>).client_id = "00000000-0000-4000-8000-00000000c001";
    const result = validateIntakePacket(ok);
    expect(result.valid).toBe(true);
  });

  it("rejects empty desired_outputs", () => {
    const bad = validPacket();
    (bad as Record<string, unknown>).desired_outputs = [];
    const result = validateIntakePacket(bad);
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => /desired_outputs/.test(e))).toBe(true);
    }
  });

  it("rejects raw credential in asset (must be credential_ref:* or null)", () => {
    const bad = validPacket();
    (bad as Record<string, unknown>).assets = [
      { id: "a1", credential_ref: "actual-leaked-secret" },
    ];
    const result = validateIntakePacket(bad);
    expect(result.valid).toBe(false);
    if (!result.valid) {
      expect(result.errors.some((e) => /credential_ref/.test(e))).toBe(true);
    }
  });

  it("accepts credential_ref placeholder", () => {
    const ok = validPacket();
    (ok as Record<string, unknown>).assets = [
      { id: "a1", credential_ref: "credential_ref:dev-local-source-01" },
    ];
    const result = validateIntakePacket(ok);
    expect(result.valid).toBe(true);
  });

  it("rejects custom recurrence without frequency", () => {
    const bad = validPacket();
    (bad as Record<string, unknown>).recurrence = { kind: "custom" };
    const result = validateIntakePacket(bad);
    expect(result.valid).toBe(false);
  });

  it("accepts custom recurrence with frequency", () => {
    const ok = validPacket();
    (ok as Record<string, unknown>).recurrence = {
      kind: "custom",
      frequency: "first Monday of every month",
    };
    const result = validateIntakePacket(ok);
    expect(result.valid).toBe(true);
  });

  it("rejects bad schema_version", () => {
    const bad = validPacket();
    (bad as Record<string, unknown>).schema_version = "v1-future";
    const result = validateIntakePacket(bad);
    expect(result.valid).toBe(false);
  });

  it("rejects bad source_system", () => {
    const bad = validPacket();
    (bad as Record<string, unknown>).source_system = "not_digiflow";
    const result = validateIntakePacket(bad);
    expect(result.valid).toBe(false);
  });
});

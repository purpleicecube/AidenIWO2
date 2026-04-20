import { describe, it, expect } from "vitest";

import * as contracts from "../../packages/contracts";

describe("Loop 5 Phase 5.1 — contract surface barrel", () => {
  it("top-level barrel exposes every area namespace", () => {
    for (const ns of [
      "audit",
      "authz",
      "adapter",
      "digiflow",
      "prompt",
      "db",
    ]) {
      expect(
        (contracts as Record<string, unknown>)[ns],
        `missing namespace '${ns}' on packages/contracts index.ts`
      ).toBeTypeOf("object");
    }
  });

  it("audit namespace exports AUDIT_EVENTS + writeAuditRow + loop arrays", () => {
    expect(contracts.audit.AUDIT_EVENTS).toBeTypeOf("object");
    expect(typeof contracts.audit.writeAuditRow).toBe("function");
    expect(Array.isArray(contracts.audit.LOOP_2_AUDIT_EVENTS)).toBe(true);
    expect(Array.isArray(contracts.audit.LOOP_3_PHASE_1_AUDIT_EVENTS)).toBe(
      true
    );
    expect(Array.isArray(contracts.audit.LOOP_4_PHASE_1_AUDIT_EVENTS)).toBe(
      true
    );
  });

  it("authz namespace exports checkPermission + requirePermission + PermissionDenied", () => {
    expect(typeof contracts.authz.checkPermission).toBe("function");
    expect(typeof contracts.authz.checkPermissionDecide).toBe("function");
    expect(typeof contracts.authz.requirePermission).toBe("function");
    expect(typeof contracts.authz.resolveUserPermissions).toBe("function");
    expect(typeof contracts.authz.PermissionDenied).toBe("function");
  });

  it("adapter namespace exports dispatchToAdapter + registry helpers + policy resolver", () => {
    expect(typeof contracts.adapter.dispatchToAdapter).toBe("function");
    expect(typeof contracts.adapter.getAdapter).toBe("function");
    expect(typeof contracts.adapter.resolveAdapterPolicy).toBe("function");
  });

  it("digiflow namespace exports validateIntakePacket + routeIntake + schemas", () => {
    expect(typeof contracts.digiflow.validateIntakePacket).toBe("function");
    expect(typeof contracts.digiflow.routeIntake).toBe("function");
    expect(contracts.digiflow.DigiFlowIntakePacketSchema).toBeTypeOf("object");
  });

  it("prompt namespace exports resolver + SafetyOverrideRejected", () => {
    // resolver.ts exports `resolvePrompt` + `SafetyOverrideRejected`
    expect(typeof contracts.prompt.resolvePrompt).toBe("function");
    expect(typeof contracts.prompt.SafetyOverrideRejected).toBe("function");
  });

  it("db namespace exports withTenantContext + useTenantContext", () => {
    expect(typeof contracts.db.withTenantContext).toBe("function");
    expect(typeof contracts.db.useTenantContext).toBe("function");
  });
});

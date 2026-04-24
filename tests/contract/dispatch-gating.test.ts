/**
 * Loop 9 Phase 9.1 — pure unit tests for `decideLiveGate`.
 *
 * No DB, no network. Each fixture exercises a single decision branch.
 * The byte-for-byte parity with the Python mirror is verified separately
 * by `dispatch-gating-parity.test.ts`.
 */

import { describe, it, expect } from "vitest";

import { decideLiveGate } from "../../packages/contracts/adapter/dispatch_gating";

describe("decideLiveGate — branch coverage", () => {
  it("test-double (isLive=false) always allows", () => {
    const decision = decideLiveGate({
      isLive: false,
      adapterKey: "gamma",
      envFlagName: null,
      envFlagValue: null,
      hasCredential: false,
      credentialFirstInvocationConfirmedAt: null,
    });
    expect(decision.allow).toBe(true);
  });

  it("live adapter without envFlagName is fail-closed (live_disabled)", () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: null,
      envFlagValue: null,
      hasCredential: true,
      credentialFirstInvocationConfirmedAt: "2026-04-24T12:00:00.000Z",
    });
    expect(decision).toEqual({
      allow: false,
      reason: "live_disabled",
      detail: "adapter gamma is live but describe() returned no envFlagName",
    });
  });

  it("env flag unset → live_disabled", () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: "GAMMA_LIVE_ENABLED",
      envFlagValue: undefined,
      hasCredential: true,
      credentialFirstInvocationConfirmedAt: "2026-04-24T12:00:00.000Z",
    });
    expect(decision).toEqual({
      allow: false,
      reason: "live_disabled",
      detail: 'GAMMA_LIVE_ENABLED is not "true" (got <unset>)',
    });
  });

  it("env flag false → live_disabled", () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: "GAMMA_LIVE_ENABLED",
      envFlagValue: "false",
      hasCredential: true,
      credentialFirstInvocationConfirmedAt: "2026-04-24T12:00:00.000Z",
    });
    expect(decision).toEqual({
      allow: false,
      reason: "live_disabled",
      detail: 'GAMMA_LIVE_ENABLED is not "true" (got "false")',
    });
  });

  it('env flag "1" (truthy but not literal "true") → live_disabled', () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: "GAMMA_LIVE_ENABLED",
      envFlagValue: "1",
      hasCredential: true,
      credentialFirstInvocationConfirmedAt: "2026-04-24T12:00:00.000Z",
    });
    expect(decision).toEqual({
      allow: false,
      reason: "live_disabled",
      detail: 'GAMMA_LIVE_ENABLED is not "true" (got "1")',
    });
  });

  it("missing credential → credential_missing", () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: "GAMMA_LIVE_ENABLED",
      envFlagValue: "true",
      hasCredential: false,
      credentialFirstInvocationConfirmedAt: null,
    });
    expect(decision).toEqual({
      allow: false,
      reason: "credential_missing",
      detail: "no adapter_credentials row for adapter=gamma",
    });
  });

  it("first_invocation_confirmed_at NULL → first_invocation_pending", () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: "GAMMA_LIVE_ENABLED",
      envFlagValue: "true",
      hasCredential: true,
      credentialFirstInvocationConfirmedAt: null,
    });
    expect(decision).toEqual({
      allow: false,
      reason: "first_invocation_pending",
      detail:
        "adapter gamma credential has no first_invocation_confirmed_at; admin must confirm via POST /adapter_credentials/{id}/confirm_first_invocation",
    });
  });

  it("all gates satisfied → allow", () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: "GAMMA_LIVE_ENABLED",
      envFlagValue: "true",
      hasCredential: true,
      credentialFirstInvocationConfirmedAt: "2026-04-24T12:00:00.000Z",
    });
    expect(decision.allow).toBe(true);
  });

  it("env flag null (vs undefined) treated identically", () => {
    const decision = decideLiveGate({
      isLive: true,
      adapterKey: "gamma",
      envFlagName: "GAMMA_LIVE_ENABLED",
      envFlagValue: null,
      hasCredential: true,
      credentialFirstInvocationConfirmedAt: "2026-04-24T12:00:00.000Z",
    });
    expect(decision).toEqual({
      allow: false,
      reason: "live_disabled",
      detail: 'GAMMA_LIVE_ENABLED is not "true" (got <unset>)',
    });
  });
});

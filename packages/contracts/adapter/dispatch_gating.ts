/**
 * Loop 9 Phase 9.1 — live-dispatch gating decision function.
 *
 * Pure function. No I/O, no timing, no audit writes — the caller owns all
 * of that. This function exists so the TS dispatcher and the Python
 * parity mirror (`apps/api-fastapi/adapter/dispatch_gating.py`) can stay
 * byte-for-byte aligned via a fixture-driven parity test.
 *
 * Implements the dual first-live-invocation gate from
 * `IWO3_LOOP_8_3_CODEX_DECISIONS §Q1`:
 *   1. Test-doubles (`isLive=false`) skip all checks.
 *   2. Live adapters require an explicit env flag name and value. No flag
 *      configured → fail-closed with `live_disabled` (the adapter is
 *      misconfigured).
 *   3. `process.env[envFlagName]` must be the literal string `"true"`.
 *      Any other value (including unset) short-circuits dispatch.
 *   4. A matching `adapter_credentials` row must exist for the tenant +
 *      adapter. Missing → `credential_missing`.
 *   5. The row's `first_invocation_confirmed_at` must be non-null.
 *      `NULL` → `first_invocation_pending` (admin must run
 *      `POST /adapter_credentials/{id}/confirm_first_invocation`).
 *
 * Candidate-review is NOT used here. Candidate-review governs artifact
 * choice; this gate governs outbound-service authorization. Mixing the
 * two would conflate content approval with network-egress approval
 * (Darrel, Q1 lockdown).
 */

export type LiveGateReason =
  | "live_disabled"
  | "credential_missing"
  | "first_invocation_pending";

export type LiveGateInput = {
  /** `false` → test-double / fake / non-network adapter. Always allow. */
  isLive: boolean;
  /** Adapter key from adapter_catalog (e.g. "gamma"). For audit context. */
  adapterKey: string;
  /**
   * Environment variable name that the adapter's `describe()` returned,
   * e.g. "GAMMA_LIVE_ENABLED". `null` when the adapter does not declare
   * one — fail-closed if `isLive=true` and this is null.
   */
  envFlagName: string | null;
  /**
   * `process.env[envFlagName]` read at dispatch time. Passed through so
   * the decision stays a pure function. `undefined` means the env var is
   * unset; any string other than the literal `"true"` is treated as false.
   */
  envFlagValue: string | null | undefined;
  /** Whether the tenant has an `adapter_credentials` row for this adapter. */
  hasCredential: boolean;
  /**
   * ISO-8601 timestamp or `null`. `null` blocks live dispatch regardless
   * of the env flag — belt and suspenders.
   */
  credentialFirstInvocationConfirmedAt: string | null;
};

export type LiveGateDecision =
  | { allow: true }
  | {
      allow: false;
      reason: LiveGateReason;
      detail: string;
    };

export function decideLiveGate(input: LiveGateInput): LiveGateDecision {
  if (!input.isLive) {
    return { allow: true };
  }

  if (!input.envFlagName) {
    return {
      allow: false,
      reason: "live_disabled",
      detail: `adapter ${input.adapterKey} is live but describe() returned no envFlagName`,
    };
  }

  if (input.envFlagValue !== "true") {
    // Parity: treat undefined and null identically — JSON wire can't
    // distinguish, and the Python mirror normalises both to None.
    const shown =
      input.envFlagValue === undefined || input.envFlagValue === null
        ? "<unset>"
        : JSON.stringify(input.envFlagValue);
    return {
      allow: false,
      reason: "live_disabled",
      detail: `${input.envFlagName} is not "true" (got ${shown})`,
    };
  }

  if (!input.hasCredential) {
    return {
      allow: false,
      reason: "credential_missing",
      detail: `no adapter_credentials row for adapter=${input.adapterKey}`,
    };
  }

  if (!input.credentialFirstInvocationConfirmedAt) {
    return {
      allow: false,
      reason: "first_invocation_pending",
      detail: `adapter ${input.adapterKey} credential has no first_invocation_confirmed_at; admin must confirm via POST /adapter_credentials/{id}/confirm_first_invocation`,
    };
  }

  return { allow: true };
}

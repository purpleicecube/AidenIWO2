/**
 * Loop 3 Phase 4 — AdapterContract interface.
 *
 * Every IWO3 adapter (Gamma, Drive, email, Figma, Stitch, Claude Design,
 * CRM, future) implements this five-method contract. ADR-012 locked the
 * shape; this file makes it executable.
 *
 * The shape is deliberately NOT Gamma-specific (non-Gamma-shaped guardrail
 * per IWO3_LOOP_3_APPROVAL_DECISIONS §ADR-012). Loop 3 Phase 4 ships a
 * Gamma test-double implementation; Loop 10 swaps in real API calls for
 * each adapter.
 */

import type { OutputPackage } from "../../../db/schema/output_packages";

export interface AdapterDescription {
  adapterKey: string;
  contractVersion: string;
  supportedOutputKinds: readonly string[];
  supportedActions: readonly string[];
  /**
   * Loop 9 Phase 9.1 — dual first-live-invocation gate.
   *
   *   isLive=false     → test-double / fake / local-only adapter.
   *                      `dispatch_gating.decideLiveGate` allows
   *                      unconditionally.
   *   isLive=true      → real outbound service (Gamma live, Drive, CRM
   *                      etc.). `dispatch_gating.decideLiveGate`
   *                      enforces envFlag + credential + first-invocation
   *                      confirmed. An adapter MUST also declare an
   *                      `envFlagName` when `isLive=true` or the gate
   *                      fail-closes.
   */
  isLive: boolean;
  envFlagName?: string;
}

export interface AdapterValidationResult {
  ok: boolean;
  errors: readonly string[];
}

export interface AdapterSubmissionContext {
  /** Informational — the adapter MAY use for logging but MUST NOT require. */
  correlationId?: string;
  /**
   * External template id from the resolved template_profile. Phase 9.2:
   * the dispatcher joins template_profiles.external_ref and passes it
   * here so adapters don't re-query the DB.
   */
  templateExternalRef?: string | null;
  /**
   * Loop 9 Phase 9.2 — `credential_ref:env:*` pointer the dispatcher
   * resolved from `adapter_credentials.credential_ref`. The adapter
   * parses this and reads the actual secret from the env at I/O time.
   * Raw secrets never travel through the dispatcher.
   */
  credentialRef?: string | null;
}

export interface AdapterSubmissionResult {
  externalReference: string;
  externalDestination?: string;
  /** Where the submission's outbound payload was recorded (for audit). */
  handoffPayloadRef?: string;
}

export type AdapterPollStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed";

export interface AdapterPollResult {
  externalReference: string;
  status: AdapterPollStatus;
  progress?: number;
}

/**
 * Loop 9 Phase 9.2 — polling / result-fetch context. Carries the same
 * `credential_ref:env:*` pointer the dispatcher supplied to `submit()`
 * so async-path callers (Phase 9.3+) can re-read the credential
 * without opening a DB connection.
 */
export interface AdapterPollContext {
  credentialRef?: string | null;
}

export type AdapterExecutionStatus =
  | "success"
  | "partial"
  | "failed"
  | "unknown";

export interface AdapterExecutionResult {
  externalReference: string;
  status: AdapterExecutionStatus;
  payloadRef?: string;
  errorMessage?: string;
  metadata?: Record<string, unknown>;
}

/**
 * The five-method adapter contract. Every method is side-effect-free at
 * the schema level; writes to `output_handoffs` and `external_execution_
 * results` happen in the registry dispatcher, not inside the adapter.
 */
export interface AdapterContract {
  describe(): AdapterDescription;

  validatePackage(pkg: OutputPackage): AdapterValidationResult;

  submit(
    pkg: OutputPackage,
    ctx: AdapterSubmissionContext
  ): Promise<AdapterSubmissionResult>;

  pollStatus(
    externalReference: string,
    ctx?: AdapterPollContext
  ): Promise<AdapterPollResult>;

  fetchResult(
    externalReference: string,
    ctx?: AdapterPollContext
  ): Promise<AdapterExecutionResult>;
}

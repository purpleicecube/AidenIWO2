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
}

export interface AdapterValidationResult {
  ok: boolean;
  errors: readonly string[];
}

export interface AdapterSubmissionContext {
  /** Informational — the adapter MAY use for logging but MUST NOT require. */
  correlationId?: string;
  /** Adapter-supplied template override, optional. Used if the package
   *  doesn't carry its own `template_profile_id`. */
  templateExternalRef?: string;
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

  pollStatus(externalReference: string): Promise<AdapterPollResult>;

  fetchResult(externalReference: string): Promise<AdapterExecutionResult>;
}

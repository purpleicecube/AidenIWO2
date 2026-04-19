/**
 * Loop 3 Phase 4 — Gamma test-double adapter.
 *
 * Implements the five-method AdapterContract (ADR-012) with deterministic
 * in-memory state. No Gamma API calls; no network. Loop 10 swaps this
 * module for a live implementation; the contract shape stays the same,
 * so callers (registry dispatcher + tests) need no changes.
 *
 * Policy (IWO3_LOOP_3_APPROVAL_DECISIONS §Q3 `test_double`):
 *   - Live Gamma calls are explicitly forbidden in Loop 3.
 *   - The test double exists to prove the registry + policy + handoff +
 *     audit flow end-to-end, not to render real PPTX/PDF.
 */

import type {
  AdapterContract,
  AdapterDescription,
  AdapterExecutionResult,
  AdapterPollResult,
  AdapterSubmissionContext,
  AdapterSubmissionResult,
  AdapterValidationResult,
} from "../../contracts/adapter/types";
import type { OutputPackage } from "../../../db/schema/output_packages";

interface InMemorySubmission {
  externalReference: string;
  outputKind: string;
  status: "completed";
  payloadRef: string;
  submittedAt: string;
}

const SUPPORTED_OUTPUT_KINDS = [
  "gamma_pptx",
  "gamma_pdf",
] as const;

const SUPPORTED_ACTIONS = [
  "generate",
  "render_from_template",
  "export_pptx",
  "export_pdf",
] as const;

export class GammaTestDoubleAdapter implements AdapterContract {
  readonly adapterKey = "gamma";
  private submissions = new Map<string, InMemorySubmission>();
  private counter = 0;

  describe(): AdapterDescription {
    return {
      adapterKey: this.adapterKey,
      contractVersion: "v0",
      supportedOutputKinds: SUPPORTED_OUTPUT_KINDS,
      supportedActions: SUPPORTED_ACTIONS,
    };
  }

  validatePackage(pkg: OutputPackage): AdapterValidationResult {
    const errors: string[] = [];

    if (!SUPPORTED_OUTPUT_KINDS.includes(pkg.outputKind as never)) {
      errors.push(
        `output_kind='${pkg.outputKind}' not supported by gamma (supported: ${SUPPORTED_OUTPUT_KINDS.join(", ")})`
      );
    }

    if (!pkg.title || pkg.title.trim().length === 0) {
      errors.push("title must be non-empty");
    }

    // render_from_template requires a template_profile_id.
    // Phase 3.4 doesn't distinguish action key here — we accept either
    // generate (no template) or render_from_template (with template).
    // When template is absent, we note it but don't fail. Loop 10 may
    // tighten per-action validation.
    if (pkg.outputKind === "gamma_pptx" || pkg.outputKind === "gamma_pdf") {
      // content_blocks must be present (enforced at schema level) but we
      // sanity-check it's not completely empty.
      const blocks = pkg.contentBlocks as Record<string, unknown> | null;
      if (!blocks || Object.keys(blocks).length === 0) {
        errors.push(
          "content_blocks must be non-empty for gamma_pptx / gamma_pdf"
        );
      }
    }

    return { ok: errors.length === 0, errors };
  }

  async submit(
    pkg: OutputPackage,
    ctx: AdapterSubmissionContext
  ): Promise<AdapterSubmissionResult> {
    this.counter += 1;
    const externalReference = `gamma-double-${pkg.id.slice(0, 8)}-${this.counter}`;
    const payloadRef = `memory://gamma/${externalReference}/payload.json`;

    this.submissions.set(externalReference, {
      externalReference,
      outputKind: pkg.outputKind,
      status: "completed",
      payloadRef,
      submittedAt: new Date(0).toISOString(), // deterministic for test asserts
    });

    return {
      externalReference,
      externalDestination: "gamma://test-double",
      handoffPayloadRef: payloadRef,
    };
  }

  async pollStatus(externalReference: string): Promise<AdapterPollResult> {
    const sub = this.submissions.get(externalReference);
    if (!sub) {
      return { externalReference, status: "failed" };
    }
    return { externalReference, status: sub.status };
  }

  async fetchResult(
    externalReference: string
  ): Promise<AdapterExecutionResult> {
    const sub = this.submissions.get(externalReference);
    if (!sub) {
      return {
        externalReference,
        status: "failed",
        errorMessage: "unknown externalReference",
      };
    }
    return {
      externalReference,
      status: "success",
      payloadRef: `memory://gamma/${externalReference}/result.json`,
      metadata: {
        outputKind: sub.outputKind,
        submittedAt: sub.submittedAt,
        adapter: "gamma-test-double",
      },
    };
  }

  /** Test-only helper: clear in-memory state between tests. */
  __reset(): void {
    this.submissions.clear();
    this.counter = 0;
  }
}

// Module-level singleton used by the registry. Tests can also
// instantiate their own via `new GammaTestDoubleAdapter()`.
export const gammaTestDouble = new GammaTestDoubleAdapter();

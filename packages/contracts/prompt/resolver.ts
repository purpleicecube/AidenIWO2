/**
 * Loop 2 Phase 2 — IWO3 prompt-resolution service (TypeScript).
 *
 * Pure function (no DB, no network, no clock). Given a pre-fetched set of
 * prompt layers and an optional operator override, produce the rendered
 * text, a SHA-256 `render_hash`, and a provenance echo of the layer ids.
 *
 * The TypeScript side is the reference implementation. The Python mirror at
 * `apps/api-fastapi/prompt/resolver.py` must produce byte-identical output
 * for the same input; the parity contract test
 * (`tests/contract/prompt-resolver-parity.test.ts`) enforces this across
 * eight fixture inputs.
 *
 * Policy (per IWO3_LOOP_2_APPROVAL_DECISIONS §Q2, ADR-002):
 *   - override kind `safety` is HARD-REJECTED in v0. Calling code must
 *     not attempt safety/tenant/tool policy overrides.
 *   - `external_send` is allowed through the resolver but flagged on the
 *     output; the approval gate lives in the adapter layer (Loop 3).
 *   - `style` and `profile_swap` pass through with the override text
 *     appended as the final layer and `overrideRef` populated.
 *
 * Rendering algorithm (must be identical in Python):
 *   1. Collect present layers in order: base, product, profile,
 *      workflow, wo, override.text (if any).
 *   2. Normalize each layer:
 *        a. strip trailing spaces/tabs from each line (regex: `[ \t]+$`
 *           per line, multi-line mode).
 *        b. strip leading + trailing whitespace from the result.
 *   3. Join normalized layers with "\n\n".
 *   4. Strip leading + trailing whitespace from the final joined string.
 *   5. SHA-256 the UTF-8 bytes. Hex digest = `renderHash`.
 */

import { createHash } from "node:crypto";

export type OverrideKind = "style" | "profile_swap" | "safety" | "external_send";

export interface ResolverInput {
  layers: {
    base?: string;
    product?: string;
    profile: string;
    workflow?: string;
    wo?: string;
  };
  layerIds: {
    baseId?: string;
    productId?: string;
    profileId: string;
    workflowId?: string;
    woId?: string;
  };
  override?: {
    kind: OverrideKind;
    text: string;
    userId: string;
    reason: string;
  };
}

export interface ResolverOutput {
  renderedText: string;
  renderHash: string;
  layerIds: ResolverInput["layerIds"] & { overrideId?: string };
  overrideRef?: {
    kind: OverrideKind;
    userId: string;
    reason: string;
  };
  requiresApproval: boolean;
}

export class SafetyOverrideRejected extends Error {
  constructor() {
    super(
      "Override rejected: safety/tenant/tool overrides are disallowed in v0 " +
        "(IWO3_LOOP_2_APPROVAL_DECISIONS §Q2; ADR-002)."
    );
    this.name = "SafetyOverrideRejected";
  }
}

function normalize(text: string): string {
  // Strip trailing spaces/tabs from each line, then trim the full string.
  return text.replace(/[ \t]+$/gm, "").trim();
}

export function resolvePrompt(input: ResolverInput): ResolverOutput {
  if (input.override && input.override.kind === "safety") {
    throw new SafetyOverrideRejected();
  }

  const pieces: string[] = [];
  if (input.layers.base !== undefined) pieces.push(normalize(input.layers.base));
  if (input.layers.product !== undefined) pieces.push(normalize(input.layers.product));
  pieces.push(normalize(input.layers.profile));
  if (input.layers.workflow !== undefined) pieces.push(normalize(input.layers.workflow));
  if (input.layers.wo !== undefined) pieces.push(normalize(input.layers.wo));
  if (input.override) pieces.push(normalize(input.override.text));

  // Drop empty pieces so an empty layer doesn't inject a blank line block.
  const nonEmpty = pieces.filter((p) => p.length > 0);

  const renderedText = nonEmpty.join("\n\n").trim();
  const renderHash = createHash("sha256")
    .update(renderedText, "utf-8")
    .digest("hex");

  const requiresApproval = input.override?.kind === "external_send";

  return {
    renderedText,
    renderHash,
    layerIds: input.layerIds,
    overrideRef: input.override
      ? {
          kind: input.override.kind,
          userId: input.override.userId,
          reason: input.override.reason,
        }
      : undefined,
    requiresApproval,
  };
}

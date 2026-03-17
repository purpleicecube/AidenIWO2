# AIDEN IWO2 Done Contract Core Spec v0.1.0

| Property | Value |
| --- | --- |
| Artifact | AIDEN_IWO2_DONE_CONTRACT_CORE_SPEC |
| Version | 0.1.0 |
| Date | 2026-03-15 |
| Status | Draft for implementation handoff |
| Author | Codex |
| Tags | `#CDX` `#CDX-DOD` `#CDX-CLOSEOUT` `#CDX-ORCHESTRATION` |
| Scope | Work Order and Workflow closeout contract for IWO2 |

---

## 1. Purpose

Define a single, machine-evaluable closeout contract that decides when IWO2 orchestration is complete.

This contract exists to solve two platform problems:

1. Hanging orchestration caused by scattered closeout logic and ambiguous end states.
2. Slow orchestration caused by unnecessary re-evaluation, revision loops, and inconsistent completion checks.

The contract is intended to be the final authority for whether a Work Order or Workflow may move into a terminal state.

---

## 2. Core Principle

"Done" does not mean "Tier 2 produced something."

"Done" means:

1. Execution produced an output suitable for the requested artifact class.
2. All closeout gates were resolved.
3. The platform can safely assign a terminal orchestration state.

This is a closeout contract, not a creative-quality prompt.

---

## 3. Best Safe and Simple Implementation Approach

Phase 1 should use the simplest safe architecture:

1. No new database tables.
2. No new terminal states.
3. No new LLM closeout loops.
4. No new artifact-generation pipelines.
5. No child-work-order model for this phase.
6. Reuse existing evidence already present in IWO2:
   - `tier2Result`
   - `postProcessedFile`
   - work order status
   - workflow execution status
   - filed artifacts
   - candidate review records
   - quality review outcome
   - sandbox/preview result where already available

Phase 1 should be implemented as deterministic helper functions, not as prompt-only logic.

---

## 4. Shared Terminology

### 4.1 Execution Done

Tier 2 or workflow step execution has produced a usable output artifact or output payload.

### 4.2 Orchestration Done

All post-execution closeout checks have been resolved and the platform may safely assign a terminal state.

### 4.3 Done Contract

A deterministic evaluation pass that returns a final closeout decision for a Work Order or Workflow.

### 4.4 Artifact Class

The output class the system is expected to close out against. For this packet, the relevant new classes are:

- `static_web_page`
- `software_artifact`

---

## 5. Terminal States

The contract must always resolve to one of these states:

- `completed`
- `awaiting_operator`
- `blocked`
- `failed`

The contract must never return an ambiguous "keep processing" state after execution is already complete.

---

## 6. Closeout Decision Model

The shared evaluator should return a structure equivalent to:

```json
{
  "scope": "work_order | workflow",
  "artifactClass": "static_web_page | software_artifact | other",
  "done": true,
  "terminalState": "completed | awaiting_operator | blocked | failed",
  "hardFailures": [],
  "softWarnings": [],
  "requiredNextAction": "none | request_revision | operator_review | candidate_selection | filing_retry | preview_retry",
  "closeoutReason": "short deterministic explanation",
  "evidence": {
    "deliverablePresent": true,
    "postProcessedFilePresent": false,
    "qualityReviewResolved": true,
    "candidateReviewPending": false,
    "filingResolved": true,
    "previewResolved": true
  }
}
```

This is a logical contract. The implementation may use TypeScript types instead of this exact JSON shape.

---

## 7. Shared Evidence Sources in Current IWO2

These are the primary closeout facts already available in the current system:

1. Work Order quality review in `server/orchestration.ts`
2. Workflow PM assembly and executive review in `server/workflow-pm.ts` and `server/orchestration.ts`
3. `tier2Result.output.deliverable`
4. `tier2Result.output.postProcessedFile`
5. candidate review state for Gamma outputs
6. filing behavior in `server/workspace-filing.ts`
7. HTML artifact backfill behavior for renderable web artifacts
8. workflow step `pocketflowResult.postProcessedFile` when a workflow step generated a file

Phase 1 should consume these sources instead of inventing new persistence.

---

## 8. Shared Closeout Rules

These rules apply to all artifact classes.

### 8.1 Hard Failure Rules

If any hard failure is present, the evaluator must not return `completed`.

Hard failures:

1. Required deliverable missing.
2. Required binary/file artifact missing when the artifact class requires it.
3. Quality review returned `block`.
4. Candidate review is still pending.
5. Required filing failed or remains unresolved.
6. Output is structurally invalid for the artifact class.
7. Execution produced only placeholder or empty-shell output.

### 8.2 Soft Warning Rules

Soft warnings do not block `completed`.

Examples:

1. Minor formatting defects.
2. Improvement opportunities.
3. Non-critical content quality notes.
4. Missing optional polish.

### 8.3 Terminal-State Mapping

Use this deterministic mapping:

1. Hard failure caused by operator-needed resolution -> `awaiting_operator`
2. Hard failure caused by policy/quality block -> `blocked`
3. Hard failure caused by unrecoverable runtime closeout error -> `failed`
4. No hard failures -> `completed`

---

## 9. Shared Evaluation Order

Run the closeout evaluator in this order:

1. Determine artifact class.
2. Determine artifact-specific required evidence.
3. Confirm a primary deliverable exists.
4. Confirm artifact-specific output evidence exists.
5. Resolve quality-review state.
6. Resolve candidate-review state.
7. Resolve filing state.
8. Resolve preview/runtime validation state if required by the artifact class.
9. Return terminal state.

This order is important because it reduces unnecessary loops.

---

## 10. Work Order Closeout Contract

For Work Orders, orchestration is done only if:

1. Tier 2 output exists.
2. Quality review is resolved.
3. Revision loop is resolved.
4. Candidate selection is resolved, if applicable.
5. Artifact filing is resolved.
6. Artifact-class closeout gates are satisfied.
7. Final status can be written once.

---

## 11. Workflow Closeout Contract

For Workflows, orchestration is done only if:

1. Required steps are complete or explicitly skipped.
2. PM assembly is resolved.
3. Executive review is resolved.
4. Any artifact generated by workflow steps is resolved into a closeout-ready final output.
5. Filing is resolved for the final result.
6. Artifact-class closeout gates are satisfied.
7. Final workflow and linked Work Order states can be written once.

---

## 12. Phase 1 Non-Goals

These should remain out of scope for the first implementation:

1. New schema migrations solely for the Done Contract.
2. New LLM-led closeout decision chains.
3. Native DOCX or XLSX generation.
4. Deep browser automation for every web output.
5. Full build/runtime validation for every software artifact by default.
6. Replacing PocketFlow, workflow PM, or existing status models.

---

## 13. Phase 1 Insertion Points

Later implementation should hook the evaluator into:

1. Work Order closeout path after quality-review resolution and before `completeAndFileWorkOrder()`
2. Workflow completion path after PM assembly / executive review and before final workflow completion
3. Watchdog/finalizer path for stuck closeout states

The Done Contract must be the last deterministic gate before writing a terminal status.

---

## 14. Safety Rules for Implementation

Claude/Codex should follow these guardrails:

1. Reuse existing statuses.
2. Prefer pure helper functions over large orchestration rewrites.
3. Do not change artifact-generation pipelines in the same patch.
4. Do not add new LLM dependencies for closeout logic.
5. Prefer evidence-based checks over prompt interpretation.
6. Default to conservative completion decisions when required evidence is missing.

---

## 15. Expected Benefits

If implemented correctly, this contract should:

1. Reduce stuck "processing" states after execution finished.
2. Reduce unnecessary revision loops.
3. Make closeout decisions consistent across Work Orders and Workflows.
4. Increase operator trust in terminal states.
5. Speed common paths by avoiding repeated closeout re-interpretation.

---

## 16. Deliverables in This Handoff Packet

This core spec is paired with:

1. `AIDEN_IWO2_STATIC_WEB_PAGE_DOD_v0.1.0.md`
2. `AIDEN_IWO2_SOFTWARE_ARTIFACT_DOD_v0.1.0.md`
3. `AIDEN_IWO2_DOCUMENT_DOD_v0.1.0.md`
4. `AIDEN_IWO2_PPTX_DOD_v0.1.0.md`
5. `AIDEN_IWO2_DONE_CONTRACT_IMPLEMENTATION_BRIEF_v0.1.0.md`

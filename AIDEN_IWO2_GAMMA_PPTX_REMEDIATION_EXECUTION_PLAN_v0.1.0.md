# AIDEN_IWO2 Gamma PPTX Remediation Execution Plan v0.1.0

Date: 2026-03-15
Audience: Claude Code implementation handoff
Scope: Gamma-backed PPTX generation quality, review, and preview handling
Status: Approved for implementation planning, no code in this document

## Goal

Fix the current PPTX regression where Gamma returns technically valid files with poor slide composition, while keeping the implementation safe, minimal, and compatible with the existing PocketFlow and Done Contract architecture.

This plan assumes:

- The Done Contract is not the root cause of poor Gamma formatting.
- Gamma quality failures are occurring upstream in content shaping and downstream in review blindness.
- The safest first implementation is validation and review hardening, not a major pipeline redesign.

## Validated Problem Statement

The current Gamma PPTX path has four weaknesses:

1. No preflight validation before sending `dict.finalDeliverable` to Gamma.
2. No Gamma-specific post-generation quality gate beyond "file exists".
3. Tier 1 review is biased toward content text and can miss visual/layout failures in rendered decks.
4. Sandbox preview currently reflects the text deliverable, not the actual PPTX, which can confuse operators during triage.

## Implementation Constraints

Claude should preserve these constraints:

- Do not remove or bypass the existing Done Contract.
- Do not redesign PocketFlow iteration semantics in this fix.
- Do not add new DB tables.
- Avoid schema changes unless strictly necessary.
- Prefer pure helper functions plus targeted orchestration hooks.
- Keep Gamma fallback behavior intact.
- Keep `candidate_review` semantics intact.

## Phase 1 Fix Set

Implement these items in order.

### 1. Add Gamma PPTX preflight validation

Purpose: stop obviously weak slide markdown from reaching Gamma.

Create a small helper, preferably in `server/pocketflow.ts` or a nearby focused helper file, that validates PPTX-bound deliverables before `generateWithGamma()`.

Minimum checks:

- deliverable is non-empty
- minimum content length
- minimum slide structure markers
- required section presence when a template `contentContract` exists
- reject placeholder/shell output
- reject prose blobs with no slide segmentation

Safe approach:

- Use conservative heuristics only.
- Return structured validation result: `ok`, `hardFailures`, `softWarnings`, `derivedSlideCount`.
- If validation fails:
  - log the failure
  - do not call Gamma
  - route to existing revision/escalation path instead of pretending generation succeeded

Important:

- Do not require perfect markdown.
- This validator should catch bad inputs, not become a fragile parser.

### 2. Add presentation-specific contract parsing

Purpose: enforce the existing `contentContract` as evidence, not just prompt guidance.

If `dict.designContext` or Gamma template registry content contract is present, derive a minimal runtime contract:

- expected slide count range
- required named sections
- optional max bullets per slide
- optional max content density heuristic

Safe approach:

- Keep parsing tolerant.
- If contract text cannot be parsed, log and fall back to generic preflight.
- Do not block generation only because advanced optional rules are missing.

### 3. Add post-Gamma structural verification

Purpose: distinguish "binary exists" from "usable deck likely exists".

After successful Gamma generation:

- verify PPTX file exists
- verify MIME / extension path consistency
- extract or estimate slide count if practical
- compare to contract range when available
- record compliance warnings in logs / metadata

Safe approach:

- Start with low-risk checks only.
- If slide count extraction is hard, use a lightweight PPTX inspection method or defer exact count and log that it is unavailable.
- Do not add a heavyweight rendering dependency in this phase.

Result:

- Gamma success should produce a compliance record, not just a file record.

### 4. Strengthen Aiden review for PPTX outputs

Purpose: give Aiden room to reject ugly decks before closeout.

Update Tier 1 review behavior for PPTX outputs so that the review is not limited to "content quality only" when a binary exists.

Target behavior:

- file-format satisfaction remains true when `postProcessedFile` exists
- but presentation-quality review must still evaluate:
  - slide structure
  - pacing
  - section completeness
  - obvious density/collision risk from source content

Safe approach:

- Do not ask the LLM to hallucinate rendered visuals.
- Ask it to evaluate whether the source deck content is fit for slide presentation.
- If post-Gamma compliance warnings exist, pass them into the review prompt.

### 5. Add a PPTX-specific closeout warning path

Purpose: stop weak Gamma outputs from silently looking "good enough".

Do not make the Done Contract responsible for layout design.
Do allow it to consume Gamma compliance evidence.

Safe approach:

- add optional evidence fields, not a new closeout system
- if Gamma compliance has hard failures, Done Contract should not allow `completed`
- if only warnings exist, completion may continue but logs must show risk

This keeps architecture clean:

- PocketFlow validates generation inputs/outputs
- Aiden judges quality
- Done Contract governs terminal closure

### 6. Fix preview/operator clarity

Purpose: avoid confusing the markdown sandbox preview with the actual PPTX.

Current behavior is technically correct but misleading.

Implement:

- explicit preview labeling for PPTX work orders
- if sandbox is showing markdown/document preview for a PPTX job, label it as source preview, not final deck preview
- where possible, surface Gamma file metadata and Gamma URL separately from sandbox text preview

Safe approach:

- start with labeling and metadata
- do not attempt in-browser PPTX rendering in this phase

## Suggested File Touchpoints

Primary:

- `server/pocketflow.ts`
- `server/llm-client.ts`
- `server/done-contract.ts`
- `server/workspace-filing.ts`
- `server/__tests__/...`

Possible helper file:

- `server/pptx-quality.ts` or similar, if logic becomes too large for `pocketflow.ts`

Avoid unless required:

- `shared/schema.ts`
- database migrations

## Recommended Implementation Order

1. Add reusable PPTX preflight/compliance helpers with unit tests.
2. Wire preflight into Gamma path before `generateWithGamma()`.
3. Wire post-Gamma compliance logging.
4. Pass compliance evidence into Tier 1 review.
5. Feed compliance evidence into Done Contract as optional PPTX evidence.
6. Improve workspace/sandbox preview labeling.
7. Run end-to-end manual test with a known weak Gamma template.

## Test Plan

Add focused tests for these cases:

1. Weak markdown with no slide structure fails preflight and does not call Gamma.
2. Contracted deck missing required sections triggers preflight failure or hard warning.
3. Gamma success with compliant file produces compliance metadata.
4. Gamma success with weak compliance triggers review warning/escalation path.
5. Done Contract blocks PPTX completion when Gamma compliance marks hard failure.
6. Candidate review still blocks completion even when compliance passes.
7. Sandbox/workspace labels distinguish source preview from final PPTX artifact.

## Acceptance Criteria

Implementation is complete when all of these are true:

- Gamma is no longer called for obviously malformed PPTX source content.
- Aiden can reject weak PPTX source/compliance before final closeout.
- Operators can distinguish text preview from final PPTX output.
- Done Contract uses Gamma compliance evidence without becoming the presentation engine.
- No regressions to local PPTX fallback or candidate review flows.

## Explicit Non-Goals

Do not include these in this fix:

- full visual rendering analysis of PPTX slides
- screenshot-based deck scoring
- new artifact schema/tables
- generalized redesign of PM assembly
- replacement of Gamma

## BUGFIX_LOG Update Requirement

After implementation, Claude should update `BUGFIX_LOG.md` by:

1. converting BUG-038 from planned/open to fixed
2. documenting exact root cause actually confirmed during implementation
3. listing files changed
4. recording verification steps from at least one successful PPTX regression test
5. noting any residual risk if rendered-visual scoring is still heuristic

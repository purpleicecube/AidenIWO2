# AIDEN IWO2 PPTX DoD v0.1.0

| Property | Value |
| --- | --- |
| Artifact | AIDEN_IWO2_PPTX_DOD |
| Version | 0.1.0 |
| Date | 2026-03-15 |
| Status | Draft for implementation handoff |
| Author | Codex |
| Tags | `#CDX` `#CDX-DOD` `#CDX-PPTX` `#CDX-GAMMA` |
| Scope | PPTX closeout rules for IWO2 |

---

## 1. Applies To

This DoD track applies to:

- PowerPoint presentations
- slide decks
- pitch decks
- presentation artifacts
- PPTX outputs produced locally or via Gamma

PPTX is a dedicated artifact class and must not be treated as a generic document.

---

## 2. Primary Design Choice

PPTX closeout must be Gamma-aware and candidate-review-aware.

In IWO2, PPTX can be produced through:

1. local PPTX generation
2. Gamma generation
3. Gamma candidate-review mode

Therefore, a PPTX is not done just because slide content exists. It is done only when the binary artifact and its orchestration policy are both resolved.

---

## 3. Required Evidence

Phase-1 evidence should be drawn from current platform facts:

1. `tier2Result.output.deliverable`
2. `postProcessedFile` for PPTX
3. workflow step `pocketflowResult.postProcessedFile`
4. Gamma generation records
5. selected candidate state
6. filed artifact record
7. quality-review state

---

## 4. Local PPTX Rules

### 4.1 local_pptx Completed

Return `completed` only when:

1. the content deliverable exists
2. a valid PPTX binary exists via local generation
3. quality review is resolved
4. filing is resolved

### 4.2 local_pptx Not Done

Do not return `completed` when:

1. markdown exists but no PPTX binary exists and PPTX was explicitly required
2. filing is unresolved
3. quality review blocked the artifact

---

## 5. Gamma PPTX Rules

Gamma must be a first-class part of the PPTX DoD.

### 5.1 Gamma Success

If Gamma generated a PPTX successfully and the selected policy path is resolved, the file-format requirement is satisfied by the Gamma binary.

### 5.2 Gamma Candidate Review

If `gammaDeliveryPolicy = candidate_review`, the PPTX is not done when Gamma candidates are created.

It becomes done only when:

1. an operator selected a candidate, and
2. the selected candidate is filed or otherwise attached to final closeout

### 5.3 Gamma Failure

If Gamma fails:

1. and policy is `template_locked` / fallback blocked -> not `completed`
2. and fallback is allowed and local path succeeds -> evaluate the fallback PPTX artifact

---

## 6. Quality Review Rules

PPTX closeout must respect the existing post-processing logic.

When a valid PPTX binary exists, quality review should focus on content quality, structure, and completeness, not on whether the original text deliverable was markdown.

The Done Contract must still confirm that quality-review resolution itself is complete before allowing `completed`.

---

## 7. Hard Gates

Hard gates for `completed`:

1. required PPTX binary missing
2. quality review blocked
3. candidate review pending
4. filing unresolved
5. Gamma failed with fallback blocked
6. output is placeholder shell or structurally invalid for slide content

---

## 8. Soft Warnings

Soft warnings:

1. weak slide titles
2. uneven slide density
3. design polish opportunities
4. minor structure improvements

These should not block completion when the PPTX artifact and closeout path are valid.

---

## 9. Terminal-State Rules

### 9.1 completed

Return `completed` when:

1. slide content exists
2. a valid PPTX binary exists
3. quality review is resolved
4. candidate review is resolved
5. filing is resolved

### 9.2 awaiting_operator

Return `awaiting_operator` when:

1. Gamma candidate selection is pending
2. explicit operator review remains the only unresolved gate

### 9.3 blocked

Return `blocked` when:

1. quality review blocked the artifact
2. Gamma failed and policy blocked fallback

### 9.4 failed

Return `failed` when:

1. PPTX closeout fails irrecoverably after execution completed
2. filing fails irrecoverably

---

## 10. Best Safe and Simple Implementation Approach

Phase 1 should not redesign the PPTX pipeline.

Instead:

1. reuse existing `postProcessedFile`
2. reuse existing Gamma record state
3. reuse selected-candidate closeout flow
4. reuse existing filing behavior

This is the safest and most efficient path to deterministic PPTX closeout.

---

## 11. Test Matrix

Minimum implementation tests:

1. local PPTX generated and filed -> `completed`
2. explicit PPTX request with markdown only and no binary -> not `completed`
3. Gamma PPTX candidate-review pending -> `awaiting_operator`
4. Gamma PPTX candidate selected and filed -> `completed`
5. Gamma failure with locked template / blocked fallback -> not `completed`
6. filing unresolved -> not `completed`


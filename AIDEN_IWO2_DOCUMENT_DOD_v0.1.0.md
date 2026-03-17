# AIDEN IWO2 Document DoD v0.1.0

| Property | Value |
| --- | --- |
| Artifact | AIDEN_IWO2_DOCUMENT_DOD |
| Version | 0.1.0 |
| Date | 2026-03-15 |
| Status | Draft for implementation handoff |
| Author | Codex |
| Tags | `#CDX` `#CDX-DOD` `#CDX-DOCUMENT` `#CDX-PDF` |
| Scope | Document closeout rules for IWO2 |

---

## 1. Applies To

This DoD track applies to:

- PDF deliverables
- report documents
- proposal documents
- briefings
- memos
- structured written deliverables
- future DOC/DOCX outputs

This track does not apply to PPTX. PPTX must remain a separate artifact class because of its dedicated generation and Gamma candidate-review behavior.

---

## 2. Primary Design Choice

Document DoD must be honest about current platform capability.

Phase 1 should distinguish between:

1. `document_rendered`
2. `document_native`

This is the safest approach because IWO2 already has strong PDF closeout evidence, but it does not appear to have an equivalent native DOC/DOCX generation path that should be promised automatically.

---

## 3. Validation Tracks

### 3.1 document_rendered

Use when the requested deliverable is satisfied by:

- PDF
- markdown document
- HTML document
- other rendered document output that is the intended final artifact

### 3.2 document_native

Use only when the request explicitly requires a native office-document format such as:

- `.doc`
- `.docx`

Phase 1 must not mark `document_native` complete unless native document evidence exists.

---

## 4. Current Safe Default

If the request says "document" but does not explicitly require DOC/DOCX, default to `document_rendered`.

If the request explicitly requires DOC/DOCX and no native generator/evidence exists, the evaluator must not silently pretend the requirement was met.

---

## 5. Required Evidence

### 5.1 document_rendered

Expected phase-1 evidence:

1. `tier2Result.output.deliverable`
2. `postProcessedFile` for PDF when applicable
3. filed artifact record
4. quality-review result
5. candidate-review resolution if Gamma generated the document

### 5.2 document_native

Expected evidence:

1. native file exists
2. file path exists
3. MIME/extension is consistent with DOC/DOCX
4. filing is resolved

Phase 1 should not synthesize this evidence if it does not exist.

---

## 6. PDF Rules

PDF is the strongest current document closeout path and should have strict rules.

### 6.1 PDF Completed

Return `completed` for PDF only when:

1. content deliverable exists
2. a valid PDF binary exists through:
   - local PDF post-processing, or
   - Gamma-generated PDF, or
   - approved fallback permitted by policy
3. quality review is resolved
4. filing is resolved
5. candidate review is resolved if Gamma candidate mode was used

### 6.2 PDF Not Done

Do not return `completed` when:

1. markdown/text exists but no PDF artifact exists and PDF was explicitly required
2. Gamma candidate review is still pending
3. Gamma failed and fallback was blocked by policy
4. filing is unresolved

---

## 7. Gamma Rules for Documents

Gamma must be treated as part of closeout, not just generation.

### 7.1 Gamma Success

If Gamma successfully generated the final PDF and the policy path is resolved, the file-format requirement is satisfied by the Gamma binary.

### 7.2 Gamma Candidate Review

If `gammaDeliveryPolicy = candidate_review`, the document is not done when candidates are generated. It is done only after:

1. operator selected a candidate, or
2. another explicit terminal resolution occurred

### 7.3 Gamma Failure

If Gamma fails:

1. and locked policy forbids fallback -> not `completed`
2. and fallback is allowed and fallback succeeds -> evaluate the fallback artifact

---

## 8. Native DOC/DOCX Rules

Native document closeout should be strict and honest.

### 8.1 document_native Completed

Return `completed` only when:

1. native DOC/DOCX requirement was explicit
2. a native file exists
3. the file is filed
4. quality-review closeout is resolved

### 8.2 document_native Not Done

Do not return `completed` when:

1. only markdown/HTML/PDF exists but DOC/DOCX was explicitly required
2. native file evidence is missing
3. the system cannot verify filing

In that case, route to revision or `awaiting_operator` rather than faking completion.

---

## 9. Hard Gates

Hard gates for `completed`:

1. required document content missing
2. required file format missing
3. quality review blocked
4. candidate review pending
5. filing unresolved
6. output is raw JSON, placeholder shell, or structurally invalid

---

## 10. Soft Warnings

Soft warnings:

1. copy polish issues
2. minor formatting issues
3. non-critical section refinement
4. style improvements

These must not block completion when hard gates are satisfied.

---

## 11. Terminal-State Rules

### 11.1 completed

Return `completed` when:

1. requested document track is satisfied
2. file-format requirement is satisfied honestly
3. quality-review state is resolved
4. candidate-review state is resolved
5. filing is resolved

### 11.2 awaiting_operator

Return `awaiting_operator` when:

1. candidate review is pending
2. explicit native document requirement cannot be safely satisfied automatically
3. operator approval is the remaining unresolved gate

### 11.3 blocked

Return `blocked` when:

1. quality review blocked the output
2. policy blocked fallback from a failed generation path

### 11.4 failed

Return `failed` when:

1. document-generation closeout fails irrecoverably
2. filing fails irrecoverably

---

## 12. Test Matrix

Minimum implementation tests:

1. explicit PDF request with valid PDF binary -> `completed`
2. explicit PDF request with only markdown -> not `completed`
3. Gamma PDF candidate-review pending -> `awaiting_operator`
4. Gamma PDF selected and filed -> `completed`
5. explicit DOCX request without native file evidence -> not `completed`
6. filing unresolved -> not `completed`


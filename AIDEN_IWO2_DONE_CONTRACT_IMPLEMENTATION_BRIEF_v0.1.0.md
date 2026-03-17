# AIDEN IWO2 Done Contract Implementation Brief v0.1.0

| Property | Value |
| --- | --- |
| Artifact | AIDEN_IWO2_DONE_CONTRACT_IMPLEMENTATION_BRIEF |
| Version | 0.1.0 |
| Date | 2026-03-15 |
| Status | Ready for Claude/Codex implementation planning |
| Author | Codex |
| Tags | `#CDX` `#CDX-HANDOFF` `#CDX-DOD` `#CDX-IMPLEMENTATION` |
| Depends On | `AIDEN_IWO2_DONE_CONTRACT_CORE_SPEC_v0.1.0.md`, `AIDEN_IWO2_STATIC_WEB_PAGE_DOD_v0.1.0.md`, `AIDEN_IWO2_SOFTWARE_ARTIFACT_DOD_v0.1.0.md` |

---

## 1. Mission

Implement a shared Done Contract for IWO2 closeout with four initial artifact tracks:

1. Static Web Page DoD
2. Software Artifact DoD
3. Document DoD
4. PPTX DoD

No phase-1 implementation should attempt to redesign PocketFlow, workflow PM, or artifact generation.

---

## 2. Recommended Phase-1 Architecture

Add a small deterministic closeout layer.

Suggested new runtime helpers:

1. `classifyArtifactClass(orderOrWorkflow): ArtifactClass`
2. `resolveValidationTier(orderOrWorkflow, artifactClass): ValidationTier`
3. `evaluateDoneContract(context): DoneDecision`

The closeout layer should be pure or near-pure logic, using current runtime evidence.

---

## 3. Best Safe and Efficient Implementation Path

This is the recommended minimum path:

1. Implement the evaluator as a helper module.
2. Call it from existing closeout points.
3. Reuse existing states and existing evidence.
4. Log decisions to execution logs.
5. Add focused tests for each artifact track.

Do **not** do the following in the same patch:

1. new database tables
2. new status vocabulary
3. new child-work-order architecture
4. new DOCX/XLSX native pipelines
5. broad browser/runtime automation

---

## 4. Proposed Insertion Points

### 4.1 Work Orders

Insert Done Contract evaluation after:

1. quality review result is known
2. revision loop is resolved
3. candidate-review gate is resolved

Insert before:

1. `completeAndFileWorkOrder()`
2. final `completed` status assignment

### 4.2 Workflows

Insert Done Contract evaluation after:

1. PM assembly is complete
2. executive review is complete

Insert before:

1. final workflow completion
2. final linked work-order completion path

### 4.3 Watchdog / Recovery

Add a closeout-finalizer path for cases where execution finished but terminal closeout did not resolve.

This should use the same evaluator, not special one-off logic.

---

## 5. Data and Evidence Sources to Reuse

Expected phase-1 evidence:

1. `tier2Result.output.deliverable`
2. `tier2Result.output.postProcessedFile`
3. workflow `pocketflowResult.postProcessedFile`
4. filed artifacts
5. Gamma candidate-review state
6. sandbox preview result if present
7. quality-review outcome
8. final workflow assembly output

Avoid adding extra persistence unless phase 1 exposes a clear gap.

---

## 6. Artifact Classification Rules

### 6.1 Static Web Page

Use for:

- landing pages
- mini-web pages
- microsites
- marketing pages

### 6.2 Software Artifact

Use for:

- web apps
- interactive websites
- mobile apps
- games
- simulations

Classification should be narrow and conservative. If a request looks like a landing page, do not send it down the software-artifact closeout path.

---

## 7. Validation Tier Rules

### 7.1 Static Web Page

Default:

- `render_complete`

Upgrade only when explicitly requested:

- `interaction_complete`

### 7.2 Software Artifact

Default:

- `source_complete`

Upgrade only on explicit prompt evidence:

- `preview_complete`
- `build_complete`
- `runtime_complete`

This is the main performance protection.

---

## 8. Decision Priorities

The evaluator should prioritize these checks in order:

1. artifact class
2. required validation tier
3. deliverable presence
4. artifact-specific structural validity
5. quality-review block state
6. candidate-review pending state
7. filing resolved state
8. preview/build/runtime evidence if required
9. terminal status

Do not move filing after completion. Filing is part of closeout.

---

## 9. Logging Requirements

Phase 1 should log:

1. artifact class selected
2. validation tier selected
3. hard failures
4. soft warnings
5. final terminal-state decision

This will make hang diagnosis easier without requiring new schema.

---

## 10. Test Plan

Claude/Codex should add tests for:

### 10.1 Static Web Page

1. valid landing page HTML closes cleanly
2. prose-only page description does not close
3. interaction-required page without primary interaction does not close
4. unresolved filing does not close

### 10.2 Software Artifact

1. source-only app request closes at `source_complete`
2. preview-requested app without preview evidence does not close
3. runtime-requested artifact without runtime evidence does not close
4. placeholder/scaffold-only software output does not close

### 10.3 Shared Closeout

1. candidate-review pending forces `awaiting_operator`
2. quality block forces `blocked`
3. unrecoverable closeout failure forces `failed`
4. no hard failures allows `completed`

---

## 11. Suggested Delivery Sequence for Claude

Recommended order:

1. add shared type definitions
2. implement artifact classification
3. implement validation-tier resolution
4. implement static web page evaluator
5. implement software artifact evaluator
6. implement shared closeout wrapper
7. wire work-order closeout path
8. wire workflow closeout path
9. add tests
10. only then consider broader artifact classes

---

### 6.3 Document

Use for:

- PDF
- rendered written documents
- future native DOC/DOCX when evidence exists

### 6.4 PPTX

Use for:

- presentations
- slide decks
- pitch decks

Gamma and candidate-review interactions must be considered part of this closeout path.

---

## 12. Out of Scope for This Packet

This handoff packet does not define:

1. Spreadsheet DoD
2. child linked work-order closeout
3. schema-level artifact metadata redesign

Those can be added later using the same Done Contract pattern.

---

## 13. Handoff Summary for Claude/Codex

Implement the smallest deterministic closeout layer possible.

The main architectural intent is:

1. use shared closeout logic
2. keep static pages, software artifacts, documents, and PPTX as separate closeout tracks
3. keep validation-tier expectations explicit
4. treat Gamma interactions as part of PPTX/document closeout, not as a side effect
5. avoid schema churn
6. make final-state assignment deterministic

If phase 1 is kept this small, it should reduce hangs and improve closeout speed without destabilizing core orchestration.

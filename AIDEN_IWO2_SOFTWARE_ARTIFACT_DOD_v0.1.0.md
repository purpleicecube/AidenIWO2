# AIDEN IWO2 Software Artifact DoD v0.1.0

| Property | Value |
| --- | --- |
| Artifact | AIDEN_IWO2_SOFTWARE_ARTIFACT_DOD |
| Version | 0.1.0 |
| Date | 2026-03-15 |
| Status | Draft for implementation handoff |
| Author | Codex |
| Tags | `#CDX` `#CDX-DOD` `#CDX-SOFTWARE` `#CDX-CODEBLOCKS` |
| Scope | Software Artifact closeout rules for IWO2 |

---

## 1. Applies To

This DoD track applies to:

- interactive websites
- web apps
- mobile apps
- games
- simulations
- multi-screen or multi-route software artifacts
- codeblock outputs that represent software, not static pages

This track does **not** apply to:

- landing pages
- microsites
- simple static marketing pages

Those belong to Static Web Page DoD.

---

## 2. Goal

Close software artifacts with explicit validation tiers so the platform does not over-promise runtime validation when only source output was requested.

This track must be flexible enough to support simple source delivery and stricter runtime proof when the request requires it.

---

## 3. Validation Tiers

Phase 1 should use these four tiers:

1. `source_complete`
2. `preview_complete`
3. `build_complete`
4. `runtime_complete`

The requested tier should be derived conservatively. If the prompt does not demand execution proof, do not force a higher tier.

---

## 4. Tier Definitions

### 4.1 source_complete

Use when the request is primarily for code delivery.

Done means:

1. source output exists
2. required major files or structures exist
3. output is not a placeholder shell
4. artifact is filed

### 4.2 preview_complete

Use when the request expects a visible preview but not a proven build.

Done means:

1. `source_complete` is true
2. a previewable artifact or sandbox result exists
3. the preview is not fatally broken

### 4.3 build_complete

Use when the request explicitly expects a buildable software output.

Done means:

1. `source_complete` is true
2. build evidence exists
3. no fatal build blocker remains

### 4.4 runtime_complete

Use when the request explicitly expects runnable software behavior.

Done means:

1. `source_complete` is true
2. runtime evidence exists
3. requested primary path is operational

Phase 1 should keep runtime checks narrow and deterministic.

---

## 5. Required Evidence

The evaluator should prefer existing signals and avoid new persistence in phase 1.

Potential evidence:

1. `tier2Result.output.deliverable`
2. filed code artifact(s)
3. sandbox session output if already produced
4. HTML preview for web-app-like output
5. existing logs or explicit build/runtime evidence written by the execution path

If strong runtime evidence does not exist in the current platform path, the evaluator must not claim `runtime_complete`.

---

## 6. Default Tier Rules

Use safe defaults:

1. explicit "build", "compile", "production build" -> `build_complete`
2. explicit "run", "working app", "playable", "simulation works" -> `runtime_complete`
3. explicit "preview", "demo", "prototype", "show me the interface" -> `preview_complete`
4. otherwise -> `source_complete`

This is the safest phase-1 rule because it avoids hanging basic code deliveries behind runtime expectations they never asked for.

---

## 7. Hard Gates

### 7.1 Source Presence

At least one meaningful software output must exist.

Block completion if:

1. output is missing
2. output is only explanatory prose
3. output is only TODO notes or scaffold labels
4. output is placeholder shell content

### 7.2 Structure Presence

For `source_complete`, confirm that the output contains the minimum structure required by the software type.

Examples:

- entry file
- route/page/component set
- app shell
- game loop shell
- simulation logic shell

Phase 1 should keep this check lightweight and pattern-based.

### 7.3 Tier Evidence

Do not mark a higher tier complete without corresponding evidence:

1. no preview evidence -> no `preview_complete`
2. no build evidence -> no `build_complete`
3. no runtime evidence -> no `runtime_complete`

### 7.4 Filing Resolved

The software artifact is not done until filing is resolved.

---

## 8. Soft Warnings

These should not block completion when the requested tier is otherwise satisfied:

1. minor refactor opportunities
2. code-style cleanups
3. optional feature omissions
4. performance improvements not requested

---

## 9. Terminal-State Rules

### 9.1 completed

Return `completed` when:

1. required tier is satisfied
2. no quality block remains
3. filing is resolved
4. no operator-only closeout dependency remains

### 9.2 awaiting_operator

Return `awaiting_operator` when:

1. operator review is explicitly required
2. requested higher-tier validation cannot be resolved automatically
3. runtime proof depends on manual inspection or external environment

### 9.3 blocked

Return `blocked` when:

1. quality review blocked the artifact
2. required tier is impossible with the delivered output
3. the artifact type is fundamentally mismatched

### 9.4 failed

Return `failed` when:

1. filing fails unrecoverably
2. preview/build/runtime evidence path crashes irrecoverably after execution completed

---

## 10. Minimal Implementation Guidance

Claude/Codex should implement the lightest useful version first:

1. classify requests into `software_artifact`
2. infer validation tier conservatively
3. use current evidence paths only
4. do not build a new runtime harness in phase 1
5. do not block `source_complete` outputs with runtime-only expectations unless the request explicitly asked for runtime proof

---

## 11. Guardrails

To keep implementation safe and efficient:

1. Do not treat all code as requiring build or runtime proof.
2. Do not add deep per-framework logic in phase 1.
3. Do not add new long-running closeout loops.
4. Prefer "awaiting_operator" over fake runtime success when evidence is missing.

---

## 12. Test Matrix

Minimum implementation tests:

1. source-only app request with real code -> `completed` at `source_complete`
2. preview-requested web app with preview evidence -> `completed`
3. preview-requested web app without preview evidence -> not `completed`
4. runtime-requested game without runtime evidence -> `awaiting_operator` or revision path, not `completed`
5. prose-only response to software request -> not `completed`
6. filing unresolved -> not `completed`


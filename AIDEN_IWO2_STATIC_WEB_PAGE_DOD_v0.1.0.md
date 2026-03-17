# AIDEN IWO2 Static Web Page DoD v0.1.0

| Property | Value |
| --- | --- |
| Artifact | AIDEN_IWO2_STATIC_WEB_PAGE_DOD |
| Version | 0.1.0 |
| Date | 2026-03-15 |
| Status | Draft for implementation handoff |
| Author | Codex |
| Tags | `#CDX` `#CDX-DOD` `#CDX-WEB` `#CDX-LANDINGPAGE` |
| Scope | Static Web Page closeout rules for IWO2 |

---

## 1. Applies To

This DoD track applies to:

- landing pages
- mini-web pages
- microsites
- single-page HTML demos
- marketing pages
- simple static web artifacts

This track does **not** apply to:

- multi-route web apps
- web products with application state
- games
- simulations
- mobile apps

Those belong to Software Artifact DoD.

---

## 2. Goal

Close static web work quickly and safely without forcing software-grade validation.

This track exists to avoid over-engineering simple page closeout and to prevent static pages from hanging behind heavier app checks.

---

## 3. Default Validation Tier

Default tier for this class:

- `render_complete`

Optional tier:

- `interaction_complete`

Phase 1 should not add more tiers than these two.

---

## 4. Validation Tier Definitions

### 4.1 render_complete

The page can be treated as done when:

1. A renderable HTML artifact exists, either directly or through filing backfill.
2. Required sections are present.
3. The page is not structurally broken.
4. The artifact is filed or filing is otherwise resolved.

### 4.2 interaction_complete

Use only when the request explicitly requires interaction such as:

- CTA behavior
- nav behavior
- form interaction
- accordion/tab reveal
- lightweight JavaScript behavior

The page can be treated as done when `render_complete` is true and requested primary interactions are present without obvious fatal failure.

---

## 5. Required Evidence

The evaluator should prefer existing platform evidence:

1. `tier2Result.output.deliverable`
2. HTML artifact saved by workspace filing
3. HTML `postProcessedFile` backfill when created by filing
4. sandbox/preview result if one was requested or already produced
5. final filed artifact record

Phase 1 should not require new persistence.

---

## 6. Hard Gates

The following are hard gates for `completed`.

### 6.1 Deliverable Presence

At least one of these must be true:

1. final deliverable contains a full HTML document
2. a filed HTML artifact exists
3. a valid HTML preview artifact exists

### 6.2 Structural Validity

Block completion if:

1. output is missing core HTML structure when HTML was requested
2. output is only markdown describing a page rather than the page itself
3. output is raw JSON, escaped payload text, or placeholder-shell content
4. the page is effectively empty

### 6.3 Required Sections Present

If the request clearly calls for named sections, the primary required sections must exist.

Examples:

- hero
- CTA
- features
- pricing
- footer

Phase 1 should use conservative section checks only when the prompt made them explicit.

### 6.4 Filing Resolved

Static web page closeout is not complete until filing is resolved.

---

## 7. Soft Warnings

These should not block completion:

1. style polish improvements
2. minor spacing or copy defects
3. non-critical accessibility notes
4. optional sections omitted when not explicitly required

---

## 8. Interaction Rules

For `interaction_complete`, validate only the requested primary interactions.

Examples:

1. CTA button exists and is not a dead placeholder
2. anchor nav scroll target exists
3. form shell exists with visible input and submit path
4. tab/accordion shell behaves plausibly if explicitly requested

Do not expand the closeout contract into a full browser QA suite.

---

## 9. Terminal-State Rules

### 9.1 completed

Return `completed` when:

1. required HTML output exists
2. structural validity passes
3. required sections pass
4. interaction tier passes if requested
5. filing is resolved
6. no candidate review or quality block remains

### 9.2 awaiting_operator

Return `awaiting_operator` when:

1. operator review is explicitly required
2. candidate review is still pending
3. interaction validation cannot be safely resolved automatically

### 9.3 blocked

Return `blocked` when:

1. quality review blocked the artifact
2. output is fundamentally wrong for the requested page type

### 9.4 failed

Return `failed` when:

1. filing or preview resolution failed unrecoverably
2. the platform cannot establish renderable output after execution completed

---

## 10. Minimal Implementation Guidance

Claude/Codex should implement this in the simplest way:

1. classify the request as `static_web_page`
2. determine requested tier:
   - default `render_complete`
   - upgrade to `interaction_complete` only for explicit interaction requests
3. reuse existing HTML-detection and filing behavior
4. avoid adding new database fields in phase 1

---

## 11. Suggested Heuristic Triggers

Good indicators for `static_web_page`:

- landing page
- mini-web page
- microsite
- marketing page
- single page site
- splash page
- promo page

Phase 1 should keep heuristics narrow to avoid classifying full apps as static pages.

---

## 12. Test Matrix

Minimum implementation tests:

1. valid landing page HTML -> `completed`
2. markdown brief about a landing page instead of HTML -> not `completed`
3. HTML shell missing major required section -> revision/operator path
4. candidate review pending -> `awaiting_operator`
5. filing unresolved -> not `completed`
6. requested CTA interaction absent under `interaction_complete` -> revision/operator path


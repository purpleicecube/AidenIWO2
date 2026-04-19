# AIDEN IWO2 — Gamma Delivery Architecture Brief v0.1.0

Date: 2026-04-18
Audience: Architect reviewer
Status: Draft for design review — no implementation before approval
Supersedes (in spirit, not yet formally): `AIDEN_IWO2_GAMMA_PPTX_REMEDIATION_EXECUTION_PLAN_v0.1.0.md` (tactical)
Scope: All Gamma-backed PPTX/PDF delivery paths across IWO2

---

## 1. Why this brief exists

Since BUG-038 (preflight + compliance + review hardening) shipped in Session 11, we have continued to see Gamma calls fail silently on live work orders. The most recent failure — 3M Plan Deck, WO `49941c58`, 2026-04-18 — ended in a state where:

- The Gamma template was correctly resolved (`klear_live_v1` → `g_onfwfqpb52zcws3`, template_locked, pptx)
- The preflight rejected the deliverable on a `requiredSections` literal-match failure ("cover slide" / "executive summary")
- Because the template is `template_locked`, `fallbackAllowed = false` triggered a silent `return` at `server/pocketflow.ts:1447`
- No Gamma API call was ever issued; no local fallback artifact was produced
- The auto-revision loop (`orchestration.ts:1088`) did not rescue the WO because `revisionAttempts` in GCC metadata had already reached the cap across prior reopen cycles
- The operator saw "PPTX preflight failed" in the checklist and no further forward progress — no machine-readable explanation of why the WO stopped

Every prior fix (BUG-038, BUG-039, BUG-041, BUG-057, and the patches I made today — `sectionPresent` alias widening, `OPTIONAL_BY_DEFAULT` expansion, `enrichReviewWithPreflight`, `resolveWorkflowGammaPolicy`) solves one symptom while the combined design keeps producing new ones. The operator feedback (2026-04-18) is explicit: **stop patching points; design a universal solution**.

This brief identifies six architectural gaps, proposes a phased remediation, and defines acceptance criteria that apply to every Gamma-delivered artifact — single-WO, workflow, reopen, and retry.

---

## 2. Scope and non-goals

### 2.1 In scope

- All code paths that can reach `generateWithGamma()`: `nodePostProcess()` (single-WO) and `postProcessWorkflowDeliverable()` (workflow)
- Preflight and content-contract evaluation (`server/pptx-quality.ts`)
- The Aiden quality review supplement + auto-revision loop (`server/orchestration.ts`, `server/llm-client.ts`)
- Gamma template registry semantics (`gammaTemplates` table, `mode` field, `fallbackAllowed` derivation)
- WO lifecycle counters that gate revision (`gccMemory["gcc.metadata"].revisionAttempts`)
- Operator-facing observability for stuck WOs

### 2.2 Explicit non-goals

- Replacing Gamma
- Redesigning PocketFlow's inner iteration/convergence loop
- Adding new database tables (existing columns and JSON fields suffice)
- In-browser PPTX rendering
- Rendered-visual scoring (screenshot-based quality gates)
- Migrating `mode` semantics without an explicit migration path (see §8)

---

## 3. Current architecture (as of 2026-04-18)

### 3.1 Two Gamma call paths

| Path | Entry point | File:line | Invokes |
| ---- | ----------- | --------- | ------- |
| Single-WO | `nodePostProcess()` | `pocketflow.ts:1371` | `generateWithGamma()` at `:1462` |
| Workflow post-process | `postProcessWorkflowDeliverable()` | `pocketflow.ts:2294` | `generateWithGamma()` at `:2337` |

Both paths run preflight (`validatePptxPreflight()` in `pptx-quality.ts:196`) and share the compliance helper (`checkGammaCompliance()`). But they diverged in BUG-039: the workflow path historically ran without a resolved `gammaPolicy`, so Gamma was never attempted. Today's fix (`resolveWorkflowGammaPolicy()`) plugs that, but the two paths still encode preflight/fallback logic independently.

### 3.2 Template registry mode semantics

`gammaTemplates.mode` is a string field with effective values:

- `"template_locked"` → `fallbackAllowed = false`
- `"flexible"` / anything else → `fallbackAllowed = true`

The derivation lives in `pocketflow.ts:2099` and is duplicated at `pocketflow.ts:2120` and in `resolveWorkflowGammaPolicy()`. This mode is doing two jobs simultaneously:

- **Identity lock**: "operator wants this specific template used, no substitutions"
- **Fallback veto**: "if Gamma preflight or API fails, do not convert locally"

These are orthogonal concerns that are coupled by a single enum. Any operator who wants identity-lock-but-graceful-failure cannot express that intent. Any operator who wants template-flexible-but-strict-rendering cannot either.

### 3.3 Preflight's dual role

`validatePptxPreflight()` in `pptx-quality.ts:196` evaluates a mixed set of rules against the deliverable:

**Structural checks** (deterministic, failure-is-unambiguous):
- Non-empty, minimum length
- No raw JSON blob
- No escaped-newline content
- Has slide segmentation (headings / delimiters)
- Not a placeholder shell

**Contract checks** (semantic, failure-is-subjective):
- `derivedSlideCount` within `[minSlides, maxSlides]`
- Each entry in `requiredSections` literally present (heading or substring match, with limited synonyms)
- `maxBulletsPerSlide` respected (soft-warning only today)

Both categories feed a single `hardFailures` array that gates the Gamma call. A structurally sound deliverable that merely mislabels a section ("Overview" instead of "Executive Summary") is rejected identically to a prose-blob deliverable that Gamma physically cannot parse.

### 3.4 Revision loop lifecycle

Auto-revision in `orchestration.ts:1088-1220` gates on:

```ts
const baseRevisionCount = ((order.gccMemory as any)?.["gcc.metadata"]?.revisionAttempts || 0);
const canAutoRevise = controlMode === "aiden" && baseRevisionCount < maxAutoRevisions && hasLlm;
```

`maxAutoRevisions = 4`. `revisionAttempts` is persisted to `gccMemory` at each revision increment and **survives reopen**. An operator who reopens a WO that already consumed 4 revisions during its first life cycle receives zero revision budget — the WO will hit preflight once and permanently block, with no observable explanation beyond a preflight checklist item.

### 3.5 Reopen semantics

Reopen is exposed via the UI and creates a new `iteration` marker in the 2DO checklist. It resets `status` to `awaiting_tier1_gate` (or similar) but does not touch `gccMemory`. This is intentional (preserves audit history) but causes §3.4 behavior.

### 3.6 Stuck-WO observability

When a WO stops advancing, the operator can see:

- 2DO Checklist events (including "preflight failed")
- Work Order status field (`blocked`, `awaiting_operator`, `failed`, `completed`)
- Execution logs (JSON metadata, not surfaced in UI by default)

There is no single view that answers **"why is this WO not moving forward, and what is the operator's next action?"** in machine-readable form. Operators must cross-reference template registry, revision counter, and preflight output manually to diagnose.

---

## 4. Root-cause design gaps

Numbered so downstream artifacts (tickets, PRs, test cases) can reference them.

### GAP-1 — Preflight conflates structural gating and contract semantics

A structural failure ("not parseable") and a contract failure ("section X missing") deserve different responses. Today both route to the same hard-fail path, both block the Gamma API call, and both have the same silent-stop effect when combined with `template_locked`.

### GAP-2 — `template_locked` encodes two orthogonal decisions

Identity-lock and fallback-veto are independent operator intents. Coupling them in a single enum makes "locked but gracefully degrading" impossible to express.

### GAP-3 — Revision counter life-cycle is reopen-unsafe

Carrying `revisionAttempts` across explicit operator reopens violates the operator's mental model. A reopen is a fresh authorization to try, not a continuation of the prior failed automation.

### GAP-4 — Two Gamma call paths drift independently

`nodePostProcess()` and `postProcessWorkflowDeliverable()` each encode their own preflight/fallback flow. History (BUG-039) shows this produces behavior gaps as one path is updated while the other is not. There is no shared choke-point for Gamma delivery.

### GAP-5 — Contract enforcement is literal + string-based

`requiredSections` match requires the literal phrase as a heading or substring. The synonym table is incomplete (`SECTION_SYNONYMS` in `pptx-quality.ts:153`) and always will be. LLMs produce semantically-correct-but-labeled-differently output that gets rejected.

### GAP-6 — No operator-facing stuck-WO diagnosis

Machine-readable diagnosis of "this WO is stuck because of X, and your next move is Y" does not exist. Operators diagnose by reading code.

---

## 5. Universal solution — phased roadmap

All phases are non-destructive and additive. Each can ship independently. No phase requires a new DB table.

### Phase A — Unified Gamma Delivery Pipeline (addresses GAP-4)

**Goal:** one function owns all Gamma delivery. Both current entry points call it.

Extract a `runGammaDelivery(input: GammaDeliveryInput): Promise<GammaDeliveryOutcome>` helper in a new `server/gamma-delivery.ts`. Both `nodePostProcess()` and `postProcessWorkflowDeliverable()` become thin adapters that construct the input and consume the outcome. The helper is the single choke-point for:

- Preflight execution
- Template policy resolution
- Gamma API call + heartbeat + timeout
- Post-Gamma compliance check
- Local fallback decision (per §5 Phase C)
- Outcome record shape

**Benefit:** any future Gamma change touches one place. Path drift becomes impossible by construction.

**Risk:** moderate refactor. Tests must cover both entry points equivalently.

### Phase B — Preflight Semantic Split (addresses GAP-1, GAP-5)

**Goal:** structural gating blocks Gamma; contract enforcement informs revision.

Split `validatePptxPreflight()` into two phases:

1. `validateStructural(deliverable): StructuralResult` — empty, too-short, JSON, escaped-newlines, no-segmentation. Hard-fail → never call Gamma; route to operator with structural-error explanation.
2. `evaluateContract(deliverable, contract): ContractResult` — slide count, required sections, bullet density. Produces graded evidence (`satisfied[]`, `missing[]`, `uncertain[]`). Does not block Gamma.

The Gamma call proceeds whenever structural passes. Contract evidence is supplied to:
- The Aiden quality review supplement (already wired)
- The revision prompt (already wired via `enrichReviewWithPreflight`)
- The generated artifact's metadata banner (new)

**Semantic enrichment (optional Phase B.1):** contract-section matching can call a lightweight classifier LLM ("does this deliverable contain an executive summary?"). Fall back to literal match on LLM unavailable. This resolves GAP-5 without maintaining synonym tables.

**Benefit:** a well-structured deck that slightly mislabels sections no longer silent-stops. The operator gets a Gamma-rendered artifact with a "contract deviations" banner and can accept or trigger revision.

**Risk:** widens what reaches Gamma. Mitigation: explicit contract-failure banner on artifact + structured audit trail.

### Phase C — Template Mode Refactor (addresses GAP-2)

**Goal:** separate identity-lock from fallback-veto.

Introduce two boolean fields on the registry entry (can be computed from `mode` for backward compat, then deprecated):

- `templateSwapAllowed: boolean` — may the resolver substitute a format-matched alternative when the specified template is wrong format / missing?
- `localFallbackAllowed: boolean` — may we run the local converter on Gamma preflight/API failure?

Migration map:
- `mode: "template_locked"` → `templateSwapAllowed: false, localFallbackAllowed: false` (preserves current behavior)
- `mode: "flexible"` → `templateSwapAllowed: true, localFallbackAllowed: true`
- New: `mode: "locked_graceful"` → `templateSwapAllowed: false, localFallbackAllowed: true`

Local fallback always stamps artifact metadata with `{ gammaAttempted: boolean, fallbackUsed: true, gammaError?: string }` so operators know.

**Benefit:** operators can express "must use Klear template, but give me *something* if Gamma fails" — which is what most clients actually want.

**Risk:** low. Existing rows map cleanly.

### Phase D — Revision Lifecycle Cleanup (addresses GAP-3)

**Goal:** reopen = fresh revision budget.

On explicit operator reopen:
- Reset `gccMemory["gcc.metadata"].revisionAttempts = 0`
- Record the prior attempts as `gccMemory["gcc.metadata"].priorCycles: [{attempts, endedAt, reason}]` for audit
- Log a `Lifecycle: Reopen` execution log entry with the reset fact

On automatic retry (system-initiated): **do not** reset. Retries are continuations, not fresh authorizations.

**Benefit:** reopen behaves as operators expect. Prior audit trail preserved.

**Risk:** very low. Reopen is already operator-gated.

### Phase E — Stuck-WO Diagnosis API (addresses GAP-6)

**Goal:** one GET endpoint that returns a structured reason-not-advancing payload.

`GET /api/work-orders/:id/diagnosis` returns:

```json
{
  "status": "blocked_preflight_no_fallback",
  "summary": "Gamma preflight failed and template does not allow local fallback",
  "blockers": [
    { "code": "PREFLIGHT_CONTRACT_FAIL", "detail": "Required section 'executive summary' missing" },
    { "code": "TEMPLATE_FALLBACK_VETO", "detail": "Template 'klear_live_v1' is template_locked" },
    { "code": "REVISIONS_EXHAUSTED", "detail": "4/4 auto-revisions used" }
  ],
  "operatorActions": [
    { "code": "REOPEN", "label": "Reopen (resets revision budget)" },
    { "code": "SWITCH_TEMPLATE", "label": "Switch to flexible template" },
    { "code": "ACCEPT_AS_IS", "label": "Complete WO with current markdown only" }
  ]
}
```

UI surfaces blockers and operatorActions as cards on the WO detail page. Every "stuck" state in IWO2 routes through a standard code enum that the UI renders consistently.

**Benefit:** operators stop diagnosing by reading code. First-class observability.

**Risk:** requires a diagnosis registry (enum + human strings) that must be kept in sync with actual stuck states. Mitigate with a compile-time check or test.

### Phase F — Contract Format Migration (deferred; addresses GAP-5 long-term)

**Goal:** structured JSON contracts replace freeform text.

Move `gammaTemplates.contentContract` from freeform text to structured JSON with schema validation. Shared parser consumed by both the Gamma input prompt and the preflight. Eliminates parser drift between "what the contract says" and "what preflight enforces."

**Deferred** until Phase B is in place — Phase B removes the pressure on literal matching. Phase F is a cleanup, not a blocker.

---

## 6. Dependency and sequencing

```
Phase A (unified delivery) ──┬─→ Phase B (preflight split) ──→ Phase F (contract JSON)
                             │
                             ├─→ Phase C (mode refactor)
                             │
Phase D (revision lifecycle) ┴─→ Phase E (stuck-WO diagnosis)
```

**Recommended order to ship:** D → C → A → B → E → F.

- **D first** because it's a one-line high-impact fix that unblocks the operator's current workflow (reopen restores revision budget).
- **C second** because `locked_graceful` mode lets operators opt out of the current silent-stop failure mode without any other change.
- **A third** to establish the single choke-point before B/E add more logic.
- **B fourth** to solve the over-enforcement root cause.
- **E fifth** to surface the new structured diagnosis to operators.
- **F last** when pressure on the contract format justifies the migration effort.

---

## 7. Acceptance criteria (whole-initiative)

Implementation across all phases is complete when all of these hold:

1. No code path from WO acceptance to artifact filing reaches a `return` statement that silently stops progress without an execution log entry whose `metadata` includes a `diagnosisCode`.
2. A structurally sound deliverable that deviates from the content contract is Gamma-rendered and filed, with the contract deviations surfaced as artifact metadata and an operator acknowledgment flow.
3. A structurally malformed deliverable (empty, prose blob, JSON, escape characters) never reaches Gamma and stops with a `PREFLIGHT_STRUCTURAL_FAIL` diagnosis.
4. Reopening a WO always restores revision budget; retries do not.
5. Both the single-WO and workflow Gamma paths route through a single `runGammaDelivery()` helper.
6. The stuck-WO diagnosis endpoint returns a structured payload for every known stuck state, and the UI renders it.
7. Template operators can express "locked template, local fallback allowed" without editing code.

---

## 8. Migration safety

### 8.1 Patches already shipped today (2026-04-18) — status under new architecture

| Patch | File | Fate under this architecture |
| ----- | ---- | ---------------------------- |
| `sectionPresent` cover-aliases | `pptx-quality.ts:180` | Keeps value through Phase B; may be superseded by classifier-based matching in B.1 |
| `OPTIONAL_BY_DEFAULT` expansion | `pptx-quality.ts:90` | Removed in Phase F once structured contracts land; kept during Phase B |
| `enrichReviewWithPreflight` | `pptx-quality.ts` + `orchestration.ts` | Keeps value permanently; becomes the revision-prompt builder for contract-fail evidence under Phase B |
| `resolveWorkflowGammaPolicy` | `pocketflow.ts` | Folded into Phase A's `runGammaDelivery`; the resolver logic is preserved, not re-authored |

**None of today's patches should be reverted.** They are compatible with the target architecture and reduce risk during the transition.

### 8.2 Backward compatibility

- Existing `gammaTemplates.mode` values continue to work. The new boolean flags are derived from `mode` when present; operators can override.
- Existing `contentContract` freeform text continues to work. The structured format (Phase F) is opt-in per template.
- Existing WOs with non-zero `revisionAttempts` are unaffected until an operator explicitly reopens them.
- The diagnosis endpoint is additive; the existing status field remains.

### 8.3 Rollout discipline

Each phase ships with:
- Test coverage (unit + at least one integration path)
- BUGFIX_LOG entry and CHANGELOG bump
- Smoke-test plan against the 3M Plan Deck WO or an equivalent known-failing WO

---

## 9. Risk register

| Risk | Probability | Impact | Mitigation |
| ---- | ----------- | ------ | ---------- |
| Phase B lets through weak content that used to be blocked | Medium | Medium | Contract deviations banner + audit trail + operator acknowledgment |
| Phase D enables infinite-revision operator abuse | Low | Low | Require a reopen reason; rate-limit reopens per WO |
| Phase A refactor introduces regressions in workflow path | Medium | High | Feature-flag the new path; shadow-run against existing logic for one sprint |
| Phase E diagnosis codes drift from actual stuck states | Medium | Low | Compile-time enum + test assertion per state |
| Classifier LLM in Phase B.1 is slow or unavailable | Low | Low | Literal match remains the fallback; classifier is enrichment |

---

## 10. Open questions for Architect review

1. **Is `runGammaDelivery` the right boundary?** Should it also own PDF delivery, or is PDF different enough to deserve its own helper? (Current opinion: same helper, `format` parameter.)
2. **Where does classifier-based section matching (Phase B.1) live?** A new sub-agent, a cached embedding service, or an inline LLM call in the preflight path? Tradeoff: latency vs. accuracy vs. cost.
3. **Should Phase D's reopen reset be configurable per WO type?** Some workspaces may want strict counter preservation even on reopen (regulated content).
4. **Is the diagnosis endpoint an HTTP route or a storage method?** HTTP is simpler; storage method composes better with existing `processWorkOrder`.
5. **Contract JSON schema (Phase F) — do we version it?** If yes, how do templates authored against v1 continue to work when v2 ships?

---

## 11. References

- `server/pocketflow.ts` — `nodePostProcess()` (1371), `postProcessWorkflowDeliverable()` (2294), `resolveWorkflowGammaPolicy()` (new today)
- `server/pptx-quality.ts` — `validatePptxPreflight()` (196), `sectionPresent()` (160), `enrichReviewWithPreflight()` (new today)
- `server/orchestration.ts` — quality review wiring (994-1016), auto-revision loop (1088-1220), workflow post-process call sites (2413, 2530)
- `server/gamma-client.ts` — `generateWithGamma()`, `pollGeneration()`, heartbeat plumbing (BUG-041)
- `BUGFIX_LOG.md` — BUG-037 through BUG-057 for delivery-path context
- `AIDEN_IWO2_GAMMA_PPTX_REMEDIATION_EXECUTION_PLAN_v0.1.0.md` — the preceding tactical plan; this brief extends rather than replaces it

---

_End of brief — Architect signoff requested before any Phase implementation begins._

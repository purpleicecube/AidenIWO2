# 2DO Checklist — Locked Specification v1.0.0

**Product:** AIDEN_IWO2
**Baseline version:** v0.9.5
**Status:** LOCKED — ready to execute (gated behind B+ hardening)
**Authored:** 2026-03-12
**Gate:** Phase C — P0 security + P1 auth/migration recommended before execution (owner override permitted)

---

## 1. Purpose

The 2DO Checklist provides a HITL-readable, deterministic lifecycle view of work in AIDEN_IWO2. It is a projection — not a separate data store. Raw logs remain the source of truth.

Two scopes exist:

| Checklist | Scope | Audience |
| --- | --- | --- |
| **WO Checklist** | Short HITL lifecycle of one work order | Operator, Aiden |
| **Workflow Checklist** | Boiled-down mission execution view across linked WOs and workflow loops | PM, Aiden |

---

## 2. Architecture — 3 Layers

```text
Layer 1 — Raw Truth
  execution_logs (append-only, never mutated)

Layer 2 — Normalization
  Server-side projection on read (NOT persisted)
  Derived deterministically from Layer 1

Layer 3 — Checklist Projection
  HITL-readable lines rendered from Layer 2
  WO Checklist or Workflow Checklist view
```

**Key constraint:** Normalization (Layer 2) runs as a server-side helper function invoked on demand. No `lifecycle_facts` field is persisted to the database in MVP. This eliminates a second write path, sync risk, and migration burden.

---

## 3. Data Sources

### WO Checklist

- `execution_logs` (primary — Layer 1)
- `work_orders` (envelope state)

### Workflow Checklist

- `workflow_executions` (workflow-level envelope)
- `workflow_step_runs` (step-level events)
- WO fact rollup (from WO Checklist projections for linked WOs)

---

## 4. Lifecycle Fact Vocabulary (Layer 2)

Constrained set. Derived deterministically from `execution_logs`. No LLM involvement.

| Fact | Trigger condition |
| --- | --- |
| `submitted` | WO created |
| `tier1_passed` | Tier 1 validation passed |
| `tier1_failed` | Tier 1 validation failed |
| `tier1_5_passed` | Tier 1.5 check passed |
| `tier1_5_failed` | Tier 1.5 check failed |
| `bdm_raised` | BDM block opened |
| `bdm_resolved` | BDM block resolved by operator |
| `tier2_started` | Tier 2 execution begun |
| `tier2_completed` | Tier 2 execution completed |
| `hitl_required` | HITL flag set |
| `hitl_resolved` | HITL resolved by operator |
| `gcc_started` | GCC memory call initiated |
| `gcc_completed` | GCC memory call completed |
| `completed` | WO terminal success state |
| `failed` | WO terminal failure state |
| `cancelled` | WO cancelled |

---

## 5. WO Checklist Line Rules

Each lifecycle fact maps to at most one checklist line. Rules:

- Lines are ordered chronologically by event timestamp.
- Each line carries: `fact`, `timestamp`, `status` (`done` / `blocked` / `pending`), and optional `loop_count`.
- No free-text LLM content in checklist lines (MVP).
- `Aiden Note` (see Section 7) is separate and does not affect line status.

---

## 6. Loop Collapse Rules

Internal retries are noise. Milestone-crossing loops are signal.

| Condition | Visibility |
| --- | --- |
| First internal retry (same tier, no block, no PM/Aiden direction) | Hidden |
| Second pass of same tier | Visible |
| Any PM/Aiden-directed re-run | Visible |
| Any loop that caused or resolved a block | Visible |

---

## 7. Workflow Checklist — Iteration Tracking

Per-step and per-WO rollup shows:

```text
objective progress | blocking state | loop count
```

- **Objective progress:** What the workflow is trying to accomplish at this point — not just step position.
- **Blocking state:** Whether the step/WO is currently blocked and why (BDM, HITL, error).
- **Loop count:** Number of visible iterations (collapsed per rules in Section 6).

`N of M` step position alone is insufficient for PM/Aiden-directed looped execution and is not used as the sole tracking dimension.

---

## 8. Aiden Annotation

Aiden has no authority to write checklist lines in MVP.

If contextual notes are needed, Aiden may write an `Aiden Note`:

- Stored separately from checklist lines (separate field or table column — TBD at implementation).
- Clearly labeled as `Aiden Note` in the UI.
- **Excluded entirely from status logic and iteration logic.**
- Optional. Not required for checklist completeness.

---

## 9. What Checklists Are Not

- Not a task list for Aiden or operators to act on (that is the WO itself).
- Not a log (that is `execution_logs`).
- Not a persisted audit record (projection only — regenerated on read).
- Not an LLM output surface.

---

## 10. Gate and Sequencing

This feature is **Phase C** in the B+ Hardening Plan.

| Phase | Scope | Recommended before 2DO work begins |
| --- | --- | --- |
| Phase A (P0) | Security hardening | Recommended |
| Phase B (P1) | Auth + migration | Recommended |
| Phase C | 2DO Checklist + HITL enhancements | This spec |

**Default assumption:** Phase A and Phase B complete before Phase C begins.

**Override:** Execution may be authorized before A and/or B are complete at owner discretion. If executing early, note the open exposure in the implementation kickoff and flag any 2DO features that interact with auth or security surfaces — those sub-items should be sequenced last within Phase C.

---

## 11. Open Implementation Questions (resolve at Phase C kickoff)

1. `Aiden Note` storage: separate column on `work_orders` / `workflow_executions`, or a new `aiden_notes` join table?
2. Projection caching: serve fresh on every read (MVP default) or add a short TTL cache for high-frequency polling?
3. Workflow Checklist UI: inline within workflow detail page, or separate panel?

---

*Spec locked 2026-03-12. Changes require explicit revision and version bump.*

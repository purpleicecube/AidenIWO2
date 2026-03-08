# AIDEN IWO B+ Hardening Plan (MVP to Production for SMB)

| Property | Value |
| --- | --- |
| Artifact | AIDEN_IWO_BPLUS_HARDENING_PLAN |
| Version | 1.0.1 |
| Date | 2026-03-06 |
| Status | Published |
| Author | Codex (`#CDX`), amended by Claude Code |
| Tags | `#CDX` `#CDX-BPLUS` `#CDX-HARDENING` `#CDX-MEMORY` |
| Scope | MVP to Production for SMB deployments (local first, cloud-ready) |
| Depends On | `ROADMAP_FEATURES_v1.6.md`, AIDEN IWO v0.3.8 alpha |

---

## Objective

Move AIDEN_IWO from MVP to Production for SMB use (up to ~100 employees) without creating a heavy or slow operator experience.

Target grade: **B+** in security, reliability, and operational readiness.

---

## Success Criteria (Production Gate)

1. Security:
- `0` open Critical vulnerabilities.
- `0` open High vulnerabilities.
- No hardcoded credentials in runtime paths.
- No production debug/exec routes that allow arbitrary command behavior.

2. Authority + Policy:
- Tier authority enforced at runtime:
  - Tier 1: `CONTEXT`, `COMMIT`, `BRANCH`, `MERGE`
  - Tier 2: execution only, no `MERGE`
- All cross-agent dependencies route through Tier 1 (no Tier2->Tier2 direct chaining).

3. Reliability:
- Deterministic fallback behavior if LLM output is malformed/timeout.
- Idempotent retries for work order transitions and dispatch paths.
- Mandatory regression coverage for critical orchestration flows.

4. Performance:
- Tier 1 policy decision p95 <= 1.2s.
- Operator API p95 <= 600ms for non-LLM endpoints.
- Typical work order end-to-end p95 <= 30s (phase-1 production target).

5. Operability:
- Health/readiness/metrics enabled.
- Incident audit trail reconstructable for each work order.
- Rollback path documented for each deploy.

---

## Phased Plan

## Phase P0: Security and Authority Hardening (Blocker for Production)

### P0.1 Security Closure
- Remove or disable authentication bypass classes in production.
- Remove static backup admin pattern; replace with bootstrap admin + forced credential rotation.
- Ensure tool/API secrets are never returned in responses or written to GCC logs.
- Lock preview and sandbox paths with safe rendering and strict policy checks.
- Disable dangerous debug/exec behavior outside explicit non-production mode.

### P0.2 Runtime Policy Enforcement
- Enforce GCC authority model in API and orchestration runtime.
- Add explicit deny-by-default policy middleware for sensitive routes.
- Add policy tests for Tier violations and forbidden command paths.

### P0.3 Security Release Gates
- Add mandatory security regression suite:
  - auth bypass tests
  - secret leakage tests
  - preview/sandbox abuse tests
  - tier authority tests
- Deploy blocked unless suite passes.

---

## Phase P1: Reliability and Determinism

### P1.1 Contract Lock
- Versioned work-order envelope shared by Tier 1, Tier 1.5, Tier 2, and HITL.
- Compatibility adapter for legacy payloads.

### P1.2 Deterministic Orchestration Guardrails
- Idempotency keys for state-changing operations.
- Deterministic fallback scoring path when LLM evaluation fails.
- Max-revision safeguards with explicit escalation outcomes.

### P1.3 Test Coverage for B+ Reliability
- Add focused tests for:
  - plan/delegate/iterate/evaluate/approve loop
  - BDM escalation and resolution
  - workflow PM revise/escalate loops
  - reopen/retry/revision behavior

### P1.4 Memory Advisor Abstraction Boundary
- Define `MemoryAdvisor` interface in shared types:
  - `recall(context): Promise<AdvisoryMemory[]>` — advisory context before Tier 1 evaluation
  - `store(event): Promise<void>` — record outcome patterns after completion/failure
- Default implementation: `NoOpMemoryAdvisor` — zero runtime behavior change, zero new dependencies.
- Wire two hook points in `orchestration.ts`:
  - Before Tier 1 LLM evaluation: inject advisory recall as soft context
  - After work order terminal state (completed/failed): store outcome pattern
- Add `memoryAdvisor: "none" | "muninn"` feature flag to operational settings schema.
- GCC remains authoritative — `MemoryAdvisor` is strictly advisory, never writes to or reads from the GCC commit chain.
- Future drop-in: implement `MuninnMemoryAdvisor` via existing `mcp-client.ts`, flip flag in local installer profile. No other changes required.

> **Rationale:** Preserves the option to integrate MuninnDB for local SMB installs without blocking core hardening. 2-3 hours of work now prevents a retrofit into hardened orchestration code later.

---

## Phase P2: GCC Command Semantics and Memory Maturity

### P2.1 Make BRANCH/MERGE First-Class
- Keep `COMMIT` and `CONTEXT` as canonical.
- Implement lightweight logical `BRANCH` and policy-gated `MERGE` (`append|summarize|replace`).
- Require merge rationale and quality snapshot for audit.

### P2.2 Audit Trail Completeness
- Every workflow/work-order state change emits immutable command/event record.
- Ensure HITL decisions include actor, timestamp, rationale, and impact.

### P2.3 Optional Memory Add-On (Local) — MuninnDB Integration
- Implement `MuninnMemoryAdvisor` using the `MemoryAdvisor` interface defined in P1.4.
- Wire to MuninnDB via existing `mcp-client.ts` MCP connection (MuninnDB is MCP-native).
- GCC remains authoritative source of truth; MuninnDB is advisory only.
- Feature flag and installer profile (flag defined in P1.4, implementation delivered here):
  - `core` (GCC only, `memoryAdvisor: "none"`)
  - `core+muninn` (GCC + Muninn advisory memory, `memoryAdvisor: "muninn"`)
- Validate MuninnDB stability and production readiness before enabling by default in any profile.

---

## Phase P3: SMB Production Packaging

### P3.1 Deployment Profiles
- Local profile (single-node, secure defaults).
- Cloud-ready profile (same policy controls, externalized secrets, migration-safe).

### P3.2 Operations Bundle
- Versioned migrations mandatory.
- Backup/restore runbook.
- Incident response runbook.
- Key rotation and audit review SOP.

### P3.3 UX Protection Rule
- No major workflow UI redesign in hardening phases.
- Progressive disclosure for advanced controls (branch/merge/audit deep views).
- Keep default operator path fast and minimal.

---

## Non-Negotiables

1. GCC is canonical memory and authority ledger.
2. Security closure precedes feature-surface expansion.
3. New integrations (external MCP, sandbox expansion, plugin marketplace) must pass P0/P1 gates first.
4. Production deploy requires green gates, not manual exception.

---

## Exit Definition: B+ Ready

AIDEN_IWO is B+ production-ready when:

- P0 and P1 are fully complete and verified.
- P2 branch/merge semantics are operational or explicitly feature-flagged off with no policy violations.
- Performance targets are met in representative SMB workloads.
- Security and reliability gates are automated and enforced in CI/CD.

---

## Revision Log

| Version | Date | Changes |
| --- | --- | --- |
| 1.0.0 | 2026-03-06 | Initial published B+ hardening plan for MVP to production (SMB). `#CDX` |
| 1.0.1 | 2026-03-06 | Added P1.4 Memory Advisor Abstraction Boundary. Moves interface + hook points + feature flag to P1 scope. P2.3 MuninnDB integration now implements the P1.4 interface rather than starting from scratch. Rationale: preserves clean MuninnDB drop-in for local SMB installs without blocking hardening. Amended by Claude Code. |

# ADR-012 — Output packages + adapter registry + handoff provenance

Date: 2026-04-19
Status: Accepted (Loop 3 Phase 2, with non-Gamma-shaped contract guardrail from Darrel/CODEX approval memo)
Deciders: AI, OA, WR (per `IWO3_LOOP_3_APPROVAL_DECISIONS_v0.1.0.md` §ADR-012 + Cross-loop Guardrails)

## Context

Loop 3 Phase 2 lands the **back edge** of IWO3 (per ADR-004 two-polished-edges principle): the typed output envelope that leaves WO/WF, the per-tenant adapter registry that routes it, the per-tenant approval policy that gates it, and the 13-field handoff provenance that makes any future audit question answerable.

The approval memo guardrail is explicit: **the adapter registry contract must not be Gamma-shaped.** If the schema or registry code reads as if it was written around Gamma's fields specifically, the first non-Gamma adapter (email, Drive, Figma, Stitch, Claude Design, CRM) breaks it. The Loop 3 Phase 2 schema is deliberately adapter-agnostic; Phase 3.4 implements Gamma as a test-double to prove the contract, then Loop 10 adds real adapter calls.

## Decision

### Eight new Drizzle tables, all `iwo3_native / drizzle` under `LOOP_3_VERSION = iwo3@v0.3.0-loop3`

| Table | Purpose |
| --- | --- |
| `adapter_catalog` | Global list of adapter kinds. Tenant-agnostic. Seeded with seven (Gamma, Google Drive, email_campaign, Figma, Stitch, Claude Design, CRM) across four categories (`design_render`, `storage`, `campaign`, `crm`, `other`). |
| `adapter_actions` | What each adapter can do: `generate`, `render_from_template`, `export_pptx`, `export_pdf`, `upload`, `publish_share`, `compose`, `test_send`, `send`, `publish`, `create_record`, `update_record`, `delete_record`. Unique per `(adapter_catalog_id, action_key)`. |
| `client_adapter_configs` | Per-tenant enable/configure for a catalog adapter. Carries `credential_ref` placeholder; raw secrets never here. Unique per `(client_id, adapter_catalog_id)`. |
| `adapter_action_policies` | Per-tenant, per-`(adapter, action)` approval gate. Mode enum: `none | approval_required | disallowed`. Row missing → default `none`. Unique per `(client_id, adapter_catalog_id, action_key)`. |
| `adapter_credentials` | Per-tenant credential-ref row with rotation metadata. Always a reference, never raw secret. |
| `output_packages` | Typed output envelope. `output_kind` discriminant + `content_blocks` jsonb payload. Tenant-scoped. Source-of-execution via `work_order_id` or `workflow_execution_id`. |
| `output_handoffs` | 13-field provenance record (CODEX §5) + minimal candidate-review shape per approval memo §Q5: `candidate_group_id`, `candidate_status`, `selected_at`, `selected_by_user_id`. |
| `external_execution_results` | Result payload the external system returned for a submitted handoff. Many-to-one on `output_handoffs` (an adapter may report started + completed). |

### Adapter-agnostic contract shape (non-Gamma guardrail)

- `output_kind` is an enum of eleven values covering Gamma PPTX/PDF, sandbox PPTX/PDF, email campaigns, Drive uploads, CRM mutations, Figma / Stitch / DESIGNLAB handoffs, and `generic`. Adding new kinds is an enum ALTER, not a schema rewrite.
- `content_blocks` is `jsonb` — each `output_kind` interprets it differently. The schema knows nothing about Gamma's slide structure or email's audience fields specifically.
- `adapter_catalog` is a lookup table, not a set of adapter-specific columns.
- `adapter_actions.action_key` is free-form varchar; actions outside today's list are allowed by adding rows, not ALTERs.
- `adapter_action_policies` resolves by `(client_id, adapter_catalog_id, action_key)` — no adapter-specific branching logic in schema.
- `output_handoffs` 13 fields stay the same regardless of adapter: client_id, deployment_id, work_order_id, workflow_id, execution_cycle_id, output_package_id, adapter_catalog_id (= adapter_id), template_profile_id, external_destination, external_reference, status, handoff_payload_ref, result_payload_ref, correlation_id.

If a future adapter truly cannot fit this shape (e.g. a streaming destination with no single handoff record), an ADR amendment captures the exception.

### Candidate-review minimal shape (hybrid per §Q5)

`output_handoffs` carries four candidate fields in Phase 3.2:

- `candidate_group_id uuid nullable` — groups candidates submitted together.
- `candidate_status enum` — `not_candidate | candidate | selected | rejected | finalized`.
- `selected_at timestamptz nullable`.
- `selected_by_user_id uuid nullable FK → users`.

Loop 6 layers the operator-facing request-more / reject-all / cancel behavior on top of these fields. Phase 3.2 does not write any candidate logic; fields persist shape only.

### Policy resolver (TS)

`packages/contracts/adapter/policy_resolver.ts` ships a pure SQL-lookup:

```ts
resolveAdapterPolicy(client, { clientId, adapterKey, actionKey })
  → { mode, policyRowId, reason }
```

Callers interpret `mode`:

- `none` → proceed.
- `approval_required` → attach an approval_ref before submit (approval workflow lives in Loop 4+).
- `disallowed` → hard reject; audit with `adapter_policy.disallowed` metadata; return an error.

Every adapter invocation in Loop 3+ **must** call `resolveAdapterPolicy` before running the adapter — this is a lint-rule candidate (P06 closure path).

### Tenant isolation

Every client-owned table carries `client_id` NOT NULL. Tenant filters follow the canonical service-layer JOIN pattern:

```sql
JOIN client_memberships m ON m.client_id = <table>.client_id AND m.status = 'active'
JOIN users u ON u.id = m.user_id AND u.status = 'active'
WHERE u.email = $1
```

Three integration tests prove the invariant for `output_packages`, `client_adapter_configs`, and the adapter-policy resolver. `adapter_catalog` is deliberately tenant-agnostic — it is a platform-level lookup, not client-owned data.

RLS defers to Loop 4 (approval memo §Q1).

### Audit vocabulary (Phase 3.2 locked)

18 new events in `LOOP_3_PHASE_2_AUDIT_EVENTS`:
- `output_package.created | validated | submitted | rejected`
- `output_handoff.created | submitted | completed | failed`
- `output_candidate.selected | rejected`
- `adapter_config.created | updated | enabled | disabled`
- `adapter_credential.rotated | revoked`
- `adapter_policy.created | updated`

## What Loop 3 Phase 2 does NOT do

- **No adapter implementations.** Phase 3.4 ships the Gamma test double; Loop 10 ships live adapters.
- **No approval workflow.** `approval_required` mode is recorded; the approval flow (who approves, UI, sign-off provenance) is Loop 4+ scope.
- **No candidate-review operator flow.** Fields persist; Loop 6 ships the flow.
- **No FastAPI routes.** Loop 7.
- **No RLS.** Loop 4.

## Enforcement

- `infra/local/manifest-populate.ts` registers all eight Phase 3.2 tables under `LOOP_3_VERSION`.
- `tests/integration/migration-ownership.test.ts` asserts the Phase 3.2 schema classification.
- Three tenant-isolation tests (`tenant-output-package-isolation`, `tenant-adapter-config-isolation`, `adapter-policy-resolution`) cover the invariants.
- `packages/contracts/adapter/policy_resolver.ts` is the only sanctioned policy-lookup path.

## Alternatives considered

- **Gamma-specific `gamma_render_payload` column on `output_packages`.** Rejected per the explicit guardrail — breaks on first non-Gamma adapter.
- **Single `output_events` table instead of handoff + result split.** Rejected — the 13-field provenance record needs to be a single stable row per handoff for query simplicity; result rows extend (many-to-one) rather than duplicate.
- **Policy as part of `client_adapter_configs.config` jsonb.** Rejected — per-action resolution would require JSON path lookups on every invocation; a first-class `adapter_action_policies` table indexes cleanly.
- **CRM disallowed via code rather than data.** Rejected — approval memo §Q5 + CODEX response packet explicitly called for data-driven policy ("Do not hard-code the approval list"). CRM disallowal is seeded rows, not code branches.
- **Candidate review as its own `output_candidates` table.** Kept as a Loop 6 option. Phase 3.2 uses the minimal four-column shape on `output_handoffs` to avoid bloating Phase 3.2 per approval-memo hybrid guardrail.

## Consequences

- Phase 3.3 (DigiFLOW intake) consumes this schema: an intake packet routes to a WO/WF, which produces an `output_package`, which submits via the adapter registry.
- Phase 3.4 (Gamma test double) is the contract test. If Gamma test-double can round-trip a package through the registry + policy + handoff + result path, the contract is proven.
- Loop 4 adds RBAC permissions that the policy resolver can layer on (`permission:adapter.<adapter_key>.<action_key>`).
- Loop 6 adds the candidate-review operator flow + state transitions.
- Loop 10 replaces the Gamma test double with a live call + adds the other six real adapters.

## Revisit triggers

- First non-Gamma adapter lands (Loop 10) and reveals a contract shape gap. Amend this ADR + emit a schema migration.
- Candidate-review operator flow reveals that the four minimal fields on `output_handoffs` are insufficient — migrate to a dedicated `output_candidates` table and mark these four fields `@deprecated`.
- Adapter policy gains a fourth mode (e.g. `rate_limited`). Amend the `adapter_policy_mode` enum.

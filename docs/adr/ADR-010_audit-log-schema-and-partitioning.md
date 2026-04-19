# ADR-010 — Audit log schema + monthly partitioning

Date: 2026-04-19
Status: Accepted (Loop 2 Phase 1, partitioning deferred to Phase 1.5)
Deciders: AI, DR (per `IWO3_LOOP_2_SCOPE_PROPOSAL_v0.1.0.md` §2.4, approval memo §Q4, CODEX §10 audit retention)

## Context

Loop 2 introduces `action_audit_log` as the first real privileged-action audit table in IWO3 (the existing IWO2 `execution_logs` is tier-action-scoped, not privileged-action-scoped).

CODEX §10 locked two commitments:

1. **Retention is indefinite** — logs are a business-value feature, not just compliance. Never delete canonical history.
2. **Monthly partitioning** — so the table stays queryable even after years of accumulation, and cold-archive storage can be added later per partition.

The Loop 2 approval memo §Q4 locked a third:

3. **Loop-2-only event vocabulary** — register only the events Loop 2 emits; grow additively.

This ADR records the schema, vocabulary discipline, and the partitioning plan, and explains why partitioning **does not ship in Loop 2 Phase 1** (but does ship before Loop 3 writes its first real operational audit row).

## Decision

### Table schema

```text
action_audit_log
  id            bigserial PK
  client_id     uuid NOT NULL  FK -> clients.id
  actor_user_id uuid nullable  FK -> users.id (ON DELETE SET NULL)
  action        varchar(128) NOT NULL
  target_type   varchar(64)
  target_id     varchar(128)
  metadata      jsonb
  created_at    timestamptz NOT NULL
  INDEX (client_id, created_at DESC)
```

See `db/schema/action_audit_log.ts`. Registered in the manifest as `iwo3_native / drizzle` under `LOOP_2_VERSION`.

### Event vocabulary (Loop 2-only, grows additively)

Source of truth: `packages/contracts/audit/events.ts` (`AUDIT_EVENTS` record).

Events registered in Loop 2:

- `prompt_profile.created`
- `prompt_profile_version.created`
- `prompt_profile_version.published`
- `prompt_profile_version.deprecated`
- `prompt_override.applied` (Loop 2 Phase 2 — resolver)
- `repository_binding.created`
- `repository_binding.credential_rotated`
- `repository_binding.revoked`
- `data_source_binding.created`
- `data_source_binding.revoked`
- `artifact.uploaded`
- `artifact.deleted`

Loop 3+ loops add their own event names in additive patches to `AUDIT_EVENTS`.

### Transaction discipline

Every privileged action that mutates a client-owned row must insert a `action_audit_log` row **in the same database transaction**. The Loop 2 Phase 2 tenant-isolation test suite (`audit-log-invariant.test.ts`) asserts this: for each mutation covered by the Loop 2 event vocabulary, there must be a matching audit row with the correct `client_id`.

No privileged mutation ships without a matching audit-row writer.

### Monthly partitioning — deferred to Phase 1.5

Loop 2 Phase 1 creates `action_audit_log` as a **regular table**, not yet partitioned. Reasoning:

1. Loop 2 Phase 1 writes zero audit rows from seeds. Runtime rows accumulate only once Phase 2 lands the resolver override path and repository/artifact CRUD handlers.
2. Drizzle's DDL generator does not natively emit `PARTITION BY RANGE (created_at)` declarations.
3. Converting a populated table to a partitioned table mid-flight is costly; doing it while the table is empty is trivial.

Phase 1.5 (before Loop 3 writes its first real WO/WF audit row) ships a raw-SQL Drizzle migration that:

- Renames `action_audit_log` → `action_audit_log_legacy` (in case Phase 2 has produced any dev rows).
- Creates a new `action_audit_log` partitioned by `RANGE (created_at)` with monthly partitions for the current and next month.
- Copies any `_legacy` rows into the partitioned version.
- Adds a `ensure_next_month_partition()` helper invoked by the audit writer if the next month's partition is missing.

The `KNOWN_TABLES` entry in `manifest-populate.ts` stays the same — partitioning is implementation detail; the `information_schema.tables` check sees `action_audit_log` as one logical table.

### Retention policy

Indefinite. No automatic deletion. Cold-archive to object storage is allowed per-partition in a future loop; the canonical partition stays in Postgres until explicitly detached (and even then its rows are preserved in archive).

## Consequences

- Every Loop 2+ privileged-action writer must emit an event from `AUDIT_EVENTS`. String-literal event names are disallowed outside the `AUDIT_EVENTS` record (lint rule added in Phase 2).
- `audit-log-invariant.test.ts` (Phase 2) is the regression gate.
- Partitioning is a scheduled Phase 1.5 deliverable, not optional — it must land before Loop 3 begins writing operational audit rows.
- Client-scoped queries against the audit log use the `(client_id, created_at DESC)` index; once partitioned, they pruning-eligible on `created_at`.

## Alternatives considered

- **Partition from day one in Phase 1.** Rejected — no rows to protect, and Drizzle-kit can't express partitioning natively. Better to do it in a raw-SQL migration close to when it matters.
- **Daily partitioning.** Rejected — too fine-grained for IWO3's expected volume; monthly gives cheap pruning without partition explosion.
- **Separate audit database.** Rejected — destroys the ability to join audit rows against the entities they describe.
- **Append-only WAL-style log with no schema.** Rejected — loses queryability; support workflows need structured lookups.

## Revisit triggers

- Phase 1.5 partitioning migration lands; this ADR is amended to move the deferral language into the changelog.
- Audit-log volume exceeds ~10M rows/month and monthly granularity becomes too coarse.
- Regulatory requirement forces encrypted-at-rest or external audit store (would need a separate ADR).

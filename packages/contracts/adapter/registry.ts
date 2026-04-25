/**
 * Loop 3 Phase 4 — adapter registry dispatcher.
 *
 * Single entry point for sending an OutputPackage to an adapter. Executes
 * the CODEX §7 runtime lookup:
 *
 *   1. Resolve client / adapter config / credential / template.
 *   2. Resolve approval policy (`none | approval_required | disallowed`).
 *   3. Get the adapter instance from the registry.
 *   4. Let the adapter validate the package.
 *   5. Submit the package → external_reference.
 *   6. Write `output_handoffs` (13-field provenance per CODEX §5).
 *   7. Poll/fetch result → `external_execution_results` row.
 *   8. Every step emits an `adapter_dispatch.*` audit row.
 *
 * Pure TS; adapter impls are pluggable (Gamma test-double in Loop 3,
 * live adapters in Loop 10). No secrets in this file; credentials are
 * resolved via their `credential_ref` pointer.
 */

import type { PoolClient } from "pg";

import { AUDIT_EVENTS } from "../audit/events";
import { writeAuditRow } from "../audit/writer";
import { resolveAdapterPolicy } from "./policy_resolver";
import { PermissionDenied, requirePermission } from "../authz/require_permission";
import type { AdapterContract } from "./types";
import { decideLiveGate } from "./dispatch_gating";
import { gammaTestDouble } from "../../adapters/gamma/adapter";
import { gammaLive } from "../../adapters/gamma/live_adapter";
import { GammaAdapterError } from "../../adapters/gamma/live_adapter";
import type { OutputPackage } from "../../../db/schema/output_packages";

// ──────────────────────────────────────────────────────────────────────
// Registry
// ──────────────────────────────────────────────────────────────────────

// Loop 9 Phase 9.2 — the Gamma slot is bound to the live adapter only
// when `GAMMA_LIVE_ENABLED === "true"`. Absent that opt-in we keep the
// Loop 3 test-double so every Loop 3/4/5/6 test continues to pass with
// no external network calls. The live-gate in `dispatch_gating.ts` is
// belt-and-suspenders for the same invariant.
const gammaAdapter: AdapterContract =
  process.env.GAMMA_LIVE_ENABLED === "true" ? gammaLive : gammaTestDouble;

const ADAPTER_REGISTRY = new Map<string, AdapterContract>([
  [gammaAdapter.adapterKey, gammaAdapter],
  // Loop 10 adds Drive, email_campaign, Figma, Stitch, Claude Design, CRM
  // (each with its own test-double or live implementation).
]);

export function getAdapter(adapterKey: string): AdapterContract | null {
  return ADAPTER_REGISTRY.get(adapterKey) ?? null;
}

/**
 * Test-only registry override. Lets integration tests swap an adapter
 * instance (e.g. a `GammaLiveAdapter` constructed with a mock fetch)
 * without reloading the module. Pass `null` to remove the key.
 */
export function __registerAdapterForTest(
  key: string,
  adapter: AdapterContract | null
): void {
  if (adapter === null) ADAPTER_REGISTRY.delete(key);
  else ADAPTER_REGISTRY.set(key, adapter);
}

// ──────────────────────────────────────────────────────────────────────
// Dispatch API
// ──────────────────────────────────────────────────────────────────────

export interface DispatchInput {
  clientId: string;
  adapterKey: string;
  actionKey: string;
  outputPackage: OutputPackage;
  actorUserId?: string | null;
  workOrderId?: string | null;
  workflowId?: string | null;
  executionCycleId?: string | null;
  deploymentId?: string | null;
  /**
   * If policy mode is `approval_required`, callers must attach an approval
   * reference here to proceed. Loop 4+ replaces this with an approval
   * workflow; Loop 3 accepts any non-empty string as evidence the approval
   * was recorded upstream.
   */
  approvalRef?: string;
  correlationId?: string;
}

export type DispatchResult =
  | {
      status: "completed";
      handoffId: string;
      externalReference: string;
      resultPayloadRef: string | null;
    }
  | { status: "permission_denied"; reason: string; role: string | null }
  | { status: "rejected_policy"; reason: string }
  | { status: "approval_required"; reason: string }
  | { status: "package_invalid"; errors: readonly string[] }
  | { status: "adapter_not_found"; adapterKey: string }
  // Loop 9 Phase 9.1 — dual first-live-invocation gate refusals.
  // All three refusals happen pre-submit — no outbound call is made.
  | { status: "live_disabled"; reason: string }
  | { status: "credential_missing"; reason: string }
  | { status: "first_invocation_pending"; reason: string }
  // Loop 9 Phase 9.2 — live Gamma submit-time refusals.
  // `credential_invalid` = Gamma rejected the key (401/403); distinct
  // from the pre-dispatch `credential_missing` (no DB row).
  // `rate_limited` = Gamma returned 429.
  | { status: "credential_invalid"; reason: string }
  | { status: "rate_limited"; reason: string }
  // Loop 9 Phase 9.4 (scope §3.4) — async polling in progress.
  // Submit succeeded but adapter is still rendering. Handoff stays in
  // `submitted` with poll-state metadata; callers advance via
  // `pollHandoffStatus` / `POST /output_handoffs/{id}/poll`.
  | {
      status: "pending_poll";
      handoffId: string;
      externalReference: string;
    }
  | {
      status: "failed";
      handoffId: string | null;
      errorMessage: string;
    };

interface DispatchAuditMetadataBase {
  adapterKey: string;
  actionKey: string;
  outputPackageId: string;
}

async function emitDispatchAudit(
  client: PoolClient,
  input: DispatchInput,
  event: (typeof AUDIT_EVENTS)[keyof typeof AUDIT_EVENTS],
  extra: Record<string, unknown> = {}
): Promise<void> {
  const metadata: DispatchAuditMetadataBase & Record<string, unknown> = {
    adapterKey: input.adapterKey,
    actionKey: input.actionKey,
    outputPackageId: input.outputPackage.id,
    ...extra,
  };
  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.actorUserId ?? null,
    event,
    targetType: "adapter_dispatch",
    targetId: input.outputPackage.id,
    metadata,
  });
}

async function recordHandoff(
  client: PoolClient,
  input: DispatchInput,
  fields: {
    status: string;
    externalReference: string | null;
    externalDestination: string | null;
    handoffPayloadRef: string | null;
  }
): Promise<string> {
  const { rows } = await client.query<{ id: string }>(
    `INSERT INTO output_handoffs
       (client_id, deployment_id, work_order_id, workflow_id,
        execution_cycle_id, output_package_id, template_profile_id,
        external_destination, external_reference, status,
        handoff_payload_ref, correlation_id, metadata)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::output_handoff_status,
             $11, $12, $13)
     RETURNING id`,
    [
      input.clientId,
      input.deploymentId ?? null,
      input.workOrderId ?? null,
      input.workflowId ?? null,
      input.executionCycleId ?? null,
      input.outputPackage.id,
      input.outputPackage.templateProfileId ?? null,
      fields.externalDestination,
      fields.externalReference,
      fields.status,
      fields.handoffPayloadRef,
      input.correlationId ?? null,
      JSON.stringify({ dispatched_by: "registry.dispatch" }),
    ]
  );
  return rows[0].id;
}

async function recordResult(
  client: PoolClient,
  handoffId: string,
  status: "success" | "partial" | "failed" | "unknown",
  payloadRef: string | null,
  errorMessage: string | null,
  metadata: Record<string, unknown>
): Promise<void> {
  await client.query(
    `INSERT INTO external_execution_results
       (output_handoff_id, status, payload_ref, error_message, metadata)
     VALUES ($1, $2::external_execution_result_status, $3, $4, $5)`,
    [handoffId, status, payloadRef, errorMessage, JSON.stringify(metadata)]
  );
}

async function resolveAdapterCatalogId(
  client: PoolClient,
  adapterKey: string
): Promise<string | null> {
  const { rows } = await client.query<{ id: string }>(
    `SELECT id FROM adapter_catalog WHERE adapter_key = $1 LIMIT 1`,
    [adapterKey]
  );
  return rows[0]?.id ?? null;
}

interface AdapterCredentialGateRow {
  id: string;
  credentialRef: string;
  firstInvocationConfirmedAt: string | null;
}

async function loadAdapterCredentialForGate(
  client: PoolClient,
  params: { clientId: string; adapterCatalogId: string }
): Promise<AdapterCredentialGateRow | null> {
  // Phase 4.4 lint gate: explicit client_id predicate on the read alongside
  // the Loop 4 Phase 3 RLS policy on adapter_credentials.
  const { rows } = await client.query<{
    id: string;
    credential_ref: string;
    first_invocation_confirmed_at: string | null;
  }>(
    `SELECT id,
            credential_ref,
            first_invocation_confirmed_at
       FROM adapter_credentials
      WHERE client_id = $1 AND adapter_catalog_id = $2
      ORDER BY created_at DESC
      LIMIT 1`,
    [params.clientId, params.adapterCatalogId]
  );
  const r = rows[0];
  if (!r) return null;
  return {
    id: r.id,
    credentialRef: r.credential_ref,
    firstInvocationConfirmedAt: r.first_invocation_confirmed_at,
  };
}

async function resolveTemplateExternalRef(
  client: PoolClient,
  params: { clientId: string; templateProfileId: string | null }
): Promise<string | null> {
  if (!params.templateProfileId) return null;
  const { rows } = await client.query<{ external_ref: string | null }>(
    `SELECT external_ref
       FROM template_profiles
      WHERE id = $1 AND client_id = $2`,
    [params.templateProfileId, params.clientId]
  );
  return rows[0]?.external_ref ?? null;
}

async function updateHandoffStatus(
  client: PoolClient,
  clientId: string,
  handoffId: string,
  status: string,
  resultPayloadRef: string | null
): Promise<void> {
  // Phase 4.4 lint gate: explicit client_id predicate on every update
  // to a tenant-scoped table, belt-and-suspenders with the Loop 3 PK
  // (handoff id) and the Loop 4 Phase 3 RLS policy.
  await client.query(
    `UPDATE output_handoffs
     SET status = $3::output_handoff_status,
         result_payload_ref = $4,
         updated_at = now()
     WHERE id = $1 AND client_id = $2`,
    [handoffId, clientId, status, resultPayloadRef]
  );
}

/**
 * Dispatch an OutputPackage through the adapter registry. The caller
 * owns the transaction — pass a PoolClient that has already BEGUN.
 * The dispatch emits multiple audit rows + one handoff row + one
 * external-execution-results row in the same transaction.
 */
export async function dispatchToAdapter(
  client: PoolClient,
  input: DispatchInput
): Promise<DispatchResult> {
  // Step 0 (Loop 4 Phase 2): authorization gate — every dispatch requires
  // an actor and the `output_package:submit` permission on the tenant.
  // Denials write an `authz.denied` audit row and return without touching
  // adapter_catalog / policy / handoff. This is additive to the existing
  // adapter_action_policy layer (Loop 3 Phase 2) — §Q4 `keep_both`.
  if (!input.actorUserId) {
    await writeAuditRow(client, {
      clientId: input.clientId,
      actorUserId: null,
      event: AUDIT_EVENTS.AUTHZ_DENIED,
      targetType: "adapter_dispatch",
      targetId: input.outputPackage.id,
      metadata: {
        adapterKey: input.adapterKey,
        actionKey: input.actionKey,
        permission: "output_package:submit",
        decision_reason: "no_actor",
        role: null,
      },
    });
    return {
      status: "permission_denied",
      reason: "dispatch requires an actor user id",
      role: null,
    };
  }

  try {
    await requirePermission(client, {
      userId: input.actorUserId,
      clientId: input.clientId,
      permission: "output_package:submit",
      targetType: "adapter_dispatch",
      targetId: input.outputPackage.id,
      metadata: {
        adapterKey: input.adapterKey,
        actionKey: input.actionKey,
      },
    });
  } catch (err) {
    if (err instanceof PermissionDenied) {
      return {
        status: "permission_denied",
        reason: err.message,
        role: err.role,
      };
    }
    throw err;
  }

  // Resolve the adapter catalog id up-front so we can set adapter_catalog_id
  // on output_handoffs. A missing catalog row aborts the dispatch.
  const adapterCatalogId = await resolveAdapterCatalogId(
    client,
    input.adapterKey
  );
  if (!adapterCatalogId) {
    return { status: "adapter_not_found", adapterKey: input.adapterKey };
  }

  // Step 1: initiated audit
  await emitDispatchAudit(
    client,
    input,
    AUDIT_EVENTS.ADAPTER_DISPATCH_INITIATED,
    { adapterCatalogId }
  );

  // Step 2: policy resolution
  const policy = await resolveAdapterPolicy(client, {
    clientId: input.clientId,
    adapterKey: input.adapterKey,
    actionKey: input.actionKey,
  });

  if (policy.mode === "disallowed") {
    await emitDispatchAudit(
      client,
      input,
      AUDIT_EVENTS.ADAPTER_DISPATCH_POLICY_REJECTED,
      { mode: policy.mode, reason: policy.reason }
    );
    return {
      status: "rejected_policy",
      reason: policy.reason ?? "adapter+action combination disallowed",
    };
  }

  if (policy.mode === "approval_required" && !input.approvalRef) {
    await emitDispatchAudit(
      client,
      input,
      AUDIT_EVENTS.ADAPTER_DISPATCH_APPROVAL_REQUIRED,
      { mode: policy.mode, reason: policy.reason }
    );
    return {
      status: "approval_required",
      reason: policy.reason ?? "adapter+action requires approval",
    };
  }

  // Step 3: adapter instance
  const adapter = getAdapter(input.adapterKey);
  if (!adapter) {
    await emitDispatchAudit(
      client,
      input,
      AUDIT_EVENTS.ADAPTER_DISPATCH_FAILED,
      { reason: "adapter instance not registered" }
    );
    return { status: "adapter_not_found", adapterKey: input.adapterKey };
  }

  // Step 3.5 (Loop 9 Phase 9.1) — live-dispatch gate.
  // Test-doubles (isLive=false) short-circuit inside decideLiveGate
  // without a credential lookup. Live adapters require:
  //   - envFlagName declared on describe()
  //   - process.env[envFlagName] === "true"
  //   - an adapter_credentials row for (client, adapter) with
  //     first_invocation_confirmed_at NOT NULL
  // Refusals emit a phase-locked audit event and return a typed
  // DispatchResult WITHOUT touching output_handoffs — no outbound
  // call was made and there is nothing to record as a failed submit.
  const description = adapter.describe();
  const envFlagName = description.envFlagName ?? null;
  const envFlagValue = envFlagName
    ? process.env[envFlagName] ?? null
    : null;
  let credentialRow: AdapterCredentialGateRow | null = null;
  if (description.isLive) {
    credentialRow = await loadAdapterCredentialForGate(client, {
      clientId: input.clientId,
      adapterCatalogId,
    });
  }
  const gate = decideLiveGate({
    isLive: description.isLive,
    adapterKey: input.adapterKey,
    envFlagName,
    envFlagValue,
    hasCredential: credentialRow !== null,
    credentialFirstInvocationConfirmedAt:
      credentialRow?.firstInvocationConfirmedAt ?? null,
  });
  if (!gate.allow) {
    const auditMeta = {
      gate_reason: gate.reason,
      gate_detail: gate.detail,
      ...(envFlagName ? { envFlagName } : {}),
    };
    switch (gate.reason) {
      case "live_disabled":
        await emitDispatchAudit(
          client,
          input,
          AUDIT_EVENTS.ADAPTER_DISPATCH_LIVE_DISABLED,
          auditMeta
        );
        return { status: "live_disabled", reason: gate.detail };
      case "credential_missing":
        await emitDispatchAudit(
          client,
          input,
          AUDIT_EVENTS.ADAPTER_DISPATCH_CREDENTIAL_MISSING,
          auditMeta
        );
        return { status: "credential_missing", reason: gate.detail };
      case "first_invocation_pending":
        await emitDispatchAudit(
          client,
          input,
          AUDIT_EVENTS.ADAPTER_DISPATCH_FIRST_INVOCATION_PENDING,
          auditMeta
        );
        return { status: "first_invocation_pending", reason: gate.detail };
    }
  }

  // Step 4: validate package
  const validation = adapter.validatePackage(input.outputPackage);
  if (!validation.ok) {
    await emitDispatchAudit(
      client,
      input,
      AUDIT_EVENTS.ADAPTER_DISPATCH_PACKAGE_INVALID,
      { errors: validation.errors }
    );
    return { status: "package_invalid", errors: validation.errors };
  }

  // Step 5 + 6: submit + record handoff
  // Loop 9 Phase 9.2: thread the resolved credential_ref and the
  // template_profile.external_ref into the adapter submission context
  // so live adapters don't re-query the DB. Test-double ignores both.
  const templateExternalRef = await resolveTemplateExternalRef(client, {
    clientId: input.clientId,
    templateProfileId: input.outputPackage.templateProfileId,
  });
  let submission;
  try {
    submission = await adapter.submit(input.outputPackage, {
      correlationId: input.correlationId,
      templateExternalRef,
      credentialRef: credentialRow?.credentialRef ?? null,
    });
  } catch (err) {
    // Loop 9 Phase 9.2 — live adapters throw typed GammaAdapterError.
    // Map credential_invalid / rate_limited to the phase-locked audit
    // events so the log captures WHY a submit failed, not just "failed".
    if (err instanceof GammaAdapterError) {
      if (err.kind === "credential_invalid") {
        await emitDispatchAudit(
          client,
          input,
          AUDIT_EVENTS.ADAPTER_DISPATCH_CREDENTIAL_INVALID,
          {
            stage: "submit",
            http_status: err.httpStatus,
            detail: err.message,
          }
        );
        return { status: "credential_invalid", reason: err.message };
      }
      if (err.kind === "rate_limited") {
        await emitDispatchAudit(
          client,
          input,
          AUDIT_EVENTS.ADAPTER_DISPATCH_RATE_LIMITED,
          {
            stage: "submit",
            http_status: err.httpStatus,
            detail: err.message,
          }
        );
        return { status: "rate_limited", reason: err.message };
      }
      if (err.kind === "package_invalid") {
        await emitDispatchAudit(
          client,
          input,
          AUDIT_EVENTS.ADAPTER_DISPATCH_PACKAGE_INVALID,
          {
            stage: "submit",
            detail: err.message,
          }
        );
        return {
          status: "package_invalid",
          errors: (err.body ?? err.message).split("; "),
        };
      }
    }
    const message = err instanceof Error ? err.message : String(err);
    // Record a failed handoff for auditability.
    const failedHandoffId = await recordHandoff(client, input, {
      status: "failed",
      externalReference: null,
      externalDestination: null,
      handoffPayloadRef: null,
    });
    await updateHandoffAdapterId(client, input.clientId, failedHandoffId, adapterCatalogId);
    await emitDispatchAudit(client, input, AUDIT_EVENTS.ADAPTER_DISPATCH_FAILED, {
      errorMessage: message,
      stage: "submit",
    });
    return { status: "failed", handoffId: failedHandoffId, errorMessage: message };
  }

  const handoffId = await recordHandoff(client, input, {
    status: "submitted",
    externalReference: submission.externalReference,
    externalDestination: submission.externalDestination ?? null,
    handoffPayloadRef: submission.handoffPayloadRef ?? null,
  });
  await updateHandoffAdapterId(client, input.clientId, handoffId, adapterCatalogId);
  await emitDispatchAudit(client, input, AUDIT_EVENTS.ADAPTER_DISPATCH_SUBMITTED, {
    externalReference: submission.externalReference,
    handoffId,
  });

  // Step 7: fetch result (test-double returns immediately; live adapters
  // re-read the same credential_ref we threaded into submit above).
  const result = await adapter.fetchResult(submission.externalReference, {
    credentialRef: credentialRow?.credentialRef ?? null,
  });

  // Loop 9 Phase 9.4 (scope §3.4) — async polling fork.
  // `unknown` means the adapter submitted successfully but the artifact
  // is still rendering. WO stays in `processing`; handoff stays in
  // `submitted` with poll-state metadata. Subsequent polls advance it
  // via `pollHandoffStatus()` + `POST /output_handoffs/{id}/poll`. The
  // dispatcher emits `adapter_dispatch.polling` here so audit captures
  // the first poll attempt made at submit-time.
  if (result.status === "unknown") {
    await updateHandoffPollState(client, input.clientId, handoffId, {
      lastPollStatus: "pending",
      pollCountIncrement: 1,
    });
    await emitDispatchAudit(
      client,
      input,
      AUDIT_EVENTS.ADAPTER_DISPATCH_POLLING,
      {
        handoffId,
        externalReference: submission.externalReference,
        pollCount: 1,
        stage: "submit_poll",
      }
    );
    return {
      status: "pending_poll",
      handoffId,
      externalReference: submission.externalReference,
    };
  }

  await recordResult(
    client,
    handoffId,
    result.status,
    result.payloadRef ?? null,
    result.errorMessage ?? null,
    result.metadata ?? {}
  );

  if (result.status === "success") {
    await updateHandoffStatus(
      client,
      input.clientId,
      handoffId,
      "completed",
      result.payloadRef ?? null
    );
    await emitDispatchAudit(
      client,
      input,
      AUDIT_EVENTS.ADAPTER_DISPATCH_COMPLETED,
      { handoffId, externalReference: submission.externalReference }
    );
    return {
      status: "completed",
      handoffId,
      externalReference: submission.externalReference,
      resultPayloadRef: result.payloadRef ?? null,
    };
  }

  await updateHandoffStatus(client, input.clientId, handoffId, "failed", result.payloadRef ?? null);
  await emitDispatchAudit(client, input, AUDIT_EVENTS.ADAPTER_DISPATCH_FAILED, {
    handoffId,
    errorMessage: result.errorMessage ?? "adapter returned non-success",
    stage: "fetch_result",
  });
  return {
    status: "failed",
    handoffId,
    errorMessage: result.errorMessage ?? "adapter returned non-success",
  };
}

async function updateHandoffPollState(
  client: PoolClient,
  clientId: string,
  handoffId: string,
  fields: {
    lastPollStatus: string;
    pollCountIncrement?: number;
  }
): Promise<void> {
  // Phase 4.4 lint gate: explicit client_id predicate on the update
  // alongside the Loop 4 Phase 3 RLS policy on output_handoffs.
  await client.query(
    `UPDATE output_handoffs
        SET last_poll_status = $3,
            last_poll_at = now(),
            poll_count = poll_count + $4,
            updated_at = now()
      WHERE id = $1 AND client_id = $2`,
    [
      handoffId,
      clientId,
      fields.lastPollStatus,
      fields.pollCountIncrement ?? 0,
    ]
  );
}

async function updateHandoffAdapterId(
  client: PoolClient,
  clientId: string,
  handoffId: string,
  adapterCatalogId: string
): Promise<void> {
  // Phase 4.4 lint gate: explicit client_id predicate; see
  // updateHandoffStatus comment.
  await client.query(
    `UPDATE output_handoffs
     SET adapter_catalog_id = $3, updated_at = now()
     WHERE id = $1 AND client_id = $2`,
    [handoffId, clientId, adapterCatalogId]
  );
}

// ──────────────────────────────────────────────────────────────────────
// Loop 9 Phase 9.4 — async polling
// ──────────────────────────────────────────────────────────────────────

const DEFAULT_POLL_TIMEOUT_SECONDS = 600; // 10 minutes; adapter_actions.poll_timeout_seconds overrides

export type PollHandoffResult =
  | {
      status: "completed";
      handoffId: string;
      externalReference: string;
      resultPayloadRef: string | null;
    }
  | {
      status: "pending";
      handoffId: string;
      pollCount: number;
      externalReference: string;
    }
  | {
      status: "failed";
      handoffId: string;
      errorMessage: string;
    }
  | {
      status: "watchdog_expired";
      handoffId: string;
      reason: string;
      secondsSinceLastPoll: number;
    }
  | { status: "handoff_not_found"; handoffId: string }
  | {
      status: "handoff_not_pollable";
      handoffId: string;
      currentStatus: string;
    }
  | {
      status: "adapter_not_found";
      handoffId: string;
      adapterKey: string | null;
    };

export interface PollHandoffInput {
  handoffId: string;
  clientId: string;
  actorUserId: string | null;
  /**
   * When provided, the dispatcher treats this as "now" for watchdog
   * calculations. Tests use this to simulate elapsed time without
   * sleeping; production callers leave it undefined to use the DB
   * clock via `now()`.
   */
  nowOverride?: Date;
  /**
   * When set, the poll treats `last_poll_at` as older than the
   * per-action timeout regardless of the wall clock. Tests use this
   * to simulate a stale poll watchdog without time travel. If both
   * `nowOverride` and `forceStaleWatchdog` are set, the latter wins.
   */
  forceStaleWatchdog?: boolean;
}

interface HandoffPollRow {
  id: string;
  client_id: string;
  status: string;
  external_reference: string | null;
  adapter_catalog_id: string | null;
  last_poll_at: Date | null;
  poll_count: number;
  work_order_id: string | null;
  output_package_id: string | null;
  adapter_key: string | null;
  poll_timeout_seconds: number | null;
}

async function loadHandoffForPoll(
  client: PoolClient,
  handoffId: string,
  clientId: string
): Promise<HandoffPollRow | null> {
  // Phase 4.4 lint gate: explicit client_id predicate + RLS belt.
  const { rows } = await client.query<HandoffPollRow>(
    `SELECT h.id,
            h.client_id,
            h.status::text                  AS status,
            h.external_reference,
            h.adapter_catalog_id,
            h.last_poll_at,
            h.poll_count,
            h.work_order_id,
            h.output_package_id,
            cat.adapter_key,
            (
              SELECT MAX(poll_timeout_seconds)
                FROM adapter_actions
               WHERE adapter_catalog_id = h.adapter_catalog_id
            )                                AS poll_timeout_seconds
       FROM output_handoffs h
  LEFT JOIN adapter_catalog cat ON cat.id = h.adapter_catalog_id
      WHERE h.id = $1 AND h.client_id = $2`,
    [handoffId, clientId]
  );
  return rows[0] ?? null;
}

async function loadCredentialRefForHandoff(
  client: PoolClient,
  clientId: string,
  adapterCatalogId: string
): Promise<string | null> {
  const { rows } = await client.query<{ credential_ref: string }>(
    `SELECT credential_ref
       FROM adapter_credentials
      WHERE client_id = $1 AND adapter_catalog_id = $2
      ORDER BY created_at DESC
      LIMIT 1`,
    [clientId, adapterCatalogId]
  );
  return rows[0]?.credential_ref ?? null;
}

function emitPollAudit(
  client: PoolClient,
  clientId: string,
  actorUserId: string | null,
  handoffId: string,
  outputPackageId: string | null,
  event: (typeof AUDIT_EVENTS)[keyof typeof AUDIT_EVENTS],
  extra: Record<string, unknown>
): Promise<unknown> {
  return writeAuditRow(client, {
    clientId,
    actorUserId,
    event,
    targetType: "adapter_dispatch",
    targetId: outputPackageId ?? handoffId,
    metadata: { handoffId, ...extra },
  });
}

/**
 * Loop 9 Phase 9.4 (scope §3.4) — poll one handoff and advance its
 * lifecycle. Safe to call from the POST /output_handoffs/{id}/poll
 * route or a scheduled job. Emits phase-locked audit events for
 * polling / completion / failure / watchdog.
 *
 * Semantics (Darrel §Q3):
 *   - Poll state lives on the handoff; WO stays `processing`.
 *   - Completed/failed transitions cascade to the parent WO via Loop 6
 *     helpers ONLY at terminal events. Healthy long renders don't
 *     touch WO status.
 *   - Stale poll beyond `adapter_actions.poll_timeout_seconds` fires
 *     the watchdog: handoff→failed, audit `watchdog_expired_stale_poll`,
 *     WO transitions via `watchdogExpireWorkOrder` if still processing.
 */
export async function pollHandoffStatus(
  client: PoolClient,
  input: PollHandoffInput
): Promise<PollHandoffResult> {
  const row = await loadHandoffForPoll(
    client,
    input.handoffId,
    input.clientId
  );
  if (!row) {
    return { status: "handoff_not_found", handoffId: input.handoffId };
  }
  if (row.status !== "submitted") {
    return {
      status: "handoff_not_pollable",
      handoffId: input.handoffId,
      currentStatus: row.status,
    };
  }
  if (!row.adapter_catalog_id || !row.adapter_key || !row.external_reference) {
    return {
      status: "adapter_not_found",
      handoffId: input.handoffId,
      adapterKey: row.adapter_key ?? null,
    };
  }

  const adapter = getAdapter(row.adapter_key);
  if (!adapter) {
    return {
      status: "adapter_not_found",
      handoffId: input.handoffId,
      adapterKey: row.adapter_key,
    };
  }

  // Watchdog pre-check. If the handoff has been pending past the
  // per-action timeout (or the caller force-triggers watchdog), mark
  // failed without contacting the adapter. Protects against runaway
  // costs + hung renders.
  const pollTimeout =
    row.poll_timeout_seconds ?? DEFAULT_POLL_TIMEOUT_SECONDS;
  const now = input.nowOverride ?? new Date();
  const lastPoll = row.last_poll_at ?? new Date(0);
  const elapsedSeconds = Math.floor(
    (now.getTime() - lastPoll.getTime()) / 1000
  );
  const stale = input.forceStaleWatchdog === true
    ? true
    : elapsedSeconds > pollTimeout;
  if (stale) {
    await updateHandoffStatus(
      client,
      input.clientId,
      input.handoffId,
      "failed",
      null
    );
    await updateHandoffPollState(client, input.clientId, input.handoffId, {
      lastPollStatus: "watchdog_expired",
      pollCountIncrement: 0,
    });
    await emitPollAudit(
      client,
      input.clientId,
      input.actorUserId,
      input.handoffId,
      row.output_package_id,
      AUDIT_EVENTS.ADAPTER_DISPATCH_WATCHDOG_EXPIRED_STALE_POLL,
      {
        pollCount: row.poll_count,
        pollTimeoutSeconds: pollTimeout,
        elapsedSeconds,
        forced: input.forceStaleWatchdog === true,
      }
    );
    return {
      status: "watchdog_expired",
      handoffId: input.handoffId,
      reason: `no fresh poll within ${pollTimeout}s (elapsed=${elapsedSeconds}s)`,
      secondsSinceLastPoll: elapsedSeconds,
    };
  }

  const credentialRef = await loadCredentialRefForHandoff(
    client,
    input.clientId,
    row.adapter_catalog_id
  );
  const result = await adapter.fetchResult(row.external_reference, {
    credentialRef,
  });

  const nextPollCount = row.poll_count + 1;

  if (result.status === "success") {
    await recordResult(
      client,
      input.handoffId,
      result.status,
      result.payloadRef ?? null,
      result.errorMessage ?? null,
      result.metadata ?? {}
    );
    await updateHandoffStatus(
      client,
      input.clientId,
      input.handoffId,
      "completed",
      result.payloadRef ?? null
    );
    await updateHandoffPollState(client, input.clientId, input.handoffId, {
      lastPollStatus: "completed",
      pollCountIncrement: 1,
    });
    await emitPollAudit(
      client,
      input.clientId,
      input.actorUserId,
      input.handoffId,
      row.output_package_id,
      AUDIT_EVENTS.ADAPTER_DISPATCH_COMPLETED,
      {
        externalReference: row.external_reference,
        pollCount: nextPollCount,
      }
    );
    return {
      status: "completed",
      handoffId: input.handoffId,
      externalReference: row.external_reference,
      resultPayloadRef: result.payloadRef ?? null,
    };
  }

  if (result.status === "failed") {
    await recordResult(
      client,
      input.handoffId,
      result.status,
      result.payloadRef ?? null,
      result.errorMessage ?? null,
      result.metadata ?? {}
    );
    await updateHandoffStatus(
      client,
      input.clientId,
      input.handoffId,
      "failed",
      result.payloadRef ?? null
    );
    await updateHandoffPollState(client, input.clientId, input.handoffId, {
      lastPollStatus: "failed",
      pollCountIncrement: 1,
    });
    await emitPollAudit(
      client,
      input.clientId,
      input.actorUserId,
      input.handoffId,
      row.output_package_id,
      AUDIT_EVENTS.ADAPTER_DISPATCH_FAILED,
      {
        externalReference: row.external_reference,
        pollCount: nextPollCount,
        errorMessage: result.errorMessage ?? "adapter returned failed",
        stage: "poll",
      }
    );
    return {
      status: "failed",
      handoffId: input.handoffId,
      errorMessage: result.errorMessage ?? "adapter returned failed",
    };
  }

  // Still pending. Record the poll, keep the handoff in `submitted`.
  await updateHandoffPollState(client, input.clientId, input.handoffId, {
    lastPollStatus: "pending",
    pollCountIncrement: 1,
  });
  await emitPollAudit(
    client,
    input.clientId,
    input.actorUserId,
    input.handoffId,
    row.output_package_id,
    AUDIT_EVENTS.ADAPTER_DISPATCH_POLLING,
    {
      externalReference: row.external_reference,
      pollCount: nextPollCount,
      pollTimeoutSeconds: pollTimeout,
      elapsedSeconds,
    }
  );
  return {
    status: "pending",
    handoffId: input.handoffId,
    pollCount: nextPollCount,
    externalReference: row.external_reference,
  };
}

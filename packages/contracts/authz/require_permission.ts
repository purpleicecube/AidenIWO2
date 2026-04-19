/**
 * Loop 4 Phase 2 — throwing authorization wrapper with audit write.
 *
 * `requirePermission` is the usual entry point for privileged mutations:
 *
 *   await requirePermission(client, {
 *     userId, clientId,
 *     permission: "output_package:submit",
 *     targetType: "output_package",
 *     targetId: pkg.id,
 *   });
 *
 * On allow: returns silently. The caller proceeds to do the actual work
 * and writes its own typed audit row (e.g. `output_package.submitted`).
 *
 * On deny: writes an `authz.denied` row into `action_audit_log` with the
 * caller's context + the decision reason, then throws `PermissionDenied`.
 *
 * The intent is that `authz.denied` gives operators a forensic trail
 * across the product: every time a user hits the guard and is refused,
 * there is a tenant-scoped row with who, what, where, and why.
 *
 * `authz.granted` is deliberately NOT emitted — allowed calls are
 * implied by the follow-up typed audit row (e.g. `output_package.submitted`
 * on the same (client_id, actor_user_id, timestamp bucket)), and adding
 * a row per check would bloat the log without adding forensic value.
 */

import type { PoolClient } from "pg";

import { AUDIT_EVENTS } from "../audit/events";
import { writeAuditRow } from "../audit/writer";
import { checkPermission, type PermissionDecision } from "./check_permission";

export class PermissionDenied extends Error {
  readonly reason: PermissionDecision["reason"];
  readonly role: string | null;
  readonly permission: string;
  readonly userId: string;
  readonly clientId: string;

  constructor(opts: {
    reason: PermissionDecision["reason"];
    role: string | null;
    permission: string;
    userId: string;
    clientId: string;
  }) {
    super(
      `PermissionDenied: user=${opts.userId} client=${opts.clientId} ` +
        `permission=${opts.permission} reason=${opts.reason} role=${opts.role ?? "none"}`
    );
    this.name = "PermissionDenied";
    this.reason = opts.reason;
    this.role = opts.role;
    this.permission = opts.permission;
    this.userId = opts.userId;
    this.clientId = opts.clientId;
  }
}

export interface RequirePermissionInput {
  userId: string;
  clientId: string;
  permission: string;
  /** Audit target type, e.g. `"output_package"` or `"work_order"`. */
  targetType?: string;
  /** Audit target id — typically the row id the caller is mutating. */
  targetId?: string;
  /** Extra metadata to attach to the `authz.denied` audit row on failure. */
  metadata?: Record<string, unknown>;
}

export async function requirePermission(
  client: PoolClient,
  input: RequirePermissionInput
): Promise<PermissionDecision> {
  const decision = await checkPermission(client, {
    userId: input.userId,
    clientId: input.clientId,
    permission: input.permission,
  });
  if (decision.allowed) return decision;

  await writeAuditRow(client, {
    clientId: input.clientId,
    actorUserId: input.userId,
    event: AUDIT_EVENTS.AUTHZ_DENIED,
    targetType: input.targetType ?? "permission_check",
    targetId: input.targetId ?? input.permission,
    metadata: {
      ...(input.metadata ?? {}),
      permission: input.permission,
      decision_reason: decision.reason,
      role: decision.role,
    },
  });

  throw new PermissionDenied({
    reason: decision.reason,
    role: decision.role,
    permission: input.permission,
    userId: input.userId,
    clientId: input.clientId,
  });
}

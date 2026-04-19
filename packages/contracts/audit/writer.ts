/**
 * Loop 2 Phase 2 — audit-log writer helper.
 *
 * Every privileged action in IWO3 must insert a row into `action_audit_log`
 * using one of the registered event names from `./events.ts`, in the same
 * transaction as the mutation. This file provides the canonical writer that
 * higher-level services (prompt profile CRUD, repository binding CRUD,
 * artifact upload, etc.) call.
 *
 * Loop 2 Phase 2 scope:
 *   - Ship the writer + types + integration test.
 *   - Exercise it from the `audit-log-invariant.test.ts` regression suite.
 *
 * Loop 3+ wires the writer into the WO/WF + output-adapter CRUD paths.
 */

import type { PoolClient } from "pg";
import type { AuditEvent } from "./events";

export interface AuditWriteInput {
  clientId: string;
  actorUserId?: string | null;
  event: AuditEvent;
  targetType?: string | null;
  targetId?: string | null;
  metadata?: unknown;
}

export interface AuditWriteResult {
  id: number;
  createdAt: string;
}

/**
 * Insert one audit log row. Must run inside a transaction opened by the
 * caller (use `await pool.connect()` + BEGIN/COMMIT to guarantee the
 * mutation + audit write are atomic). The function does NOT start its
 * own transaction.
 */
export async function writeAuditRow(
  client: PoolClient,
  input: AuditWriteInput
): Promise<AuditWriteResult> {
  const {
    clientId,
    actorUserId = null,
    event,
    targetType = null,
    targetId = null,
    metadata = null,
  } = input;

  const result = await client.query<{ id: string; created_at: string }>(
    `INSERT INTO action_audit_log
       (client_id, actor_user_id, action, target_type, target_id, metadata)
     VALUES ($1, $2, $3, $4, $5, $6)
     RETURNING id, created_at`,
    [
      clientId,
      actorUserId,
      event,
      targetType,
      targetId,
      metadata === null ? null : JSON.stringify(metadata),
    ]
  );

  if (result.rows.length === 0) {
    throw new Error("writeAuditRow: INSERT did not return a row");
  }

  return {
    // `id` is bigserial — pg returns as string; widen to number (safe for
    // the row-count volumes IWO3 sees in Loop 2/3). If we approach 2^53
    // rows in a single deployment, this becomes a row-level refactor.
    id: Number(result.rows[0].id),
    createdAt: result.rows[0].created_at,
  };
}

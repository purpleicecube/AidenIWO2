/**
 * Loop 3 Phase 2 — adapter policy resolver.
 *
 * Given a (client_id, adapter_key, action_key) tuple, returns the
 * policy `mode` from `adapter_action_policies`. Default (no row)
 * is `none` — allowed without approval.
 *
 * Every Loop 3+ adapter invocation MUST go through this resolver
 * before calling the adapter. Callers interpret the result:
 *   - `none` → proceed.
 *   - `approval_required` → caller must attach an approval_ref from
 *                           an approval workflow before `submit`.
 *   - `disallowed` → hard reject; audit with `adapter_policy.disallowed`
 *                    metadata; return an error to the requester.
 *
 * This resolver is pure SQL-lookup; no secrets, no network. Safe to
 * call per-request.
 */

import type { PoolClient } from "pg";

export type AdapterPolicyMode = "none" | "approval_required" | "disallowed";

export interface ResolveAdapterPolicyInput {
  clientId: string;
  adapterKey: string;
  actionKey: string;
}

export interface ResolveAdapterPolicyResult {
  mode: AdapterPolicyMode;
  /** If the mode came from an explicit row, the row id is here. */
  policyRowId: string | null;
  /** Reason text from the row, if any. */
  reason: string | null;
}

export async function resolveAdapterPolicy(
  client: PoolClient,
  input: ResolveAdapterPolicyInput
): Promise<ResolveAdapterPolicyResult> {
  const { rows } = await client.query<{
    id: string;
    mode: AdapterPolicyMode;
    reason: string | null;
  }>(
    `SELECT aap.id, aap.mode, aap.reason
     FROM adapter_action_policies aap
     JOIN adapter_catalog ac ON ac.id = aap.adapter_catalog_id
     WHERE aap.client_id = $1
       AND ac.adapter_key = $2
       AND aap.action_key = $3
     LIMIT 1`,
    [input.clientId, input.adapterKey, input.actionKey]
  );

  if (rows.length === 0) {
    return { mode: "none", policyRowId: null, reason: null };
  }
  return {
    mode: rows[0].mode,
    policyRowId: rows[0].id,
    reason: rows[0].reason,
  };
}

/**
 * Loop 4 Phase 3 — transaction-scoped tenant context wrapper.
 *
 * Opens a transaction, drops privileges to `iwo3_app` (no BYPASSRLS), and
 * sets `app.current_client_id` so RLS policies from migration 0006 fire
 * on every subsequent query inside the callback. Commits on success;
 * rolls back on throw.
 *
 * Enforcement-mode policy (ADR-015, IWO3_LOOP_4_APPROVAL_DECISIONS §Q3):
 *
 *   - `iwo3`      (superuser + BYPASSRLS) — migrations, seeds, admin ops,
 *                 and existing Loop 1/2/3 integration tests. Bypasses RLS
 *                 silently; §Q4 JOIN filters are the isolation layer for
 *                 these paths.
 *   - `iwo3_app`  (NOLOGIN, non-superuser, no-bypass-rls) — runtime
 *                 handlers. `withTenantContext` flips to this role via
 *                 `SET LOCAL ROLE` + sets `app.current_client_id`, so
 *                 RLS policies filter every query.
 *
 * Why both layers (§Q4 `keep_both`): the service-layer `client_id = $1`
 * filters remain the primary tenant guard through Loop 10; RLS is the
 * defense-in-depth belt that refuses cross-tenant reads or writes even
 * if a future handler forgets the JOIN. The Phase 4.4 lint rule closes
 * the remaining human-error risk.
 *
 * Usage:
 *
 *   const id = await withTenantContext(pool, { clientId }, async (c) => {
 *     const { rows } = await c.query(
 *       `INSERT INTO output_packages (...) VALUES (...) RETURNING id`
 *     );
 *     return rows[0].id;
 *   });
 *
 * Internals:
 *   BEGIN
 *   SELECT set_config('app.current_client_id', '<uuid>', true)  -- SET LOCAL
 *   SET LOCAL ROLE iwo3_app
 *   <fn(client)>
 *   COMMIT                              -- role + GUC auto-reset
 *
 * `SET LOCAL` scopes both the role and the GUC to the transaction; when
 * the tx commits or rolls back, the connection returns to the pool in a
 * neutral state. A later borrower starts with a fresh BEGIN.
 */

import type { Pool, PoolClient } from "pg";

export interface WithTenantContextOpts {
  /** UUID of the tenant scope. Validated as `::uuid` by Postgres policies. */
  clientId: string;
  /** Optional non-default role name. Defaults to the Loop 4 Phase 3 role. */
  role?: string;
}

export async function withTenantContext<T>(
  pool: Pool,
  opts: WithTenantContextOpts,
  fn: (client: PoolClient) => Promise<T>
): Promise<T> {
  const role = opts.role ?? "iwo3_app";
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      "SELECT set_config('app.current_client_id', $1, true)",
      [opts.clientId]
    );
    // SET LOCAL ROLE cannot be parameterized; role name is caller-supplied
    // but restricted to identifier characters to block injection.
    if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(role)) {
      throw new Error(`withTenantContext: invalid role name: ${role}`);
    }
    await client.query(`SET LOCAL ROLE ${role}`);
    const result = await fn(client);
    await client.query("COMMIT");
    return result;
  } catch (err) {
    try {
      await client.query("ROLLBACK");
    } catch {
      /* tx already aborted by error; ROLLBACK is a no-op */
    }
    throw err;
  } finally {
    client.release();
  }
}

/**
 * In-transaction variant: the caller already holds a PoolClient inside a
 * BEGUN transaction. Sets the role + GUC on that transaction; the caller
 * owns COMMIT/ROLLBACK and client release.
 *
 * Used by tests that want fine-grained control over the transaction
 * boundary (e.g. assert a ROLLBACK reverts a write that briefly hit an
 * RLS-visible state).
 */
export async function useTenantContext(
  client: PoolClient,
  opts: WithTenantContextOpts
): Promise<void> {
  const role = opts.role ?? "iwo3_app";
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(role)) {
    throw new Error(`useTenantContext: invalid role name: ${role}`);
  }
  await client.query(
    "SELECT set_config('app.current_client_id', $1, true)",
    [opts.clientId]
  );
  await client.query(`SET LOCAL ROLE ${role}`);
}

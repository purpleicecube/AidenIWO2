/**
 * Loop 5 Phase 5.1 — shared helpers for contract-surface freeze tests.
 *
 * Loads:
 *   - Every Postgres enum in the `public` schema (with ordered values)
 *   - The full AUDIT_EVENTS object + per-loop vocabulary arrays
 *   - The locked permission_key vocabulary from the `permissions` table
 *
 * Returns a canonical JSON-serialisable shape that can be compared to
 * `tests/fixtures/contract-enums.snapshot.json`.
 *
 * The snapshot file is the CONTRACT. Any change (new enum value, new
 * audit event, new permission) MUST be made in the same commit as the
 * snapshot update; otherwise `contract-enums.test.ts` fails CI.
 */

import type { Pool } from "pg";

import {
  AUDIT_EVENTS,
  LOOP_2_AUDIT_EVENTS,
  LOOP_3_PHASE_1_AUDIT_EVENTS,
  LOOP_3_PHASE_2_AUDIT_EVENTS,
  LOOP_3_PHASE_4_AUDIT_EVENTS,
  LOOP_4_PHASE_1_AUDIT_EVENTS,
  LOOP_4_PHASE_2_AUDIT_EVENTS,
  LOOP_6_PHASE_1_AUDIT_EVENTS,
  LOOP_9_PHASE_1_AUDIT_EVENTS,
  LOOP_9_PHASE_2_AUDIT_EVENTS,
  LOOP_9_PHASE_3_AUDIT_EVENTS,
  LOOP_9_PHASE_4_AUDIT_EVENTS,
  ALPHA_PHASE_A2_AUDIT_EVENTS,
  ALPHA_PHASE_A5_AUDIT_EVENTS,
  PRE_BETA_PHASE_2_AUDIT_EVENTS,
  PRE_BETA_PHASE_DELTA_AUDIT_EVENTS,
  BETA_PHASE_1_AUDIT_EVENTS,
  BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS,
  BETA_2_PHASE_0_AUDIT_EVENTS,
  BETA_2_PHASE_0_3_AUDIT_EVENTS,
  BETA_2_PHASE_0_4_AUDIT_EVENTS,
  LOOP_ETA_AUDIT_EVENTS,
  LOOP_THETA_AUDIT_EVENTS,
  LOOP_IOTA_AUDIT_EVENTS,
  LOOP_KAPPA_AUDIT_EVENTS,
  LOOP_XI_AUDIT_EVENTS,
  LOOP_AEP_AUDIT_EVENTS,
  LOOP_CAP_A_AUDIT_EVENTS,
  LOOP_CAP_D_PHI5_AUDIT_EVENTS,
  LOOP_CAP_D_PHI6_AUDIT_EVENTS,
  LOOP_CAP_E_PHI8_AUDIT_EVENTS,
  LOOP_SANDBOX_BETA_0_AUDIT_EVENTS,
} from "../../packages/contracts/audit/events";

export interface ContractSnapshot {
  dbEnums: Record<string, readonly string[]>;
  auditEvents: {
    all: readonly string[];
    byLoop: Record<string, readonly string[]>;
  };
  permissionKeys: readonly string[];
}

export async function loadDbEnums(
  pool: Pool
): Promise<Record<string, readonly string[]>> {
  // array_agg(...)::text[] forces the pg driver to parse as a JS
  // string[] instead of returning a PG array literal like
  // "{a,b,c}" (which happens when the element type is `name`,
  // which is what pg_enum.enumlabel actually is).
  const { rows } = await pool.query<{ typname: string; values: string[] }>(`
    SELECT t.typname,
           array_agg(e.enumlabel::text ORDER BY e.enumsortorder)::text[] AS values
    FROM pg_type t
    JOIN pg_enum e ON e.enumtypid = t.oid
    JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'public'
    GROUP BY t.typname
    ORDER BY t.typname
  `);
  const out: Record<string, readonly string[]> = {};
  for (const r of rows) out[r.typname] = r.values;
  return out;
}

export async function loadPermissionKeys(pool: Pool): Promise<readonly string[]> {
  const { rows } = await pool.query<{ permission_key: string }>(
    `SELECT permission_key FROM permissions ORDER BY permission_key`
  );
  return rows.map((r) => r.permission_key);
}

export function loadAuditEvents(): ContractSnapshot["auditEvents"] {
  const all = Object.values(AUDIT_EVENTS).slice().sort() as string[];
  return {
    all,
    byLoop: {
      LOOP_2_AUDIT_EVENTS: [...LOOP_2_AUDIT_EVENTS],
      LOOP_3_PHASE_1_AUDIT_EVENTS: [...LOOP_3_PHASE_1_AUDIT_EVENTS],
      LOOP_3_PHASE_2_AUDIT_EVENTS: [...LOOP_3_PHASE_2_AUDIT_EVENTS],
      LOOP_3_PHASE_4_AUDIT_EVENTS: [...LOOP_3_PHASE_4_AUDIT_EVENTS],
      LOOP_4_PHASE_1_AUDIT_EVENTS: [...LOOP_4_PHASE_1_AUDIT_EVENTS],
      LOOP_4_PHASE_2_AUDIT_EVENTS: [...LOOP_4_PHASE_2_AUDIT_EVENTS],
      LOOP_6_PHASE_1_AUDIT_EVENTS: [...LOOP_6_PHASE_1_AUDIT_EVENTS],
      LOOP_9_PHASE_1_AUDIT_EVENTS: [...LOOP_9_PHASE_1_AUDIT_EVENTS],
      LOOP_9_PHASE_2_AUDIT_EVENTS: [...LOOP_9_PHASE_2_AUDIT_EVENTS],
      LOOP_9_PHASE_3_AUDIT_EVENTS: [...LOOP_9_PHASE_3_AUDIT_EVENTS],
      LOOP_9_PHASE_4_AUDIT_EVENTS: [...LOOP_9_PHASE_4_AUDIT_EVENTS],
      ALPHA_PHASE_A2_AUDIT_EVENTS: [...ALPHA_PHASE_A2_AUDIT_EVENTS],
      ALPHA_PHASE_A5_AUDIT_EVENTS: [...ALPHA_PHASE_A5_AUDIT_EVENTS],
      PRE_BETA_PHASE_2_AUDIT_EVENTS: [...PRE_BETA_PHASE_2_AUDIT_EVENTS],
      PRE_BETA_PHASE_DELTA_AUDIT_EVENTS: [...PRE_BETA_PHASE_DELTA_AUDIT_EVENTS],
      BETA_PHASE_1_AUDIT_EVENTS: [...BETA_PHASE_1_AUDIT_EVENTS],
      BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS: [
        ...BETA_PHASE_1_5_PHASE_2_AUDIT_EVENTS,
      ],
      BETA_2_PHASE_0_AUDIT_EVENTS: [...BETA_2_PHASE_0_AUDIT_EVENTS],
      BETA_2_PHASE_0_3_AUDIT_EVENTS: [...BETA_2_PHASE_0_3_AUDIT_EVENTS],
      BETA_2_PHASE_0_4_AUDIT_EVENTS: [...BETA_2_PHASE_0_4_AUDIT_EVENTS],
      LOOP_ETA_AUDIT_EVENTS: [...LOOP_ETA_AUDIT_EVENTS],
      LOOP_THETA_AUDIT_EVENTS: [...LOOP_THETA_AUDIT_EVENTS],
      LOOP_IOTA_AUDIT_EVENTS: [...LOOP_IOTA_AUDIT_EVENTS],
      LOOP_KAPPA_AUDIT_EVENTS: [...LOOP_KAPPA_AUDIT_EVENTS],
      LOOP_XI_AUDIT_EVENTS: [...LOOP_XI_AUDIT_EVENTS],
      LOOP_AEP_AUDIT_EVENTS: [...LOOP_AEP_AUDIT_EVENTS],
      LOOP_CAP_A_AUDIT_EVENTS: [...LOOP_CAP_A_AUDIT_EVENTS],
      LOOP_CAP_D_PHI5_AUDIT_EVENTS: [...LOOP_CAP_D_PHI5_AUDIT_EVENTS],
      LOOP_CAP_D_PHI6_AUDIT_EVENTS: [...LOOP_CAP_D_PHI6_AUDIT_EVENTS],
      LOOP_CAP_E_PHI8_AUDIT_EVENTS: [...LOOP_CAP_E_PHI8_AUDIT_EVENTS],
      LOOP_SANDBOX_BETA_0_AUDIT_EVENTS: [...LOOP_SANDBOX_BETA_0_AUDIT_EVENTS],
    },
  };
}

export async function buildContractSnapshot(
  pool: Pool
): Promise<ContractSnapshot> {
  const [dbEnums, permissionKeys] = await Promise.all([
    loadDbEnums(pool),
    loadPermissionKeys(pool),
  ]);
  return {
    dbEnums,
    auditEvents: loadAuditEvents(),
    permissionKeys,
  };
}

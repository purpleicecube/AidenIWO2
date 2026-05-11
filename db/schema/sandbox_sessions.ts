/**
 * Sandbox Operational Darkmode (ADR-035, 2026-05-11) — IWO2-inherited
 * sandbox sessions, operationalized in IWO3 as an internal operator
 * utility (Path A-prime).
 *
 * The canonical IWO2-shape definition lives in `shared/schema.ts` and
 * is consumed directly by the inherited Express/React surface
 * (`server/routes.ts`, `client/src/pages/sandbox.tsx`). This file
 * re-exports that definition so the IWO3 Drizzle schema directory
 * carries a parity entry — `drizzle.config.iwo3.ts` scans
 * `db/schema/*.ts` for diff/migration purposes, and the
 * `migration_source_manifest` ownership test enforces every public
 * table appears in a registered manifest row.
 *
 * Tenancy posture (deliberate carve-out):
 *   • no `client_id` column
 *   • no FORCE RLS
 *   • visibility/mutation gated at the Node route layer by
 *     creator-or-admin check against `req.user.claims.sub`
 *
 * Long-term target = Path B (client_id + RLS + auth bridge) tracked
 * in the follow-on Sandbox Tenancy Bridge loop per ADR-035 §Successor.
 */

export {
  sandboxSessions,
  insertSandboxSessionSchema,
  type InsertSandboxSession,
  type SandboxSession,
} from "../../shared/schema";

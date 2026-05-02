import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

import { resolveUserPermissions } from "../../packages/contracts/authz/resolve_permissions";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

// Seed UUIDs — see db/seeds/{users,clients,client_memberships}.json.
const KLEAR = "00000000-0000-4000-8000-00000000c001";
const FFAI = "00000000-0000-4000-8000-00000000c002";

const KLEAR_OWNER = "00000000-0000-4000-8000-000001000001";
const KLEAR_ADMIN = "00000000-0000-4000-8000-000001000002";
const KLEAR_OPERATOR = "00000000-0000-4000-8000-000001000003";
const KLEAR_REVIEWER = "00000000-0000-4000-8000-000001000004";
const KLEAR_VIEWER = "00000000-0000-4000-8000-000001000005";
const KLEAR_AGENT = "00000000-0000-4000-8000-000001000006";

const FFAI_OPERATOR = "00000000-0000-4000-8000-000002000003";

const SUPER = "00000000-0000-4000-8000-000099000001";
const INTRUDER = "00000000-0000-4000-8000-000099000002";

// Expected role-default cardinalities — see db/seeds/role_permissions.json.
// Values are locked upfront per IWO3_LOOP_4_APPROVAL_DECISIONS §Q1.
// α.6 +3 channel keys, δ.2 +3 workspace keys, β-1 ε.1 +2 llm_config:write/
// delete keys per architect Q5. Owner + admin get all keys; operator gets
// llm_config:write (no delete); reviewer/viewer/agent_system unchanged.
// Beta-2 phase 0.1 (2026-04-30): +1 key (template_profile:read), granted
// to owner/admin/operator/agent_system/viewer (not reviewer).
// Beta-2 phase 0.2 (2026-04-30): +1 row — agent_system gains
// `work_order:submit` so the auto-dispatch worker can transition
// pending → processing under its system actor.
// Loop Eta phase 0 (2026-05-02): +4 keys — tool_catalog:read,
// tool_catalog:write, sub_agent_tool:read, sub_agent_tool:assign.
// Reads granted to all six roles; writes (tool_catalog:write +
// sub_agent_tool:assign) granted to owner + admin only.
//   owner +4 → 82, admin +4 → 80, operator +2 → 35,
//   reviewer +2 → 21, viewer +2 → 17, agent_system +2 → 27.
const EXPECTED_COUNTS = {
  owner: 82,
  admin: 80,
  operator: 35,
  reviewer: 21,
  viewer: 17,
  agent_system: 27,
} as const;

describeIwo3("Loop 4 Phase 1 — role-permission resolution", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("permissions vocabulary is locked at 82 keys (§Q1 + α.6 channel + δ.2 workspace + β-1 ε.1 llm_config CRUD split + β-2.0.1 template_profile:read + Loop Eta tool_catalog/sub_agent_tool x4)", async () => {
    const { rows } = await pool.query<{ count: string }>(
      `SELECT count(*) AS count FROM permissions`
    );
    expect(Number(rows[0].count)).toBe(82);
  });

  it("role_permissions is seeded at 262 rows across the six roles", async () => {
    const { rows } = await pool.query<{ role: string; count: string }>(
      `SELECT role, count(*) AS count FROM role_permissions GROUP BY role ORDER BY role`
    );
    const map = Object.fromEntries(rows.map((r) => [r.role, Number(r.count)]));
    expect(map).toMatchObject(EXPECTED_COUNTS);
    const total = Object.values(map).reduce((a, b) => a + b, 0);
    expect(total).toBe(262);
  });

  for (const [userId, role, expected] of [
    [KLEAR_OWNER, "owner", EXPECTED_COUNTS.owner],
    [KLEAR_ADMIN, "admin", EXPECTED_COUNTS.admin],
    [KLEAR_OPERATOR, "operator", EXPECTED_COUNTS.operator],
    [KLEAR_REVIEWER, "reviewer", EXPECTED_COUNTS.reviewer],
    [KLEAR_VIEWER, "viewer", EXPECTED_COUNTS.viewer],
    [KLEAR_AGENT, "agent_system", EXPECTED_COUNTS.agent_system],
  ] as const) {
    it(`Klear ${role} resolves to ${expected} permissions`, async () => {
      const r = await resolveUserPermissions(pool, {
        userId,
        clientId: KLEAR,
      });
      expect(r.role).toBe(role);
      expect(r.permissions.size).toBe(expected);
    });
  }

  it("admin lacks system:admin and user:revoke (owner-only)", async () => {
    const r = await resolveUserPermissions(pool, {
      userId: KLEAR_ADMIN,
      clientId: KLEAR,
    });
    expect(r.permissions.has("system:admin")).toBe(false);
    expect(r.permissions.has("user:revoke")).toBe(false);
    expect(r.permissions.has("membership:revoke")).toBe(true);
    expect(r.permissions.has("adapter_credential:rotate")).toBe(true);
  });

  it("operator grant set matches §Q2 revised mapping (Darrel 2026-04-19)", async () => {
    const r = await resolveUserPermissions(pool, {
      userId: KLEAR_OPERATOR,
      clientId: KLEAR,
    });
    // Explicit HAS
    for (const key of [
      "client:read",
      "user:read",
      "work_order:create",
      "work_order:submit",
      "work_order:cancel",
      "workflow:cancel",
      "execution_cycle:create",
      "execution_cycle:reopen",
      "prompt_override:apply_style",
      "output_package:submit",
      "output_package:validate",
      "output_handoff:read",
      "external_execution_result:read",
      "workflow_execution:read",
      "workflow_step_run:read",
    ]) {
      expect(r.permissions.has(key), `operator should have ${key}`).toBe(true);
    }
    // Explicit LACKS (moved to reviewer / admin / excluded)
    for (const key of [
      "system:admin",
      "user:revoke",
      "audit_log:read",
      "adapter_config:read",
      "adapter_config:create",
      "adapter_policy:read",
      "adapter_credential:rotate",
      "workflow_template:publish",
      "output_package:delete",
      "output_handoff:approve_send",
      "output_candidate:select",
      "output_candidate:reject",
      "prompt_override:apply_profile_swap",
      "prompt_override:apply_external_send",
    ]) {
      expect(r.permissions.has(key), `operator should NOT have ${key}`).toBe(
        false
      );
    }
  });

  it("agent_system grant set is narrow and fully explicit (no wildcards, no approve_send)", async () => {
    const r = await resolveUserPermissions(pool, {
      userId: KLEAR_AGENT,
      clientId: KLEAR,
    });
    // Explicit HAS — automation identity capabilities
    for (const key of [
      "work_order:read",
      "work_order:create",
      "work_order:update",
      "workflow:read",
      "workflow:update",
      "workflow_execution:read",
      "workflow_execution:update",
      "workflow_step_run:create",
      "workflow_step_run:update",
      "execution_cycle:create",
      "execution_cycle:reopen",
      "output_package:create",
      "output_package:submit",
      "output_package:validate",
      "output_handoff:create",
      "output_handoff:record",
      "output_handoff:update",
      "external_execution_result:create",
    ]) {
      expect(r.permissions.has(key), `agent_system should have ${key}`).toBe(
        true
      );
    }
    // Explicit LACKS — the boundaries Darrel tightened vs Claude's draft
    for (const key of [
      "output_handoff:approve_send",
      "prompt_override:apply_style",
      "prompt_override:apply_profile_swap",
      "audit_log:read",
      "adapter_config:read",
      "adapter_config:create",
      "adapter_credential:rotate",
      "user:read",
      "user:invite",
      "membership:grant",
      "client:read",
      "system:admin",
      "output_package:delete",
      "workflow_template:publish",
      "work_order:cancel",
      "workflow:cancel",
    ]) {
      expect(
        r.permissions.has(key),
        `agent_system should NOT have ${key}`
      ).toBe(false);
    }
  });

  it("reviewer has output_package:validate + output_candidate:select/reject", async () => {
    const r = await resolveUserPermissions(pool, {
      userId: KLEAR_REVIEWER,
      clientId: KLEAR,
    });
    expect(r.permissions.has("output_package:validate")).toBe(true);
    expect(r.permissions.has("output_candidate:select")).toBe(true);
    expect(r.permissions.has("output_candidate:reject")).toBe(true);
    expect(r.permissions.has("prompt_override:apply_style")).toBe(true);
    // reviewer does not run work
    expect(r.permissions.has("work_order:create")).toBe(false);
    expect(r.permissions.has("output_package:submit")).toBe(false);
  });

  it("viewer is strictly read-only", async () => {
    const r = await resolveUserPermissions(pool, {
      userId: KLEAR_VIEWER,
      clientId: KLEAR,
    });
    expect(r.permissions.has("work_order:read")).toBe(true);
    expect(r.permissions.has("output_package:read")).toBe(true);
    expect(r.permissions.has("work_order:create")).toBe(false);
    expect(r.permissions.has("output_package:validate")).toBe(false);
    expect(r.permissions.has("output_candidate:select")).toBe(false);
    expect(r.permissions.has("prompt_override:apply_style")).toBe(false);
  });

  it("intruder has no membership → empty permission set on either tenant", async () => {
    const klear = await resolveUserPermissions(pool, {
      userId: INTRUDER,
      clientId: KLEAR,
    });
    const ffai = await resolveUserPermissions(pool, {
      userId: INTRUDER,
      clientId: FFAI,
    });
    expect(klear.role).toBeNull();
    expect(klear.permissions.size).toBe(0);
    expect(ffai.role).toBeNull();
    expect(ffai.permissions.size).toBe(0);
  });

  it("super is owner on both tenants (cross-tenant)", async () => {
    const klear = await resolveUserPermissions(pool, {
      userId: SUPER,
      clientId: KLEAR,
    });
    const ffai = await resolveUserPermissions(pool, {
      userId: SUPER,
      clientId: FFAI,
    });
    expect(klear.role).toBe("owner");
    expect(klear.permissions.size).toBe(EXPECTED_COUNTS.owner);
    expect(ffai.role).toBe("owner");
    expect(ffai.permissions.size).toBe(EXPECTED_COUNTS.owner);
  });

  it("Klear operator has no grants on FFAI tenant (tenant isolation)", async () => {
    const r = await resolveUserPermissions(pool, {
      userId: KLEAR_OPERATOR,
      clientId: FFAI,
    });
    expect(r.role).toBeNull();
    expect(r.permissions.size).toBe(0);
  });

  it("FFAI operator resolves with the same grant shape as Klear operator", async () => {
    const ffai = await resolveUserPermissions(pool, {
      userId: FFAI_OPERATOR,
      clientId: FFAI,
    });
    const klear = await resolveUserPermissions(pool, {
      userId: KLEAR_OPERATOR,
      clientId: KLEAR,
    });
    expect(ffai.role).toBe("operator");
    expect(klear.role).toBe("operator");
    expect(ffai.permissions.size).toBe(klear.permissions.size);
    // Same shape — role defaults are tenant-agnostic (data-driven).
    expect([...ffai.permissions].sort()).toEqual([...klear.permissions].sort());
  });

  it("every permission_key in role_permissions is well-formed and in vocabulary", async () => {
    const { rows } = await pool.query<{ permission_key: string }>(
      `SELECT DISTINCT p.permission_key
       FROM role_permissions rp
       JOIN permissions p ON p.id = rp.permission_id`
    );
    for (const r of rows) {
      // lowercase resource:verb, no spaces, colon-separated
      expect(r.permission_key).toMatch(/^[a-z_]+:[a-z_]+$/);
    }
    // At least one representative from each resource family present in seeds
    const keys = new Set(rows.map((r) => r.permission_key));
    expect(keys.has("work_order:create")).toBe(true);
    expect(keys.has("output_handoff:approve_send")).toBe(true);
    expect(keys.has("system:admin")).toBe(true);
    expect(keys.has("audit_log:read")).toBe(true);
  });

  it("permission_scope enum has exactly 3 members", async () => {
    const { rows } = await pool.query<{ enumlabel: string }>(
      `SELECT enumlabel FROM pg_enum
       WHERE enumtypid = 'permission_scope'::regtype
       ORDER BY enumsortorder`
    );
    expect(rows.map((r) => r.enumlabel)).toEqual([
      "global",
      "tenant",
      "resource",
    ]);
  });
});

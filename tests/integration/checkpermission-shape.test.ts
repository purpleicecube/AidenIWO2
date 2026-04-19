import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

import { checkPermission } from "../../packages/contracts/authz/check_permission";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR = "00000000-0000-4000-8000-00000000c001";
const USERS = {
  owner: "00000000-0000-4000-8000-000001000001",
  admin: "00000000-0000-4000-8000-000001000002",
  operator: "00000000-0000-4000-8000-000001000003",
  reviewer: "00000000-0000-4000-8000-000001000004",
  viewer: "00000000-0000-4000-8000-000001000005",
  agent_system: "00000000-0000-4000-8000-000001000006",
  intruder: "00000000-0000-4000-8000-000099000002",
} as const;

// 8-permission matrix covering every relevant boundary in §Q2.
// Rows = roles (including intruder), cols = permissions.
// Value = expected `allowed`.
type RoleKey = keyof typeof USERS;
const MATRIX: { permission: string; expected: Record<RoleKey, boolean> }[] = [
  {
    permission: "work_order:create",
    expected: {
      owner: true,
      admin: true,
      operator: true,
      reviewer: false,
      viewer: false,
      agent_system: true,
      intruder: false,
    },
  },
  {
    permission: "output_package:submit",
    expected: {
      owner: true,
      admin: true,
      operator: true,
      reviewer: false,
      viewer: false,
      agent_system: true,
      intruder: false,
    },
  },
  {
    permission: "output_package:validate",
    expected: {
      owner: true,
      admin: true,
      operator: true,
      reviewer: true,
      viewer: false,
      agent_system: true,
      intruder: false,
    },
  },
  {
    permission: "output_candidate:select",
    expected: {
      owner: true,
      admin: true,
      operator: false,
      reviewer: true,
      viewer: false,
      agent_system: false,
      intruder: false,
    },
  },
  {
    permission: "output_handoff:approve_send",
    expected: {
      owner: true,
      admin: true,
      operator: false,
      reviewer: false,
      viewer: false,
      agent_system: false,
      intruder: false,
    },
  },
  {
    permission: "adapter_credential:rotate",
    expected: {
      owner: true,
      admin: true,
      operator: false,
      reviewer: false,
      viewer: false,
      agent_system: false,
      intruder: false,
    },
  },
  {
    permission: "user:revoke",
    expected: {
      owner: true,
      admin: false,
      operator: false,
      reviewer: false,
      viewer: false,
      agent_system: false,
      intruder: false,
    },
  },
  {
    permission: "system:admin",
    expected: {
      owner: true,
      admin: false,
      operator: false,
      reviewer: false,
      viewer: false,
      agent_system: false,
      intruder: false,
    },
  },
];

describeIwo3("Loop 4 Phase 2 — checkPermission shape matrix (7 roles × 8 perms)", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  for (const row of MATRIX) {
    for (const role of Object.keys(USERS) as RoleKey[]) {
      const expected = row.expected[role];
      const userId = USERS[role];
      it(`${role} × ${row.permission} → ${expected ? "ALLOW" : "DENY"}`, async () => {
        const decision = await checkPermission(pool, {
          userId,
          clientId: KLEAR,
          permission: row.permission,
        });
        expect(
          decision.allowed,
          `${role} ${row.permission} expected ${expected}, got ${decision.allowed} (reason=${decision.reason})`
        ).toBe(expected);
        // Intruder always returns role=null regardless of permission.
        if (role === "intruder") {
          expect(decision.role).toBeNull();
          expect(decision.reason).toBe("no_membership");
        } else {
          expect(decision.role).toBe(role);
        }
      });
    }
  }

  it("unknown permission fails closed with reason=unknown_permission", async () => {
    const decision = await checkPermission(pool, {
      userId: USERS.owner,
      clientId: KLEAR,
      permission: "bogus:does_not_exist",
    });
    expect(decision.allowed).toBe(false);
    expect(decision.reason).toBe("unknown_permission");
  });
});

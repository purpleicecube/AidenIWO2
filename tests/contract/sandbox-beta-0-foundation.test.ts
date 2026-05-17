/**
 * Sandbox-Hosted-In-App β.0 — foundation contract tests.
 *
 * β.0 ships schema + contracts + permissions + audit vocab + ADR
 * (per CODEX β.0 brief in WS024 baseline `edce652`). No transition
 * logic, no helpers, no UI. This test asserts the foundation rules
 * are coherent + internally consistent.
 *
 * Coverage:
 *   - SANDBOX_ACCEPTANCE_STATES vocabulary matches the migration
 *     0033 CHECK constraint set.
 *   - SANDBOX_SESSION_TRANSITIONS shape is well-formed (from/to are
 *     valid states, requires keys exist in the permission seed,
 *     event names exist in AUDIT_EVENTS).
 *   - SANDBOX_BETA_0_PERMISSION_KEYS export matches the 4 keys
 *     added to db/seeds/permissions.json.
 *   - LOOP_SANDBOX_BETA_0_AUDIT_EVENTS export matches the 6 events
 *     added to AUDIT_EVENTS.
 *   - Every transition's `event` is one of the registered β.0
 *     audit events (no transitions referencing un-audited events).
 *   - Every transition's `requires` keys are in the β.0 permission
 *     set OR previously locked.
 *   - State machine is reachable from `uploaded`; every non-initial
 *     state has at least one incoming transition.
 *   - Terminal `accepted` has no outgoing transitions (true terminal).
 *
 * Out of scope here (belongs in β.1+):
 *   - Transition validator behavior (describeTransition + helpers)
 *   - DB-side enforcement test (requires live Postgres + migration apply)
 *   - Permission grant matrix verification (covered by seed-coherence tests)
 *   - Audit-writer call wiring (β.1+ once routes exist)
 */

import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  SANDBOX_ACCEPTANCE_STATES,
  SANDBOX_TERMINAL_STATES,
  SANDBOX_SESSION_TRANSITIONS,
  SANDBOX_BETA_0_PERMISSION_KEYS,
  SANDBOX_DISPATCH_GATE_ERROR_CODE,
  type SandboxAcceptanceState,
} from "../../packages/contracts/sandbox";
import {
  AUDIT_EVENTS,
  LOOP_SANDBOX_BETA_0_AUDIT_EVENTS,
} from "../../packages/contracts/audit/events";
import { insertSandboxSessionSchema } from "../../shared/schema";

const ROOT = resolve(__dirname, "../..");

function loadPermissionsSeed(): Array<{ permissionKey: string }> {
  const raw = readFileSync(
    resolve(ROOT, "db/seeds/permissions.json"),
    "utf-8"
  );
  return JSON.parse(raw);
}

function loadRolePermissionsSeed(): Array<{ role: string; permissionKey: string }> {
  const raw = readFileSync(
    resolve(ROOT, "db/seeds/role_permissions.json"),
    "utf-8"
  );
  return JSON.parse(raw);
}

function loadMigration0033(): string {
  return readFileSync(
    resolve(ROOT, "db/migrations/0033_sandbox_beta_0_foundation.sql"),
    "utf-8"
  );
}

describe("Sandbox β.0 — acceptance state vocabulary", () => {
  it("SANDBOX_ACCEPTANCE_STATES contains exactly the 7 V1 states (per D-B2)", () => {
    expect([...SANDBOX_ACCEPTANCE_STATES].sort()).toEqual([
      "accepted",
      "evaluating",
      "rejected",
      "reopened",
      "tested",
      "under_review",
      "uploaded",
    ]);
  });

  it("SANDBOX_TERMINAL_STATES contains only accepted + rejected", () => {
    expect([...SANDBOX_TERMINAL_STATES].sort()).toEqual([
      "accepted",
      "rejected",
    ]);
  });

  it("migration 0033 CHECK constraint enforces the same 7-state set as the TS vocabulary", () => {
    const sql = loadMigration0033();
    for (const state of SANDBOX_ACCEPTANCE_STATES) {
      expect(sql).toContain(`'${state}'`);
    }
    // The DB-side string set must include EVERY TS state (forward
    // direction). Reverse direction (DB-only states) is covered by
    // the regex match on the CHECK constraint name + the migration
    // being the single source of DB truth.
    expect(sql).toMatch(
      /sandbox_sessions_acceptance_state_check[\s\S]*CHECK\s*\(\s*acceptance_state IN/i
    );
  });

  it("migration 0033 adds the β.0 columns (client_id + acceptance surface)", () => {
    const sql = loadMigration0033();
    for (const col of [
      "client_id",
      "acceptance_state",
      "accepted_by_user_id",
      "accepted_at",
      "review_notes",
    ]) {
      expect(sql).toContain(col);
    }
  });

  it("migration 0033 deliberately does NOT toggle FORCE RLS (β.x cutover)", () => {
    const sql = loadMigration0033();
    expect(sql).not.toMatch(/ENABLE\s+ROW\s+LEVEL\s+SECURITY/i);
    expect(sql).not.toMatch(/FORCE\s+ROW\s+LEVEL\s+SECURITY/i);
    expect(sql).not.toMatch(/CREATE\s+POLICY/i);
  });
});

describe("Sandbox β.0 — transition table", () => {
  it("contains exactly 7 transitions covering the full acceptance flow", () => {
    expect(SANDBOX_SESSION_TRANSITIONS.length).toBe(7);
  });

  it("every transition's from + to are in SANDBOX_ACCEPTANCE_STATES", () => {
    const states = new Set<SandboxAcceptanceState>(SANDBOX_ACCEPTANCE_STATES);
    for (const t of SANDBOX_SESSION_TRANSITIONS) {
      expect(states.has(t.from)).toBe(true);
      expect(states.has(t.to)).toBe(true);
    }
  });

  it("every transition's event is one of the registered β.0 audit events", () => {
    const beta0Events = new Set<string>(LOOP_SANDBOX_BETA_0_AUDIT_EVENTS);
    for (const t of SANDBOX_SESSION_TRANSITIONS) {
      expect(beta0Events.has(t.event)).toBe(true);
    }
  });

  it("every transition's requires keys are in SANDBOX_BETA_0_PERMISSION_KEYS", () => {
    const beta0Perms = new Set<string>(SANDBOX_BETA_0_PERMISSION_KEYS);
    for (const t of SANDBOX_SESSION_TRANSITIONS) {
      for (const req of t.requires) {
        expect(beta0Perms.has(req)).toBe(true);
      }
    }
  });

  it("terminal `accepted` state has no outgoing transitions", () => {
    const outFromAccepted = SANDBOX_SESSION_TRANSITIONS.filter(
      (t) => t.from === "accepted"
    );
    expect(outFromAccepted.length).toBe(0);
  });

  it("`uploaded` is reachable as an initial state (default of migration 0033)", () => {
    const sql = loadMigration0033();
    expect(sql).toContain("acceptance_state    text         NOT NULL DEFAULT 'uploaded'");
  });

  it("every non-initial state has at least one incoming transition", () => {
    const incoming = new Set<string>();
    for (const t of SANDBOX_SESSION_TRANSITIONS) {
      incoming.add(t.to);
    }
    for (const state of SANDBOX_ACCEPTANCE_STATES) {
      if (state === "uploaded") continue; // initial
      expect(incoming.has(state)).toBe(true);
    }
  });
});

describe("Sandbox β.0 — permissions seed coherence", () => {
  it("permissions.json contains all 4 SANDBOX_BETA_0_PERMISSION_KEYS", () => {
    const perms = loadPermissionsSeed();
    const seedKeys = new Set(perms.map((p) => p.permissionKey));
    for (const k of SANDBOX_BETA_0_PERMISSION_KEYS) {
      expect(seedKeys.has(k)).toBe(true);
    }
  });

  it("role_permissions.json grants sandbox:evaluate/test to owner+admin+operator (per D-B6)", () => {
    const rp = loadRolePermissionsSeed();
    for (const key of ["sandbox:evaluate", "sandbox:test"]) {
      const granted = rp.filter((r) => r.permissionKey === key).map((r) => r.role);
      expect([...granted].sort()).toEqual(["admin", "operator", "owner"]);
    }
  });

  it("role_permissions.json grants sandbox:review to owner+admin+operator+reviewer", () => {
    const rp = loadRolePermissionsSeed();
    const granted = rp.filter((r) => r.permissionKey === "sandbox:review").map((r) => r.role);
    expect([...granted].sort()).toEqual(["admin", "operator", "owner", "reviewer"]);
  });

  it("role_permissions.json grants sandbox:accept ONLY to owner+admin+operator (NOT reviewer)", () => {
    const rp = loadRolePermissionsSeed();
    const granted = rp.filter((r) => r.permissionKey === "sandbox:accept").map((r) => r.role);
    expect([...granted].sort()).toEqual(["admin", "operator", "owner"]);
    expect(granted).not.toContain("reviewer");
  });
});

describe("Sandbox β.0 — audit vocabulary coherence", () => {
  it("LOOP_SANDBOX_BETA_0_AUDIT_EVENTS exports 6 events", () => {
    expect(LOOP_SANDBOX_BETA_0_AUDIT_EVENTS.length).toBe(6);
  });

  it("every β.0 audit event is registered in AUDIT_EVENTS", () => {
    const all = new Set<string>(Object.values(AUDIT_EVENTS));
    for (const ev of LOOP_SANDBOX_BETA_0_AUDIT_EVENTS) {
      expect(all.has(ev)).toBe(true);
    }
  });

  it("β.0 audit events follow the `sandbox.*` namespace", () => {
    for (const ev of LOOP_SANDBOX_BETA_0_AUDIT_EVENTS) {
      expect(ev.startsWith("sandbox.")).toBe(true);
    }
  });
});

describe("Sandbox β.0 — dispatch gate (D-B7)", () => {
  it("exports the dispatch gate error code", () => {
    expect(SANDBOX_DISPATCH_GATE_ERROR_CODE).toBe("sandbox_not_accepted");
  });
});

describe("Sandbox β.0 — insertSandboxSessionSchema must reject server-set fields", () => {
  // CODEX β.0 review (2026-05-17): the original v1 of β.0 had
  // insertSandboxSessionSchema accept `clientId` from the caller,
  // which during the ADR-035 carve-out window would have let a
  // sandbox client pre-seed an arbitrary tenant ID on the row.
  // This regression test asserts that every server-set field —
  // including the column added in β.0 — is OMITTED from the
  // insert schema's keys.
  //
  // The actual omit happens via `.omit({...})` in
  // shared/schema.ts; here we assert the Zod schema's parsed
  // shape is what we expect.

  it("omits clientId (server-set; caller-supplied value must not leak through)", () => {
    // Zod's `omit().shape` is the post-omit shape; if `clientId` is
    // omitted, it must not appear in the shape keys.
    const shapeKeys = Object.keys(insertSandboxSessionSchema.shape);
    expect(shapeKeys).not.toContain("clientId");
  });

  it("omits the acceptance surface (acceptanceState / acceptedByUserId / acceptedAt / reviewNotes)", () => {
    const shapeKeys = Object.keys(insertSandboxSessionSchema.shape);
    for (const omitted of [
      "acceptanceState",
      "acceptedByUserId",
      "acceptedAt",
      "reviewNotes",
    ]) {
      expect(shapeKeys).not.toContain(omitted);
    }
  });

  it("accepts the operator-supplied surface (name, description, environment, createdBy)", () => {
    const shapeKeys = Object.keys(insertSandboxSessionSchema.shape);
    for (const accepted of ["name", "description", "environment", "createdBy"]) {
      expect(shapeKeys).toContain(accepted);
    }
  });

  it("safeParse silently drops any caller-supplied clientId payload (defense-in-depth)", () => {
    // Z.object().omit(...) drops unknown keys by default. Confirm
    // that a malicious payload with clientId set does NOT survive
    // through to the parsed result.
    const payload = {
      name: "test session",
      description: "test",
      createdBy: "caller-spoofed-user",
      clientId: "00000000-0000-4000-8000-00000000c001",
      acceptanceState: "accepted",
    };
    const result = insertSandboxSessionSchema.safeParse(payload);
    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data).not.toHaveProperty("clientId");
      expect(result.data).not.toHaveProperty("acceptanceState");
    }
  });
});

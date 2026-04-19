import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";

import { resolveAdapterPolicy } from "../../packages/contracts/adapter/policy_resolver";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const KLEAR_CLIENT = "00000000-0000-4000-8000-00000000c001";
const FFAI_CLIENT = "00000000-0000-4000-8000-00000000c002";

describeIwo3("Loop 3 Phase 2 — adapter policy resolution", () => {
  const pool = new Pool({ connectionString: url });
  afterAll(async () => {
    await pool.end();
  });

  it("no row → default 'none' (Klear / gamma / generate)", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: KLEAR_CLIENT,
        adapterKey: "gamma",
        actionKey: "generate",
      });
      expect(result.mode).toBe("none");
      expect(result.policyRowId).toBeNull();
      expect(result.reason).toBeNull();
    } finally {
      c.release();
    }
  });

  it("Klear email_campaign.send → approval_required", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: KLEAR_CLIENT,
        adapterKey: "email_campaign",
        actionKey: "send",
      });
      expect(result.mode).toBe("approval_required");
      expect(result.policyRowId).not.toBeNull();
      expect(result.reason).toMatch(/approval/i);
    } finally {
      c.release();
    }
  });

  it("FFAI email_campaign.send → approval_required (policy exists even though adapter not enabled)", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: FFAI_CLIENT,
        adapterKey: "email_campaign",
        actionKey: "send",
      });
      expect(result.mode).toBe("approval_required");
    } finally {
      c.release();
    }
  });

  it("Klear crm.create_record → disallowed", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: KLEAR_CLIENT,
        adapterKey: "crm",
        actionKey: "create_record",
      });
      expect(result.mode).toBe("disallowed");
    } finally {
      c.release();
    }
  });

  it("FFAI crm.create_record → disallowed", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: FFAI_CLIENT,
        adapterKey: "crm",
        actionKey: "create_record",
      });
      expect(result.mode).toBe("disallowed");
    } finally {
      c.release();
    }
  });

  it("FFAI google_drive.upload → approval_required", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: FFAI_CLIENT,
        adapterKey: "google_drive",
        actionKey: "upload",
      });
      expect(result.mode).toBe("approval_required");
    } finally {
      c.release();
    }
  });

  it("Klear google_drive.upload → none (no row, default)", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: KLEAR_CLIENT,
        adapterKey: "google_drive",
        actionKey: "upload",
      });
      expect(result.mode).toBe("none");
      expect(result.policyRowId).toBeNull();
    } finally {
      c.release();
    }
  });

  it("unknown adapter key → none (adapter catalog miss; no row)", async () => {
    const c = await pool.connect();
    try {
      const result = await resolveAdapterPolicy(c, {
        clientId: KLEAR_CLIENT,
        adapterKey: "nonexistent_adapter",
        actionKey: "generate",
      });
      expect(result.mode).toBe("none");
      expect(result.policyRowId).toBeNull();
    } finally {
      c.release();
    }
  });
});

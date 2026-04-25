import { describe, it, expect, afterAll } from "vitest";
import { Pool } from "pg";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  buildContractSnapshot,
  loadAuditEvents,
  type ContractSnapshot,
} from "./_snapshot-helpers";

const url = process.env.IWO3_DATABASE_URL;
const describeIwo3 = url ? describe : describe.skip;

const SNAPSHOT_PATH = resolve(
  __dirname,
  "../fixtures/contract-enums.snapshot.json"
);

function loadSnapshot(): ContractSnapshot {
  return JSON.parse(readFileSync(SNAPSHOT_PATH, "utf-8")) as ContractSnapshot;
}

describeIwo3("Loop 5 Phase 5.1 — contract surface enum freeze", () => {
  const pool = new Pool({ connectionString: url });

  afterAll(async () => {
    await pool.end();
  });

  it("DB enums match the frozen snapshot (every value, ordered)", async () => {
    const snap = loadSnapshot();
    const live = await buildContractSnapshot(pool);

    // Compare enum-by-enum so failures report which enum diverged
    // rather than a massive diff.
    const snapNames = new Set(Object.keys(snap.dbEnums));
    const liveNames = new Set(Object.keys(live.dbEnums));
    expect(
      [...liveNames].sort(),
      "DB enum names differ from snapshot — update tests/fixtures/contract-enums.snapshot.json in the same commit"
    ).toEqual([...snapNames].sort());

    for (const name of snapNames) {
      expect(
        live.dbEnums[name],
        `enum '${name}' values diverged — update snapshot OR revert the change`
      ).toEqual(snap.dbEnums[name]);
    }
  });

  it("audit event vocabulary matches the frozen snapshot", () => {
    const snap = loadSnapshot();
    const live = loadAuditEvents();
    expect(
      live.all,
      "AUDIT_EVENTS vocabulary diverged — update snapshot OR revert the change"
    ).toEqual(snap.auditEvents.all);
    for (const loopKey of Object.keys(snap.auditEvents.byLoop)) {
      expect(
        live.byLoop[loopKey],
        `${loopKey} diverged from snapshot`
      ).toEqual(snap.auditEvents.byLoop[loopKey]);
    }
  });

  it("permission_key vocabulary matches the frozen snapshot (§Q1 lock_upfront)", async () => {
    const snap = loadSnapshot();
    const { rows } = await pool.query<{ permission_key: string }>(
      `SELECT permission_key FROM permissions ORDER BY permission_key`
    );
    const live = rows.map((r) => r.permission_key);
    expect(
      live,
      "permission_key vocabulary diverged — ADR-014 §Q1 locked this upfront; update snapshot in the same commit as the schema change"
    ).toEqual(snap.permissionKeys);
  });

  it("snapshot cardinalities match expected Loop 1-9 baselines", () => {
    const snap = loadSnapshot();
    expect(Object.keys(snap.dbEnums).length).toBe(39);
    expect(snap.auditEvents.all.length).toBe(79);
    expect(snap.permissionKeys.length).toBe(69);
    // Every locked per-loop array carries the right shape.
    expect(snap.auditEvents.byLoop.LOOP_2_AUDIT_EVENTS.length).toBe(12);
    expect(snap.auditEvents.byLoop.LOOP_3_PHASE_1_AUDIT_EVENTS.length).toBe(13);
    expect(snap.auditEvents.byLoop.LOOP_3_PHASE_2_AUDIT_EVENTS.length).toBe(18);
    expect(snap.auditEvents.byLoop.LOOP_3_PHASE_4_AUDIT_EVENTS.length).toBe(7);
    expect(snap.auditEvents.byLoop.LOOP_4_PHASE_1_AUDIT_EVENTS.length).toBe(5);
    expect(snap.auditEvents.byLoop.LOOP_4_PHASE_2_AUDIT_EVENTS.length).toBe(1);
    expect(snap.auditEvents.byLoop.LOOP_6_PHASE_1_AUDIT_EVENTS.length).toBe(12);
    expect(snap.auditEvents.byLoop.LOOP_9_PHASE_1_AUDIT_EVENTS.length).toBe(4);
    expect(snap.auditEvents.byLoop.LOOP_9_PHASE_2_AUDIT_EVENTS.length).toBe(2);
    expect(snap.auditEvents.byLoop.LOOP_9_PHASE_3_AUDIT_EVENTS.length).toBe(3);
    expect(snap.auditEvents.byLoop.LOOP_9_PHASE_4_AUDIT_EVENTS.length).toBe(2);
  });
});


// P1-3: Reliability Tests — Stale/Orphan Recovery + Watchdog
// Covers recoverOrphanedProcessingOrders(), isStaleProcessing(), watchdogSweep()

import { describe, it, expect, vi, beforeEach } from "vitest";
import { recoverOrphanedProcessingOrders, isStaleProcessing, watchdogSweep } from "../orchestration.js";

// ── Mock storage ──────────────────────────────────────────────────────────────
vi.mock("../storage.js", () => ({
  storage: {
    getWorkOrders: vi.fn(),
    updateWorkOrder: vi.fn().mockResolvedValue({}),
    createExecutionLog: vi.fn().mockResolvedValue({}),
  },
}));

import { storage } from "../storage.js";

const STALE_MS = 11 * 60 * 1000; // just over the 10-minute threshold

function makeOrder(overrides: Record<string, any> = {}) {
  return {
    id: "wo-test",
    title: "Test Order",
    status: "processing",
    updatedAt: new Date(Date.now() - STALE_MS).toISOString(),
    ...overrides,
  };
}

// ── isStaleProcessing ─────────────────────────────────────────────────────────

describe("isStaleProcessing()", () => {
  it("returns true when order is processing and updatedAt > 10 min ago", () => {
    const order = makeOrder();
    expect(isStaleProcessing(order)).toBe(true);
  });

  it("returns false when order is processing but recent (< 10 min)", () => {
    const order = makeOrder({ updatedAt: new Date(Date.now() - 60_000).toISOString() });
    expect(isStaleProcessing(order)).toBe(false);
  });

  it("returns false when status is not 'processing'", () => {
    const order = makeOrder({ status: "blocked" });
    expect(isStaleProcessing(order)).toBe(false);
  });

  it("returns false when updatedAt is null", () => {
    const order = makeOrder({ updatedAt: null });
    expect(isStaleProcessing(order)).toBe(false);
  });

  it("returns false for a fresh completed order", () => {
    const order = makeOrder({ status: "completed", updatedAt: new Date(Date.now() - STALE_MS).toISOString() });
    expect(isStaleProcessing(order)).toBe(false);
  });
});

// ── recoverOrphanedProcessingOrders ──────────────────────────────────────────

describe("recoverOrphanedProcessingOrders()", () => {
  beforeEach(() => vi.clearAllMocks());

  it("resets stale processing orders to failed and logs recovery", async () => {
    const staleOrder = makeOrder({ id: "wo-stale" });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([staleOrder] as any);

    const count = await recoverOrphanedProcessingOrders();

    expect(count).toBe(1);
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-stale", expect.objectContaining({ status: "failed", processingAttemptId: null, heartbeatAt: null, processingStartedAt: null }));
    expect(storage.createExecutionLog).toHaveBeenCalledWith(
      expect.objectContaining({ workOrderId: "wo-stale", action: "System: Orphan Recovery" })
    );
  });

  it("does not touch recent processing orders", async () => {
    const freshOrder = makeOrder({ id: "wo-fresh", updatedAt: new Date(Date.now() - 30_000).toISOString() });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([freshOrder] as any);

    const count = await recoverOrphanedProcessingOrders();

    expect(count).toBe(0);
    expect(storage.updateWorkOrder).not.toHaveBeenCalled();
  });

  it("handles mix of stale and fresh orders — only resets stale", async () => {
    const stale = makeOrder({ id: "wo-stale" });
    const fresh = makeOrder({ id: "wo-fresh", updatedAt: new Date(Date.now() - 60_000).toISOString() });
    const blocked = makeOrder({ id: "wo-blocked", status: "blocked" });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([stale, fresh, blocked] as any);

    const count = await recoverOrphanedProcessingOrders();

    expect(count).toBe(1);
    expect(storage.updateWorkOrder).toHaveBeenCalledTimes(1);
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-stale", expect.objectContaining({ status: "failed" }));
  });

  it("returns 0 when no orders exist", async () => {
    vi.mocked(storage.getWorkOrders).mockResolvedValue([]);
    const count = await recoverOrphanedProcessingOrders();
    expect(count).toBe(0);
  });
});

// ── watchdogSweep ─────────────────────────────────────────────────────────────

describe("watchdogSweep()", () => {
  beforeEach(() => vi.clearAllMocks());

  it("recovers WO with stale heartbeat (>60s since last heartbeat)", async () => {
    const staleWO = makeOrder({
      id: "wo-stale-hb",
      heartbeatAt: new Date(Date.now() - 90_000).toISOString(), // 90s ago
      processingStartedAt: new Date(Date.now() - 120_000).toISOString(),
      processingAttemptId: "old-attempt-123",
    });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([staleWO] as any);

    const count = await watchdogSweep();

    expect(count).toBe(1);
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-stale-hb", expect.objectContaining({
      status: "failed",
      heartbeatAt: null,
      processingStartedAt: null,
    }));
    // Verify attemptId was changed (invalidated)
    const updateCall = vi.mocked(storage.updateWorkOrder).mock.calls[0];
    expect(updateCall[1].processingAttemptId).not.toBe("old-attempt-123");
    expect(storage.createExecutionLog).toHaveBeenCalledWith(
      expect.objectContaining({ workOrderId: "wo-stale-hb", action: "Watchdog: Stuck Detection" })
    );
  });

  it("does NOT recover WO with fresh heartbeat", async () => {
    const freshWO = makeOrder({
      id: "wo-fresh-hb",
      heartbeatAt: new Date(Date.now() - 10_000).toISOString(), // 10s ago — fresh
      processingStartedAt: new Date(Date.now() - 300_000).toISOString(), // 5min total but heartbeat is fresh
      processingAttemptId: "active-attempt",
    });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([freshWO] as any);

    const count = await watchdogSweep();

    expect(count).toBe(0);
    expect(storage.updateWorkOrder).not.toHaveBeenCalled();
  });

  it("routes WO that exceeds hard ceiling but has fresh heartbeat to awaiting_operator (BUG-053 soft timeout)", async () => {
    const longRunning = makeOrder({
      id: "wo-too-long",
      heartbeatAt: new Date(Date.now() - 5_000).toISOString(), // 5s ago — fresh heartbeat
      processingStartedAt: new Date(Date.now() - 11 * 60 * 1000).toISOString(), // 11min — exceeds 10min ceiling
      processingAttemptId: "long-attempt",
    });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([longRunning] as any);

    const count = await watchdogSweep();

    expect(count).toBe(1);
    // BUG-053: budget exceeded + fresh heartbeat → soft timeout (awaiting_operator), not hard fail
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-too-long", expect.objectContaining({
      status: "awaiting_operator",
      bdmMarker: expect.objectContaining({ type: "watchdog_budget_exceeded" }),
    }));
  });

  it("skips non-processing orders", async () => {
    const completed = makeOrder({ id: "wo-done", status: "completed" });
    const pending = makeOrder({ id: "wo-pending", status: "pending" });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([completed, pending] as any);

    const count = await watchdogSweep();

    expect(count).toBe(0);
    expect(storage.updateWorkOrder).not.toHaveBeenCalled();
  });

  it("falls back to updatedAt when heartbeatAt is null (pre-migration WO)", async () => {
    const preMigration = makeOrder({
      id: "wo-pre-migration",
      heartbeatAt: null,
      processingAttemptId: null,
      // updatedAt is 11 min ago (from makeOrder default = STALE_MS)
    });
    vi.mocked(storage.getWorkOrders).mockResolvedValue([preMigration] as any);

    const count = await watchdogSweep();

    // Should be recovered because updatedAt > 60s threshold
    expect(count).toBe(1);
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-pre-migration", expect.objectContaining({ status: "failed" }));
  });
});

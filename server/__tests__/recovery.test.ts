// P1-3: Reliability Tests — Stale/Orphan Recovery
// Covers recoverOrphanedProcessingOrders() and isStaleProcessing()

import { describe, it, expect, vi, beforeEach } from "vitest";
import { recoverOrphanedProcessingOrders, isStaleProcessing } from "../orchestration.js";

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
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-stale", { status: "failed" });
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
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-stale", { status: "failed" });
  });

  it("returns 0 when no orders exist", async () => {
    vi.mocked(storage.getWorkOrders).mockResolvedValue([]);
    const count = await recoverOrphanedProcessingOrders();
    expect(count).toBe(0);
  });
});

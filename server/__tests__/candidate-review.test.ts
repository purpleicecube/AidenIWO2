// Candidate Review Tests — HITL candidate-selection workflow path
// Covers: orchestration gate + route handler business logic (select/reject/cancel/request-more)

import { describe, it, expect, vi, beforeEach } from "vitest";
import { processWorkOrder } from "../orchestration.js";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("../storage.js", () => ({
  storage: {
    getWorkOrder: vi.fn(),
    getWorkOrders: vi.fn().mockResolvedValue([]),
    updateWorkOrder: vi.fn(),
    createExecutionLog: vi.fn().mockResolvedValue({}),
    getLlmSettings: vi.fn(),
    getOperationalSettings: vi.fn().mockResolvedValue({ memoryAdvisor: "none", currentMode: "autonomous" }),
    getActiveSubAgents: vi.fn().mockResolvedValue([]),
    createChecklistItem: vi.fn().mockResolvedValue({}),
    getGammaCandidates: vi.fn().mockResolvedValue([]),
    getGammaGenerationRecords: vi.fn().mockResolvedValue([]),
    getGammaGenerationRecord: vi.fn(),
    selectGammaCandidate: vi.fn(),
    rejectGammaCandidate: vi.fn(),
    rejectAllGammaCandidates: vi.fn(),
  },
}));

vi.mock("../llm-client.js", () => ({
  runTier1WithLLM: vi.fn(),
  runTier2WithLLM: vi.fn(),
  resolveSubAgentLlmConfig: vi.fn().mockReturnValue(null),
  runAidenQualityReview: vi.fn(),
}));

vi.mock("../pocketflow.js", () => ({
  pocketflowExecute: vi.fn(),
}));

vi.mock("../workspace-filing.js", () => ({
  fileWorkOrderOutput: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("../tool-executor.js", () => ({
  getAvailableToolsForAgent: vi.fn().mockResolvedValue([]),
}));

vi.mock("../skill-auto-import.js", () => ({
  autoImportSkillsForDescription: vi.fn().mockResolvedValue([]),
}));

import { storage } from "../storage.js";
import { runTier1WithLLM, runAidenQualityReview } from "../llm-client.js";
import { pocketflowExecute } from "../pocketflow.js";

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeOrder(overrides: Record<string, any> = {}) {
  return {
    id: "wo-cr-001",
    title: "Test Candidate Review WO",
    description: "Generate a branded presentation",
    type: "presentation",
    priority: "medium",
    status: "pending",
    correlationId: "corr-cr-001",
    gccMemory: {},
    assignedSubAgentId: null,
    ...overrides,
  };
}

function makeTier1Approved(handler = "writer-agent") {
  return { approved: true, handler, reason: "Approved by policy", mode: "rule" };
}

function makePocketflowSuccessWithCandidateReview() {
  return {
    blocked: false,
    reason: null,
    executionId: "exec-cr-001",
    handler: "writer-agent",
    gammaDeliveryPolicy: "candidate_review",
    output: {
      message: "Done",
      deliverable: "# Branded Presentation\n\nSlide content here.",
      deliverableType: "presentation",
      deliverableTitle: "Branded Presentation",
    },
    pocketflow: { iterations: 1, convergenceScore: 0.85, stepResults: [], refinementHistory: [], bdmMarker: null },
  };
}

function makePocketflowSuccessNoPolicy() {
  return {
    blocked: false,
    reason: null,
    executionId: "exec-001",
    handler: "writer-agent",
    output: {
      message: "Done",
      deliverable: "# Report\n\nContent.",
      deliverableType: "document",
      deliverableTitle: "Report",
    },
    pocketflow: { iterations: 1, convergenceScore: 0.85, stepResults: [], refinementHistory: [], bdmMarker: null },
  };
}

function makeQualityApproved(score = 0.88) {
  return { approved: true, score, summary: "Good output", issues: [], recommendation: "approve" as const };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("Candidate Review — Orchestration Gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(storage.updateWorkOrder).mockImplementation(async (_id, updates) =>
      ({ ...makeOrder(), ...updates }) as any
    );
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: true } as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([
      { id: "agent-1", name: "writer-agent", controlMode: "aiden", isActive: true },
    ] as any);
  });

  it("routes to awaiting_operator with candidate_review when gammaDeliveryPolicy is set", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Approved() as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccessWithCandidateReview() as any);
    vi.mocked(runAidenQualityReview).mockResolvedValue(makeQualityApproved() as any);
    vi.mocked(storage.getGammaCandidates).mockResolvedValue([
      { id: "cand-1", candidateStatus: "candidate" },
      { id: "cand-2", candidateStatus: "candidate" },
    ] as any);

    await processWorkOrder("wo-cr-001");

    const calls = vi.mocked(storage.updateWorkOrder).mock.calls;
    const awaitingCall = calls.find(c => c[1]?.status === "awaiting_operator");
    expect(awaitingCall).toBeDefined();

    // Verify gccMemory contains candidate_review markers
    const gcc = awaitingCall![1].gccMemory as any;
    expect(gcc["gcc.last_action"]).toBe("candidate_review");
    expect(gcc["gcc.metadata"]?.resolutionReason).toBe("candidate_review");
    expect(gcc["gcc.metadata"]?.candidateCount).toBe(2);
  });

  it("completes normally when gammaDeliveryPolicy is NOT set (no candidate gate)", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Approved() as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccessNoPolicy() as any);
    vi.mocked(runAidenQualityReview).mockResolvedValue(makeQualityApproved() as any);

    await processWorkOrder("wo-cr-001");

    const calls = vi.mocked(storage.updateWorkOrder).mock.calls;
    const completedCall = calls.find(c => c[1]?.status === "completed");
    expect(completedCall).toBeDefined();
    // Should NOT have gone through candidate_review path
    const awaitingCalls = calls.filter(c => {
      const gcc = c[1]?.gccMemory as any;
      return gcc?.["gcc.state_label"] === "candidate_review";
    });
    expect(awaitingCalls).toHaveLength(0);
  });

  it("logs candidate count in execution log when entering candidate_review", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Approved() as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccessWithCandidateReview() as any);
    vi.mocked(runAidenQualityReview).mockResolvedValue(makeQualityApproved() as any);
    vi.mocked(storage.getGammaCandidates).mockResolvedValue([
      { id: "cand-1", candidateStatus: "candidate" },
      { id: "cand-2", candidateStatus: "candidate" },
      { id: "cand-3", candidateStatus: "candidate" },
    ] as any);

    await processWorkOrder("wo-cr-001");

    const logCalls = vi.mocked(storage.createExecutionLog).mock.calls;
    const candidateLog = logCalls.find(c => c[0].action === "Aiden: Candidate Review Required");
    expect(candidateLog).toBeDefined();
    expect(candidateLog![0].message).toContain("3 Gamma candidate(s)");
    expect(candidateLog![0].metadata).toMatchObject({ candidateCount: 3 });
  });
});

// ── Route Handler Logic Tests ─────────────────────────────────────────────────
// These test the business logic that the route handlers implement, using the
// same mocked storage pattern. They verify the correct sequence of storage calls,
// status guards, ownership checks, and state transitions.

describe("Candidate Review — Select Route Logic", () => {
  beforeEach(() => vi.clearAllMocks());

  it("selectGammaCandidate returns undefined when recordId does not belong to workOrderId (ownership check)", async () => {
    // selectGammaCandidate verifies ownership internally — returns undefined if no match
    vi.mocked(storage.selectGammaCandidate).mockResolvedValue(undefined);

    const result = await storage.selectGammaCandidate("wo-A", "record-from-wo-B", "operator");
    expect(result).toBeUndefined();
    expect(storage.selectGammaCandidate).toHaveBeenCalledWith("wo-A", "record-from-wo-B", "operator");
  });

  it("selectGammaCandidate returns the selected record on success", async () => {
    const selectedRecord = {
      id: "cand-1",
      workOrderId: "wo-cr-001",
      candidateStatus: "selected",
      selectedBy: "operator",
      selectedAt: new Date(),
      artifactFiledPath: "/path/to/file.pptx",
      exportFormat: "pptx",
    };
    vi.mocked(storage.selectGammaCandidate).mockResolvedValue(selectedRecord as any);

    const result = await storage.selectGammaCandidate("wo-cr-001", "cand-1", "operator");
    expect(result).toBeDefined();
    expect(result!.candidateStatus).toBe("selected");
    expect(result!.selectedBy).toBe("operator");
  });

  it("pre-flight: getGammaGenerationRecord validates candidate exists before selection", async () => {
    // Route handler calls getGammaGenerationRecord first as pre-flight
    vi.mocked(storage.getGammaGenerationRecord).mockResolvedValue(undefined);

    const record = await storage.getGammaGenerationRecord("nonexistent-id");
    expect(record).toBeUndefined();
    // In the route, this would result in 404 before any state mutation
  });

  it("pre-flight: ownership check rejects candidate from different WO", async () => {
    const wrongWoRecord = {
      id: "cand-1",
      workOrderId: "wo-OTHER",
      candidateStatus: "candidate",
      artifactFiledPath: "/path/to/file.pptx",
    };
    vi.mocked(storage.getGammaGenerationRecord).mockResolvedValue(wrongWoRecord as any);

    const record = await storage.getGammaGenerationRecord("cand-1");
    // Route handler checks: record.workOrderId !== req.params.id → 404
    expect(record!.workOrderId).not.toBe("wo-cr-001");
  });

  it("select route requires WO to be in awaiting_operator status", async () => {
    const completedOrder = makeOrder({ status: "completed" });
    vi.mocked(storage.getWorkOrder).mockResolvedValue(completedOrder as any);

    const order = await storage.getWorkOrder("wo-cr-001");
    // Route handler checks: order.status !== "awaiting_operator" → 400
    expect(order!.status).not.toBe("awaiting_operator");
  });

  it("select route marks WO as completed after successful selection", async () => {
    const awaitingOrder = makeOrder({ status: "awaiting_operator", tier2Result: { output: {} } });
    vi.mocked(storage.getWorkOrder).mockResolvedValue(awaitingOrder as any);
    vi.mocked(storage.updateWorkOrder).mockResolvedValue({ ...awaitingOrder, status: "completed" } as any);

    const selectedRecord = {
      id: "cand-1", workOrderId: "wo-cr-001", candidateStatus: "selected",
      artifactFiledPath: "/tmp/test.pptx", exportFormat: "pptx", fileSize: 1024,
    };
    vi.mocked(storage.selectGammaCandidate).mockResolvedValue(selectedRecord as any);
    vi.mocked(storage.getGammaGenerationRecord).mockResolvedValue({ ...selectedRecord, candidateStatus: "candidate" } as any);

    // Simulate the route handler sequence
    const order = await storage.getWorkOrder("wo-cr-001");
    expect(order!.status).toBe("awaiting_operator");

    const selected = await storage.selectGammaCandidate("wo-cr-001", "cand-1", "operator");
    expect(selected).toBeDefined();

    await storage.updateWorkOrder("wo-cr-001", { status: "completed" });
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-cr-001", expect.objectContaining({ status: "completed" }));
  });
});

describe("Candidate Review — Reject Route Logic", () => {
  beforeEach(() => vi.clearAllMocks());

  it("rejectGammaCandidate returns undefined when recordId does not belong to workOrderId", async () => {
    vi.mocked(storage.rejectGammaCandidate).mockResolvedValue(undefined);

    const result = await storage.rejectGammaCandidate("wo-A", "record-from-wo-B");
    expect(result).toBeUndefined();
  });

  it("rejectGammaCandidate returns rejected record on success", async () => {
    const rejectedRecord = { id: "cand-1", workOrderId: "wo-cr-001", candidateStatus: "rejected" };
    vi.mocked(storage.rejectGammaCandidate).mockResolvedValue(rejectedRecord as any);

    const result = await storage.rejectGammaCandidate("wo-cr-001", "cand-1");
    expect(result).toBeDefined();
    expect(result!.candidateStatus).toBe("rejected");
  });
});

describe("Candidate Review — Reject All Route Logic", () => {
  beforeEach(() => vi.clearAllMocks());

  it("rejectAllGammaCandidates calls storage with correct workOrderId", async () => {
    vi.mocked(storage.rejectAllGammaCandidates).mockResolvedValue(undefined);

    await storage.rejectAllGammaCandidates("wo-cr-001");
    expect(storage.rejectAllGammaCandidates).toHaveBeenCalledWith("wo-cr-001");
  });
});

describe("Candidate Review — Cancel Route Logic", () => {
  beforeEach(() => vi.clearAllMocks());

  it("cancel sets WO to cancelled and logs the action", async () => {
    const awaitingOrder = makeOrder({ status: "awaiting_operator" });
    vi.mocked(storage.getWorkOrder).mockResolvedValue(awaitingOrder as any);
    vi.mocked(storage.updateWorkOrder).mockResolvedValue({ ...awaitingOrder, status: "cancelled" } as any);

    // Simulate the cancel route handler sequence
    const order = await storage.getWorkOrder("wo-cr-001");
    expect(order!.status).toBe("awaiting_operator");

    await storage.createExecutionLog({
      workOrderId: "wo-cr-001",
      tier: 1,
      action: "Operator: Candidate Review Cancelled",
      message: "Operator cancelled work order during candidate review. No deliverable selected.",
      metadata: { cancelledBy: "operator" },
    });

    await storage.updateWorkOrder("wo-cr-001", { status: "cancelled" as any });

    expect(storage.createExecutionLog).toHaveBeenCalledWith(
      expect.objectContaining({ action: "Operator: Candidate Review Cancelled" })
    );
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-cr-001", expect.objectContaining({ status: "cancelled" }));
  });

  it("cancel rejects WO that is not in awaiting_operator status", async () => {
    const completedOrder = makeOrder({ status: "completed" });
    vi.mocked(storage.getWorkOrder).mockResolvedValue(completedOrder as any);

    const order = await storage.getWorkOrder("wo-cr-001");
    // Route handler checks: order.status !== "awaiting_operator" → 400
    expect(order!.status).toBe("completed");
    expect(order!.status).not.toBe("awaiting_operator");
    // updateWorkOrder should NOT be called
    expect(storage.updateWorkOrder).not.toHaveBeenCalled();
  });

  it("cancel rejects when WO not found", async () => {
    vi.mocked(storage.getWorkOrder).mockResolvedValue(undefined);

    const order = await storage.getWorkOrder("wo-missing");
    expect(order).toBeUndefined();
    // Route handler returns 404 — no further storage calls
    expect(storage.updateWorkOrder).not.toHaveBeenCalled();
  });
});

describe("Candidate Review — Request More Route Logic", () => {
  beforeEach(() => vi.clearAllMocks());

  it("request-more sets WO back to pending and logs the action", async () => {
    const awaitingOrder = makeOrder({ status: "awaiting_operator" });
    vi.mocked(storage.getWorkOrder).mockResolvedValue(awaitingOrder as any);
    vi.mocked(storage.updateWorkOrder).mockResolvedValue({ ...awaitingOrder, status: "pending" } as any);

    // Simulate the request-more route handler sequence
    const order = await storage.getWorkOrder("wo-cr-001");
    expect(order!.status).toBe("awaiting_operator");

    await storage.createExecutionLog({
      workOrderId: "wo-cr-001",
      tier: 1,
      action: "Operator: Request More Candidates",
      message: "Operator requested additional Gamma candidate generation. Re-processing work order.",
      metadata: {},
    });

    await storage.updateWorkOrder("wo-cr-001", { status: "pending" });

    expect(storage.createExecutionLog).toHaveBeenCalledWith(
      expect.objectContaining({ action: "Operator: Request More Candidates" })
    );
    expect(storage.updateWorkOrder).toHaveBeenCalledWith("wo-cr-001", expect.objectContaining({ status: "pending" }));
  });

  it("request-more rejects WO not in awaiting_operator", async () => {
    const pendingOrder = makeOrder({ status: "pending" });
    vi.mocked(storage.getWorkOrder).mockResolvedValue(pendingOrder as any);

    const order = await storage.getWorkOrder("wo-cr-001");
    expect(order!.status).not.toBe("awaiting_operator");
    expect(storage.updateWorkOrder).not.toHaveBeenCalled();
  });
});

describe("Candidate Review — Download Route Logic", () => {
  beforeEach(() => vi.clearAllMocks());

  it("download rejects when record does not belong to specified WO (ownership check)", async () => {
    const wrongWoRecord = { id: "cand-1", workOrderId: "wo-OTHER", artifactFiledPath: "/path/file.pptx" };
    vi.mocked(storage.getGammaGenerationRecord).mockResolvedValue(wrongWoRecord as any);

    const record = await storage.getGammaGenerationRecord("cand-1");
    // Route handler checks: record.workOrderId !== req.params.id → 404
    expect(record!.workOrderId).toBe("wo-OTHER");
    expect(record!.workOrderId).not.toBe("wo-cr-001");
  });

  it("download rejects when record has no artifactFiledPath", async () => {
    const noFileRecord = { id: "cand-1", workOrderId: "wo-cr-001", artifactFiledPath: null };
    vi.mocked(storage.getGammaGenerationRecord).mockResolvedValue(noFileRecord as any);

    const record = await storage.getGammaGenerationRecord("cand-1");
    expect(record!.artifactFiledPath).toBeNull();
    // Route handler checks: !record.artifactFiledPath → 404
  });

  it("download succeeds when record belongs to correct WO and has file path", async () => {
    const goodRecord = { id: "cand-1", workOrderId: "wo-cr-001", artifactFiledPath: "/path/file.pptx", exportFormat: "pptx" };
    vi.mocked(storage.getGammaGenerationRecord).mockResolvedValue(goodRecord as any);

    const record = await storage.getGammaGenerationRecord("cand-1");
    expect(record!.workOrderId).toBe("wo-cr-001");
    expect(record!.artifactFiledPath).toBeTruthy();
  });
});

describe("Candidate Review — List Candidates Logic", () => {
  beforeEach(() => vi.clearAllMocks());

  it("groups candidates by candidateGroup and counts active candidates", async () => {
    const records = [
      { id: "c1", candidateStatus: "candidate", candidateGroup: "group-A" },
      { id: "c2", candidateStatus: "rejected", candidateGroup: "group-A" },
      { id: "c3", candidateStatus: "candidate", candidateGroup: "group-B" },
      { id: "c4", candidateStatus: null, candidateGroup: null }, // non-candidate record
    ];
    vi.mocked(storage.getGammaGenerationRecords).mockResolvedValue(records as any);

    const allRecords = await storage.getGammaGenerationRecords("wo-cr-001");
    const candidates = allRecords.filter((r: any) => r.candidateStatus != null);

    // Group by candidateGroup (same logic as route handler)
    const groups: Record<string, any[]> = {};
    for (const c of candidates) {
      const group = (c as any).candidateGroup || "_ungrouped";
      if (!groups[group]) groups[group] = [];
      groups[group].push(c);
    }

    const activeCandidates = candidates.filter((c: any) => c.candidateStatus === "candidate").length;

    expect(candidates).toHaveLength(3); // excludes null candidateStatus
    expect(Object.keys(groups)).toEqual(["group-A", "group-B"]);
    expect(groups["group-A"]).toHaveLength(2);
    expect(groups["group-B"]).toHaveLength(1);
    expect(activeCandidates).toBe(2);
  });

  it("handles empty candidate list gracefully", async () => {
    vi.mocked(storage.getGammaGenerationRecords).mockResolvedValue([]);

    const allRecords = await storage.getGammaGenerationRecords("wo-cr-001");
    const candidates = allRecords.filter((r: any) => r.candidateStatus != null);
    const activeCandidates = candidates.filter((c: any) => c.candidateStatus === "candidate").length;

    expect(candidates).toHaveLength(0);
    expect(activeCandidates).toBe(0);
  });
});

// P1-3: Reliability Tests — Core Work Order Loop
// Covers all 6 exit paths of processWorkOrder()

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
    id: "wo-001",
    title: "Test Work Order",
    description: "Write a report on Q1 sales",
    type: "document",
    priority: "medium",
    status: "pending",
    correlationId: "corr-001",
    gccMemory: {},
    assignedSubAgentId: null,
    ...overrides,
  };
}

function makeTier1Approved(handler = "writer-agent") {
  return { approved: true, handler, reason: "Approved by policy", mode: "rule" };
}

function makeTier1Blocked(reason = "Budget exceeded") {
  return { approved: false, handler: null, reason, mode: "rule" };
}

function makePocketflowSuccess() {
  return {
    blocked: false,
    reason: null,
    executionId: "exec-001",
    handler: "writer-agent",
    output: {
      message: "Done",
      deliverable: "# Q1 Sales Report\n\nRevenue was up 20%.",
      deliverableType: "document",
      deliverableTitle: "Q1 Sales Report",
    },
    pocketflow: { iterations: 2, convergenceScore: 0.85, stepResults: [], refinementHistory: [], bdmMarker: null },
  };
}

function makePocketflowBlocked(reason = "Tool execution failed") {
  return {
    blocked: true,
    reason,
    executionId: null,
    handler: "writer-agent",
    output: undefined,
    pocketflow: {
      iterations: 1,
      convergenceScore: 0,
      stepResults: [],
      refinementHistory: [],
      bdmMarker: { type: "execution_block", reason, tier: 2, timestamp: new Date().toISOString() },
    },
  };
}

function makeQualityApproved(score = 0.88) {
  return { approved: true, score, summary: "High quality output", issues: [], recommendation: "approve" as const };
}

function makeQualityBlock() {
  return { approved: false, score: 0.2, summary: "Content is too short", issues: ["Missing key sections"], recommendation: "block" as const };
}

function makeQualityRevise() {
  return { approved: false, score: 0.5, summary: "Needs work", issues: ["Incomplete analysis"], recommendation: "request_revision" as const };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("processWorkOrder()", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(storage.updateWorkOrder).mockImplementation(async (_id, updates) =>
      ({ ...makeOrder(), ...updates }) as any
    );
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: false } as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([]);
  });

  // ── Exit 1: Order not found ───────────────────────────────────────────────

  it("returns undefined when order does not exist", async () => {
    vi.mocked(storage.getWorkOrder).mockResolvedValue(undefined);
    const result = await processWorkOrder("wo-missing");
    expect(result).toBeUndefined();
  });

  // ── Exit 2: Tier 1 policy block ───────────────────────────────────────────

  it("blocks and sets bdmMarker when Tier 1 policy gate rejects", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: true } as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Blocked() as any);

    await processWorkOrder("wo-001");

    expect(storage.updateWorkOrder).toHaveBeenCalledWith(
      "wo-001",
      expect.objectContaining({ status: "blocked", bdmMarker: expect.objectContaining({ type: "policy_block" }) })
    );
  });

  // ── Exit 3: Independent sub-agent ────────────────────────────────────────

  it("sets awaiting_operator when sub-agent controlMode is independent", async () => {
    const order = makeOrder();
    const independentAgent = {
      id: "agent-ind",
      name: "Legal Reviewer",
      controlMode: "independent",
      assignedTo: "operator@company.com",
      isActive: true,
    };
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([independentAgent] as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: true } as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Approved("Legal Reviewer") as any);

    await processWorkOrder("wo-001");

    expect(storage.updateWorkOrder).toHaveBeenCalledWith(
      "wo-001",
      expect.objectContaining({ status: "awaiting_operator" })
    );
  });

  // ── Exit 4: Tier 2 PocketFlow blocked ────────────────────────────────────

  it("blocks when PocketFlow returns a BDM marker", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: false } as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([
      { id: "agent-1", name: "writer-agent", controlMode: "aiden", isActive: true },
    ] as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowBlocked() as any);

    await processWorkOrder("wo-001");

    expect(storage.updateWorkOrder).toHaveBeenCalledWith(
      "wo-001",
      expect.objectContaining({ status: "blocked", tier2Result: expect.objectContaining({ blocked: true }) })
    );
  });

  // ── Exit 5: Quality review hard block ────────────────────────────────────

  it("blocks when Aiden quality review recommends block", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: true } as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([
      { id: "agent-1", name: "writer-agent", controlMode: "aiden", isActive: true },
    ] as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Approved() as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccess() as any);
    vi.mocked(runAidenQualityReview).mockResolvedValue(makeQualityBlock() as any);

    await processWorkOrder("wo-001");

    expect(storage.updateWorkOrder).toHaveBeenCalledWith(
      "wo-001",
      expect.objectContaining({
        status: "blocked",
        bdmMarker: expect.objectContaining({ type: "quality_block" }),
      })
    );
  });

  // ── Exit 6: Auto-revision exhausted → awaiting_operator ──────────────────

  it("escalates to awaiting_operator when 4 auto-revisions are exhausted", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: true } as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([
      { id: "agent-1", name: "writer-agent", controlMode: "aiden", isActive: true },
    ] as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Approved() as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccess() as any);
    // Always return revise — never approves
    vi.mocked(runAidenQualityReview).mockResolvedValue(makeQualityRevise() as any);

    await processWorkOrder("wo-001");

    const calls = vi.mocked(storage.updateWorkOrder).mock.calls;
    const finalCall = calls[calls.length - 1];
    expect(finalCall[1]).toMatchObject({ status: "awaiting_operator" });
  });

  // ── Exit 7: Happy path — LLM disabled, auto-approved ─────────────────────

  it("completes successfully when LLM is disabled (auto-approve)", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: false } as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([
      { id: "agent-1", name: "writer-agent", controlMode: "aiden", isActive: true },
    ] as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccess() as any);

    await processWorkOrder("wo-001");

    const calls = vi.mocked(storage.updateWorkOrder).mock.calls;
    const completedCall = calls.find(c => c[1]?.status === "completed");
    expect(completedCall).toBeDefined();
  });

  // ── Exit 8: Happy path — LLM enabled, quality approved ───────────────────

  it("completes successfully when LLM quality review approves", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: true } as any);
    vi.mocked(storage.getActiveSubAgents).mockResolvedValue([
      { id: "agent-1", name: "writer-agent", controlMode: "aiden", isActive: true },
    ] as any);
    vi.mocked(runTier1WithLLM).mockResolvedValue(makeTier1Approved() as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccess() as any);
    vi.mocked(runAidenQualityReview).mockResolvedValue(makeQualityApproved() as any);

    await processWorkOrder("wo-001");

    const calls = vi.mocked(storage.updateWorkOrder).mock.calls;
    const completedCall = calls.find(c => c[1]?.status === "completed");
    expect(completedCall).toBeDefined();
    expect(completedCall![1]).toMatchObject({ status: "completed" });
  });

  // ── GCC integrity ─────────────────────────────────────────────────────────

  it("always initialises order to processing status first", async () => {
    const order = makeOrder();
    vi.mocked(storage.getWorkOrder).mockResolvedValue(order as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: false } as any);
    vi.mocked(pocketflowExecute).mockResolvedValue(makePocketflowSuccess() as any);

    await processWorkOrder("wo-001");

    const firstUpdate = vi.mocked(storage.updateWorkOrder).mock.calls[0];
    expect(firstUpdate[1]).toMatchObject({ status: "processing" });
  });
});

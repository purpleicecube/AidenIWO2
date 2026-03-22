// P1-3: Reliability Tests — Workflow PM Loop
// Covers advanceWorkflowExecution() terminal state transitions.
// Note: advanceWorkflowExecution() is recursive; tests use mockResolvedValueOnce
// chaining to ensure the mock returns terminal state on the recursive call.

import { describe, it, expect, vi, beforeEach } from "vitest";
import { advanceWorkflowExecution } from "../orchestration.js";

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock("../storage.js", () => ({
  storage: {
    getWorkflowExecution: vi.fn(),
    getWorkflowTemplate: vi.fn(),
    getWorkflowSteps: vi.fn(),
    getWorkflowStepRuns: vi.fn(),
    getLlmSettings: vi.fn().mockResolvedValue({ enabled: false }),
    getOperationalSettings: vi.fn().mockResolvedValue({ memoryAdvisor: "none", currentMode: "autonomous" }),
    getWorkOrder: vi.fn().mockResolvedValue(null),
    updateWorkflowExecution: vi.fn().mockResolvedValue({}),
    updateWorkflowStepRun: vi.fn().mockResolvedValue({}),
    updateWorkOrder: vi.fn().mockResolvedValue({}),
    createExecutionLog: vi.fn().mockResolvedValue({}),
    getActiveSubAgents: vi.fn().mockResolvedValue([]),
    getTools: vi.fn().mockResolvedValue([]),
    getSubAgent: vi.fn().mockResolvedValue(null),
    getSubAgentTools: vi.fn().mockResolvedValue([]),
    createWorkflowStepRun: vi.fn().mockResolvedValue({}),
    updateWorkflowStep: vi.fn().mockResolvedValue({}),
    getGammaTemplates: vi.fn().mockResolvedValue([]),
    getWorkflowTemplates: vi.fn().mockResolvedValue([]),
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

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeExecution(overrides: Record<string, any> = {}) {
  return {
    id: "exec-001", templateId: "tpl-001",
    workOrderId: null,   // null = no work order side effects
    status: "running", goal: "Generate Q1 report", context: {},
    pmSubAgentId: null, pmLlmConfig: null,
    currentStepKey: "s1", startedAt: new Date(), completedAt: null,
    ...overrides,
  };
}

function makeTemplate() {
  return { id: "tpl-001", name: "Q1 Report", goal: "Generate Q1 report", executionMode: "autonomous", llmMode: "none" };
}

function makeStep(stepKey: string, order: number, overrides: Record<string, any> = {}) {
  return {
    id: `def-${order}`, templateId: "tpl-001",
    stepKey, name: `Step ${order}`, description: `Desc ${order}`,
    order, stepType: "work_order", conditions: null,
    toolIds: [], assignedSubAgentId: null, dependencies: [],
    ...overrides,
  };
}

function makeRun(stepKey: string, status: string) {
  return {
    id: `run-${stepKey}`, executionId: "exec-001",
    stepKey, stepName: `Step ${stepKey}`, status,
    input: {}, output: status === "completed" ? { deliverable: "done" } : null,
    startedAt: status !== "pending" ? new Date() : null,
    completedAt: status === "completed" ? new Date() : null,
    toolsUsed: [], assignedSubAgentId: null, revisionAttempt: 0,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("advanceWorkflowExecution()", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(storage.updateWorkflowExecution).mockResolvedValue({} as any);
    vi.mocked(storage.updateWorkflowStepRun).mockResolvedValue({} as any);
    vi.mocked(storage.updateWorkOrder).mockResolvedValue({} as any);
    vi.mocked(storage.getWorkflowExecution).mockResolvedValue(makeExecution() as any);
    vi.mocked(storage.getWorkflowTemplate).mockResolvedValue(makeTemplate() as any);
    vi.mocked(storage.getLlmSettings).mockResolvedValue({ enabled: false } as any);
    vi.mocked(storage.getOperationalSettings).mockResolvedValue({ memoryAdvisor: "none", currentMode: "autonomous" } as any);
    vi.mocked(storage.getTools).mockResolvedValue([] as any);
    vi.mocked(storage.getSubAgent).mockResolvedValue(null as any);
  });

  // ── All steps completed → workflow completes ──────────────────────────────

  it("marks workflow completed when all steps are done and no PM", async () => {
    vi.mocked(storage.getWorkflowSteps).mockResolvedValue([makeStep("s1", 1)] as any);
    vi.mocked(storage.getWorkflowStepRuns).mockResolvedValue([makeRun("s1", "completed")] as any);

    await advanceWorkflowExecution("exec-001");

    expect(storage.updateWorkflowExecution).toHaveBeenCalledWith(
      "exec-001", expect.objectContaining({ status: "completed" })
    );
  });

  // ── Single failed step, no PM → workflow fails ────────────────────────────

  it("marks workflow failed when all steps are done and one failed (no PM)", async () => {
    vi.mocked(storage.getWorkflowSteps).mockResolvedValue([makeStep("s1", 1)] as any);
    // Only 1 step, it's failed — findNextRunnableStep returns null immediately
    vi.mocked(storage.getWorkflowStepRuns).mockResolvedValue([makeRun("s1", "failed")] as any);

    await advanceWorkflowExecution("exec-001");

    expect(storage.updateWorkflowExecution).toHaveBeenCalledWith(
      "exec-001", expect.objectContaining({ status: "failed" })
    );
  });

  // ── Pending step gets marked running ──────────────────────────────────────

  it("marks the next pending step as running", async () => {
    vi.mocked(storage.getWorkflowSteps).mockResolvedValue([
      makeStep("s1", 1), makeStep("s2", 2),
    ] as any);
    // 1st call: s2 pending → marked running → executeWorkflowStep → marks completed → recurses
    // 2nd call: both completed → terminates
    vi.mocked(storage.getWorkflowStepRuns)
      .mockResolvedValueOnce([makeRun("s1", "completed"), makeRun("s2", "pending")] as any)
      .mockResolvedValue([makeRun("s1", "completed"), makeRun("s2", "completed")] as any);

    await advanceWorkflowExecution("exec-001");

    expect(storage.updateWorkflowStepRun).toHaveBeenCalledWith(
      "run-s2", expect.objectContaining({ status: "running" })
    );
  });

  // ── Current step key is updated ───────────────────────────────────────────

  it("updates currentStepKey when advancing to a new step", async () => {
    vi.mocked(storage.getWorkflowSteps).mockResolvedValue([
      makeStep("s1", 1), makeStep("s2", 2),
    ] as any);
    vi.mocked(storage.getWorkflowStepRuns)
      .mockResolvedValueOnce([makeRun("s1", "completed"), makeRun("s2", "pending")] as any)
      .mockResolvedValue([makeRun("s1", "completed"), makeRun("s2", "completed")] as any);

    await advanceWorkflowExecution("exec-001");

    expect(storage.updateWorkflowExecution).toHaveBeenCalledWith(
      "exec-001", expect.objectContaining({ currentStepKey: "s2" })
    );
  });

  // ── Condition check — step skipped ───────────────────────────────────────

  it("skips a step when requirePreviousSuccess condition is not met", async () => {
    const conditionalStep = makeStep("s2", 2, {
      conditions: { requirePreviousSuccess: "s1" },  // s1 must be completed
    });
    vi.mocked(storage.getWorkflowSteps).mockResolvedValue([
      makeStep("s1", 1), conditionalStep,
    ] as any);
    // s1 failed → condition false → s2 skipped
    // 2nd call: s1 failed, s2 skipped → terminal → marks failed
    vi.mocked(storage.getWorkflowStepRuns)
      .mockResolvedValueOnce([makeRun("s1", "failed"), makeRun("s2", "pending")] as any)
      .mockResolvedValue([makeRun("s1", "failed"), makeRun("s2", "skipped")] as any);

    await advanceWorkflowExecution("exec-001");

    expect(storage.updateWorkflowStepRun).toHaveBeenCalledWith(
      "run-s2", expect.objectContaining({ status: "skipped" })
    );
  });

  // ── Execution not found ───────────────────────────────────────────────────

  it("throws when the workflow execution does not exist", async () => {
    vi.mocked(storage.getWorkflowExecution).mockResolvedValue(null as any);

    await expect(advanceWorkflowExecution("exec-missing"))
      .rejects.toThrow("Workflow execution not found");
  });
});

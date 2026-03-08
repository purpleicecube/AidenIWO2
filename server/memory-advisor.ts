/**
 * memory-advisor.ts
 *
 * P1.4: Memory Advisor abstraction boundary.
 *
 * Defines the MemoryAdvisor interface and the default NoOpMemoryAdvisor.
 * Two hook points are wired in orchestration.ts:
 *   1. Pre-Tier-1 evaluation → recall() injects advisory context into the prompt (soft, not authoritative)
 *   2. Post-terminal state  → store() records outcome patterns for future recall
 *
 * GCC remains the authoritative memory ledger. MemoryAdvisor is strictly
 * advisory — it never writes to or reads from the GCC commit chain.
 *
 * To enable MuninnDB (P2.3):
 *   1. Implement MuninnMemoryAdvisor in server/memory-advisor-muninn.ts
 *   2. Flip operationalSettings.memoryAdvisor from "none" → "muninn"
 *   3. No other changes required.
 */

export interface AdvisoryMemory {
  /** Short summary of a past outcome relevant to the current context */
  context: string;
  /** 0.0–1.0 relevance score as assessed by the advisor */
  relevance: number;
  /** Source identifier (e.g. "muninn", "local-cache") */
  source: string;
}

export interface WorkOrderEvent {
  orderId: string;
  title: string;
  description: string;
  status: "completed" | "failed" | "blocked";
  summary?: string;
  issues?: string[];
  qualityScore?: number;
  handler?: string;
}

export interface MemoryAdvisor {
  /**
   * Called before Tier 1 LLM evaluation.
   * Returns advisory memories to be injected as soft context into the prompt.
   * Must never throw — return [] on any error.
   */
  recall(context: string): Promise<AdvisoryMemory[]>;

  /**
   * Called after a work order reaches a terminal state (completed/failed/blocked).
   * Stores outcome patterns for future recall.
   * Must never throw — log and swallow errors silently.
   */
  store(event: WorkOrderEvent): Promise<void>;
}

/**
 * NoOpMemoryAdvisor — default implementation.
 * Zero runtime behavior change, zero new dependencies.
 * Active when operationalSettings.memoryAdvisor === "none".
 */
export class NoOpMemoryAdvisor implements MemoryAdvisor {
  async recall(_context: string): Promise<AdvisoryMemory[]> {
    return [];
  }

  async store(_event: WorkOrderEvent): Promise<void> {
    return;
  }
}

/**
 * Factory — returns the appropriate advisor based on the settings flag.
 * Extend this when MuninnMemoryAdvisor is implemented (P2.3).
 */
export function createMemoryAdvisor(mode: string): MemoryAdvisor {
  switch (mode) {
    case "muninn":
      // P2.3: import and return MuninnMemoryAdvisor here
      console.warn("[memory-advisor] muninn mode requested but not yet implemented — falling back to NoOp");
      return new NoOpMemoryAdvisor();
    case "none":
    default:
      return new NoOpMemoryAdvisor();
  }
}

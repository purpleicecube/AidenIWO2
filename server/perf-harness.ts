/**
 * Performance Harness — Phase 1 instrumentation for IWO2
 *
 * Provides request-scoped timing, LLM call counting, and structured perf logging.
 * Read-only instrumentation — no behavioral changes.
 */

export type PerfCategory = "orchestration" | "db" | "llm" | "tool" | "postprocess" | "total";

interface PerfEntry {
  category: PerfCategory;
  label: string;
  durationMs: number;
  metadata?: Record<string, any>;
}

export class PerfTrace {
  readonly id: string;
  readonly type: "work_order" | "workflow" | "chat";
  readonly startTime: number;
  private entries: PerfEntry[] = [];
  private llmCallCount = 0;
  private llmTotalMs = 0;
  private dbCallCount = 0;
  private dbTotalMs = 0;
  private toolCallCount = 0;
  private toolTotalMs = 0;

  constructor(type: "work_order" | "workflow" | "chat", id: string) {
    this.type = type;
    this.id = id;
    this.startTime = Date.now();
  }

  /** Record a timed operation */
  record(category: PerfCategory, label: string, durationMs: number, metadata?: Record<string, any>): void {
    this.entries.push({ category, label, durationMs, metadata });
    if (category === "llm") {
      this.llmCallCount++;
      this.llmTotalMs += durationMs;
    } else if (category === "db") {
      this.dbCallCount++;
      this.dbTotalMs += durationMs;
    } else if (category === "tool") {
      this.toolCallCount++;
      this.toolTotalMs += durationMs;
    }
  }

  /** Time an async operation and record it */
  async time<T>(category: PerfCategory, label: string, fn: () => Promise<T>, metadata?: Record<string, any>): Promise<T> {
    const start = Date.now();
    try {
      const result = await fn();
      this.record(category, label, Date.now() - start, metadata);
      return result;
    } catch (err) {
      this.record(category, label, Date.now() - start, { ...metadata, error: (err as Error).message });
      throw err;
    }
  }

  /** Get summary for logging */
  summary(): PerfSummary {
    const totalMs = Date.now() - this.startTime;
    const orchestrationMs = this.entries
      .filter(e => e.category === "orchestration")
      .reduce((sum, e) => sum + e.durationMs, 0);
    const postprocessMs = this.entries
      .filter(e => e.category === "postprocess")
      .reduce((sum, e) => sum + e.durationMs, 0);

    return {
      traceId: this.id,
      type: this.type,
      t_total: totalMs,
      t_orchestration: orchestrationMs,
      t_db: this.dbTotalMs,
      t_llm: this.llmTotalMs,
      t_tool: this.toolTotalMs,
      t_postprocess: postprocessMs,
      llmCalls: this.llmCallCount,
      dbCalls: this.dbCallCount,
      toolCalls: this.toolCallCount,
      entries: this.entries,
    };
  }

  /** Emit structured perf log */
  log(): void {
    const s = this.summary();
    const parts = [
      `t_total=${s.t_total}ms`,
      `t_llm=${s.t_llm}ms(${s.llmCalls} calls)`,
      `t_db=${s.t_db}ms(${s.dbCalls} calls)`,
      `t_tool=${s.t_tool}ms(${s.toolCalls} calls)`,
      `t_orch=${s.t_orchestration}ms`,
      `t_post=${s.t_postprocess}ms`,
    ];
    console.log(`[perf] ${s.type}:${s.traceId} ${parts.join(" | ")}`);
  }
}

export interface PerfSummary {
  traceId: string;
  type: "work_order" | "workflow" | "chat";
  t_total: number;
  t_orchestration: number;
  t_db: number;
  t_llm: number;
  t_tool: number;
  t_postprocess: number;
  llmCalls: number;
  dbCalls: number;
  toolCalls: number;
  entries: PerfEntry[];
}

/** Standalone timer for one-off measurements */
export function startTimer(): () => number {
  const start = Date.now();
  return () => Date.now() - start;
}

/** Log a single LLM call timing (for use in llm-client.ts without a full PerfTrace) */
export function logLlmCall(
  provider: string,
  model: string,
  durationMs: number,
  promptTokensEst: number,
  caller: string
): void {
  console.log(`[perf:llm] ${caller} ${provider}/${model} ${durationMs}ms ~${promptTokensEst}tok`);
}

/** Log a single DB query timing */
export function logDbQuery(method: string, durationMs: number): void {
  if (durationMs > 50) {
    // Only log slow queries (> 50ms) to avoid noise
    console.log(`[perf:db] ${method} ${durationMs}ms`);
  }
}

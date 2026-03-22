/**
 * Benchmark Pack — Phase 1 fixed set of representative work orders and workflows
 *
 * Run: npx tsx server/benchmark-pack.ts
 *
 * Creates WOs/workflows via API, records wall-clock timings per category,
 * and outputs a baseline report. Run 3x to establish regression baseline.
 */

const BASE_URL = "http://localhost:5001";
let cookie = "";

async function login(): Promise<void> {
  const resp = await fetch(`${BASE_URL}/api/login`, { redirect: "manual" });
  const setCookie = resp.headers.get("set-cookie");
  if (setCookie) {
    cookie = setCookie.split(";")[0];
  }
}

async function api(method: string, path: string, body?: any): Promise<any> {
  const resp = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      "Cookie": cookie,
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${method} ${path} → ${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

interface BenchResult {
  name: string;
  type: "work_order" | "workflow" | "chat";
  wallClockMs: number;
  status: string;
  error?: string;
}

// ==================== Benchmark Scenarios ====================

async function bench1_SimpleWO(): Promise<BenchResult> {
  const start = Date.now();
  try {
    const wo = await api("POST", "/api/work-orders", {
      title: "[BENCH] Simple Content Brief",
      description: "Write a 3-paragraph executive summary about the benefits of AI in insurance operations. Focus on claims processing, underwriting, and customer service. Keep it under 500 words.",
      type: "creative",
      priority: "medium",
    });
    // Trigger processing
    await api("POST", `/api/work-orders/${wo.id}/process`, {});
    // Poll until done (max 120s)
    let status = "processing";
    const deadline = Date.now() + 120_000;
    while (status === "processing" && Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 3000));
      const check = await api("GET", `/api/work-orders/${wo.id}`);
      status = check.status;
    }
    return { name: "1_simple_wo", type: "work_order", wallClockMs: Date.now() - start, status };
  } catch (err: any) {
    return { name: "1_simple_wo", type: "work_order", wallClockMs: Date.now() - start, status: "error", error: err.message };
  }
}

async function bench2_MultiStepWO(): Promise<BenchResult> {
  const start = Date.now();
  try {
    const wo = await api("POST", "/api/work-orders", {
      title: "[BENCH] Research + Write with Tools",
      description: "Research current trends in AI-powered risk management for insurance companies. Use web search to find recent developments. Then write a 2-page briefing document summarizing key findings with citations.",
      type: "research",
      priority: "medium",
    });
    await api("POST", `/api/work-orders/${wo.id}/process`, {});
    let status = "processing";
    const deadline = Date.now() + 180_000;
    while (status === "processing" && Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 5000));
      const check = await api("GET", `/api/work-orders/${wo.id}`);
      status = check.status;
    }
    return { name: "2_multistep_wo", type: "work_order", wallClockMs: Date.now() - start, status };
  } catch (err: any) {
    return { name: "2_multistep_wo", type: "work_order", wallClockMs: Date.now() - start, status: "error", error: err.message };
  }
}

async function bench3_LinearWorkflow(): Promise<BenchResult> {
  const start = Date.now();
  try {
    // Find a PPTX workflow template
    const templates = await api("GET", "/api/workflow-templates");
    const pptxTemplate = templates.find((t: any) =>
      t.name?.toLowerCase().includes("pptx") || t.name?.toLowerCase().includes("presentation") ||
      t.name?.toLowerCase().includes("deck")
    );
    if (!pptxTemplate) {
      return { name: "3_linear_wf", type: "workflow", wallClockMs: Date.now() - start, status: "skipped", error: "No PPTX workflow template found" };
    }
    // Create WO for the workflow
    const wo = await api("POST", "/api/work-orders", {
      title: "[BENCH] Linear Workflow — Mark → Tom → Paul",
      description: "Create a 6-slide presentation about Klear.ai's AI-powered claims management platform. Cover: problem statement, solution overview, key features, ROI metrics, implementation timeline, and call to action.",
      type: "creative",
      priority: "medium",
    });
    // Start workflow execution
    await api("POST", "/api/workflow-executions", {
      templateId: pptxTemplate.id,
      workOrderId: wo.id,
      goal: "6-slide Klear.ai claims management presentation",
    });
    // Poll WO until done (max 300s for workflow)
    let status = "processing";
    const deadline = Date.now() + 300_000;
    while ((status === "processing" || status === "pending") && Date.now() < deadline) {
      await new Promise(r => setTimeout(r, 8000));
      const check = await api("GET", `/api/work-orders/${wo.id}`);
      status = check.status;
    }
    return { name: "3_linear_wf", type: "workflow", wallClockMs: Date.now() - start, status };
  } catch (err: any) {
    return { name: "3_linear_wf", type: "workflow", wallClockMs: Date.now() - start, status: "error", error: err.message };
  }
}

async function bench4_ChatRoundtrip(): Promise<BenchResult> {
  const start = Date.now();
  try {
    const result = await api("POST", "/api/chat", {
      message: "Give me a summary of all active sub-agents and their current capabilities.",
      history: [],
    });
    return {
      name: "4_chat_roundtrip",
      type: "chat",
      wallClockMs: Date.now() - start,
      status: result.reply ? "completed" : "empty",
    };
  } catch (err: any) {
    return { name: "4_chat_roundtrip", type: "chat", wallClockMs: Date.now() - start, status: "error", error: err.message };
  }
}

async function bench5_ChatWebSearch(): Promise<BenchResult> {
  const start = Date.now();
  try {
    const result = await api("POST", "/api/chat", {
      message: "What are the latest developments in parametric insurance?",
      history: [],
    });
    return {
      name: "5_chat_websearch",
      type: "chat",
      wallClockMs: Date.now() - start,
      status: result.reply ? "completed" : "empty",
    };
  } catch (err: any) {
    return { name: "5_chat_websearch", type: "chat", wallClockMs: Date.now() - start, status: "error", error: err.message };
  }
}

// ==================== Runner ====================

async function runBenchmarkPack(runNumber: number): Promise<BenchResult[]> {
  console.log(`\n${"=".repeat(60)}`);
  console.log(`BENCHMARK RUN #${runNumber} — ${new Date().toISOString()}`);
  console.log(`${"=".repeat(60)}\n`);

  const results: BenchResult[] = [];

  // Run chat benchmarks first (fast, no side effects)
  console.log("Running bench 4: Chat roundtrip...");
  results.push(await bench4_ChatRoundtrip());
  console.log(`  → ${results[results.length - 1].status} in ${results[results.length - 1].wallClockMs}ms`);

  console.log("Running bench 5: Chat with web search...");
  results.push(await bench5_ChatWebSearch());
  console.log(`  → ${results[results.length - 1].status} in ${results[results.length - 1].wallClockMs}ms`);

  // Run WO benchmarks (slower)
  console.log("Running bench 1: Simple WO...");
  results.push(await bench1_SimpleWO());
  console.log(`  → ${results[results.length - 1].status} in ${results[results.length - 1].wallClockMs}ms`);

  console.log("Running bench 2: Multi-step WO with tools...");
  results.push(await bench2_MultiStepWO());
  console.log(`  → ${results[results.length - 1].status} in ${results[results.length - 1].wallClockMs}ms`);

  // Workflow benchmark (slowest)
  console.log("Running bench 3: Linear workflow...");
  results.push(await bench3_LinearWorkflow());
  console.log(`  → ${results[results.length - 1].status} in ${results[results.length - 1].wallClockMs}ms`);

  return results;
}

async function main() {
  const runCount = parseInt(process.argv[2] || "1", 10);

  await login();
  console.log("Authenticated with dev session");

  const allRuns: BenchResult[][] = [];

  for (let i = 1; i <= runCount; i++) {
    const results = await runBenchmarkPack(i);
    allRuns.push(results);
  }

  // Summary
  console.log(`\n${"=".repeat(60)}`);
  console.log("BENCHMARK SUMMARY");
  console.log(`${"=".repeat(60)}`);
  console.log(`Runs: ${runCount} | Date: ${new Date().toISOString()}\n`);

  const benchNames = allRuns[0].map(r => r.name);
  for (const name of benchNames) {
    const timings = allRuns.map(run => run.find(r => r.name === name)!);
    const times = timings.map(t => t.wallClockMs);
    const avg = Math.round(times.reduce((a, b) => a + b, 0) / times.length);
    const min = Math.min(...times);
    const max = Math.max(...times);
    const statuses = timings.map(t => t.status).join(", ");
    const variance = times.length > 1
      ? Math.round(((max - min) / avg) * 100)
      : 0;

    console.log(`${name}:`);
    console.log(`  avg=${avg}ms  min=${min}ms  max=${max}ms  variance=${variance}%`);
    console.log(`  statuses: ${statuses}`);
    if (timings.some(t => t.error)) {
      console.log(`  errors: ${timings.filter(t => t.error).map(t => t.error).join("; ")}`);
    }
    console.log();
  }

  // Output JSON baseline for future comparison
  const baseline = {
    date: new Date().toISOString(),
    runs: runCount,
    results: allRuns,
  };
  const fs = await import("fs");
  const baselinePath = `/home/virgina/VS_AIDEN_IWO2/server/benchmark-baseline.json`;
  fs.writeFileSync(baselinePath, JSON.stringify(baseline, null, 2));
  console.log(`Baseline saved to: ${baselinePath}`);
}

main().catch(err => {
  console.error("Benchmark failed:", err);
  process.exit(1);
});

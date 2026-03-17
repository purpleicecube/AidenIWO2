import { sql } from "drizzle-orm";
import { pgTable, text, varchar, timestamp, jsonb, integer, boolean } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";

export const subAgents = pgTable("sub_agents", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  type: text("type").notNull().default("general"),
  controlMode: text("control_mode").notNull().default("aiden"),
  assignedTo: text("assigned_to"),
  status: text("status").notNull().default("active"),
  capabilities: jsonb("capabilities").default(sql`'[]'::jsonb`),
  description: text("description"),
  llmEnabled: boolean("llm_enabled").default(true),
  llmProvider: text("llm_provider").default("groq"),
  llmModel: text("llm_model").default("llama-3.3-70b-versatile"),
  llmBaseUrl: text("llm_base_url"),
  llmSystemPrompt: text("llm_system_prompt"),
  llmApiKeyEnvVar: text("llm_api_key_env_var").default("GROQ_API_KEY"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertSubAgentSchema = createInsertSchema(subAgents).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertSubAgent = z.infer<typeof insertSubAgentSchema>;
export type SubAgent = typeof subAgents.$inferSelect;

export const workOrders = pgTable("work_orders", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  correlationId: varchar("correlation_id").notNull().default(sql`gen_random_uuid()`),
  title: text("title").notNull(),
  description: text("description").notNull(),
  type: text("type").notNull().default("standard"),
  priority: text("priority").notNull().default("medium"),
  status: text("status").notNull().default("pending"),
  assignedSubAgentId: varchar("assigned_sub_agent_id"),
  executionMode: text("execution_mode"),
  workflowExecutionId: varchar("workflow_execution_id"),
  tier1Result: jsonb("tier1_result"),
  tier2Result: jsonb("tier2_result"),
  gccMemory: jsonb("gcc_memory").default(sql`'{}'::jsonb`),
  bdmMarker: jsonb("bdm_marker"),
  effectiveMode: text("effective_mode"),
  impactScore: integer("impact_score"),
  approvalStatus: text("approval_status"),
  deferredUntil: timestamp("deferred_until"),
  deferredReason: text("deferred_reason"),
  tags: text("tags").array().default(sql`'{}'::text[]`),
  isArchived: boolean("is_archived").default(false).notNull(),
  archivedAt: timestamp("archived_at"),
  archivedBy: text("archived_by"),
  archivedReason: text("archived_reason"),
  submittedBy: text("submitted_by").default("system"),
  gammaTemplateKey: text("gamma_template_key"),     // WO-level override: takes precedence over workflow default and global default
  processingAttemptId: varchar("processing_attempt_id"),    // UUID: current processing attempt token (watchdog ownership)
  heartbeatAt: timestamp("heartbeat_at"),                   // last heartbeat from active processing
  processingStartedAt: timestamp("processing_started_at"),  // when current processing attempt began
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

// ==================== Operational Settings ====================

export const operationalSettings = pgTable("operational_settings", {
  id: varchar("id").primaryKey().default(sql`'default'`),
  currentMode: text("current_mode").notNull().default("autonomous"),
  thresholds: jsonb("thresholds").default(sql`'{"financialAmount": 10000, "riskLevel": "high", "categories": ["legal", "security", "strategic"]}'::jsonb`),
  scheduleRules: jsonb("schedule_rules").default(sql`'[]'::jsonb`),
  emergencyOverrideEnabled: boolean("emergency_override_enabled").notNull().default(true),
  emergencyTriggers: jsonb("emergency_triggers").default(sql`'["security_breach", "legal_deadline_24h", "revenue_loss", "system_outage"]'::jsonb`),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
  updatedBy: text("updated_by").default("system"),
  memoryAdvisor: text("memory_advisor").notNull().default("none"),
});

export const insertOperationalSettingsSchema = createInsertSchema(operationalSettings).omit({
  id: true,
  updatedAt: true,
});

export type InsertOperationalSettings = z.infer<typeof insertOperationalSettingsSchema>;
export type OperationalSettings = typeof operationalSettings.$inferSelect;

// ==================== Approvals ====================

export const approvals = pgTable("approvals", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  workOrderId: varchar("work_order_id").notNull(),
  bdmType: text("bdm_type"),
  impactScore: integer("impact_score").default(0),
  effectiveMode: text("effective_mode").notNull().default("hitl"),
  triggerReason: text("trigger_reason"),
  aidenRecommendation: jsonb("aiden_recommendation"),
  status: text("status").notNull().default("pending"),
  decidedBy: text("decided_by"),
  decidedByName: text("decided_by_name"),
  decision: text("decision"),
  rationale: text("rationale"),
  decidedAt: timestamp("decided_at"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertApprovalSchema = createInsertSchema(approvals).omit({
  id: true,
  status: true,
  decidedBy: true,
  decidedByName: true,
  decision: true,
  rationale: true,
  decidedAt: true,
  createdAt: true,
});

export type InsertApproval = z.infer<typeof insertApprovalSchema>;
export type Approval = typeof approvals.$inferSelect;

// ==================== Execution Logs ====================

export const executionLogs = pgTable("execution_logs", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  workOrderId: varchar("work_order_id").notNull(),
  tier: integer("tier").notNull(),
  action: text("action").notNull(),
  message: text("message").notNull(),
  metadata: jsonb("metadata"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertWorkOrderSchema = createInsertSchema(workOrders).omit({
  id: true,
  correlationId: true,
  status: true,
  assignedSubAgentId: true,
  executionMode: true,
  workflowExecutionId: true,
  tier1Result: true,
  tier2Result: true,
  bdmMarker: true,
  effectiveMode: true,
  impactScore: true,
  approvalStatus: true,
  isArchived: true,
  archivedAt: true,
  archivedBy: true,
  archivedReason: true,
  createdAt: true,
  updatedAt: true,
});

export const insertExecutionLogSchema = createInsertSchema(executionLogs).omit({
  id: true,
  createdAt: true,
});

export type InsertWorkOrder = z.infer<typeof insertWorkOrderSchema>;
export type WorkOrder = typeof workOrders.$inferSelect;
export type InsertExecutionLog = z.infer<typeof insertExecutionLogSchema>;
export type ExecutionLog = typeof executionLogs.$inferSelect;

export const llmSettings = pgTable("llm_settings", {
  id: varchar("id").primaryKey().default(sql`'default'`),
  provider: text("provider").notNull().default("openai"),
  model: text("model").notNull().default("gpt-4o"),
  baseUrl: text("base_url"),
  systemPrompt: text("system_prompt").notNull().default(
    `You are Aiden, the Tier 1 Orchestrator on IOWA (Intelligent Work Orchestration). You are the executive layer of a 2-tier system built on PocketFlow, with GCC (Git-like Context Control) as your persistent memory substrate. Your role: receive work orders, plan execution strategy, delegate to Tier 2 sub-agents, iterate on blocked work, evaluate deliverables, and approve final output. You make all decisions as structured JSON.

═══════════════════════════════════════════════
IDENTITY
═══════════════════════════════════════════════
- Role: Autonomous CEO / Tier 1 Orchestrator
- Org: Klear.ai
- Platform: IOWA — Intelligent Work Orchestration by Aiden
- Tone: confident, decisive, action-first, energetic
- Mode: autonomous | semi-autonomous | human-in-the-loop
- Sub-agents: Jamie (EA), Nyx (Security), Polaris (Ops), Mark (Marketing — includes PPTX pipeline)

═══════════════════════════════════════════════
ARCHITECTURE — HARD RULES
═══════════════════════════════════════════════
The system operates on a 3-tier hierarchy:

  Tier 1   — Aiden (you): executive orchestrator. Routes, approves, merges, final review.
  Tier 1.5 — Workflow PM: project manager sub-agent. Sits between Aiden and executors.
             Activates during multi-step workflow execution only.
  Tier 2   — Executor sub-agents (Jamie, Mark, Nyx, Polaris, etc.): execute steps only.

TIER 1.5 — WORKFLOW PM
The PM is selected by Aiden when a multi-step workflow is dispatched. The PM does NOT
route or approve work orders — that authority stays with Tier 1. The PM's scope:
  • Review each step output for quality and completeness (score 0.0–1.0).
  • Issue revision instructions when a step score < 0.7.
  • Assemble all step outputs into a cohesive final work product.
  • Escalate to Aiden when a step cannot be recovered (score < 0.4 or max revisions hit).
  • Receive final executive sign-off from Aiden before delivery.
Escalation path: Tier 2 step → PM review → PM escalates → Aiden decides → retry/skip/abort/HITL.

HARD RULES:
1. TWO-TIER BOUNDARY IS INVIOLABLE.
   - Tier 1 (you): policy, planning, routing, approval, GCC MERGE authority.
   - Tier 1.5 (PM): step QA, assembly, escalation within an active workflow only.
   - Tier 2 (sub-agents): execution only.
   - No Tier 2 → Tier 2 direct chaining. Ever.
2. PocketFlow is the orchestration engine. Every node follows prep → exec → post.
3. GCC memory is shared context. Use it for routing context, correlation IDs, execution breadcrumbs. Never for secrets or raw payload dumps.
4. Work Orders flow DOWN (Tier 1 → Tier 1.5 → Tier 2). BDM Markers and escalations flow UP. The shared dict does NOT cross tier boundaries — each tier receives only the keys it needs.

═══════════════════════════════════════════════
GCC AUTHORITY (YOUR EXCLUSIVE POWERS)
═══════════════════════════════════════════════
| Command | You (Tier 1)           | Tier 2              |
|---------|------------------------|----------------------|
| CONTEXT | Full access            | Read-only            |
| COMMIT  | Full access            | Own branch only      |
| BRANCH  | Create + approve       | Propose only         |
| MERGE   | EXCLUSIVE — only you   | DENIED (hard fail)   |

GCC authority is runtime-enforced. Tier 2 MERGE → immediate hard fail + HITL escalation.
Tier 2 BRANCH → downgraded to proposal; Tier 1 approval required before execution.

═══════════════════════════════════════════════
PLATFORM CONSTRAINTS
═══════════════════════════════════════════════
Auth: password-based only. No OIDC. Production auto-login (GET /api/login) is permanently blocked.
Rate limits (platform-enforced):
  • 5 auth attempts / 15 min / IP
  • 30 work orders / hour / user — your dispatch budget
  • 150 API requests / min / IP
If any limit is hit, queue and retry at next window. Persistent throttle → emit BDM-OPS to Polaris.
File output: smart-preview auto-selects mode per artifact type (rendered | raw | binary | error).
PPTX: input = Markdown, pipeline = md-to-pptx.py, output = branded PPTX. Owner: Mark (B04_MKTG).
Memory Advisor (P1.4): MemoryAdvisor interface with recall() and store() hooks. Default = NoOp.
  Future path = MuninnDB (Ebbinghaus decay, Hebbian learning, Bayesian confidence, <20ms recall).
  GCC is always authoritative — Memory Advisor is advisory only.

═══════════════════════════════════════════════
THE 5-PHASE ORCHESTRATION CYCLE
═══════════════════════════════════════════════

PHASE 1 — PLAN
When a work order arrives:
- Load GCC context (CONTEXT command, scope: "branch" or "project").
- If Memory Advisor is active, call recall(project_id, context_keys) for soft pattern hints.
  Hints inform domain classification and sub-agent selection only — GCC context is authoritative.
- Classify the request: domain, complexity, risk level, required tools.
- Select the execution mode (autonomous / semi-auto / HITL) based on:
  • cost > 0 → HITL
  • sensitive or irreversible > 60d → HITL
  • cross-domain or multi-agent → semi-autonomous
  • everything else → autonomous
- Identify which sub-agent owns the domain:
  • marketing|growth|campaign|funnel → Mark (B04_MKTG)
  • document|presentation|pptx|slide|deck → Mark (B04_MKTG) via PPTX pipeline (md-to-pptx)
  • scheduling|stakeholder|vendor → Jamie
  • compliance|PII|audit → Nyx
  • SLA|KPI|capacity|escalation → Polaris
- Check the Tools Locker if tools_required are specified or inferred.
- Emit your plan as JSON (see output schema below).

PHASE 2 — DELEGATE (Orchestrate)
- Build a Work Order with: taskId, description, due, priority, acceptance_criteria, context (from GCC), tools_required (with lease refs if applicable).
- Dispatch to the selected Tier 2 agent via DispatchTier2Node.
- The dispatcher creates a fresh shared dict for Tier 2, copying only: gcc.project_id, gcc.branch, gcc.tier="tier2", and channel provenance keys.
- Create a tracking task: "Track:{TOPIC}" due=original.due-4h, tags=delegation,tracking.
- Rate limit: platform enforces 30 work orders / hour / user. Batch or schedule heavy workflows to stay within budget. Persistent throttle → emit BDM-OPS.
- Expect: ack ≤ 15m, status update at 50%, delivery or escalation at due.

PHASE 3 — ITERATE (Orchestrate)
When Tier 2 emits a BDM marker (work is blocked):
- BDM-FIN → route to Controller or Owner for budget approval, return answer to agent.
- BDM-OPS → route to Polaris for resource allocation.
- BDM-LEGAL → route to Legal Sentinel or Owner for compliance clearance.
- BDM-HIST → route to Company Historian or Owner for historical data.
- BDM-EXEC → handle directly — provide strategic guidance.
- BDM-HR → route to HR Guardian or Owner.
- BDM-TECH → route to Tech Architect or Owner.
- BDM-TOOL → route to Locker Manager: discover → checkout → lease → inject tool access via shared dict → agent continues.
When a BDM is resolved, inject the resolution back and let Tier 2 continue. Log every resolution to GCC (ContextLogNode). If resolution fails or times out, escalate to HITL.

PHASE 4 — EVALUATE (Orchestrate)
When Tier 2 delivers results:
- Extract gcc.commit_id and gcc.last_commit_summary from the Tier 2 shared dict.
- Score the deliverable on three axes (0.0–1.0 each):
  • Completeness: did it meet acceptance_criteria?
  • Timeliness: delivered before due?
  • Quality: is the output actionable and well-structured?
- If any score < 0.7 → flag for review, request revision (re-enter PHASE 2 with feedback).
- If all scores ≥ 0.7 → proceed to PHASE 5.

PHASE 5 — APPROVE
- Commit the final result to GCC (COMMIT command with summary + tags).
- If branches were created during execution, evaluate MERGE:
  • Strategy: append (default), summarize, or replace.
  • Replace strategy requires HITL mode.
  • Only Tier 1 may MERGE. This is non-negotiable.
- For file artifacts, select delivery mode via smart-preview: rendered (HTML/MD), raw (text), binary (PPTX/PDF/images), or error. PPTX artifacts route through md-to-pptx pipeline first.
- Assemble the response for the originating channel.
- Dispatch via ChannelDispatchNode (telegram preferred, email fallback).
- If Memory Advisor is active, call store() to record routing pattern + outcome.
- Close the tracking task.
- Archive or mark the Work Order as complete.

═══════════════════════════════════════════════
GUARDRAILS
═══════════════════════════════════════════════
- BLOCK: passwords, SSNs, credit cards, bank accounts, auth codes.
- REDACT on draft. Never self-identify as Founder/Co-founder.
- Sensitive topics (revenue, biz opportunity) → pause, board approval via Polaris/Nyx.
- Proactive stance: surface risks, follow up on stale tasks (>24h no update), nudge unresponsive agents, send daily standup at 09:00 PT.

═══════════════════════════════════════════════
OUTPUT FORMAT — ALL DECISIONS AS JSON
═══════════════════════════════════════════════
{
  "phase": "plan|delegate|iterate|evaluate|approve",
  "work_order_id": "<uuid>",
  "decision": "approve|reject|delegate|escalate|revise|block",
  "mode": "autonomous|semi-autonomous|hitl",
  "reasoning": "<1-2 sentence rationale>",
  "assigned_agent": "<agent_id or null>",
  "gcc": {
    "project_id": "<slug>",
    "branch": "<branch_name>",
    "command": "CONTEXT|COMMIT|BRANCH|MERGE|null",
    "scope": "<if CONTEXT>"
  },
  "bdm_resolution": {
    "marker": "<BDM code or null>",
    "routed_to": "<resolver>",
    "status": "pending|resolved|escalated"
  },
  "evaluation": {
    "completeness": 0.0,
    "timeliness": 0.0,
    "quality": 0.0,
    "verdict": "accept|revise|reject"
  },
  "artifact_type": "text|html|pptx|pdf|image|binary|null",
  "next_action": "<concrete next step>",
  "tracking_task": "<task title or null>"
}

Omit null blocks. Include only the fields relevant to the current phase.

═══════════════════════════════════════════════
CHAT ACTION PROTOCOL — HOW TO EXECUTE FROM CHAT
═══════════════════════════════════════════════
When a user asks you to DO work, you MUST emit an action comment in your reply.
The platform executes it automatically. Do NOT just describe what you will do — emit the
action and it will happen. Describing without acting is a failure mode.

─── SINGLE WORK ORDER (one task, one agent) ────────────────────────────────────
<!-- AIDEN_ACTION:CREATE_WORK_ORDER:{"title":"...","description":"...","type":"general","priority":"medium","autoProcess":true} -->

─── MULTI-STEP WORKFLOW (PM + sub-agent orchestration) ─────────────────────────
<!-- AIDEN_ACTION:EXECUTE_WORKFLOW:{"name":"...","goal":"...","category":"general","steps":[{"stepKey":"step_1","name":"...","description":"...","order":1,"assignTo":"<agent-name-or-null>"}]} -->

WHEN TO USE EACH:
- EXECUTE_WORKFLOW: multi-step builds, campaigns, research+deliver, anything with 3+ steps
  or multiple domains. The Workflow PM (Tier 1.5) automatically selects the best PM
  sub-agent, spins up Tier 2 sub-agents per step, and advances execution autonomously.
  Steps with no matching sub-agent execute via Aiden directly.
- CREATE_WORK_ORDER: single-task requests (draft, summarize, analyze, one deliverable).

SUB-AGENT NAMES FOR assignTo (use exact name or partial match):
  Jamie (EA/scheduling/vendor), Nyx (security/compliance/PII), Polaris (ops/SLA/KPI),
  Mark (marketing/content/PPTX/design/website/creative). Set null if no match.

TOOLS / MCP / SKILLS:
  The PM activates tools, MCP integrations, and skills via the Tool Locker automatically.
  Reference tools by name in step descriptions if known (e.g. "use md-to-pptx pipeline").
  Do not reference external APIs or URLs not available in the platform.

RULES:
  • Emit the action comment in the SAME reply as your plan description.
  • You may emit up to 3 CREATE_WORK_ORDER actions per reply. Max 1 EXECUTE_WORKFLOW.
  • Always briefly describe the plan in natural language AFTER the action comment.
  • Use {{WORK_ORDER_ID}}, {{CORRELATION_ID}}, {{WORKFLOW_EXECUTION_ID}} as placeholders
    in your reply text — the platform substitutes the real IDs automatically.

═══════════════════════════════════════════════
STANCE
═══════════════════════════════════════════════
You do not wait. You plan, orchestrate, and close loops. Every input gets a structured decision. Every delegation gets tracked. Every deliverable gets scored. You ship. You are the executive layer — act like it.`
  ),
  enabled: boolean("enabled").notNull().default(false),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertLlmSettingsSchema = createInsertSchema(llmSettings).omit({
  id: true,
  updatedAt: true,
});

export type InsertLlmSettings = z.infer<typeof insertLlmSettingsSchema>;
export type LlmSettings = typeof llmSettings.$inferSelect;

// ==================== Workflow Templates ====================

export const workflowTemplates = pgTable("workflow_templates", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  description: text("description"),
  goal: text("goal"),
  category: text("category").notNull().default("general"),
  status: text("status").notNull().default("active"),
  preferredPmId: varchar("preferred_pm_id"),
  executionMode: text("execution_mode").notNull().default("autonomous"),
  llmMode: text("llm_mode").notNull().default("inherited"),
  pptxEngine: text("pptx_engine"),           // "local" | "gamma" | null (falls back to global default)
  gammaThemeId: text("gamma_theme_id"),       // Gamma theme ID for this template
  gammaTemplateId: text("gamma_template_id"), // Gamma gammaId for from-template mode (legacy)
  gammaTemplateKey: text("gamma_template_key"), // Registry templateKey (preferred over raw gammaTemplateId)
  gammaDeliveryPolicy: text("gamma_delivery_policy"), // "auto_revise" (default) | "candidate_review" (HITL selection for public deliverables)
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertWorkflowTemplateSchema = createInsertSchema(workflowTemplates).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertWorkflowTemplate = z.infer<typeof insertWorkflowTemplateSchema>;
export type WorkflowTemplate = typeof workflowTemplates.$inferSelect;

// ==================== Workflow Steps ====================

export const workflowSteps = pgTable("workflow_steps", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  templateId: varchar("template_id").notNull(),
  stepKey: text("step_key").notNull(),
  name: text("name").notNull(),
  description: text("description"),
  order: integer("order").notNull().default(0),
  stepType: text("step_type").notNull().default("internal"),
  agentType: text("agent_type"),
  assignedSubAgentId: varchar("assigned_sub_agent_id"),
  promptTemplate: text("prompt_template"),
  toolIds: jsonb("tool_ids").default(sql`'[]'::jsonb`),
  conditions: jsonb("conditions").default(sql`'{}'::jsonb`),
  dependencies: text("dependencies").array().default(sql`'{}'::text[]`),
  retryPolicy: jsonb("retry_policy").default(sql`'{"maxRetries": 1, "retryDelay": 1000}'::jsonb`),
  timeoutMs: integer("timeout_ms").default(30000),
});

export const insertWorkflowStepSchema = createInsertSchema(workflowSteps).omit({
  id: true,
});

export type InsertWorkflowStep = z.infer<typeof insertWorkflowStepSchema>;
export type WorkflowStep = typeof workflowSteps.$inferSelect;

// ==================== Workflow Executions ====================

export const workflowExecutions = pgTable("workflow_executions", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  workOrderId: varchar("work_order_id"),
  templateId: varchar("template_id").notNull(),
  goal: text("goal"),
  status: text("status").notNull().default("pending"),
  context: jsonb("context").default(sql`'{}'::jsonb`),
  currentStepKey: text("current_step_key"),
  pmSubAgentId: varchar("pm_sub_agent_id"),
  pmLlmConfig: jsonb("pm_llm_config"),
  executionMode: text("execution_mode").notNull().default("autonomous"),
  finalWorkProduct: jsonb("final_work_product"),
  executiveReview: jsonb("executive_review"),
  startedAt: timestamp("started_at"),
  completedAt: timestamp("completed_at"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertWorkflowExecutionSchema = createInsertSchema(workflowExecutions).omit({
  id: true,
  status: true,
  currentStepKey: true,
  pmLlmConfig: true,
  finalWorkProduct: true,
  executiveReview: true,
  startedAt: true,
  completedAt: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertWorkflowExecution = z.infer<typeof insertWorkflowExecutionSchema>;
export type WorkflowExecution = typeof workflowExecutions.$inferSelect;

// ==================== Workflow Step Runs ====================

export const workflowStepRuns = pgTable("workflow_step_runs", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  executionId: varchar("execution_id").notNull(),
  stepKey: text("step_key").notNull(),
  stepName: text("step_name").notNull(),
  status: text("status").notNull().default("pending"),
  assignedSubAgentId: varchar("assigned_sub_agent_id"),
  toolsUsed: jsonb("tools_used").default(sql`'[]'::jsonb`),
  input: jsonb("input").default(sql`'{}'::jsonb`),
  output: jsonb("output"),
  aidenPrompt: text("aiden_prompt"),
  aidenDecision: jsonb("aiden_decision"),
  pmReview: jsonb("pm_review"),
  revisionAttempt: integer("revision_attempt").notNull().default(0),
  pocketflowResult: jsonb("pocketflow_result"),
  error: text("error"),
  heartbeatAt: timestamp("heartbeat_at"),           // last heartbeat from active step execution (watchdog)
  startedAt: timestamp("started_at"),
  completedAt: timestamp("completed_at"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertWorkflowStepRunSchema = createInsertSchema(workflowStepRuns).omit({
  id: true,
  status: true,
  output: true,
  aidenPrompt: true,
  aidenDecision: true,
  pmReview: true,
  pocketflowResult: true,
  error: true,
  startedAt: true,
  completedAt: true,
  createdAt: true,
});

export type InsertWorkflowStepRun = z.infer<typeof insertWorkflowStepRunSchema>;
export type WorkflowStepRun = typeof workflowStepRuns.$inferSelect;

// ==================== Agentic Tools ====================

export const tools = pgTable("tools", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  slug: text("slug").notNull().unique(),
  description: text("description"),
  type: text("type").notNull().default("skill"),
  category: text("category").notNull().default("general"),
  status: text("status").notNull().default("active"),
  config: jsonb("config").default(sql`'{}'::jsonb`),
  inputSchema: jsonb("input_schema").default(sql`'{}'::jsonb`),
  outputSchema: jsonb("output_schema").default(sql`'{}'::jsonb`),
  executionConfig: jsonb("execution_config").default(sql`'{}'::jsonb`),
  version: text("version").notNull().default("1.0.0"),
  skillContent: text("skill_content"),
  skillInstructions: text("skill_instructions"),
  triggerConditions: jsonb("trigger_conditions").default(sql`'[]'::jsonb`),
  executionMode: text("execution_mode").default("prompt_injection"),
  runtimeEnvironment: text("runtime_environment"),
  sourceCode: text("source_code"),
  entryPoint: text("entry_point"),
  sandboxConfig: jsonb("sandbox_config").default(sql`'{}'::jsonb`),
  credentials: jsonb("credentials").default(sql`'[]'::jsonb`),
  usageInstructions: text("usage_instructions"),
  mcpConfig: jsonb("mcp_config").default(sql`'{}'::jsonb`),
  accessTier: text("access_tier").notNull().default("any"),
  maxConcurrent: integer("max_concurrent").notNull().default(0),
  defaultLeaseSeconds: integer("default_lease_seconds").notNull().default(300),
  maxLeaseSeconds: integer("max_lease_seconds").notNull().default(3600),
  dailyUsageLimit: integer("daily_usage_limit"),
  costCeilingPerDay: text("cost_ceiling_per_day"),
  requiresApproval: boolean("requires_approval").notNull().default(false),
  restricted: boolean("restricted").notNull().default(false),
  restrictedReason: text("restricted_reason"),
  restrictedBy: text("restricted_by"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertToolSchema = createInsertSchema(tools).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertTool = z.infer<typeof insertToolSchema>;
export type Tool = typeof tools.$inferSelect;

// ==================== Sub-Agent Tool Assignments (Default Entitlements) ====================

export const subAgentTools = pgTable("sub_agent_tools", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  subAgentId: varchar("sub_agent_id").notNull(),
  toolId: varchar("tool_id").notNull(),
  enabled: boolean("enabled").notNull().default(true),
  config: jsonb("config").default(sql`'{}'::jsonb`),
  assignedAt: timestamp("assigned_at").defaultNow().notNull(),
});

export const insertSubAgentToolSchema = createInsertSchema(subAgentTools).omit({
  id: true,
  assignedAt: true,
});

export type InsertSubAgentTool = z.infer<typeof insertSubAgentToolSchema>;
export type SubAgentTool = typeof subAgentTools.$inferSelect;

// ==================== Tool Tags (Discovery Metadata) ====================

export const toolTags = pgTable("tool_tags", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull().unique(),
  category: text("category").notNull().default("general"),
  description: text("description"),
  color: text("color").default("#6366f1"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertToolTagSchema = createInsertSchema(toolTags).omit({
  id: true,
  createdAt: true,
});

export type InsertToolTag = z.infer<typeof insertToolTagSchema>;
export type ToolTag = typeof toolTags.$inferSelect;

export const toolTagAssignments = pgTable("tool_tag_assignments", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  toolId: varchar("tool_id").notNull(),
  tagId: varchar("tag_id").notNull(),
  assignedAt: timestamp("assigned_at").defaultNow().notNull(),
});

export const insertToolTagAssignmentSchema = createInsertSchema(toolTagAssignments).omit({
  id: true,
  assignedAt: true,
});

export type InsertToolTagAssignment = z.infer<typeof insertToolTagAssignmentSchema>;
export type ToolTagAssignment = typeof toolTagAssignments.$inferSelect;

// ==================== Tool Leases (Checkout/Return Tracking) ====================

export const toolLeases = pgTable("tool_leases", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  toolId: varchar("tool_id").notNull(),
  agentId: varchar("agent_id").notNull(),
  agentType: text("agent_type").notNull().default("sub_agent"),
  tier: text("tier").notNull().default("tier2"),
  leaseType: text("lease_type").notNull().default("checkout"),
  status: text("status").notNull().default("active"),
  toolVersion: text("tool_version"),
  context: jsonb("context").default(sql`'{}'::jsonb`),
  workOrderId: varchar("work_order_id"),
  issuedAt: timestamp("issued_at").defaultNow().notNull(),
  expiresAt: timestamp("expires_at").notNull(),
  returnedAt: timestamp("returned_at"),
  heartbeatAt: timestamp("heartbeat_at"),
  result: jsonb("result").default(sql`'{}'::jsonb`),
  error: text("error"),
});

export const insertToolLeaseSchema = createInsertSchema(toolLeases).omit({
  id: true,
  issuedAt: true,
  returnedAt: true,
  heartbeatAt: true,
});

export type InsertToolLease = z.infer<typeof insertToolLeaseSchema>;
export type ToolLease = typeof toolLeases.$inferSelect;

// ==================== Locker Keys (Agent Permissions & Scopes) ====================

export const lockerKeys = pgTable("locker_keys", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  ownerId: varchar("owner_id").notNull(),
  ownerType: text("owner_type").notNull().default("sub_agent"),
  scopes: jsonb("scopes").default(sql`'[]'::jsonb`),
  toolIds: jsonb("tool_ids").default(sql`'[]'::jsonb`),
  tagIds: jsonb("tag_ids").default(sql`'[]'::jsonb`),
  permissions: jsonb("permissions").default(sql`'[]'::jsonb`),
  maxConcurrentLeases: integer("max_concurrent_leases").notNull().default(5),
  issuedBy: text("issued_by").notNull().default("admin"),
  active: boolean("active").notNull().default(true),
  expiresAt: timestamp("expires_at"),
  revokedAt: timestamp("revoked_at"),
  revokedBy: text("revoked_by"),
  revokedReason: text("revoked_reason"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertLockerKeySchema = createInsertSchema(lockerKeys).omit({
  id: true,
  createdAt: true,
  revokedAt: true,
  revokedBy: true,
  revokedReason: true,
});

export type InsertLockerKey = z.infer<typeof insertLockerKeySchema>;
export type LockerKey = typeof lockerKeys.$inferSelect;

// ==================== Tool Audit Logs ====================

export const toolAuditLogs = pgTable("tool_audit_logs", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  toolId: varchar("tool_id").notNull(),
  leaseId: varchar("lease_id"),
  action: text("action").notNull(),
  actorId: varchar("actor_id").notNull(),
  actorType: text("actor_type").notNull().default("sub_agent"),
  reason: text("reason"),
  metadata: jsonb("metadata").default(sql`'{}'::jsonb`),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertToolAuditLogSchema = createInsertSchema(toolAuditLogs).omit({
  id: true,
  createdAt: true,
});

export type InsertToolAuditLog = z.infer<typeof insertToolAuditLogSchema>;
export type ToolAuditLog = typeof toolAuditLogs.$inferSelect;

// ==================== Skill Templates (CLAUDE.md / AGENTS.md / AIDEN.md) ====================

export const skillTemplates = pgTable("skill_templates", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  toolId: varchar("tool_id"),
  name: text("name").notNull(),
  slug: text("slug").notNull().unique(),
  description: text("description"),
  format: text("format").notNull().default("aiden_md"),
  category: text("category").notNull().default("general"),
  status: text("status").notNull().default("active"),
  version: text("version").notNull().default("1.0.0"),
  content: text("content").notNull(),
  instructions: text("instructions"),
  triggerConditions: jsonb("trigger_conditions").default(sql`'[]'::jsonb`),
  inputContract: jsonb("input_contract").default(sql`'{}'::jsonb`),
  outputContract: jsonb("output_contract").default(sql`'{}'::jsonb`),
  referencedResources: jsonb("referenced_resources").default(sql`'[]'::jsonb`),
  executionMode: text("execution_mode").notNull().default("prompt_injection"),
  runtimeEnvironment: text("runtime_environment"),
  sourceCode: text("source_code"),
  entryPoint: text("entry_point"),
  sandboxConfig: jsonb("sandbox_config").default(sql`'{}'::jsonb`),
  createdBy: text("created_by").default("admin"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertSkillTemplateSchema = createInsertSchema(skillTemplates).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertSkillTemplate = z.infer<typeof insertSkillTemplateSchema>;
export type SkillTemplate = typeof skillTemplates.$inferSelect;

// ==================== Artifact Folders ====================

export const artifactFolders = pgTable("artifact_folders", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  parentId: varchar("parent_id"),
  path: text("path").notNull().default("/"),
  description: text("description"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertArtifactFolderSchema = createInsertSchema(artifactFolders).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertArtifactFolder = z.infer<typeof insertArtifactFolderSchema>;
export type ArtifactFolder = typeof artifactFolders.$inferSelect;

// ==================== Artifacts ====================

export const artifacts = pgTable("artifacts", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  folderId: varchar("folder_id"),
  type: text("type").notNull().default("file"),
  mimeType: text("mime_type").default("text/plain"),
  content: text("content"),
  size: integer("size").default(0),
  sourceType: text("source_type"),
  sourceId: varchar("source_id"),
  metadata: jsonb("metadata").default(sql`'{}'::jsonb`),
  tags: text("tags").array().default(sql`'{}'::text[]`),
  status: text("status").notNull().default("active"),
  createdBy: text("created_by").default("system"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertArtifactSchema = createInsertSchema(artifacts).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertArtifact = z.infer<typeof insertArtifactSchema>;
export type Artifact = typeof artifacts.$inferSelect;

// ==================== Chat Groups ====================

export const chatGroups = pgTable("chat_groups", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  parentId: varchar("parent_id"),
  color: text("color"),
  sortOrder: integer("sort_order").notNull().default(0),
  isCollapsed: boolean("is_collapsed").notNull().default(false),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertChatGroupSchema = createInsertSchema(chatGroups).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertChatGroup = z.infer<typeof insertChatGroupSchema>;
export type ChatGroup = typeof chatGroups.$inferSelect;

// ==================== Chat Sessions (GCC Memory Protocol) ====================

export const chatSessions = pgTable("chat_sessions", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  correlationId: varchar("correlation_id").notNull().default(sql`gen_random_uuid()`),
  title: text("title").notNull().default("New Conversation"),
  status: text("status").notNull().default("active"),
  groupId: varchar("group_id"),
  isArchived: boolean("is_archived").notNull().default(false),
  archivedAt: timestamp("archived_at"),
  gccMemory: jsonb("gcc_memory").default(sql`'{}'::jsonb`),
  messageCount: integer("message_count").notNull().default(0),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertChatSessionSchema = createInsertSchema(chatSessions).omit({
  id: true,
  correlationId: true,
  status: true,
  gccMemory: true,
  messageCount: true,
  isArchived: true,
  archivedAt: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertChatSession = z.infer<typeof insertChatSessionSchema>;
export type ChatSession = typeof chatSessions.$inferSelect;

// ==================== Chat Messages ====================

export const chatMessages = pgTable("chat_messages", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  sessionId: varchar("session_id").notNull(),
  role: text("role").notNull(),
  content: text("content").notNull(),
  gccBreadcrumb: text("gcc_breadcrumb"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertChatMessageSchema = createInsertSchema(chatMessages).omit({
  id: true,
  createdAt: true,
});

export type InsertChatMessage = z.infer<typeof insertChatMessageSchema>;
export type ChatMessage = typeof chatMessages.$inferSelect;

// ==================== Sandbox Sessions ====================

export const sandboxSessions = pgTable("sandbox_sessions", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  name: text("name").notNull(),
  description: text("description"),
  status: text("status").notNull().default("active"),
  environment: jsonb("environment").default(sql`'{}'::jsonb`),
  logs: jsonb("logs").default(sql`'[]'::jsonb`),
  result: jsonb("result"),
  createdBy: text("created_by").default("system"),
  startedAt: timestamp("started_at").defaultNow(),
  completedAt: timestamp("completed_at"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertSandboxSessionSchema = createInsertSchema(sandboxSessions).omit({
  id: true,
  status: true,
  logs: true,
  result: true,
  completedAt: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertSandboxSession = z.infer<typeof insertSandboxSessionSchema>;
export type SandboxSession = typeof sandboxSessions.$inferSelect;

// ==================== Uploaded Images ====================

export const uploadedImages = pgTable("uploaded_images", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  placeholderId: varchar("placeholder_id").notNull(),
  filename: text("filename").notNull(),
  mimeType: text("mime_type").notNull(),
  size: integer("size").notNull(),
  data: text("data").notNull(),
  alt: text("alt"),
  uploadedBy: text("uploaded_by").default("system"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertUploadedImageSchema = createInsertSchema(uploadedImages).omit({
  id: true,
  createdAt: true,
});

export type InsertUploadedImage = z.infer<typeof insertUploadedImageSchema>;
export type UploadedImage = typeof uploadedImages.$inferSelect;

// ==================== Gamma Settings ====================

export const gammaSettings = pgTable("gamma_settings", {
  id: varchar("id").primaryKey().default(sql`'default'`),
  enabled: boolean("enabled").notNull().default(false),
  mode: text("mode").notNull().default("generate"), // "generate" | "from_template"
  themeId: text("theme_id"),
  gammaId: text("gamma_id"),                  // raw Gamma ID (legacy)
  templateKey: text("template_key"),           // Registry templateKey (preferred over raw gammaId)
  fallbackToLocal: boolean("fallback_to_local").notNull().default(true),
  numCards: integer("num_cards"),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
  updatedBy: text("updated_by").default("system"),
});

export const insertGammaSettingsSchema = createInsertSchema(gammaSettings).omit({
  id: true,
  updatedAt: true,
});

export type InsertGammaSettings = z.infer<typeof insertGammaSettingsSchema>;
export type GammaSettings = typeof gammaSettings.$inferSelect;

// ==================== Gamma Template Registry ====================

export const gammaTemplateRegistry = pgTable("gamma_template_registry", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  templateKey: text("template_key").notNull().unique(),
  gammaId: text("gamma_id").notNull(),
  name: text("name").notNull(),
  description: text("description"),
  outputFormat: text("output_format").notNull().default("pptx"),
  contentContract: text("content_contract"),
  mode: text("mode").notNull().default("template_locked"),
  status: text("status").notNull().default("approved"),
  owner: text("owner"),
  allowedWoTypes: jsonb("allowed_wo_types"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertGammaTemplateRegistrySchema = createInsertSchema(gammaTemplateRegistry).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertGammaTemplateRegistry = z.infer<typeof insertGammaTemplateRegistrySchema>;
export type GammaTemplateRegistryEntry = typeof gammaTemplateRegistry.$inferSelect;

// ==================== Gamma Generation Records ====================

export const gammaGenerationRecords = pgTable("gamma_generation_records", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  workOrderId: varchar("work_order_id").notNull(),
  workflowExecutionId: varchar("workflow_execution_id"),
  templateKey: text("template_key").notNull(),
  gammaId: text("gamma_id").notNull(),
  generationId: text("generation_id"),
  exportFormat: text("export_format").notNull(),
  status: text("status").notNull(),
  gammaUrl: text("gamma_url"),
  artifactId: varchar("artifact_id"),
  fileSize: integer("file_size"),
  creditsDeducted: integer("credits_deducted"),
  creditsRemaining: integer("credits_remaining"),
  metadata: jsonb("metadata"),
  candidateStatus: text("candidate_status"),           // "candidate" | "selected" | "rejected" — null for non-candidate runs
  candidateGroup: text("candidate_group"),              // UUID grouping candidates from same revision cycle
  artifactFiledPath: text("artifact_filed_path"),       // durable path in gamma_candidates/ dir
  selectedAt: timestamp("selected_at"),
  selectedBy: text("selected_by"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});

export const insertGammaGenerationRecordSchema = createInsertSchema(gammaGenerationRecords).omit({
  id: true,
  createdAt: true,
});

export type InsertGammaGenerationRecord = z.infer<typeof insertGammaGenerationRecordSchema>;
export type GammaGenerationRecord = typeof gammaGenerationRecords.$inferSelect;

// ==================== 2DO Checklists ====================

export const checklistItems = pgTable("checklist_items", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  workOrderId: varchar("work_order_id").notNull(),
  workflowExecutionId: varchar("workflow_execution_id"),
  stepRunId: varchar("step_run_id"),
  phase: text("phase").notNull().default("tier2_exec"),
  summary: text("summary").notNull(),
  status: text("status").notNull().default("pending"),
  addedBy: text("added_by").notNull().default("system"),
  iteration: integer("iteration").notNull().default(1),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

export const insertChecklistItemSchema = createInsertSchema(checklistItems).omit({
  id: true,
  createdAt: true,
  updatedAt: true,
});

export type InsertChecklistItem = z.infer<typeof insertChecklistItemSchema>;
export type ChecklistItem = typeof checklistItems.$inferSelect;

export * from "./models/auth";

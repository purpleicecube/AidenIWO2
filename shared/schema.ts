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
  isArchived: boolean("is_archived").default(false).notNull(),
  archivedAt: timestamp("archived_at"),
  archivedBy: text("archived_by"),
  archivedReason: text("archived_reason"),
  submittedBy: text("submitted_by").default("system"),
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
  gccMemory: true,
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
    `You are Aiden, the Tier 1 intelligent orchestration manager. You are the central decision-making authority for all work orders.

Your Role (Tier 1 - Manager):
You evaluate incoming work orders against policy rules. You decide whether to approve or block them, and which sub-agent (Tier 2 worker) to route approved orders to.

Sub-Agents (Tier 2 - Workers):
Sub-agents are specialized workers that execute work orders under your direction. Each sub-agent has a control mode:
- "aiden" mode: You directly control and execute through this sub-agent
- "independent" mode: The sub-agent is controlled by an authorized human or AI operator; you assign the work but they execute independently

Rules:
- Critical deployments should be blocked at Tier 1 for manual review
- Critical incidents should be carefully evaluated - block if escalation is needed
- Route work orders to the most appropriate sub-agent based on their type and capabilities
- Always provide clear reasoning for your decisions
- Never allow sub-agent to sub-agent direct chaining (no Tier 2 to Tier 2)
- Use GCC memory for routing context and correlation IDs only
- When routing to an independent sub-agent, clearly state who should handle it`
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

export * from "./models/auth";

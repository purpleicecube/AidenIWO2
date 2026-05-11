import {
  type WorkOrder,
  type InsertWorkOrder,
  type ExecutionLog,
  type InsertExecutionLog,
  type User,
  type LlmSettings,
  type InsertLlmSettings,
  type SubAgent,
  type InsertSubAgent,
  type WorkflowTemplate,
  type InsertWorkflowTemplate,
  type WorkflowStep,
  type InsertWorkflowStep,
  type WorkflowExecution,
  type InsertWorkflowExecution,
  type WorkflowStepRun,
  type InsertWorkflowStepRun,
  type Tool,
  type InsertTool,
  type SubAgentTool,
  type InsertSubAgentTool,
  type ArtifactFolder,
  type InsertArtifactFolder,
  type Artifact,
  type InsertArtifact,
  type SandboxSession,
  type InsertSandboxSession,
  type ChatSession,
  type InsertChatSession,
  type ChatGroup,
  type InsertChatGroup,
  type ChatMessage,
  type InsertChatMessage,
  type OperationalSettings,
  type InsertOperationalSettings,
  type Approval,
  type InsertApproval,
  type UploadedImage,
  type InsertUploadedImage,
  type ToolTag,
  type InsertToolTag,
  type ToolTagAssignment,
  type InsertToolTagAssignment,
  type ToolLease,
  type InsertToolLease,
  type LockerKey,
  type InsertLockerKey,
  type ToolAuditLog,
  type InsertToolAuditLog,
  type SkillTemplate,
  type InsertSkillTemplate,
  workOrders,
  executionLogs,
  users,
  llmSettings,
  subAgents,
  workflowTemplates,
  workflowSteps,
  workflowExecutions,
  workflowStepRuns,
  tools,
  subAgentTools,
  artifactFolders,
  artifacts,
  sandboxSessions,
  chatGroups,
  chatSessions,
  chatMessages,
  operationalSettings,
  approvals,
  uploadedImages,
  toolTags,
  toolTagAssignments,
  toolLeases,
  lockerKeys,
  toolAuditLogs,
  skillTemplates,
  type ChecklistItem,
  type InsertChecklistItem,
  checklistItems,
  type GammaSettings,
  type InsertGammaSettings,
  gammaSettings,
  type GammaTemplateRegistryEntry,
  type InsertGammaTemplateRegistry,
  gammaTemplateRegistry,
  type GammaGenerationRecord,
  type InsertGammaGenerationRecord,
  gammaGenerationRecords,
  type CodeBlock,
  type InsertCodeBlock,
  codeBlocks,
  type InsertContextRetrieval,
  contextRetrievals,
  type Pipeline,
  type InsertPipeline,
  pipelines,
} from "@shared/schema";
import { db } from "./db";
import { eq, desc, sql, and, asc, inArray } from "drizzle-orm";

/** Levenshtein edit distance — used for fuzzy folder name matching */
function levenshtein(a: string, b: string): number {
  const m = a.length, n = b.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      dp[i][j] = a[i - 1] === b[j - 1]
        ? dp[i - 1][j - 1]
        : 1 + Math.min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1]);
    }
  }
  return dp[m][n];
}

export interface IStorage {
  getUser(id: string): Promise<User | undefined>;
  getAllUsers(): Promise<User[]>;
  updateUserRole(id: string, role: string): Promise<User | undefined>;
  deleteUser(id: string): Promise<boolean>;

  getWorkOrders(includeArchived?: boolean): Promise<WorkOrder[]>;
  getWorkOrder(id: string): Promise<WorkOrder | undefined>;
  getRecentWorkOrders(limit?: number): Promise<WorkOrder[]>;
  getWorkOrderStats(): Promise<{
    total: number;
    pending: number;
    processing: number;
    completed: number;
    blocked: number;
    failed: number;
    reopened: number;
    deferred: number;
    archived: number;
  }>;
  createWorkOrder(order: InsertWorkOrder): Promise<WorkOrder>;
  updateWorkOrder(id: string, updates: Partial<WorkOrder>): Promise<WorkOrder | undefined>;

  getExecutionLogs(workOrderId: string): Promise<ExecutionLog[]>;
  createExecutionLog(log: InsertExecutionLog): Promise<ExecutionLog>;

  getLlmSettings(): Promise<LlmSettings | undefined>;
  upsertLlmSettings(settings: InsertLlmSettings): Promise<LlmSettings>;

  getSubAgents(): Promise<SubAgent[]>;
  getSubAgent(id: string): Promise<SubAgent | undefined>;
  getActiveSubAgents(): Promise<SubAgent[]>;
  createSubAgent(agent: InsertSubAgent): Promise<SubAgent>;
  updateSubAgent(id: string, updates: Partial<SubAgent>): Promise<SubAgent | undefined>;
  deleteSubAgent(id: string): Promise<boolean>;

  getWorkflowTemplates(): Promise<WorkflowTemplate[]>;
  getWorkflowTemplate(id: string): Promise<WorkflowTemplate | undefined>;
  createWorkflowTemplate(template: InsertWorkflowTemplate): Promise<WorkflowTemplate>;
  updateWorkflowTemplate(id: string, updates: Partial<WorkflowTemplate>): Promise<WorkflowTemplate | undefined>;
  deleteWorkflowTemplate(id: string): Promise<boolean>;

  getWorkflowSteps(templateId: string): Promise<WorkflowStep[]>;
  getWorkflowStep(id: string): Promise<WorkflowStep | undefined>;
  createWorkflowStep(step: InsertWorkflowStep): Promise<WorkflowStep>;
  updateWorkflowStep(id: string, updates: Partial<WorkflowStep>): Promise<WorkflowStep | undefined>;
  deleteWorkflowStep(id: string): Promise<boolean>;

  getWorkflowExecutions(): Promise<WorkflowExecution[]>;
  getWorkflowExecution(id: string): Promise<WorkflowExecution | undefined>;
  getWorkflowExecutionsByWorkOrder(workOrderId: string): Promise<WorkflowExecution[]>;
  createWorkflowExecution(execution: InsertWorkflowExecution): Promise<WorkflowExecution>;
  updateWorkflowExecution(id: string, updates: Partial<WorkflowExecution>): Promise<WorkflowExecution | undefined>;

  getWorkflowStepRuns(executionId: string): Promise<WorkflowStepRun[]>;
  getWorkflowStepRun(id: string): Promise<WorkflowStepRun | undefined>;
  createWorkflowStepRun(run: InsertWorkflowStepRun): Promise<WorkflowStepRun>;
  updateWorkflowStepRun(id: string, updates: Partial<WorkflowStepRun>): Promise<WorkflowStepRun | undefined>;

  getTools(): Promise<Tool[]>;
  getTool(id: string): Promise<Tool | undefined>;
  getToolBySlug(slug: string): Promise<Tool | undefined>;
  createTool(tool: InsertTool): Promise<Tool>;
  updateTool(id: string, updates: Partial<Tool>): Promise<Tool | undefined>;
  deleteTool(id: string): Promise<boolean>;

  getSubAgentTools(subAgentId: string): Promise<(SubAgentTool & { tool: Tool })[]>;
  assignToolToSubAgent(assignment: InsertSubAgentTool): Promise<SubAgentTool>;
  updateSubAgentTool(id: string, updates: Partial<SubAgentTool>): Promise<SubAgentTool | undefined>;
  removeToolFromSubAgent(subAgentId: string, toolId: string): Promise<boolean>;

  getArtifactFolders(parentId?: string | null): Promise<ArtifactFolder[]>;
  getArtifactFolder(id: string): Promise<ArtifactFolder | undefined>;
  createArtifactFolder(folder: InsertArtifactFolder): Promise<ArtifactFolder>;
  updateArtifactFolder(id: string, updates: Partial<ArtifactFolder>): Promise<ArtifactFolder | undefined>;
  deleteArtifactFolder(id: string): Promise<boolean>;

  getArtifacts(folderId?: string | null, sourceId?: string): Promise<Artifact[]>;
  getArtifact(id: string): Promise<Artifact | undefined>;
  createArtifact(artifact: InsertArtifact): Promise<Artifact>;
  updateArtifact(id: string, updates: Partial<Artifact>): Promise<Artifact | undefined>;
  deleteArtifact(id: string): Promise<boolean>;

  getSandboxSessions(): Promise<SandboxSession[]>;
  getSandboxSession(id: string): Promise<SandboxSession | undefined>;
  createSandboxSession(session: InsertSandboxSession): Promise<SandboxSession>;
  updateSandboxSession(id: string, updates: Partial<SandboxSession>): Promise<SandboxSession | undefined>;
  deleteSandboxSession(id: string): Promise<boolean>;

  getChatGroups(): Promise<ChatGroup[]>;
  getChatGroup(id: string): Promise<ChatGroup | undefined>;
  createChatGroup(group: InsertChatGroup): Promise<ChatGroup>;
  updateChatGroup(id: string, updates: Partial<ChatGroup>): Promise<ChatGroup | undefined>;
  deleteChatGroup(id: string): Promise<boolean>;

  getChatSessions(includeArchived?: boolean): Promise<ChatSession[]>;
  getChatSession(id: string): Promise<ChatSession | undefined>;
  createChatSession(session: InsertChatSession): Promise<ChatSession>;
  updateChatSession(id: string, updates: Partial<ChatSession>): Promise<ChatSession | undefined>;
  deleteChatSession(id: string): Promise<boolean>;
  getChatMessages(sessionId: string): Promise<ChatMessage[]>;
  addChatMessage(message: InsertChatMessage): Promise<ChatMessage>;

  getOperationalSettings(): Promise<OperationalSettings | undefined>;
  upsertOperationalSettings(settings: InsertOperationalSettings): Promise<OperationalSettings>;

  getApprovals(): Promise<Approval[]>;
  getPendingApprovals(): Promise<Approval[]>;
  getApproval(id: string): Promise<Approval | undefined>;
  getApprovalsByWorkOrder(workOrderId: string): Promise<Approval[]>;
  createApproval(approval: InsertApproval): Promise<Approval>;
  updateApproval(id: string, updates: Partial<Approval>): Promise<Approval | undefined>;

  getUploadedImage(placeholderId: string): Promise<UploadedImage | undefined>;
  getUploadedImageById(id: string): Promise<UploadedImage | undefined>;
  upsertUploadedImage(image: InsertUploadedImage): Promise<UploadedImage>;
  deleteUploadedImage(placeholderId: string): Promise<boolean>;

  // Tools Locker: Tags
  getToolTags(): Promise<ToolTag[]>;
  getToolTag(id: string): Promise<ToolTag | undefined>;
  createToolTag(tag: InsertToolTag): Promise<ToolTag>;
  deleteToolTag(id: string): Promise<boolean>;
  getToolTagAssignments(toolId: string): Promise<(ToolTagAssignment & { tag: ToolTag })[]>;
  assignTagToTool(assignment: InsertToolTagAssignment): Promise<ToolTagAssignment>;
  removeTagFromTool(toolId: string, tagId: string): Promise<boolean>;

  // Tools Locker: Leases
  getToolLeases(filters?: { toolId?: string; agentId?: string; status?: string }): Promise<ToolLease[]>;
  getToolLeasesBySubAgent(subAgentId: string): Promise<ToolLease[]>;
  getToolLease(id: string): Promise<ToolLease | undefined>;
  getActiveLeases(toolId: string): Promise<ToolLease[]>;
  createToolLease(lease: InsertToolLease): Promise<ToolLease>;
  updateToolLease(id: string, updates: Partial<ToolLease>): Promise<ToolLease | undefined>;
  expireOverdueLeases(): Promise<number>;

  // Tools Locker: Keys
  getLockerKeys(ownerId?: string): Promise<LockerKey[]>;
  getLockerKey(id: string): Promise<LockerKey | undefined>;
  createLockerKey(key: InsertLockerKey): Promise<LockerKey>;
  updateLockerKey(id: string, updates: Partial<LockerKey>): Promise<LockerKey | undefined>;
  revokeLockerKey(id: string, revokedBy: string, reason: string): Promise<LockerKey | undefined>;

  // Tools Locker: Audit Logs
  getToolAuditLogs(filters?: { toolId?: string; actorId?: string; action?: string }): Promise<ToolAuditLog[]>;
  createToolAuditLog(log: InsertToolAuditLog): Promise<ToolAuditLog>;

  // Skill Templates
  getSkillTemplates(filters?: { format?: string; category?: string; status?: string }): Promise<SkillTemplate[]>;
  getSkillTemplate(id: string): Promise<SkillTemplate | undefined>;
  getSkillTemplateBySlug(slug: string): Promise<SkillTemplate | undefined>;
  createSkillTemplate(template: InsertSkillTemplate): Promise<SkillTemplate>;
  updateSkillTemplate(id: string, updates: Partial<SkillTemplate>): Promise<SkillTemplate | undefined>;
  deleteSkillTemplate(id: string): Promise<boolean>;

  // Gamma Settings
  getGammaSettings(): Promise<GammaSettings | undefined>;
  upsertGammaSettings(settings: InsertGammaSettings): Promise<GammaSettings>;

  // Gamma Template Registry
  getGammaTemplates(): Promise<GammaTemplateRegistryEntry[]>;
  getGammaTemplateByKey(templateKey: string): Promise<GammaTemplateRegistryEntry | undefined>;
  createGammaTemplate(entry: InsertGammaTemplateRegistry): Promise<GammaTemplateRegistryEntry>;
  updateGammaTemplate(id: string, updates: Partial<GammaTemplateRegistryEntry>): Promise<GammaTemplateRegistryEntry | undefined>;

  // Gamma Generation Records
  createGammaGenerationRecord(record: InsertGammaGenerationRecord): Promise<GammaGenerationRecord>;
  getGammaGenerationRecords(workOrderId: string): Promise<GammaGenerationRecord[]>;
  getGammaGenerationRecord(id: string): Promise<GammaGenerationRecord | undefined>;
  getGammaCandidates(workOrderId: string): Promise<GammaGenerationRecord[]>;
  selectGammaCandidate(workOrderId: string, recordId: string, selectedBy: string): Promise<GammaGenerationRecord | undefined>;
  rejectGammaCandidate(workOrderId: string, recordId: string): Promise<GammaGenerationRecord | undefined>;
  rejectAllGammaCandidates(workOrderId: string): Promise<void>;

  // 2DO Checklists
  getChecklistItems(workOrderId: string): Promise<ChecklistItem[]>;
  getChecklistItemsByWorkflow(workflowExecutionId: string): Promise<ChecklistItem[]>;
  createChecklistItem(item: InsertChecklistItem): Promise<ChecklistItem>;
  updateChecklistItem(id: string, updates: Partial<ChecklistItem>): Promise<ChecklistItem | undefined>;

  // Know-How Retrieval
  getCodeBlocks(filters?: { language?: string; sourceId?: string; tags?: string[] }): Promise<CodeBlock[]>;
  getCodeBlock(id: string): Promise<CodeBlock | undefined>;
  createCodeBlock(block: InsertCodeBlock): Promise<CodeBlock>;
  searchArtifactsByKeyword(keyword: string, folderId?: string | null): Promise<Artifact[]>;
  searchArtifactsByName(keyword: string): Promise<Artifact[]>;
  getArtifactFolderByPath(path: string): Promise<ArtifactFolder | undefined>;
  createContextRetrieval(record: InsertContextRetrieval): Promise<void>;

  // Pipelines
  getPipelines(): Promise<Pipeline[]>;
  getPipeline(id: string): Promise<Pipeline | undefined>;
  getPipelineBySlug(slug: string): Promise<Pipeline | undefined>;
  createPipeline(pipeline: InsertPipeline): Promise<Pipeline>;
  updatePipeline(id: string, updates: Partial<Pipeline>): Promise<Pipeline | undefined>;
  deletePipeline(id: string): Promise<boolean>;
}

export class DatabaseStorage implements IStorage {
  async getUser(id: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user;
  }

  async getAllUsers(): Promise<User[]> {
    return db.select().from(users).orderBy(desc(users.createdAt));
  }

  async updateUserRole(id: string, role: string): Promise<User | undefined> {
    // Node Storage Adaptation Darkmode (2026-05-11): IWO3 users have no
    // role column; roles live in client_memberships. Delegate the
    // write to authStorage.setUserRole which handles the membership
    // table. Returns the user row unchanged.
    const { authStorage } = await import("./replit_integrations/auth/storage");
    await authStorage.setUserRole(id, role);
    const [user] = await db
      .update(users)
      .set({ updatedAt: new Date() })
      .where(eq(users.id, id))
      .returning();
    return user;
  }

  async deleteUser(id: string): Promise<boolean> {
    const result = await db.delete(users).where(eq(users.id, id)).returning();
    return result.length > 0;
  }

  async getWorkOrders(includeArchived = false): Promise<WorkOrder[]> {
    if (includeArchived) {
      return db.select().from(workOrders).orderBy(desc(workOrders.createdAt));
    }
    return db.select().from(workOrders).where(eq(workOrders.isArchived, false)).orderBy(desc(workOrders.createdAt));
  }

  async getWorkOrder(id: string): Promise<WorkOrder | undefined> {
    const [order] = await db.select().from(workOrders).where(eq(workOrders.id, id));
    return order;
  }

  async getRecentWorkOrders(limit = 8): Promise<WorkOrder[]> {
    return db.select().from(workOrders).where(eq(workOrders.isArchived, false)).orderBy(desc(workOrders.createdAt)).limit(limit);
  }

  async getWorkOrderStats() {
    const allOrders = await db.select().from(workOrders);
    const activeOrders = allOrders.filter(o => !o.isArchived);
    const stats = {
      total: activeOrders.length,
      pending: 0,
      processing: 0,
      completed: 0,
      blocked: 0,
      failed: 0,
      awaiting_operator: 0,
      reopened: 0,
      deferred: 0,
      archived: allOrders.filter(o => o.isArchived).length,
    };
    for (const order of activeOrders) {
      if (order.status in stats) {
        (stats as any)[order.status]++;
      }
    }
    return stats;
  }

  async createWorkOrder(order: InsertWorkOrder): Promise<WorkOrder> {
    const [created] = await db.insert(workOrders).values(order).returning();
    return created;
  }

  async updateWorkOrder(id: string, updates: Partial<WorkOrder>): Promise<WorkOrder | undefined> {
    const [updated] = await db
      .update(workOrders)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(workOrders.id, id))
      .returning();
    return updated;
  }

  async getExecutionLogs(workOrderId: string): Promise<ExecutionLog[]> {
    return db
      .select()
      .from(executionLogs)
      .where(eq(executionLogs.workOrderId, workOrderId))
      .orderBy(executionLogs.createdAt);
  }

  async createExecutionLog(log: InsertExecutionLog): Promise<ExecutionLog> {
    const [created] = await db.insert(executionLogs).values(log).returning();
    return created;
  }

  async getLlmSettings(): Promise<LlmSettings | undefined> {
    const [settings] = await db.select().from(llmSettings).where(eq(llmSettings.id, "default"));
    return settings;
  }

  async getSubAgents(): Promise<SubAgent[]> {
    return db.select().from(subAgents).orderBy(subAgents.name);
  }

  async getSubAgent(id: string): Promise<SubAgent | undefined> {
    const [agent] = await db.select().from(subAgents).where(eq(subAgents.id, id));
    return agent;
  }

  async getActiveSubAgents(): Promise<SubAgent[]> {
    return db.select().from(subAgents).where(eq(subAgents.status, "active")).orderBy(subAgents.name);
  }

  async createSubAgent(agent: InsertSubAgent): Promise<SubAgent> {
    const [created] = await db.insert(subAgents).values(agent).returning();
    return created;
  }

  async updateSubAgent(id: string, updates: Partial<SubAgent>): Promise<SubAgent | undefined> {
    const [updated] = await db
      .update(subAgents)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(subAgents.id, id))
      .returning();
    return updated;
  }

  async deleteSubAgent(id: string): Promise<boolean> {
    const result = await db.delete(subAgents).where(eq(subAgents.id, id));
    return true;
  }

  async upsertLlmSettings(settings: InsertLlmSettings): Promise<LlmSettings> {
    const existing = await this.getLlmSettings();
    if (existing) {
      const [updated] = await db
        .update(llmSettings)
        .set({ ...settings, updatedAt: new Date() })
        .where(eq(llmSettings.id, "default"))
        .returning();
      return updated;
    }
    const [created] = await db
      .insert(llmSettings)
      .values({ ...settings, id: "default" })
      .returning();
    return created;
  }

  async getWorkflowTemplates(): Promise<WorkflowTemplate[]> {
    return db.select().from(workflowTemplates).orderBy(desc(workflowTemplates.createdAt));
  }

  async getWorkflowTemplate(id: string): Promise<WorkflowTemplate | undefined> {
    const [template] = await db.select().from(workflowTemplates).where(eq(workflowTemplates.id, id));
    return template;
  }

  async createWorkflowTemplate(template: InsertWorkflowTemplate): Promise<WorkflowTemplate> {
    const [created] = await db.insert(workflowTemplates).values(template).returning();
    return created;
  }

  async updateWorkflowTemplate(id: string, updates: Partial<WorkflowTemplate>): Promise<WorkflowTemplate | undefined> {
    const [updated] = await db
      .update(workflowTemplates)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(workflowTemplates.id, id))
      .returning();
    return updated;
  }

  async deleteWorkflowTemplate(id: string): Promise<boolean> {
    await db.delete(workflowSteps).where(eq(workflowSteps.templateId, id));
    await db.delete(workflowTemplates).where(eq(workflowTemplates.id, id));
    return true;
  }

  async getWorkflowSteps(templateId: string): Promise<WorkflowStep[]> {
    return db.select().from(workflowSteps).where(eq(workflowSteps.templateId, templateId)).orderBy(asc(workflowSteps.order));
  }

  async getWorkflowStep(id: string): Promise<WorkflowStep | undefined> {
    const [step] = await db.select().from(workflowSteps).where(eq(workflowSteps.id, id));
    return step;
  }

  async createWorkflowStep(step: InsertWorkflowStep): Promise<WorkflowStep> {
    const [created] = await db.insert(workflowSteps).values(step).returning();
    return created;
  }

  async updateWorkflowStep(id: string, updates: Partial<WorkflowStep>): Promise<WorkflowStep | undefined> {
    const [updated] = await db
      .update(workflowSteps)
      .set(updates)
      .where(eq(workflowSteps.id, id))
      .returning();
    return updated;
  }

  async deleteWorkflowStep(id: string): Promise<boolean> {
    await db.delete(workflowSteps).where(eq(workflowSteps.id, id));
    return true;
  }

  async getWorkflowExecutions(): Promise<WorkflowExecution[]> {
    return db.select().from(workflowExecutions).orderBy(desc(workflowExecutions.createdAt));
  }

  async getWorkflowExecution(id: string): Promise<WorkflowExecution | undefined> {
    const [execution] = await db.select().from(workflowExecutions).where(eq(workflowExecutions.id, id));
    return execution;
  }

  async getWorkflowExecutionsByWorkOrder(workOrderId: string): Promise<WorkflowExecution[]> {
    return db.select().from(workflowExecutions).where(eq(workflowExecutions.workOrderId, workOrderId)).orderBy(desc(workflowExecutions.createdAt));
  }

  async createWorkflowExecution(execution: InsertWorkflowExecution): Promise<WorkflowExecution> {
    const [created] = await db.insert(workflowExecutions).values(execution).returning();
    return created;
  }

  async updateWorkflowExecution(id: string, updates: Partial<WorkflowExecution>): Promise<WorkflowExecution | undefined> {
    const [updated] = await db
      .update(workflowExecutions)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(workflowExecutions.id, id))
      .returning();
    return updated;
  }

  async getWorkflowStepRuns(executionId: string): Promise<WorkflowStepRun[]> {
    return db.select().from(workflowStepRuns).where(eq(workflowStepRuns.executionId, executionId)).orderBy(asc(workflowStepRuns.createdAt));
  }

  async getWorkflowStepRun(id: string): Promise<WorkflowStepRun | undefined> {
    const [run] = await db.select().from(workflowStepRuns).where(eq(workflowStepRuns.id, id));
    return run;
  }

  async createWorkflowStepRun(run: InsertWorkflowStepRun): Promise<WorkflowStepRun> {
    const [created] = await db.insert(workflowStepRuns).values(run).returning();
    return created;
  }

  async updateWorkflowStepRun(id: string, updates: Partial<WorkflowStepRun>): Promise<WorkflowStepRun | undefined> {
    const [updated] = await db
      .update(workflowStepRuns)
      .set(updates)
      .where(eq(workflowStepRuns.id, id))
      .returning();
    return updated;
  }

  async getTools(): Promise<Tool[]> {
    return db.select().from(tools).orderBy(tools.name);
  }

  async getTool(id: string): Promise<Tool | undefined> {
    const [tool] = await db.select().from(tools).where(eq(tools.id, id));
    return tool;
  }

  async getToolBySlug(slug: string): Promise<Tool | undefined> {
    const [tool] = await db.select().from(tools).where(eq(tools.slug, slug));
    return tool;
  }

  async createTool(tool: InsertTool): Promise<Tool> {
    const [created] = await db.insert(tools).values(tool).returning();
    return created;
  }

  async updateTool(id: string, updates: Partial<Tool>): Promise<Tool | undefined> {
    const [updated] = await db
      .update(tools)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(tools.id, id))
      .returning();
    return updated;
  }

  async deleteTool(id: string): Promise<boolean> {
    await db.delete(subAgentTools).where(eq(subAgentTools.toolId, id));
    await db.delete(tools).where(eq(tools.id, id));
    return true;
  }

  async getSubAgentTools(subAgentId: string): Promise<(SubAgentTool & { tool: Tool })[]> {
    const assignments = await db.select().from(subAgentTools).where(eq(subAgentTools.subAgentId, subAgentId));
    const results: (SubAgentTool & { tool: Tool })[] = [];
    for (const assignment of assignments) {
      const [tool] = await db.select().from(tools).where(eq(tools.id, assignment.toolId));
      if (tool) {
        results.push({ ...assignment, tool });
      }
    }
    return results;
  }

  async assignToolToSubAgent(assignment: InsertSubAgentTool): Promise<SubAgentTool> {
    const [created] = await db.insert(subAgentTools).values(assignment).returning();
    return created;
  }

  async updateSubAgentTool(id: string, updates: Partial<SubAgentTool>): Promise<SubAgentTool | undefined> {
    const [updated] = await db.update(subAgentTools).set(updates).where(eq(subAgentTools.id, id)).returning();
    return updated;
  }

  async removeToolFromSubAgent(subAgentId: string, toolId: string): Promise<boolean> {
    await db.delete(subAgentTools).where(
      and(eq(subAgentTools.subAgentId, subAgentId), eq(subAgentTools.toolId, toolId))
    );
    return true;
  }

  async getArtifactFolders(parentId?: string | null): Promise<ArtifactFolder[]> {
    if (parentId === undefined) {
      return db.select().from(artifactFolders).orderBy(artifactFolders.name);
    }
    if (parentId === null) {
      return db.select().from(artifactFolders).where(sql`${artifactFolders.parentId} IS NULL`).orderBy(artifactFolders.name);
    }
    return db.select().from(artifactFolders).where(eq(artifactFolders.parentId, parentId)).orderBy(artifactFolders.name);
  }

  async getArtifactFolder(id: string): Promise<ArtifactFolder | undefined> {
    const [folder] = await db.select().from(artifactFolders).where(eq(artifactFolders.id, id));
    return folder;
  }

  async createArtifactFolder(folder: InsertArtifactFolder): Promise<ArtifactFolder> {
    const [created] = await db.insert(artifactFolders).values(folder).returning();
    return created;
  }

  async updateArtifactFolder(id: string, updates: Partial<ArtifactFolder>): Promise<ArtifactFolder | undefined> {
    const [updated] = await db
      .update(artifactFolders)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(artifactFolders.id, id))
      .returning();
    return updated;
  }

  async deleteArtifactFolder(id: string): Promise<boolean> {
    await db.delete(artifacts).where(eq(artifacts.folderId, id));
    const children = await db.select().from(artifactFolders).where(eq(artifactFolders.parentId, id));
    for (const child of children) {
      await this.deleteArtifactFolder(child.id);
    }
    await db.delete(artifactFolders).where(eq(artifactFolders.id, id));
    return true;
  }

  async getArtifacts(folderId?: string | null, sourceId?: string): Promise<Artifact[]> {
    if (sourceId) {
      return db.select().from(artifacts).where(eq(artifacts.sourceId, sourceId)).orderBy(desc(artifacts.createdAt));
    }
    if (folderId === undefined) {
      return db.select().from(artifacts).orderBy(desc(artifacts.createdAt));
    }
    if (folderId === null) {
      return db.select().from(artifacts).where(sql`${artifacts.folderId} IS NULL`).orderBy(artifacts.name);
    }
    return db.select().from(artifacts).where(eq(artifacts.folderId, folderId)).orderBy(artifacts.name);
  }

  async getArtifact(id: string): Promise<Artifact | undefined> {
    const [artifact] = await db.select().from(artifacts).where(eq(artifacts.id, id));
    return artifact;
  }

  async createArtifact(artifact: InsertArtifact): Promise<Artifact> {
    const [created] = await db.insert(artifacts).values(artifact).returning();
    return created;
  }

  async updateArtifact(id: string, updates: Partial<Artifact>): Promise<Artifact | undefined> {
    const [updated] = await db
      .update(artifacts)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(artifacts.id, id))
      .returning();
    return updated;
  }

  async deleteArtifact(id: string): Promise<boolean> {
    await db.delete(artifacts).where(eq(artifacts.id, id));
    return true;
  }

  async getArtifactBySlug(slug: string): Promise<Artifact | undefined> {
    const [artifact] = await db.select().from(artifacts).where(eq(artifacts.publishedSlug, slug));
    return artifact;
  }

  async getPublishedArtifacts(): Promise<Artifact[]> {
    return db.select().from(artifacts)
      .where(sql`${artifacts.publishedAt} IS NOT NULL`)
      .orderBy(desc(artifacts.publishedAt));
  }

  async getSandboxSessions(): Promise<SandboxSession[]> {
    return db.select().from(sandboxSessions).orderBy(desc(sandboxSessions.createdAt));
  }

  async getSandboxSession(id: string): Promise<SandboxSession | undefined> {
    const [session] = await db.select().from(sandboxSessions).where(eq(sandboxSessions.id, id));
    return session;
  }

  async createSandboxSession(session: InsertSandboxSession): Promise<SandboxSession> {
    const [created] = await db.insert(sandboxSessions).values(session).returning();
    return created;
  }

  async updateSandboxSession(id: string, updates: Partial<SandboxSession>): Promise<SandboxSession | undefined> {
    const [updated] = await db
      .update(sandboxSessions)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(sandboxSessions.id, id))
      .returning();
    return updated;
  }

  async deleteSandboxSession(id: string): Promise<boolean> {
    await db.delete(sandboxSessions).where(eq(sandboxSessions.id, id));
    return true;
  }

  async getChatGroups(): Promise<ChatGroup[]> {
    return db.select().from(chatGroups).orderBy(asc(chatGroups.sortOrder), asc(chatGroups.name));
  }

  async getChatGroup(id: string): Promise<ChatGroup | undefined> {
    const [group] = await db.select().from(chatGroups).where(eq(chatGroups.id, id));
    return group;
  }

  async createChatGroup(group: InsertChatGroup): Promise<ChatGroup> {
    const [created] = await db.insert(chatGroups).values(group).returning();
    return created;
  }

  async updateChatGroup(id: string, updates: Partial<ChatGroup>): Promise<ChatGroup | undefined> {
    const [updated] = await db
      .update(chatGroups)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(chatGroups.id, id))
      .returning();
    return updated;
  }

  async deleteChatGroup(id: string): Promise<boolean> {
    const allDescendants = async (parentId: string): Promise<string[]> => {
      const children = await db.select().from(chatGroups).where(eq(chatGroups.parentId, parentId));
      const ids: string[] = [];
      for (const child of children) {
        ids.push(child.id);
        ids.push(...await allDescendants(child.id));
      }
      return ids;
    };
    const descendantIds = await allDescendants(id);
    const allIds = [id, ...descendantIds];
    for (const gid of allIds) {
      await db.update(chatSessions).set({ groupId: null }).where(eq(chatSessions.groupId, gid));
    }
    for (const gid of [...descendantIds].reverse()) {
      await db.delete(chatGroups).where(eq(chatGroups.id, gid));
    }
    await db.delete(chatGroups).where(eq(chatGroups.id, id));
    return true;
  }

  async getChatSessions(includeArchived = false): Promise<ChatSession[]> {
    if (includeArchived) {
      return db.select().from(chatSessions).orderBy(desc(chatSessions.updatedAt));
    }
    return db.select().from(chatSessions)
      .where(and(eq(chatSessions.isArchived, false), sql`${chatSessions.status} != 'archived'`))
      .orderBy(desc(chatSessions.updatedAt));
  }

  async getChatSession(id: string): Promise<ChatSession | undefined> {
    const [session] = await db.select().from(chatSessions).where(eq(chatSessions.id, id));
    return session;
  }

  async createChatSession(session: InsertChatSession): Promise<ChatSession> {
    const [created] = await db.insert(chatSessions).values(session).returning();
    return created;
  }

  async updateChatSession(id: string, updates: Partial<ChatSession>): Promise<ChatSession | undefined> {
    const [updated] = await db
      .update(chatSessions)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(chatSessions.id, id))
      .returning();
    return updated;
  }

  async deleteChatSession(id: string): Promise<boolean> {
    await db.delete(chatMessages).where(eq(chatMessages.sessionId, id));
    await db.delete(chatSessions).where(eq(chatSessions.id, id));
    return true;
  }

  async getChatMessages(sessionId: string): Promise<ChatMessage[]> {
    return db.select().from(chatMessages).where(eq(chatMessages.sessionId, sessionId)).orderBy(asc(chatMessages.createdAt));
  }

  async addChatMessage(message: InsertChatMessage): Promise<ChatMessage> {
    const [created] = await db.insert(chatMessages).values(message).returning();
    await db
      .update(chatSessions)
      .set({
        messageCount: sql`${chatSessions.messageCount} + 1`,
        updatedAt: new Date(),
      })
      .where(eq(chatSessions.id, message.sessionId));
    return created;
  }

  async getOperationalSettings(): Promise<OperationalSettings | undefined> {
    const [settings] = await db.select().from(operationalSettings).where(eq(operationalSettings.id, "default"));
    return settings;
  }

  async upsertOperationalSettings(settings: InsertOperationalSettings): Promise<OperationalSettings> {
    const existing = await this.getOperationalSettings();
    if (existing) {
      const [updated] = await db
        .update(operationalSettings)
        .set({ ...settings, updatedAt: new Date() })
        .where(eq(operationalSettings.id, "default"))
        .returning();
      return updated;
    }
    const [created] = await db.insert(operationalSettings).values({ ...settings, id: "default" } as any).returning();
    return created;
  }

  async getApprovals(): Promise<Approval[]> {
    return db.select().from(approvals).orderBy(desc(approvals.createdAt));
  }

  async getPendingApprovals(): Promise<Approval[]> {
    return db.select().from(approvals).where(eq(approvals.status, "pending")).orderBy(desc(approvals.createdAt));
  }

  async getApproval(id: string): Promise<Approval | undefined> {
    const [approval] = await db.select().from(approvals).where(eq(approvals.id, id));
    return approval;
  }

  async getApprovalsByWorkOrder(workOrderId: string): Promise<Approval[]> {
    return db.select().from(approvals).where(eq(approvals.workOrderId, workOrderId)).orderBy(desc(approvals.createdAt));
  }

  async createApproval(approval: InsertApproval): Promise<Approval> {
    const [created] = await db.insert(approvals).values(approval).returning();
    return created;
  }

  async updateApproval(id: string, updates: Partial<Approval>): Promise<Approval | undefined> {
    const [updated] = await db.update(approvals).set(updates).where(eq(approvals.id, id)).returning();
    return updated;
  }

  async getUploadedImage(placeholderId: string): Promise<UploadedImage | undefined> {
    const [image] = await db.select().from(uploadedImages).where(eq(uploadedImages.placeholderId, placeholderId));
    return image;
  }

  async getUploadedImageById(id: string): Promise<UploadedImage | undefined> {
    const [image] = await db.select().from(uploadedImages).where(eq(uploadedImages.id, id));
    return image;
  }

  async upsertUploadedImage(image: InsertUploadedImage): Promise<UploadedImage> {
    const existing = await this.getUploadedImage(image.placeholderId);
    if (existing) {
      const { createdAt, ...updateFields } = image as any;
      const [updated] = await db.update(uploadedImages)
        .set(updateFields)
        .where(eq(uploadedImages.placeholderId, image.placeholderId))
        .returning();
      return updated;
    }
    const [created] = await db.insert(uploadedImages).values(image).returning();
    return created;
  }

  async deleteUploadedImage(placeholderId: string): Promise<boolean> {
    const result = await db.delete(uploadedImages).where(eq(uploadedImages.placeholderId, placeholderId)).returning();
    return result.length > 0;
  }

  // ==================== Tools Locker: Tags ====================

  async getToolTags(): Promise<ToolTag[]> {
    return db.select().from(toolTags).orderBy(asc(toolTags.name));
  }

  async getToolTag(id: string): Promise<ToolTag | undefined> {
    const [tag] = await db.select().from(toolTags).where(eq(toolTags.id, id));
    return tag;
  }

  async createToolTag(tag: InsertToolTag): Promise<ToolTag> {
    const [created] = await db.insert(toolTags).values(tag).returning();
    return created;
  }

  async deleteToolTag(id: string): Promise<boolean> {
    await db.delete(toolTagAssignments).where(eq(toolTagAssignments.tagId, id));
    const result = await db.delete(toolTags).where(eq(toolTags.id, id)).returning();
    return result.length > 0;
  }

  async getToolTagAssignments(toolId: string): Promise<(ToolTagAssignment & { tag: ToolTag })[]> {
    const assignments = await db.select().from(toolTagAssignments).where(eq(toolTagAssignments.toolId, toolId));
    const result: (ToolTagAssignment & { tag: ToolTag })[] = [];
    for (const assignment of assignments) {
      const tag = await this.getToolTag(assignment.tagId);
      if (tag) result.push({ ...assignment, tag });
    }
    return result;
  }

  async assignTagToTool(assignment: InsertToolTagAssignment): Promise<ToolTagAssignment> {
    const [created] = await db.insert(toolTagAssignments).values(assignment).returning();
    return created;
  }

  async removeTagFromTool(toolId: string, tagId: string): Promise<boolean> {
    const result = await db.delete(toolTagAssignments)
      .where(and(eq(toolTagAssignments.toolId, toolId), eq(toolTagAssignments.tagId, tagId)))
      .returning();
    return result.length > 0;
  }

  // ==================== Tools Locker: Leases ====================

  async getToolLeases(filters?: { toolId?: string; agentId?: string; status?: string }): Promise<ToolLease[]> {
    if (!filters) return db.select().from(toolLeases).orderBy(desc(toolLeases.issuedAt));
    const conditions = [];
    if (filters.toolId) conditions.push(eq(toolLeases.toolId, filters.toolId));
    if (filters.agentId) conditions.push(eq(toolLeases.agentId, filters.agentId));
    if (filters.status) conditions.push(eq(toolLeases.status, filters.status));
    if (conditions.length === 0) return db.select().from(toolLeases).orderBy(desc(toolLeases.issuedAt));
    return db.select().from(toolLeases).where(and(...conditions)).orderBy(desc(toolLeases.issuedAt));
  }

  async getToolLeasesBySubAgent(subAgentId: string): Promise<ToolLease[]> {
    const assignedWOs = await db.select({ id: workOrders.id })
      .from(workOrders)
      .where(eq(workOrders.assignedSubAgentId, subAgentId));
    if (assignedWOs.length === 0) return [];
    const woIds = assignedWOs.map(wo => wo.id);
    return db.select().from(toolLeases)
      .where(inArray(toolLeases.workOrderId, woIds))
      .orderBy(desc(toolLeases.issuedAt));
  }

  async getToolLease(id: string): Promise<ToolLease | undefined> {
    const [lease] = await db.select().from(toolLeases).where(eq(toolLeases.id, id));
    return lease;
  }

  async getActiveLeases(toolId: string): Promise<ToolLease[]> {
    return db.select().from(toolLeases)
      .where(and(eq(toolLeases.toolId, toolId), eq(toolLeases.status, "active")));
  }

  async createToolLease(lease: InsertToolLease): Promise<ToolLease> {
    const [created] = await db.insert(toolLeases).values(lease).returning();
    return created;
  }

  async updateToolLease(id: string, updates: Partial<ToolLease>): Promise<ToolLease | undefined> {
    const [updated] = await db.update(toolLeases).set(updates).where(eq(toolLeases.id, id)).returning();
    return updated;
  }

  async expireOverdueLeases(): Promise<number> {
    const now = new Date();
    const expired = await db.update(toolLeases)
      .set({ status: "expired" })
      .where(and(eq(toolLeases.status, "active"), sql`${toolLeases.expiresAt} < ${now}`))
      .returning();
    return expired.length;
  }

  // ==================== Tools Locker: Keys ====================

  async getLockerKeys(ownerId?: string): Promise<LockerKey[]> {
    if (ownerId) {
      return db.select().from(lockerKeys).where(eq(lockerKeys.ownerId, ownerId)).orderBy(desc(lockerKeys.createdAt));
    }
    return db.select().from(lockerKeys).orderBy(desc(lockerKeys.createdAt));
  }

  async getLockerKey(id: string): Promise<LockerKey | undefined> {
    const [key] = await db.select().from(lockerKeys).where(eq(lockerKeys.id, id));
    return key;
  }

  async createLockerKey(key: InsertLockerKey): Promise<LockerKey> {
    const [created] = await db.insert(lockerKeys).values(key).returning();
    return created;
  }

  async updateLockerKey(id: string, updates: Partial<LockerKey>): Promise<LockerKey | undefined> {
    const [updated] = await db.update(lockerKeys).set(updates).where(eq(lockerKeys.id, id)).returning();
    return updated;
  }

  async revokeLockerKey(id: string, revokedBy: string, reason: string): Promise<LockerKey | undefined> {
    const [revoked] = await db.update(lockerKeys)
      .set({ active: false, revokedAt: new Date(), revokedBy, revokedReason: reason })
      .where(eq(lockerKeys.id, id))
      .returning();
    return revoked;
  }

  // ==================== Tools Locker: Audit Logs ====================

  async getToolAuditLogs(filters?: { toolId?: string; actorId?: string; action?: string }): Promise<ToolAuditLog[]> {
    if (!filters) return db.select().from(toolAuditLogs).orderBy(desc(toolAuditLogs.createdAt)).limit(200);
    const conditions = [];
    if (filters.toolId) conditions.push(eq(toolAuditLogs.toolId, filters.toolId));
    if (filters.actorId) conditions.push(eq(toolAuditLogs.actorId, filters.actorId));
    if (filters.action) conditions.push(eq(toolAuditLogs.action, filters.action));
    if (conditions.length === 0) return db.select().from(toolAuditLogs).orderBy(desc(toolAuditLogs.createdAt)).limit(200);
    return db.select().from(toolAuditLogs).where(and(...conditions)).orderBy(desc(toolAuditLogs.createdAt)).limit(200);
  }

  async createToolAuditLog(log: InsertToolAuditLog): Promise<ToolAuditLog> {
    const [created] = await db.insert(toolAuditLogs).values(log).returning();
    return created;
  }

  // ==================== Skill Templates ====================

  async getSkillTemplates(filters?: { format?: string; category?: string; status?: string }): Promise<SkillTemplate[]> {
    if (!filters) return db.select().from(skillTemplates).orderBy(desc(skillTemplates.updatedAt));
    const conditions = [];
    if (filters.format) conditions.push(eq(skillTemplates.format, filters.format));
    if (filters.category) conditions.push(eq(skillTemplates.category, filters.category));
    if (filters.status) conditions.push(eq(skillTemplates.status, filters.status));
    if (conditions.length === 0) return db.select().from(skillTemplates).orderBy(desc(skillTemplates.updatedAt));
    return db.select().from(skillTemplates).where(and(...conditions)).orderBy(desc(skillTemplates.updatedAt));
  }

  async getSkillTemplate(id: string): Promise<SkillTemplate | undefined> {
    const [template] = await db.select().from(skillTemplates).where(eq(skillTemplates.id, id));
    return template;
  }

  async getSkillTemplateBySlug(slug: string): Promise<SkillTemplate | undefined> {
    const [template] = await db.select().from(skillTemplates).where(eq(skillTemplates.slug, slug));
    return template;
  }

  async createSkillTemplate(template: InsertSkillTemplate): Promise<SkillTemplate> {
    const [created] = await db.insert(skillTemplates).values(template).returning();
    return created;
  }

  async updateSkillTemplate(id: string, updates: Partial<SkillTemplate>): Promise<SkillTemplate | undefined> {
    const [updated] = await db.update(skillTemplates).set({ ...updates, updatedAt: new Date() }).where(eq(skillTemplates.id, id)).returning();
    return updated;
  }

  async deleteSkillTemplate(id: string): Promise<boolean> {
    const result = await db.delete(skillTemplates).where(eq(skillTemplates.id, id)).returning();
    return result.length > 0;
  }

  // Gamma Settings
  async getGammaSettings(): Promise<GammaSettings | undefined> {
    const [settings] = await db.select().from(gammaSettings).where(eq(gammaSettings.id, "default"));
    return settings;
  }

  async upsertGammaSettings(settings: InsertGammaSettings): Promise<GammaSettings> {
    const existing = await this.getGammaSettings();
    if (existing) {
      const [updated] = await db
        .update(gammaSettings)
        .set({ ...settings, updatedAt: new Date() })
        .where(eq(gammaSettings.id, "default"))
        .returning();
      return updated;
    }
    const [created] = await db.insert(gammaSettings).values({ ...settings, id: "default" } as any).returning();
    return created;
  }

  // Gamma Template Registry
  async getGammaTemplates(): Promise<GammaTemplateRegistryEntry[]> {
    return db.select().from(gammaTemplateRegistry).orderBy(gammaTemplateRegistry.name);
  }

  async getGammaTemplateByKey(templateKey: string): Promise<GammaTemplateRegistryEntry | undefined> {
    const [entry] = await db.select().from(gammaTemplateRegistry).where(eq(gammaTemplateRegistry.templateKey, templateKey));
    return entry;
  }

  async createGammaTemplate(entry: InsertGammaTemplateRegistry): Promise<GammaTemplateRegistryEntry> {
    const [created] = await db.insert(gammaTemplateRegistry).values(entry).returning();
    return created;
  }

  async updateGammaTemplate(id: string, updates: Partial<GammaTemplateRegistryEntry>): Promise<GammaTemplateRegistryEntry | undefined> {
    const [updated] = await db
      .update(gammaTemplateRegistry)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(gammaTemplateRegistry.id, id))
      .returning();
    return updated;
  }

  // Gamma Generation Records
  async createGammaGenerationRecord(record: InsertGammaGenerationRecord): Promise<GammaGenerationRecord> {
    const [created] = await db.insert(gammaGenerationRecords).values(record).returning();
    return created;
  }

  async getGammaGenerationRecords(workOrderId: string): Promise<GammaGenerationRecord[]> {
    return db.select().from(gammaGenerationRecords).where(eq(gammaGenerationRecords.workOrderId, workOrderId)).orderBy(desc(gammaGenerationRecords.createdAt));
  }

  async getGammaGenerationRecord(id: string): Promise<GammaGenerationRecord | undefined> {
    const [record] = await db.select().from(gammaGenerationRecords).where(eq(gammaGenerationRecords.id, id));
    return record;
  }

  async getGammaCandidates(workOrderId: string): Promise<GammaGenerationRecord[]> {
    return db.select().from(gammaGenerationRecords)
      .where(and(eq(gammaGenerationRecords.workOrderId, workOrderId), eq(gammaGenerationRecords.candidateStatus, "candidate")))
      .orderBy(asc(gammaGenerationRecords.createdAt));
  }

  async selectGammaCandidate(workOrderId: string, recordId: string, selectedBy: string): Promise<GammaGenerationRecord | undefined> {
    // Verify record belongs to this WO
    const [record] = await db.select().from(gammaGenerationRecords)
      .where(and(eq(gammaGenerationRecords.id, recordId), eq(gammaGenerationRecords.workOrderId, workOrderId)));
    if (!record) return undefined;

    // Reject all other candidates for this WO
    await db.update(gammaGenerationRecords)
      .set({ candidateStatus: "rejected" })
      .where(and(
        eq(gammaGenerationRecords.workOrderId, workOrderId),
        eq(gammaGenerationRecords.candidateStatus, "candidate"),
      ));

    // Mark this one as selected
    const [updated] = await db.update(gammaGenerationRecords)
      .set({ candidateStatus: "selected", selectedAt: new Date(), selectedBy })
      .where(eq(gammaGenerationRecords.id, recordId))
      .returning();
    return updated;
  }

  async rejectGammaCandidate(workOrderId: string, recordId: string): Promise<GammaGenerationRecord | undefined> {
    // Verify record belongs to this WO
    const [updated] = await db.update(gammaGenerationRecords)
      .set({ candidateStatus: "rejected" })
      .where(and(eq(gammaGenerationRecords.id, recordId), eq(gammaGenerationRecords.workOrderId, workOrderId)))
      .returning();
    return updated;
  }

  async rejectAllGammaCandidates(workOrderId: string): Promise<void> {
    await db.update(gammaGenerationRecords)
      .set({ candidateStatus: "rejected" })
      .where(and(
        eq(gammaGenerationRecords.workOrderId, workOrderId),
        eq(gammaGenerationRecords.candidateStatus, "candidate"),
      ));
  }

  // 2DO Checklists
  async getChecklistItems(workOrderId: string): Promise<ChecklistItem[]> {
    return db.select().from(checklistItems).where(eq(checklistItems.workOrderId, workOrderId)).orderBy(asc(checklistItems.createdAt));
  }

  async getChecklistItemsByWorkflow(workflowExecutionId: string): Promise<ChecklistItem[]> {
    return db.select().from(checklistItems).where(eq(checklistItems.workflowExecutionId, workflowExecutionId)).orderBy(asc(checklistItems.createdAt));
  }

  async createChecklistItem(item: InsertChecklistItem): Promise<ChecklistItem> {
    const [created] = await db.insert(checklistItems).values(item).returning();
    return created;
  }

  async updateChecklistItem(id: string, updates: Partial<ChecklistItem>): Promise<ChecklistItem | undefined> {
    const [updated] = await db.update(checklistItems).set({ ...updates, updatedAt: new Date() }).where(eq(checklistItems.id, id)).returning();
    return updated;
  }

  // Know-How Retrieval

  async getCodeBlocks(filters?: { language?: string; sourceId?: string; tags?: string[] }): Promise<CodeBlock[]> {
    const conditions = [];
    if (filters?.language) conditions.push(eq(codeBlocks.language, filters.language));
    if (filters?.sourceId) conditions.push(eq(codeBlocks.sourceId, filters.sourceId));
    if (filters?.tags && filters.tags.length > 0) {
      conditions.push(sql`${codeBlocks.tags} && ${sql`ARRAY[${sql.join(filters.tags.map(t => sql`${t}`), sql`, `)}]::text[]`}`);
    }
    if (conditions.length === 0) {
      return db.select().from(codeBlocks).orderBy(desc(codeBlocks.updatedAt)).limit(100);
    }
    return db.select().from(codeBlocks).where(and(...conditions)).orderBy(desc(codeBlocks.updatedAt)).limit(100);
  }

  async getCodeBlock(id: string): Promise<CodeBlock | undefined> {
    const [block] = await db.select().from(codeBlocks).where(eq(codeBlocks.id, id));
    return block;
  }

  async createCodeBlock(block: InsertCodeBlock): Promise<CodeBlock> {
    const [created] = await db.insert(codeBlocks).values(block).returning();
    return created;
  }

  async searchArtifactsByKeyword(keyword: string, folderId?: string | null): Promise<Artifact[]> {
    // Loop 23: Use PostgreSQL full-text search (tsquery/tsvector + GIN index) when search_vector
    // is populated, falling back to name-only ILIKE for unindexed artifacts.
    // This replaces the old content-column ILIKE scan that was O(n * content_size).
    const tsMatch = sql`search_vector @@ plainto_tsquery('english', ${keyword})`;
    const namePattern = `%${keyword}%`;
    const nameFallback = sql`${artifacts.name} ILIKE ${namePattern}`;
    const combinedMatch = sql`(${tsMatch} OR ${nameFallback})`;

    if (folderId) {
      return db.select().from(artifacts)
        .where(and(combinedMatch, eq(artifacts.folderId, folderId)))
        .orderBy(desc(artifacts.updatedAt)).limit(50);
    }
    return db.select().from(artifacts)
      .where(combinedMatch)
      .orderBy(desc(artifacts.updatedAt)).limit(50);
  }

  /**
   * Search artifacts by name only — no content column scan.
   * Much faster than searchArtifactsByKeyword for binary-heavy workspaces
   * since content stores base64 blobs that are expensive to ILIKE.
   */
  async searchArtifactsByName(keyword: string): Promise<Artifact[]> {
    const pattern = `%${keyword}%`;
    return db.select().from(artifacts)
      .where(sql`${artifacts.name} ILIKE ${pattern}`)
      .orderBy(desc(artifacts.updatedAt)).limit(20);
  }

  async getArtifactFolderByPath(path: string): Promise<ArtifactFolder | undefined> {
    // Normalize: try with and without leading slash
    const withSlash = path.startsWith("/") ? path : `/${path}`;
    const withoutSlash = path.startsWith("/") ? path.slice(1) : path;

    const [byPath] = await db.select().from(artifactFolders).where(eq(artifactFolders.path, withSlash));
    if (byPath) return byPath;

    const [byPathNoSlash] = await db.select().from(artifactFolders).where(eq(artifactFolders.path, withoutSlash));
    if (byPathNoSlash) return byPathNoSlash;

    // Loop 14 Patch C: Try with "Workspace/" prefix (UI breadcrumb paths store this prefix)
    const withWorkspace = `Workspace/${withoutSlash}`;
    const [byWorkspacePath] = await db.select().from(artifactFolders).where(eq(artifactFolders.path, withWorkspace));
    if (byWorkspacePath) return byWorkspacePath;

    // Fallback: match by name (last segment)
    const lastName = withoutSlash.split("/").pop() || withoutSlash;
    const [byName] = await db.select().from(artifactFolders).where(eq(artifactFolders.name, lastName));
    if (byName) return byName;

    // Fuzzy fallback: Levenshtein distance on folder name (catches typos like "Referendes" vs "References")
    const allFolders = await db.select().from(artifactFolders);
    let bestMatch: ArtifactFolder | undefined;
    let bestDist = Infinity;
    const lastNameLC = lastName.toLowerCase();
    for (const folder of allFolders) {
      const dist = levenshtein(lastNameLC, folder.name.toLowerCase());
      // Accept if edit distance <= 2 and name is at least 5 chars (avoid false positives on short names)
      if (dist < bestDist && dist <= 2 && lastName.length >= 5) {
        bestDist = dist;
        bestMatch = folder;
      }
    }
    if (bestMatch) {
      console.log(`[storage] Fuzzy folder match: "${lastName}" → "${bestMatch.name}" (edit distance ${bestDist})`);
    }
    return bestMatch;
  }

  async createContextRetrieval(record: InsertContextRetrieval): Promise<void> {
    await db.insert(contextRetrievals).values(record);
  }
  // Pipelines
  async getPipelines(): Promise<Pipeline[]> {
    return db.select().from(pipelines).orderBy(pipelines.name);
  }

  async getPipeline(id: string): Promise<Pipeline | undefined> {
    const [entry] = await db.select().from(pipelines).where(eq(pipelines.id, id));
    return entry;
  }

  async getPipelineBySlug(slug: string): Promise<Pipeline | undefined> {
    const [entry] = await db.select().from(pipelines).where(eq(pipelines.slug, slug));
    return entry;
  }

  async createPipeline(pipeline: InsertPipeline): Promise<Pipeline> {
    const [created] = await db.insert(pipelines).values(pipeline).returning();
    return created;
  }

  async updatePipeline(id: string, updates: Partial<Pipeline>): Promise<Pipeline | undefined> {
    const [updated] = await db
      .update(pipelines)
      .set({ ...updates, updatedAt: new Date() })
      .where(eq(pipelines.id, id))
      .returning();
    return updated;
  }

  async deletePipeline(id: string): Promise<boolean> {
    const result = await db.delete(pipelines).where(eq(pipelines.id, id)).returning();
    return result.length > 0;
  }
}

const _dbStorage = new DatabaseStorage();

// Perf instrumentation: wrap hot-path methods with timing (logs only when > 50ms)
const DB_PERF_METHODS = [
  "getWorkOrder", "getLlmSettings", "getActiveSubAgents", "getGammaTemplates",
  "getWorkflowTemplate", "getWorkflowSteps", "getOperationalSettings", "getTools",
  "updateWorkOrder", "getSubAgents", "getWorkflowExecution",
] as const;

for (const method of DB_PERF_METHODS) {
  const original = (_dbStorage as any)[method];
  if (typeof original === "function") {
    (_dbStorage as any)[method] = async function (...args: any[]) {
      const start = Date.now();
      const result = await original.apply(_dbStorage, args);
      const dur = Date.now() - start;
      if (dur > 50) console.log(`[perf:db] ${method} ${dur}ms`);
      return result;
    };
  }
}

export const storage = _dbStorage;

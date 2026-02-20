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
  type ChatMessage,
  type InsertChatMessage,
  type OperationalSettings,
  type InsertOperationalSettings,
  type Approval,
  type InsertApproval,
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
  chatSessions,
  chatMessages,
  operationalSettings,
  approvals,
} from "@shared/schema";
import { db } from "./db";
import { eq, desc, sql, and, asc } from "drizzle-orm";

export interface IStorage {
  getUser(id: string): Promise<User | undefined>;
  getAllUsers(): Promise<User[]>;
  updateUserRole(id: string, role: string): Promise<User | undefined>;
  deleteUser(id: string): Promise<boolean>;

  getWorkOrders(): Promise<WorkOrder[]>;
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
  removeToolFromSubAgent(subAgentId: string, toolId: string): Promise<boolean>;

  getArtifactFolders(parentId?: string | null): Promise<ArtifactFolder[]>;
  getArtifactFolder(id: string): Promise<ArtifactFolder | undefined>;
  createArtifactFolder(folder: InsertArtifactFolder): Promise<ArtifactFolder>;
  updateArtifactFolder(id: string, updates: Partial<ArtifactFolder>): Promise<ArtifactFolder | undefined>;
  deleteArtifactFolder(id: string): Promise<boolean>;

  getArtifacts(folderId?: string | null): Promise<Artifact[]>;
  getArtifact(id: string): Promise<Artifact | undefined>;
  createArtifact(artifact: InsertArtifact): Promise<Artifact>;
  updateArtifact(id: string, updates: Partial<Artifact>): Promise<Artifact | undefined>;
  deleteArtifact(id: string): Promise<boolean>;

  getSandboxSessions(): Promise<SandboxSession[]>;
  getSandboxSession(id: string): Promise<SandboxSession | undefined>;
  createSandboxSession(session: InsertSandboxSession): Promise<SandboxSession>;
  updateSandboxSession(id: string, updates: Partial<SandboxSession>): Promise<SandboxSession | undefined>;
  deleteSandboxSession(id: string): Promise<boolean>;

  getChatSessions(): Promise<ChatSession[]>;
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
    const [user] = await db
      .update(users)
      .set({ role, updatedAt: new Date() })
      .where(eq(users.id, id))
      .returning();
    return user;
  }

  async deleteUser(id: string): Promise<boolean> {
    const result = await db.delete(users).where(eq(users.id, id)).returning();
    return result.length > 0;
  }

  async getWorkOrders(): Promise<WorkOrder[]> {
    return db.select().from(workOrders).orderBy(desc(workOrders.createdAt));
  }

  async getWorkOrder(id: string): Promise<WorkOrder | undefined> {
    const [order] = await db.select().from(workOrders).where(eq(workOrders.id, id));
    return order;
  }

  async getRecentWorkOrders(limit = 8): Promise<WorkOrder[]> {
    return db.select().from(workOrders).orderBy(desc(workOrders.createdAt)).limit(limit);
  }

  async getWorkOrderStats() {
    const allOrders = await db.select().from(workOrders);
    const stats = {
      total: allOrders.length,
      pending: 0,
      processing: 0,
      completed: 0,
      blocked: 0,
      failed: 0,
      awaiting_operator: 0,
      reopened: 0,
    };
    for (const order of allOrders) {
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

  async getArtifacts(folderId?: string | null): Promise<Artifact[]> {
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

  async getChatSessions(): Promise<ChatSession[]> {
    return db.select().from(chatSessions).orderBy(desc(chatSessions.updatedAt));
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
}

export const storage = new DatabaseStorage();

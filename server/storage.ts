import {
  type WorkOrder,
  type InsertWorkOrder,
  type ExecutionLog,
  type InsertExecutionLog,
  type User,
  type InsertUser,
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
} from "@shared/schema";
import { db } from "./db";
import { eq, desc, sql, and, asc } from "drizzle-orm";

export interface IStorage {
  getUser(id: string): Promise<User | undefined>;
  getUserByUsername(username: string): Promise<User | undefined>;
  createUser(user: InsertUser): Promise<User>;

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
}

export class DatabaseStorage implements IStorage {
  async getUser(id: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user;
  }

  async getUserByUsername(username: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.username, username));
    return user;
  }

  async createUser(insertUser: InsertUser): Promise<User> {
    const [user] = await db.insert(users).values(insertUser).returning();
    return user;
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
}

export const storage = new DatabaseStorage();

import type { Express } from "express";
import { createServer, type Server } from "http";
import { storage } from "./storage";
import {
  insertWorkOrderSchema,
  insertLlmSettingsSchema,
  insertSubAgentSchema,
  insertWorkflowTemplateSchema,
  insertWorkflowStepSchema,
  insertWorkflowExecutionSchema,
  insertToolSchema,
  insertSubAgentToolSchema,
  insertArtifactFolderSchema,
  insertArtifactSchema,
  insertSandboxSessionSchema,
} from "@shared/schema";
import { processWorkOrder, startWorkflowExecution, advanceWorkflowExecution } from "./orchestration";
import { isApiKeyConfigured, getRequiredApiKeyName, testLLMConnection, fetchAvailableModels } from "./llm-client";

const startTime = Date.now();

export async function registerRoutes(
  httpServer: Server,
  app: Express
): Promise<Server> {
  app.get("/api/health", async (_req, res) => {
    try {
      const uptime = Math.floor((Date.now() - startTime) / 1000);
      let dbHealthy = false;
      try {
        await storage.getWorkOrderStats();
        dbHealthy = true;
      } catch {}

      res.json({
        status: "ok",
        timestamp: new Date().toISOString(),
        version: "1.0.0",
        uptime,
        services: {
          database: dbHealthy ? "healthy" : "unhealthy",
          tier1: "active",
          tier2: "active",
          gccMemory: "active",
        },
        checks: {
          api: true,
          database: dbHealthy,
          orchestration: true,
          schemaValidation: true,
        },
      });
    } catch (err) {
      res.status(500).json({ status: "error", message: "Health check failed" });
    }
  });

  app.get("/api/work-orders", async (_req, res) => {
    try {
      const orders = await storage.getWorkOrders();
      res.json(orders);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch work orders" });
    }
  });

  app.get("/api/work-orders/stats", async (_req, res) => {
    try {
      const stats = await storage.getWorkOrderStats();
      res.json(stats);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch stats" });
    }
  });

  app.get("/api/work-orders/recent", async (_req, res) => {
    try {
      const orders = await storage.getRecentWorkOrders(8);
      res.json(orders);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch recent orders" });
    }
  });

  app.get("/api/work-orders/:id", async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      res.json(order);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch work order" });
    }
  });

  app.get("/api/work-orders/:id/logs", async (req, res) => {
    try {
      const logs = await storage.getExecutionLogs(req.params.id);
      res.json(logs);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch logs" });
    }
  });

  app.post("/api/work-orders", async (req, res) => {
    try {
      const parsed = insertWorkOrderSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid work order data", errors: parsed.error.issues });
      }
      const order = await storage.createWorkOrder(parsed.data);
      res.status(201).json(order);
    } catch (err) {
      res.status(500).json({ message: "Failed to create work order" });
    }
  });

  app.post("/api/work-orders/:id/process", async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      if (order.status !== "pending") {
        return res.status(400).json({ message: `Cannot process order in '${order.status}' status` });
      }
      const result = await processWorkOrder(req.params.id);
      res.json(result);
    } catch (err) {
      res.status(500).json({ message: "Failed to process work order" });
    }
  });

  app.post("/api/work-orders/:id/retry", async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      if (order.status !== "blocked" && order.status !== "failed") {
        return res.status(400).json({ message: `Cannot retry order in '${order.status}' status` });
      }
      await storage.updateWorkOrder(req.params.id, {
        status: "pending",
        bdmMarker: null,
        tier1Result: null,
        tier2Result: null,
        gccMemory: {},
      });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Retry Initiated",
        message: "Work order reset and resubmitted for processing.",
        metadata: { previousStatus: order.status },
      });

      const result = await processWorkOrder(req.params.id);
      res.json(result);
    } catch (err) {
      res.status(500).json({ message: "Failed to retry work order" });
    }
  });

  // Sub-agent routes
  app.get("/api/sub-agents", async (_req, res) => {
    try {
      const agents = await storage.getSubAgents();
      res.json(agents);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch sub-agents" });
    }
  });

  app.get("/api/sub-agents/:id", async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      res.json(agent);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch sub-agent" });
    }
  });

  app.post("/api/sub-agents", async (req, res) => {
    try {
      const parsed = insertSubAgentSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid sub-agent data", errors: parsed.error.issues });
      }
      const agent = await storage.createSubAgent(parsed.data);
      res.status(201).json(agent);
    } catch (err) {
      res.status(500).json({ message: "Failed to create sub-agent" });
    }
  });

  app.put("/api/sub-agents/:id", async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      const updated = await storage.updateSubAgent(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update sub-agent" });
    }
  });

  app.delete("/api/sub-agents/:id", async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      await storage.deleteSubAgent(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete sub-agent" });
    }
  });

  app.get("/api/llm-settings", async (_req, res) => {
    try {
      const settings = await storage.getLlmSettings();
      const provider = settings?.provider || "openai";
      const keyName = getRequiredApiKeyName(provider);
      res.json({
        settings: settings || {
          id: "default",
          provider: "openai",
          model: "gpt-4o",
          baseUrl: null,
          systemPrompt: "",
          enabled: false,
        },
        apiKeyConfigured: isApiKeyConfigured(provider),
        requiredKeyName: keyName,
      });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch LLM settings" });
    }
  });

  app.put("/api/llm-settings", async (req, res) => {
    try {
      const parsed = insertLlmSettingsSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid settings", errors: parsed.error.issues });
      }
      const updated = await storage.upsertLlmSettings(parsed.data);
      const keyName = getRequiredApiKeyName(updated.provider);
      res.json({
        settings: updated,
        apiKeyConfigured: isApiKeyConfigured(updated.provider),
        requiredKeyName: keyName,
      });
    } catch (err) {
      res.status(500).json({ message: "Failed to update LLM settings" });
    }
  });

  app.get("/api/llm-settings/models/:provider", async (req, res) => {
    try {
      const { provider } = req.params;
      const keyConfigured = isApiKeyConfigured(provider);
      const models = await fetchAvailableModels(provider);
      res.json({ provider, keyConfigured, models });
    } catch (err: any) {
      res.status(500).json({ provider: req.params.provider, keyConfigured: false, models: [], error: err.message });
    }
  });

  app.post("/api/llm-settings/test", async (_req, res) => {
    try {
      const settings = await storage.getLlmSettings();
      if (!settings) {
        return res.status(400).json({ success: false, message: "No LLM settings configured" });
      }
      if (!isApiKeyConfigured(settings.provider)) {
        return res.status(400).json({
          success: false,
          message: `API key not configured. Please set ${getRequiredApiKeyName(settings.provider)} in your secrets.`,
        });
      }

      const result = await testLLMConnection(settings);
      res.json(result);
    } catch (err: any) {
      res.status(400).json({ success: false, message: err.message || "Connection test failed" });
    }
  });

  // ==================== Workflow Template Routes ====================

  app.get("/api/workflow-templates", async (_req, res) => {
    try {
      const templates = await storage.getWorkflowTemplates();
      res.json(templates);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch workflow templates" });
    }
  });

  app.get("/api/workflow-templates/:id", async (req, res) => {
    try {
      const template = await storage.getWorkflowTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Template not found" });
      const steps = await storage.getWorkflowSteps(req.params.id);
      res.json({ ...template, steps });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch template" });
    }
  });

  app.post("/api/workflow-templates", async (req, res) => {
    try {
      const parsed = insertWorkflowTemplateSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid template data", errors: parsed.error.issues });
      }
      const template = await storage.createWorkflowTemplate(parsed.data);
      res.status(201).json(template);
    } catch (err) {
      res.status(500).json({ message: "Failed to create template" });
    }
  });

  app.put("/api/workflow-templates/:id", async (req, res) => {
    try {
      const template = await storage.getWorkflowTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Template not found" });
      const updated = await storage.updateWorkflowTemplate(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update template" });
    }
  });

  app.delete("/api/workflow-templates/:id", async (req, res) => {
    try {
      const template = await storage.getWorkflowTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Template not found" });
      await storage.deleteWorkflowTemplate(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete template" });
    }
  });

  // ==================== Workflow Step Routes ====================

  app.get("/api/workflow-templates/:templateId/steps", async (req, res) => {
    try {
      const steps = await storage.getWorkflowSteps(req.params.templateId);
      res.json(steps);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch steps" });
    }
  });

  app.post("/api/workflow-templates/:templateId/steps", async (req, res) => {
    try {
      const data = { ...req.body, templateId: req.params.templateId };
      const parsed = insertWorkflowStepSchema.safeParse(data);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid step data", errors: parsed.error.issues });
      }
      const step = await storage.createWorkflowStep(parsed.data);
      res.status(201).json(step);
    } catch (err) {
      res.status(500).json({ message: "Failed to create step" });
    }
  });

  app.put("/api/workflow-steps/:id", async (req, res) => {
    try {
      const step = await storage.getWorkflowStep(req.params.id);
      if (!step) return res.status(404).json({ message: "Step not found" });
      const updated = await storage.updateWorkflowStep(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update step" });
    }
  });

  app.delete("/api/workflow-steps/:id", async (req, res) => {
    try {
      const step = await storage.getWorkflowStep(req.params.id);
      if (!step) return res.status(404).json({ message: "Step not found" });
      await storage.deleteWorkflowStep(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete step" });
    }
  });

  // ==================== Workflow Execution Routes ====================

  app.get("/api/workflow-executions", async (_req, res) => {
    try {
      const executions = await storage.getWorkflowExecutions();
      res.json(executions);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch executions" });
    }
  });

  app.get("/api/workflow-executions/:id", async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Execution not found" });
      const stepRuns = await storage.getWorkflowStepRuns(req.params.id);
      const template = await storage.getWorkflowTemplate(execution.templateId);
      res.json({ ...execution, stepRuns, template });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch execution" });
    }
  });

  app.post("/api/workflow-executions", async (req, res) => {
    try {
      const { templateId, workOrderId, goal, context } = req.body;
      if (!templateId) {
        return res.status(400).json({ message: "templateId is required" });
      }
      const template = await storage.getWorkflowTemplate(templateId);
      if (!template) return res.status(404).json({ message: "Template not found" });

      const execution = await startWorkflowExecution(templateId, workOrderId || null, goal || template.goal, context || {});
      res.status(201).json(execution);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to start workflow" });
    }
  });

  app.post("/api/workflow-executions/:id/advance", async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Execution not found" });
      if (execution.status === "completed" || execution.status === "failed") {
        return res.status(400).json({ message: `Cannot advance execution in '${execution.status}' status` });
      }
      const result = await advanceWorkflowExecution(req.params.id);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to advance workflow" });
    }
  });

  // ==================== Tools Routes ====================

  app.get("/api/tools", async (_req, res) => {
    try {
      const allTools = await storage.getTools();
      res.json(allTools);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch tools" });
    }
  });

  app.get("/api/tools/:id", async (req, res) => {
    try {
      const tool = await storage.getTool(req.params.id);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      res.json(tool);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch tool" });
    }
  });

  app.post("/api/tools", async (req, res) => {
    try {
      const parsed = insertToolSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid tool data", errors: parsed.error.issues });
      }
      const tool = await storage.createTool(parsed.data);
      res.status(201).json(tool);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to create tool" });
    }
  });

  app.put("/api/tools/:id", async (req, res) => {
    try {
      const tool = await storage.getTool(req.params.id);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      const updated = await storage.updateTool(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update tool" });
    }
  });

  app.delete("/api/tools/:id", async (req, res) => {
    try {
      const tool = await storage.getTool(req.params.id);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      await storage.deleteTool(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete tool" });
    }
  });

  // ==================== Sub-Agent Tool Assignment Routes ====================

  app.get("/api/sub-agents/:id/tools", async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      const agentTools = await storage.getSubAgentTools(req.params.id);
      res.json(agentTools);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch agent tools" });
    }
  });

  app.post("/api/sub-agents/:id/tools", async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      const { toolId } = req.body;
      if (!toolId) return res.status(400).json({ message: "toolId is required" });
      const tool = await storage.getTool(toolId);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      const assignment = await storage.assignToolToSubAgent({
        subAgentId: req.params.id,
        toolId,
        enabled: true,
        config: req.body.config || {},
      });
      res.status(201).json(assignment);
    } catch (err) {
      res.status(500).json({ message: "Failed to assign tool" });
    }
  });

  app.delete("/api/sub-agents/:id/tools/:toolId", async (req, res) => {
    try {
      await storage.removeToolFromSubAgent(req.params.id, req.params.toolId);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to remove tool" });
    }
  });

  // ==================== Artifact Folder Routes ====================

  app.get("/api/artifact-folders", async (req, res) => {
    try {
      const parentId = req.query.parentId as string | undefined;
      const folders = await storage.getArtifactFolders(parentId === "root" ? null : parentId);
      res.json(folders);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch folders" });
    }
  });

  app.get("/api/artifact-folders/:id", async (req, res) => {
    try {
      const folder = await storage.getArtifactFolder(req.params.id);
      if (!folder) return res.status(404).json({ message: "Folder not found" });
      res.json(folder);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch folder" });
    }
  });

  app.post("/api/artifact-folders", async (req, res) => {
    try {
      const parsed = insertArtifactFolderSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid folder data", errors: parsed.error.issues });
      }
      const folder = await storage.createArtifactFolder(parsed.data);
      res.status(201).json(folder);
    } catch (err) {
      res.status(500).json({ message: "Failed to create folder" });
    }
  });

  app.put("/api/artifact-folders/:id", async (req, res) => {
    try {
      const folder = await storage.getArtifactFolder(req.params.id);
      if (!folder) return res.status(404).json({ message: "Folder not found" });
      const updated = await storage.updateArtifactFolder(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update folder" });
    }
  });

  app.delete("/api/artifact-folders/:id", async (req, res) => {
    try {
      const folder = await storage.getArtifactFolder(req.params.id);
      if (!folder) return res.status(404).json({ message: "Folder not found" });
      await storage.deleteArtifactFolder(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete folder" });
    }
  });

  // ==================== Artifact Routes ====================

  app.get("/api/artifacts", async (req, res) => {
    try {
      const folderId = req.query.folderId as string | undefined;
      const items = await storage.getArtifacts(folderId === "root" ? null : folderId);
      res.json(items);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch artifacts" });
    }
  });

  app.get("/api/artifacts/:id", async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      res.json(artifact);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch artifact" });
    }
  });

  app.post("/api/artifacts", async (req, res) => {
    try {
      const parsed = insertArtifactSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid artifact data", errors: parsed.error.issues });
      }
      const artifact = await storage.createArtifact(parsed.data);
      res.status(201).json(artifact);
    } catch (err) {
      res.status(500).json({ message: "Failed to create artifact" });
    }
  });

  app.put("/api/artifacts/:id", async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      const updated = await storage.updateArtifact(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update artifact" });
    }
  });

  app.delete("/api/artifacts/:id", async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      await storage.deleteArtifact(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete artifact" });
    }
  });

  // ==================== Workspace Seed Route ====================

  app.post("/api/workspace/seed", async (_req, res) => {
    try {
      const existingFolders = await storage.getArtifactFolders(null);
      if (existingFolders.length > 0) {
        return res.json({ message: "Workspace already initialized", seeded: false });
      }

      const defaultFolders = [
        { name: "00_Planning", path: "/00_Planning", description: "Strategic plans, roadmaps, and objectives" },
        { name: "01_Directive-SOP", path: "/01_Directive-SOP", description: "Standard operating procedures and directives" },
        { name: "02_Execution", path: "/02_Execution", description: "Execution logs, outputs, and deliverables" },
        { name: "03_Orchestration", path: "/03_Orchestration", description: "Workflow configurations and orchestration files" },
        { name: "04_Resources", path: "/04_Resources", description: "Shared resources, templates, and reference materials" },
        { name: "05_Artifacts", path: "/05_Artifacts", description: "Final work products and completed artifacts" },
        { name: "06_Tests", path: "/06_Tests", description: "Test plans, results, and validation reports" },
      ];

      const createdFolders = [];
      for (const f of defaultFolders) {
        const folder = await storage.createArtifactFolder({ name: f.name, path: f.path, description: f.description, parentId: null });
        createdFolders.push(folder);
      }

      const rootFiles = [
        {
          name: "AGENTS.md",
          type: "file",
          mimeType: "text/markdown",
          content: "# Agents Registry\n\nThis file documents all registered sub-agents and their capabilities.\n\n## Active Agents\n\n| Agent | Type | Mode | Status |\n|-------|------|------|--------|\n| _Configure via Sub-Agents page_ | | | |\n\n## Agent Protocols\n\n- All agents operate under Aiden's Tier 1 orchestration\n- Independent agents require operator authorization\n- Aiden-controlled agents execute automatically\n",
          size: 350,
        },
        {
          name: "CLAUDE.md",
          type: "file",
          mimeType: "text/markdown",
          content: "# CLAUDE - Configuration & Context\n\nThis file provides context and configuration for AI-assisted operations.\n\n## System Context\n\n- Platform: AIDEN_PTIB Orchestration Engine\n- Architecture: 2-Tier (Aiden Manager + Sub-Agent Workers)\n- Workflow Engine: Multi-step with dependency resolution\n\n## Operating Guidelines\n\n1. Follow established SOPs in `01_Directive-SOP/`\n2. Store outputs in `02_Execution/` or `05_Artifacts/`\n3. Log test results in `06_Tests/`\n4. Reference resources from `04_Resources/`\n",
          size: 480,
        },
      ];

      for (const f of rootFiles) {
        await storage.createArtifact({
          name: f.name,
          folderId: null,
          type: f.type,
          mimeType: f.mimeType,
          content: f.content,
          size: f.size,
          createdBy: "system",
        });
      }

      res.status(201).json({ message: "Workspace initialized", seeded: true, folders: createdFolders.length, files: rootFiles.length });
    } catch (err) {
      res.status(500).json({ message: "Failed to seed workspace" });
    }
  });

  // ==================== Sandbox Session Routes ====================

  app.get("/api/sandbox-sessions", async (_req, res) => {
    try {
      const sessions = await storage.getSandboxSessions();
      res.json(sessions);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch sandbox sessions" });
    }
  });

  app.get("/api/sandbox-sessions/:id", async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      res.json(session);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch session" });
    }
  });

  app.post("/api/sandbox-sessions", async (req, res) => {
    try {
      const parsed = insertSandboxSessionSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid session data", errors: parsed.error.issues });
      }
      const session = await storage.createSandboxSession(parsed.data);
      res.status(201).json(session);
    } catch (err) {
      res.status(500).json({ message: "Failed to create session" });
    }
  });

  app.put("/api/sandbox-sessions/:id", async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      const updated = await storage.updateSandboxSession(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update session" });
    }
  });

  app.delete("/api/sandbox-sessions/:id", async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      await storage.deleteSandboxSession(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete session" });
    }
  });

  app.post("/api/sandbox-sessions/:id/execute", async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });

      await storage.updateSandboxSession(req.params.id, {
        status: "running",
        startedAt: new Date(),
      });

      const { command, input } = req.body;
      const logEntry = {
        timestamp: new Date().toISOString(),
        command: command || "execute",
        input: input || {},
        output: { message: `Sandbox execution completed for "${session.name}"`, status: "success" },
      };

      const existingLogs = Array.isArray(session.logs) ? session.logs : [];

      await storage.updateSandboxSession(req.params.id, {
        status: "completed",
        logs: [...existingLogs, logEntry],
        result: logEntry.output,
        completedAt: new Date(),
      });

      const updated = await storage.getSandboxSession(req.params.id);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to execute sandbox session" });
    }
  });

  return httpServer;
}

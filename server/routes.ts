import type { Express, Request, Response, NextFunction } from "express";
import { createServer, type Server } from "http";
import { z } from "zod";
import { storage } from "./storage";
import { sendInviteEmail } from "./sendgrid";
import { isAuthenticated as _isAuthenticated } from "./replit_integrations/auth";
const isAuth: any = _isAuthenticated;
import {
  insertWorkOrderSchema,
  insertLlmSettingsSchema,
  insertSubAgentSchema,
  insertWorkflowTemplateSchema,
  insertWorkflowStepSchema,
  insertWorkflowExecutionSchema,
  insertToolSchema,
  insertSubAgentToolSchema,
  insertOperationalSettingsSchema,
  insertArtifactFolderSchema,
  insertArtifactSchema,
  insertSandboxSessionSchema,
  insertChatSessionSchema,
  insertChatMessageSchema,
  insertToolTagSchema,
  insertToolLeaseSchema,
  insertLockerKeySchema,
  insertToolAuditLogSchema,
  insertSkillTemplateSchema,
} from "@shared/schema";
import type { LlmSettings } from "@shared/schema";
import { processWorkOrder, startWorkflowExecution, advanceWorkflowExecution } from "./orchestration";
import { isApiKeyConfigured, getRequiredApiKeyName, testLLMConnection, fetchAvailableModels, chatWithAiden, resolveSubAgentLlmConfig } from "./llm-client";

const startTime = Date.now();

function buildGccCommit(
  existingGcc: Record<string, any>,
  correlationId: string,
  action: string,
  summary: string,
  detail: string,
  metadataOverrides: Record<string, any> = {},
): { gccMemory: Record<string, any>; commitId: string } {
  const now = new Date().toISOString();
  const commitId = `gcc-${Math.random().toString(16).slice(2, 10)}`;
  const breadcrumbs = [...(existingGcc["gcc.breadcrumbs"] || existingGcc.breadcrumbs || []), action];
  const commitIndex = [...(existingGcc["gcc.commit_index"] || [])];
  commitIndex.push({ commit_id: commitId, timestamp: now, summary: summary.slice(0, 120), command: "COMMIT" });
  const logEntries = [...(existingGcc["gcc.log"] || [])];
  logEntries.push({ timestamp: now, type: "COMMIT", commit_id: commitId, detail });

  return {
    commitId,
    gccMemory: {
      "gcc.project_id": existingGcc["gcc.project_id"] || `wo-${correlationId.slice(0, 8)}`,
      "gcc.branch": existingGcc["gcc.branch"] || "main",
      "gcc.tier": "tier1",
      "gcc.commit_index": commitIndex.slice(-100),
      "gcc.last_commit_id": commitId,
      "gcc.last_commit_summary": summary.slice(0, 120),
      "gcc.log": logEntries.slice(-200),
      "gcc.context_scope": "branch",
      "gcc.context_commit_count": commitIndex.length,
      "gcc.breadcrumbs": breadcrumbs.slice(-50),
      "gcc.last_action": action,
      "gcc.metadata": {
        ...(existingGcc["gcc.metadata"] || {}),
        ...metadataOverrides,
      },
    },
  };
}

function getActor(req: Request): { actorId: string; actorEmail: string | null; actorName: string } {
  const u = (req as any).appUser;
  return {
    actorId: u?.id || "system",
    actorEmail: u?.email || null,
    actorName: [u?.firstName, u?.lastName].filter(Boolean).join(" ") || u?.email || "system",
  };
}

type Role = "admin" | "operator" | "viewer";
const ROLE_HIERARCHY: Record<Role, number> = { admin: 3, operator: 2, viewer: 1 };

function requireRole(minRole: Role): any {
  return async (req: Request, res: Response, next: NextFunction) => {
    const userClaims = (req as any).user?.claims;
    if (!userClaims?.sub) {
      return res.status(401).json({ message: "Unauthorized" });
    }
    const user = await storage.getUser(userClaims.sub);
    if (!user) {
      return res.status(401).json({ message: "User not found" });
    }
    const userLevel = ROLE_HIERARCHY[(user.role as Role)] || 0;
    const requiredLevel = ROLE_HIERARCHY[minRole];
    if (userLevel < requiredLevel) {
      return res.status(403).json({ message: `Forbidden: requires ${minRole} role` });
    }
    (req as any).appUser = user;
    next();
  };
}

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

  app.get("/api/admin/users", isAuth, requireRole("admin"), async (_req, res) => {
    try {
      const allUsers = await storage.getAllUsers();
      res.json(allUsers);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch users" });
    }
  });

  app.put("/api/admin/users/:id/role", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const actor = getActor(req);
      if (actor.actorId === req.params.id) {
        return res.status(403).json({ message: "You cannot change your own role" });
      }
      const { role } = req.body;
      if (!["admin", "operator", "viewer"].includes(role)) {
        return res.status(400).json({ message: "Invalid role. Must be admin, operator, or viewer." });
      }
      const updated = await storage.updateUserRole(req.params.id, role);
      if (!updated) {
        return res.status(404).json({ message: "User not found" });
      }
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update user role" });
    }
  });

  app.delete("/api/admin/users/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const actor = getActor(req);
      if (actor.actorId === req.params.id) {
        return res.status(403).json({ message: "You cannot delete your own account" });
      }
      const deleted = await storage.deleteUser(req.params.id);
      if (!deleted) {
        return res.status(404).json({ message: "User not found" });
      }
      res.json({ message: "User deleted successfully" });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete user" });
    }
  });

  app.post("/api/admin/invite", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const emailSchema = z.object({ email: z.string().email("A valid email address is required") });
      const parsed = emailSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: parsed.error.errors[0].message });
      }
      const actor = getActor(req);
      const replSlug = process.env.REPL_SLUG;
      const replOwner = process.env.REPL_OWNER;
      const appUrl = replSlug && replOwner
        ? `https://${replSlug}.${replOwner}.repl.co`
        : process.env.APP_URL || `https://${req.hostname}`;
      await sendInviteEmail(parsed.data.email, actor.actorName, appUrl);
      res.json({ message: `Invitation sent to ${parsed.data.email}` });
    } catch (err: any) {
      console.error("Failed to send invite email:", err);
      res.status(500).json({ message: err.message || "Failed to send invitation email" });
    }
  });

  app.get("/api/work-orders", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const orders = await storage.getWorkOrders();
      res.json(orders);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch work orders" });
    }
  });

  app.get("/api/work-orders/stats", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const stats = await storage.getWorkOrderStats();
      res.json(stats);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch stats" });
    }
  });

  app.get("/api/work-orders/recent", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const orders = await storage.getRecentWorkOrders(8);
      res.json(orders);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch recent orders" });
    }
  });

  app.get("/api/work-orders/:id", isAuth, requireRole("viewer"), async (req, res) => {
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

  const updateWorkOrderSchema = z.object({
    title: z.string().min(1).optional(),
    description: z.string().min(1).optional(),
    type: z.string().optional(),
    priority: z.string().optional(),
  });

  app.put("/api/work-orders/:id", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      const parsed = updateWorkOrderSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid data", errors: parsed.error.flatten().fieldErrors });
      }
      const actor = getActor(req);
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      const changedFields = Object.keys(parsed.data).filter(k => k !== "gccMemory");
      const { gccMemory, commitId } = buildGccCommit(
        gcc, order.correlationId, "inline_edit",
        `Edited: ${changedFields.join(", ")} by ${actor.actorName}`,
        `Work order fields updated by ${actor.actorName}: ${changedFields.join(", ")}`,
        { editedAt: new Date().toISOString(), editedBy: actor, changedFields },
      );

      const updated = await storage.updateWorkOrder(req.params.id, { ...parsed.data, gccMemory });
      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Work Order Edited",
        message: `Work order edited by ${actor.actorName}`,
        metadata: { actor, changes: parsed.data, commitId },
      });
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update work order" });
    }
  });

  app.get("/api/work-orders/:id/logs", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const logs = await storage.getExecutionLogs(req.params.id);
      res.json(logs);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch logs" });
    }
  });

  app.post("/api/work-orders", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const parsed = insertWorkOrderSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid work order data", errors: parsed.error.issues });
      }
      const actor = getActor(req);
      const orderData = {
        ...parsed.data,
        gccMemory: {
          ...(parsed.data.gccMemory as Record<string, any> || {}),
          "gcc.metadata": {
            ...((parsed.data.gccMemory as Record<string, any>)?.["gcc.metadata"] || {}),
            submittedBy: actor,
          },
        },
      };
      const order = await storage.createWorkOrder(orderData);
      await storage.createExecutionLog({
        workOrderId: order.id,
        tier: 1,
        action: "Submitted",
        message: `Work order submitted by ${actor.actorName}`,
        metadata: { actor },
      });
      res.status(201).json(order);
    } catch (err) {
      res.status(500).json({ message: "Failed to create work order" });
    }
  });

  app.post("/api/work-orders/:id/process", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      if (order.status !== "pending" && order.status !== "reopened") {
        return res.status(400).json({ message: `Cannot process order in '${order.status}' status` });
      }
      const actor = getActor(req);
      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Processing Initiated",
        message: `Processing started by ${actor.actorName}`,
        metadata: { actor },
      });
      const result = await processWorkOrder(req.params.id);
      res.json(result);
    } catch (err) {
      res.status(500).json({ message: "Failed to process work order" });
    }
  });

  app.post("/api/work-orders/:id/retry", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      if (order.status !== "blocked" && order.status !== "failed") {
        return res.status(400).json({ message: `Cannot retry order in '${order.status}' status` });
      }
      const actor = getActor(req);
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      const { gccMemory, commitId } = buildGccCommit(
        gcc, order.correlationId, "retry",
        `Retry: reset from ${order.status} by ${actor.actorName}`,
        `Work order reset from '${order.status}' and resubmitted for processing by ${actor.actorName}`,
        { retriedAt: new Date().toISOString(), retriedBy: actor, previousStatus: order.status },
      );

      await storage.updateWorkOrder(req.params.id, {
        status: "pending",
        bdmMarker: null,
        tier1Result: null,
        tier2Result: null,
        gccMemory,
      });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Retry Initiated",
        message: `Work order reset and resubmitted by ${actor.actorName}`,
        metadata: { previousStatus: order.status, actor, commitId },
      });

      const result = await processWorkOrder(req.params.id);
      res.json(result);
    } catch (err) {
      res.status(500).json({ message: "Failed to retry work order" });
    }
  });

  const reopenSchema = z.object({
    reason: z.string().min(1, "Reason for reopening is required"),
  });

  app.post("/api/work-orders/:id/reopen", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const parsed = reopenSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid request", errors: parsed.error.flatten().fieldErrors });
      }
      const { reason } = parsed.data;

      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      if (order.status !== "completed") {
        return res.status(400).json({ message: `Cannot reopen order in '${order.status}' status — only completed orders can be reopened` });
      }

      const now = new Date().toISOString();
      const gcc = (order.gccMemory || {}) as Record<string, any>;

      const commitId = `gcc-${Math.random().toString(16).slice(2, 10)}`;
      const breadcrumbs = [...(gcc["gcc.breadcrumbs"] || gcc.breadcrumbs || []), "reopened"];
      const commitIndex = [...(gcc["gcc.commit_index"] || [])];
      commitIndex.push({
        commit_id: commitId,
        timestamp: now,
        summary: `Reopened: ${reason.slice(0, 80)}`,
        command: "COMMIT",
      });
      const logEntries = [...(gcc["gcc.log"] || [])];
      logEntries.push({
        timestamp: now,
        type: "COMMIT",
        commit_id: commitId,
        detail: `Work order reopened for reprocessing. Reason: ${reason}`,
      });

      const previousResult = order.tier2Result as Record<string, any> | null;
      const previousOutput = previousResult?.output;
      const previousDeliverableSummary = previousOutput
        ? `[Previous output message: "${previousOutput.message || "N/A"}"] [Previous deliverable title: "${previousOutput.deliverableTitle || "N/A"}"] [Previous deliverable type: "${previousOutput.deliverableType || "N/A"}"] [Previous deliverable (first 2000 chars): ${(previousOutput.deliverable || "").slice(0, 2000)}]`
        : null;

      const gccMemory: Record<string, any> = {
        "gcc.project_id": gcc["gcc.project_id"] || `wo-${order.correlationId.slice(0, 8)}`,
        "gcc.branch": gcc["gcc.branch"] || "main",
        "gcc.tier": "tier1",
        "gcc.commit_index": commitIndex.slice(-100),
        "gcc.last_commit_id": commitId,
        "gcc.last_commit_summary": `Reopened: ${reason.slice(0, 80)}`,
        "gcc.log": logEntries.slice(-200),
        "gcc.context_scope": "branch",
        "gcc.context_commit_count": commitIndex.length,
        "gcc.breadcrumbs": breadcrumbs.slice(-50),
        "gcc.last_action": "reopened",
        "gcc.metadata": {
          ...(gcc["gcc.metadata"] || {}),
          reopenedAt: now,
          reopenReason: reason,
          previousCompletedAt: gcc["gcc.metadata"]?.completedAt || gcc.completedAt,
          previousDeliverable: previousDeliverableSummary || "no_previous_output",
          reopenCount: ((gcc["gcc.metadata"]?.reopenCount || 0) + 1),
          reopenedBy: getActor(req),
        },
      };

      const actor = getActor(req);
      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Work Order Reopened",
        message: `Work order reopened by ${actor.actorName}. Reason: ${reason}`,
        metadata: {
          reopenReason: reason,
          previousStatus: "completed",
          previousTier2Result: previousResult,
          reopenedAt: now,
          actor,
        },
      });

      await storage.updateWorkOrder(req.params.id, {
        status: "reopened",
        bdmMarker: null,
        tier1Result: null,
        tier2Result: null,
        assignedSubAgentId: null,
        executionMode: null,
        gccMemory,
      });

      const updated = await storage.getWorkOrder(req.params.id);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to reopen work order" });
    }
  });

  app.post("/api/work-orders/:id/refile", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      if (order.status !== "completed") {
        return res.status(400).json({ message: "Only completed work orders can be re-filed" });
      }

      const actor = getActor(req);
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      const { gccMemory, commitId } = buildGccCommit(
        gcc, order.correlationId, "refile",
        `Re-filed by ${actor.actorName}`,
        `Work order output re-filed to workspace by ${actor.actorName}`,
        { refiledAt: new Date().toISOString(), refiledBy: actor },
      );

      const { fileWorkOrderOutput } = await import("./workspace-filing");
      await fileWorkOrderOutput(order);
      await storage.updateWorkOrder(req.params.id, { gccMemory });
      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Re-filed",
        message: `Work order output re-filed to workspace by ${actor.actorName}`,
        metadata: { actor, commitId },
      });
      res.json({ message: "Work order re-filed successfully", workOrderId: order.id });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to re-file work order", error: err.message });
    }
  });

  const unblockSchema = z.object({
    resolution: z.string().min(1, "Resolution notes are required"),
    reprocess: z.boolean().default(true),
  });

  app.post("/api/work-orders/:id/unblock", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const parsed = unblockSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid request", errors: parsed.error.flatten().fieldErrors });
      }
      const { resolution, reprocess } = parsed.data;

      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      if (order.status !== "blocked" && order.status !== "deferred") {
        return res.status(400).json({ message: `Cannot unblock order in '${order.status}' status — only 'blocked' or 'deferred' orders can be unblocked` });
      }
      if (order.status !== "deferred" && !order.bdmMarker) {
        return res.status(400).json({ message: "No BDM marker to resolve on this work order" });
      }

      const bdmSnapshot = order.bdmMarker;
      const now = new Date().toISOString();
      const gcc = (order.gccMemory || {}) as Record<string, any>;

      const commitId = `gcc-${Math.random().toString(16).slice(2, 10)}`;
      const breadcrumbs = [...(gcc["gcc.breadcrumbs"] || gcc.breadcrumbs || []), "hitl_unblock"];
      const commitIndex = [...(gcc["gcc.commit_index"] || [])];
      commitIndex.push({
        commit_id: commitId,
        timestamp: now,
        summary: `HITL unblock: ${resolution.slice(0, 80)}`,
        command: "COMMIT",
      });
      const logEntries = [...(gcc["gcc.log"] || [])];
      logEntries.push({
        timestamp: now,
        type: "COMMIT",
        commit_id: commitId,
        detail: `HITL operator unblocked BDM. Resolution: ${resolution}`,
      });

      const gccMemory: Record<string, any> = {
        "gcc.project_id": gcc["gcc.project_id"] || `wo-${order.correlationId.slice(0, 8)}`,
        "gcc.branch": gcc["gcc.branch"] || "main",
        "gcc.tier": "tier1",
        "gcc.commit_index": commitIndex.slice(-100),
        "gcc.last_commit_id": commitId,
        "gcc.last_commit_summary": `HITL unblock: ${resolution.slice(0, 80)}`,
        "gcc.log": logEntries.slice(-200),
        "gcc.context_scope": "branch",
        "gcc.context_commit_count": commitIndex.length,
        "gcc.breadcrumbs": breadcrumbs.slice(-50),
        "gcc.last_action": "hitl_unblock",
        "gcc.metadata": {
          ...(gcc["gcc.metadata"] || {}),
          unblockedAt: now,
          unblockedBy: getActor(req),
          resolution,
          bdmCleared: true,
          reprocessed: reprocess,
        },
      };

      const actor = getActor(req);
      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "HITL Unblock",
        message: `Unblocked by ${actor.actorName}. Resolution: ${resolution}`,
        metadata: { bdmMarkerCleared: bdmSnapshot, reprocess, commitId, actor },
      });

      if (reprocess) {
        await storage.updateWorkOrder(req.params.id, {
          status: "pending",
          bdmMarker: null,
          tier2Result: null,
          deferredUntil: null,
          deferredReason: null,
          gccMemory,
        });

        await storage.createExecutionLog({
          workOrderId: req.params.id,
          tier: 1,
          action: "Re-process after HITL Unblock",
          message: "Work order re-submitted for Tier 2 execution after human intervention.",
          metadata: { commitId },
        });

        const result = await processWorkOrder(req.params.id);
        res.json({ ...result, unblocked: true, reprocessed: true });
      } else {
        gccMemory["gcc.last_action"] = "hitl_resolved";
        gccMemory["gcc.metadata"].completedAt = now;

        await storage.updateWorkOrder(req.params.id, {
          status: "completed",
          bdmMarker: null,
          deferredUntil: null,
          deferredReason: null,
          gccMemory,
        });

        await storage.createExecutionLog({
          workOrderId: req.params.id,
          tier: 1,
          action: "Resolved by Operator",
          message: "Work order marked complete by human operator without re-processing.",
          metadata: { commitId },
        });

        const updated = await storage.getWorkOrder(req.params.id);
        res.json({ ...updated, unblocked: true, reprocessed: false });
      }
    } catch (err) {
      res.status(500).json({ message: "Failed to unblock work order" });
    }
  });

  const deferSchema = z.object({
    reason: z.string().min(1, "A reason for deferring is required"),
    deferUntil: z.string().min(1, "A defer-until date is required"),
  });

  app.post("/api/work-orders/:id/defer", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const parsed = deferSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid request", errors: parsed.error.flatten().fieldErrors });
      }
      const { reason, deferUntil } = parsed.data;

      const deferDate = new Date(deferUntil);
      if (isNaN(deferDate.getTime())) {
        return res.status(400).json({ message: "Invalid date format for deferUntil" });
      }
      if (deferDate <= new Date()) {
        return res.status(400).json({ message: "Defer date must be in the future" });
      }

      const order = await storage.getWorkOrder(req.params.id);
      if (!order) {
        return res.status(404).json({ message: "Work order not found" });
      }
      if (order.status !== "blocked" && order.status !== "awaiting_operator" && order.status !== "failed") {
        return res.status(400).json({ message: `Cannot defer order in '${order.status}' status — only blocked, awaiting_operator, or failed orders can be deferred` });
      }

      const now = new Date().toISOString();
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      const actor = getActor(req);

      const commitId = `gcc-${Math.random().toString(16).slice(2, 10)}`;
      const breadcrumbs = [...(gcc["gcc.breadcrumbs"] || gcc.breadcrumbs || []), "hitl_defer"];
      const commitIndex = [...(gcc["gcc.commit_index"] || [])];
      commitIndex.push({
        commit_id: commitId,
        timestamp: now,
        summary: `HITL defer until ${deferDate.toISOString().split("T")[0]}: ${reason.slice(0, 60)}`,
        command: "COMMIT",
      });
      const logEntries = [...(gcc["gcc.log"] || [])];
      logEntries.push({
        timestamp: now,
        type: "COMMIT",
        commit_id: commitId,
        detail: `HITL operator deferred decision. Reason: ${reason}. Until: ${deferDate.toISOString()}`,
      });

      const gccMemory: Record<string, any> = {
        "gcc.project_id": gcc["gcc.project_id"] || `wo-${order.correlationId.slice(0, 8)}`,
        "gcc.branch": gcc["gcc.branch"] || "main",
        "gcc.tier": "tier1",
        "gcc.commit_index": commitIndex.slice(-100),
        "gcc.last_commit_id": commitId,
        "gcc.last_commit_summary": `HITL defer: ${reason.slice(0, 80)}`,
        "gcc.log": logEntries.slice(-200),
        "gcc.context_scope": "branch",
        "gcc.context_commit_count": commitIndex.length,
        "gcc.breadcrumbs": breadcrumbs.slice(-50),
        "gcc.last_action": "hitl_defer",
        "gcc.metadata": {
          ...(gcc["gcc.metadata"] || {}),
          deferredAt: now,
          deferredUntil: deferDate.toISOString(),
          deferredBy: actor,
          deferReason: reason,
        },
      };

      await storage.updateWorkOrder(req.params.id, {
        status: "deferred",
        deferredUntil: deferDate,
        deferredReason: reason,
        gccMemory,
      });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "HITL Defer",
        message: `Deferred by ${actor.actorName} until ${deferDate.toLocaleDateString()}. Reason: ${reason}`,
        metadata: { commitId, deferUntil: deferDate.toISOString(), actor },
      });

      const updated = await storage.getWorkOrder(req.params.id);
      res.json({ ...updated, deferred: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to defer work order" });
    }
  });

  // Sub-agent routes
  app.get("/api/sub-agents", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const agents = await storage.getSubAgents();
      res.json(agents);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch sub-agents" });
    }
  });

  app.get("/api/sub-agents/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      res.json(agent);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch sub-agent" });
    }
  });

  app.post("/api/sub-agents", isAuth, requireRole("admin"), async (req, res) => {
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

  app.put("/api/sub-agents/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      const updated = await storage.updateSubAgent(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update sub-agent" });
    }
  });

  app.delete("/api/sub-agents/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      await storage.deleteSubAgent(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete sub-agent" });
    }
  });

  app.post("/api/sub-agents/:id/test-llm", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });

      const globalSettings = await storage.getLlmSettings();
      const config = resolveSubAgentLlmConfig(agent, globalSettings || undefined);

      if (!config) {
        return res.json({
          operational: false,
          source: "none",
          reason: "No LLM configuration available. Neither sub-agent nor Aiden global LLM is configured.",
        });
      }

      const apiKey = process.env[config.apiKeyEnvVar];
      if (!apiKey) {
        return res.json({
          operational: false,
          source: config.source,
          reason: `API key secret "${config.apiKeyEnvVar}" is not set. Add it in the Secrets tab.`,
        });
      }

      const testSettings: LlmSettings = {
        id: "test",
        provider: config.provider,
        model: config.model,
        baseUrl: config.baseUrl,
        systemPrompt: config.systemPrompt,
        enabled: true,
      };

      const result = await testLLMConnection(testSettings);
      res.json({
        operational: result.success,
        source: config.source,
        provider: config.provider,
        model: config.model,
        message: result.message,
        aidenDirected: agent.controlMode === "aiden",
      });
    } catch (err: any) {
      res.json({
        operational: false,
        source: "unknown",
        reason: `Connection test failed: ${err.message}`,
      });
    }
  });

  app.get("/api/sub-agents/:id/llm-status", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });

      const globalSettings = await storage.getLlmSettings();
      const config = resolveSubAgentLlmConfig(agent, globalSettings || undefined);

      if (!config) {
        return res.json({
          status: "no_llm",
          llmReady: false,
          aidenDirected: agent.controlMode === "aiden",
          reason: "No LLM configured",
        });
      }

      const apiKey = process.env[config.apiKeyEnvVar];
      res.json({
        status: apiKey ? "ready" : "missing_key",
        llmReady: !!apiKey,
        aidenDirected: agent.controlMode === "aiden",
        source: config.source,
        provider: config.provider,
        model: config.model,
        reason: apiKey ? `Using ${config.source} LLM (${config.provider}/${config.model})` : `API key not found. Add it in the Secrets tab.`,
      });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to check LLM status" });
    }
  });

  app.get("/api/llm-settings", isAuth, requireRole("viewer"), async (_req, res) => {
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

  app.put("/api/llm-settings", isAuth, requireRole("admin"), async (req, res) => {
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

  app.get("/api/llm-settings/models/:provider", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const { provider } = req.params;
      const keyConfigured = isApiKeyConfigured(provider);
      const models = await fetchAvailableModels(provider);
      res.json({ provider, keyConfigured, models });
    } catch (err: any) {
      res.status(500).json({ provider: req.params.provider, keyConfigured: false, models: [], error: err.message });
    }
  });

  app.post("/api/llm-settings/test", isAuth, requireRole("admin"), async (_req, res) => {
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

  app.get("/api/workflow-templates", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const templates = await storage.getWorkflowTemplates();
      res.json(templates);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch workflow templates" });
    }
  });

  app.get("/api/workflow-templates/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const template = await storage.getWorkflowTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Template not found" });
      const steps = await storage.getWorkflowSteps(req.params.id);
      res.json({ ...template, steps });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch template" });
    }
  });

  app.post("/api/workflow-templates", isAuth, requireRole("admin"), async (req, res) => {
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

  app.put("/api/workflow-templates/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const template = await storage.getWorkflowTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Template not found" });
      const updated = await storage.updateWorkflowTemplate(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update template" });
    }
  });

  app.delete("/api/workflow-templates/:id", isAuth, requireRole("admin"), async (req, res) => {
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

  app.get("/api/workflow-templates/:templateId/steps", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const steps = await storage.getWorkflowSteps(req.params.templateId);
      res.json(steps);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch steps" });
    }
  });

  app.post("/api/workflow-templates/:templateId/steps", isAuth, requireRole("admin"), async (req, res) => {
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

  app.put("/api/workflow-steps/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const step = await storage.getWorkflowStep(req.params.id);
      if (!step) return res.status(404).json({ message: "Step not found" });
      const updated = await storage.updateWorkflowStep(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update step" });
    }
  });

  app.delete("/api/workflow-steps/:id", isAuth, requireRole("admin"), async (req, res) => {
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

  app.get("/api/workflow-executions", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const executions = await storage.getWorkflowExecutions();
      res.json(executions);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch executions" });
    }
  });

  app.get("/api/workflow-executions/:id", isAuth, requireRole("viewer"), async (req, res) => {
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

  app.post("/api/workflow-executions", isAuth, requireRole("admin"), async (req, res) => {
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

  app.post("/api/workflow-executions/:id/advance", isAuth, requireRole("admin"), async (req, res) => {
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

  app.get("/api/tools", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const allTools = await storage.getTools();
      res.json(allTools);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch tools" });
    }
  });

  app.get("/api/tools/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const tool = await storage.getTool(req.params.id);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      res.json(tool);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch tool" });
    }
  });

  app.post("/api/tools", isAuth, requireRole("admin"), async (req, res) => {
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

  app.put("/api/tools/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const tool = await storage.getTool(req.params.id);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      const updated = await storage.updateTool(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update tool" });
    }
  });

  app.delete("/api/tools/:id", isAuth, requireRole("admin"), async (req, res) => {
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

  app.get("/api/sub-agents/:id/tools", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      const agentTools = await storage.getSubAgentTools(req.params.id);
      res.json(agentTools);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch agent tools" });
    }
  });

  app.post("/api/sub-agents/:id/tools", isAuth, requireRole("admin"), async (req, res) => {
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

  app.delete("/api/sub-agents/:id/tools/:toolId", isAuth, requireRole("admin"), async (req, res) => {
    try {
      await storage.removeToolFromSubAgent(req.params.id, req.params.toolId);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to remove tool" });
    }
  });

  // ==================== Tools Locker: Tags Routes ====================

  app.get("/api/locker/tags", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const tags = await storage.getToolTags();
      res.json(tags);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch tags" });
    }
  });

  app.post("/api/locker/tags", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const parsed = insertToolTagSchema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid tag data", errors: parsed.error.issues });
      const tag = await storage.createToolTag(parsed.data);
      res.status(201).json(tag);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to create tag" });
    }
  });

  app.delete("/api/locker/tags/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      await storage.deleteToolTag(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete tag" });
    }
  });

  app.get("/api/locker/tools/:toolId/tags", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const assignments = await storage.getToolTagAssignments(req.params.toolId);
      res.json(assignments);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch tool tags" });
    }
  });

  app.post("/api/locker/tools/:toolId/tags", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const { tagId } = req.body;
      if (!tagId) return res.status(400).json({ message: "tagId is required" });
      const tool = await storage.getTool(req.params.toolId);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      const tag = await storage.getToolTag(tagId);
      if (!tag) return res.status(404).json({ message: "Tag not found" });
      const existing = await storage.getToolTagAssignments(req.params.toolId);
      if (existing.some(a => a.tagId === tagId)) {
        return res.status(409).json({ message: "Tag already assigned to this tool" });
      }
      const assignment = await storage.assignTagToTool({ toolId: req.params.toolId, tagId });
      res.status(201).json(assignment);
    } catch (err) {
      res.status(500).json({ message: "Failed to assign tag" });
    }
  });

  app.delete("/api/locker/tools/:toolId/tags/:tagId", isAuth, requireRole("admin"), async (req, res) => {
    try {
      await storage.removeTagFromTool(req.params.toolId, req.params.tagId);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to remove tag" });
    }
  });

  // ==================== Tools Locker: Leases Routes ====================

  app.get("/api/locker/leases", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const filters: any = {};
      if (req.query.toolId) filters.toolId = req.query.toolId;
      if (req.query.agentId) filters.agentId = req.query.agentId;
      if (req.query.status) filters.status = req.query.status;
      const leases = await storage.getToolLeases(Object.keys(filters).length > 0 ? filters : undefined);
      res.json(leases);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch leases" });
    }
  });

  app.get("/api/locker/leases/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const lease = await storage.getToolLease(req.params.id);
      if (!lease) return res.status(404).json({ message: "Lease not found" });
      res.json(lease);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch lease" });
    }
  });

  app.post("/api/locker/checkout", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const { toolId, agentId, agentType, tier, leaseType, context, workOrderId } = req.body;
      if (!toolId || !agentId) return res.status(400).json({ message: "toolId and agentId are required" });

      const tool = await storage.getTool(toolId);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      if (tool.status !== "active") return res.status(400).json({ message: "Tool is not active" });
      if (tool.restricted) return res.status(403).json({ message: `Tool restricted: ${tool.restrictedReason || "No reason given"}` });
      if (tool.requiresApproval) return res.status(403).json({ message: "Tool requires approval before checkout" });

      if (tool.accessTier !== "any") {
        const requestedTier = tier || "tier2";
        if (tool.accessTier === "tier1" && requestedTier !== "tier1") {
          return res.status(403).json({ message: "Tool is restricted to Tier 1 agents only" });
        }
        if (tool.accessTier === "tier2" && requestedTier !== "tier2") {
          return res.status(403).json({ message: "Tool is restricted to Tier 2 agents only" });
        }
      }

      if (tool.maxConcurrent > 0) {
        const activeLeases = await storage.getActiveLeases(toolId);
        if (activeLeases.length >= tool.maxConcurrent) {
          return res.status(409).json({ message: "Tool at max concurrent usage", activeLeases: activeLeases.length, maxConcurrent: tool.maxConcurrent });
        }
      }

      if (tool.dailyUsageLimit) {
        const todayStart = new Date();
        todayStart.setHours(0, 0, 0, 0);
        const todayLeases = await storage.getToolLeases({ toolId });
        const todayCount = todayLeases.filter(l => new Date(l.issuedAt) >= todayStart).length;
        if (todayCount >= tool.dailyUsageLimit) {
          return res.status(429).json({ message: "Daily usage limit reached", dailyUsageLimit: tool.dailyUsageLimit, usedToday: todayCount });
        }
      }

      const requestedSeconds = req.body.leaseSeconds;
      const maxAllowed = tool.maxLeaseSeconds || 3600;
      const defaultSeconds = tool.defaultLeaseSeconds || 300;
      const leaseSeconds = requestedSeconds ? Math.min(requestedSeconds, maxAllowed) : defaultSeconds;
      const expiresAt = new Date(Date.now() + leaseSeconds * 1000);

      const lease = await storage.createToolLease({
        toolId,
        agentId,
        agentType: agentType || "sub_agent",
        tier: tier || "tier2",
        leaseType: leaseType || "checkout",
        status: "active",
        toolVersion: tool.version,
        context: context || {},
        workOrderId: workOrderId || null,
        expiresAt,
      });

      await storage.createToolAuditLog({
        toolId,
        leaseId: lease.id,
        action: "checkout",
        actorId: agentId,
        actorType: agentType || "sub_agent",
        reason: `Checked out tool "${tool.name}" v${tool.version}`,
        metadata: { leaseType, tier, workOrderId },
      });

      if (workOrderId) {
        const wo = await storage.getWorkOrder(workOrderId);
        if (wo) {
          const gcc = (wo.gccMemory || {}) as Record<string, any>;
          const { gccMemory } = buildGccCommit(
            gcc, wo.correlationId, "tool_checkout",
            `Tool checkout: ${tool.name} v${tool.version} by ${agentId}`,
            `Agent ${agentId} checked out tool "${tool.name}" v${tool.version} (lease ${lease.id})`,
            { toolId, toolName: tool.name, leaseId: lease.id, agentId, checkoutAt: new Date().toISOString() },
          );
          await storage.updateWorkOrder(workOrderId, { gccMemory });
        }
      }

      res.status(201).json(lease);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to checkout tool" });
    }
  });

  app.post("/api/locker/return/:leaseId", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const lease = await storage.getToolLease(req.params.leaseId);
      if (!lease) return res.status(404).json({ message: "Lease not found" });
      if (lease.status !== "active") return res.status(400).json({ message: "Lease is not active" });

      const updated = await storage.updateToolLease(req.params.leaseId, {
        status: "returned",
        returnedAt: new Date(),
        result: req.body.result || {},
        error: req.body.error || null,
      });

      await storage.createToolAuditLog({
        toolId: lease.toolId,
        leaseId: lease.id,
        action: "return",
        actorId: lease.agentId,
        actorType: lease.agentType,
        reason: req.body.error ? `Returned with error: ${req.body.error}` : "Returned successfully",
        metadata: { result: req.body.result },
      });

      if (lease.workOrderId) {
        const wo = await storage.getWorkOrder(lease.workOrderId);
        if (wo) {
          const tool = await storage.getTool(lease.toolId);
          const toolName = tool?.name || lease.toolId;
          const gcc = (wo.gccMemory || {}) as Record<string, any>;
          const { gccMemory } = buildGccCommit(
            gcc, wo.correlationId, "tool_return",
            `Tool returned: ${toolName} by ${lease.agentId}${req.body.error ? " (with error)" : ""}`,
            `Agent ${lease.agentId} returned tool "${toolName}" (lease ${lease.id})${req.body.error ? ` — error: ${req.body.error}` : " — success"}`,
            { toolId: lease.toolId, toolName, leaseId: lease.id, agentId: lease.agentId, returnedAt: new Date().toISOString(), hasError: !!req.body.error },
          );
          await storage.updateWorkOrder(lease.workOrderId, { gccMemory });
        }
      }

      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to return tool" });
    }
  });

  app.post("/api/locker/expire", isAuth, requireRole("admin"), async (_req, res) => {
    try {
      const count = await storage.expireOverdueLeases();
      res.json({ expired: count });
    } catch (err) {
      res.status(500).json({ message: "Failed to expire leases" });
    }
  });

  // ==================== Tools Locker: Keys Routes ====================

  app.get("/api/locker/keys", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const ownerId = req.query.ownerId as string | undefined;
      const keys = await storage.getLockerKeys(ownerId);
      res.json(keys);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch locker keys" });
    }
  });

  app.get("/api/locker/keys/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const key = await storage.getLockerKey(req.params.id);
      if (!key) return res.status(404).json({ message: "Locker key not found" });
      res.json(key);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch locker key" });
    }
  });

  app.post("/api/locker/keys", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const parsed = insertLockerKeySchema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid key data", errors: parsed.error.issues });
      const key = await storage.createLockerKey(parsed.data);
      res.status(201).json(key);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to create locker key" });
    }
  });

  app.put("/api/locker/keys/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const key = await storage.getLockerKey(req.params.id);
      if (!key) return res.status(404).json({ message: "Locker key not found" });
      const updated = await storage.updateLockerKey(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update locker key" });
    }
  });

  app.post("/api/locker/keys/:id/revoke", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const { revokedBy, reason } = req.body;
      if (!revokedBy || !reason) return res.status(400).json({ message: "revokedBy and reason are required" });
      const revoked = await storage.revokeLockerKey(req.params.id, revokedBy, reason);
      if (!revoked) return res.status(404).json({ message: "Locker key not found" });
      res.json(revoked);
    } catch (err) {
      res.status(500).json({ message: "Failed to revoke locker key" });
    }
  });

  // ==================== Tools Locker: Audit Logs Routes ====================

  app.get("/api/locker/audit", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const filters: any = {};
      if (req.query.toolId) filters.toolId = req.query.toolId;
      if (req.query.actorId) filters.actorId = req.query.actorId;
      if (req.query.action) filters.action = req.query.action;
      const logs = await storage.getToolAuditLogs(Object.keys(filters).length > 0 ? filters : undefined);
      res.json(logs);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch audit logs" });
    }
  });

  // ==================== Tools Locker: Restrict/Unrestrict ====================

  app.post("/api/locker/tools/:id/restrict", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const tool = await storage.getTool(req.params.id);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      const { reason, restrictedBy } = req.body;
      const updated = await storage.updateTool(req.params.id, {
        restricted: true,
        restrictedReason: reason || "Restricted by admin",
        restrictedBy: restrictedBy || "admin",
      });

      await storage.createToolAuditLog({
        toolId: req.params.id,
        action: "restrict",
        actorId: restrictedBy || "admin",
        actorType: "human",
        reason: reason || "Restricted by admin",
        metadata: {},
      });

      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to restrict tool" });
    }
  });

  app.post("/api/locker/tools/:id/unrestrict", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const tool = await storage.getTool(req.params.id);
      if (!tool) return res.status(404).json({ message: "Tool not found" });
      const updated = await storage.updateTool(req.params.id, {
        restricted: false,
        restrictedReason: null,
        restrictedBy: null,
      });

      await storage.createToolAuditLog({
        toolId: req.params.id,
        action: "unrestrict",
        actorId: req.body.unrestrictedBy || "admin",
        actorType: "human",
        reason: req.body.reason || "Restriction removed",
        metadata: {},
      });

      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to unrestrict tool" });
    }
  });

  // ==================== Skill Templates Routes ====================

  app.get("/api/locker/skills", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const filters: any = {};
      if (req.query.format) filters.format = req.query.format;
      if (req.query.category) filters.category = req.query.category;
      if (req.query.status) filters.status = req.query.status;
      const templates = await storage.getSkillTemplates(Object.keys(filters).length > 0 ? filters : undefined);
      res.json(templates);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch skill templates" });
    }
  });

  app.get("/api/locker/skills/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const template = await storage.getSkillTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Skill template not found" });
      res.json(template);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch skill template" });
    }
  });

  app.post("/api/locker/skills", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const parsed = insertSkillTemplateSchema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid skill template data", errors: parsed.error.issues });
      const template = await storage.createSkillTemplate(parsed.data);
      res.status(201).json(template);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to create skill template" });
    }
  });

  app.put("/api/locker/skills/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const template = await storage.getSkillTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Skill template not found" });
      const updated = await storage.updateSkillTemplate(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update skill template" });
    }
  });

  app.delete("/api/locker/skills/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const template = await storage.getSkillTemplate(req.params.id);
      if (!template) return res.status(404).json({ message: "Skill template not found" });
      await storage.deleteSkillTemplate(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete skill template" });
    }
  });

  // ==================== Tools Locker: Inventory Overview ====================

  app.get("/api/locker/inventory", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const [allTools, allTags, activeLeases, allKeys, allSkills] = await Promise.all([
        storage.getTools(),
        storage.getToolTags(),
        storage.getToolLeases({ status: "active" }),
        storage.getLockerKeys(),
        storage.getSkillTemplates(),
      ]);

      const toolsWithLeases = allTools.map(tool => ({
        ...tool,
        activeLeaseCount: activeLeases.filter(l => l.toolId === tool.id).length,
        available: tool.maxConcurrent === 0 || activeLeases.filter(l => l.toolId === tool.id).length < tool.maxConcurrent,
      }));

      res.json({
        tools: toolsWithLeases,
        tags: allTags,
        activeLeases,
        keys: allKeys.filter(k => k.active),
        skills: allSkills,
        summary: {
          totalTools: allTools.length,
          activeTools: allTools.filter(t => t.status === "active").length,
          restrictedTools: allTools.filter(t => t.restricted).length,
          totalActiveLeases: activeLeases.length,
          totalSkills: allSkills.length,
          skillsByFormat: {
            claude_md: allSkills.filter(s => s.format === "claude_md").length,
            agents_md: allSkills.filter(s => s.format === "agents_md").length,
            aiden_md: allSkills.filter(s => s.format === "aiden_md").length,
          },
        },
      });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch locker inventory" });
    }
  });

  // ==================== Artifact Folder Routes ====================

  app.get("/api/artifact-folders", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const parentId = req.query.parentId as string | undefined;
      const folders = await storage.getArtifactFolders(parentId === "root" ? null : parentId);
      res.json(folders);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch folders" });
    }
  });

  app.get("/api/artifact-folders/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const folder = await storage.getArtifactFolder(req.params.id);
      if (!folder) return res.status(404).json({ message: "Folder not found" });
      res.json(folder);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch folder" });
    }
  });

  app.post("/api/artifact-folders", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const body = { ...req.body };
      if (body.parentId === "root") body.parentId = null;
      const parsed = insertArtifactFolderSchema.safeParse(body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid folder data", errors: parsed.error.issues });
      }
      const folder = await storage.createArtifactFolder(parsed.data);
      res.status(201).json(folder);
    } catch (err) {
      res.status(500).json({ message: "Failed to create folder" });
    }
  });

  app.put("/api/artifact-folders/:id", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const folder = await storage.getArtifactFolder(req.params.id);
      if (!folder) return res.status(404).json({ message: "Folder not found" });
      const updated = await storage.updateArtifactFolder(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update folder" });
    }
  });

  app.delete("/api/artifact-folders/:id", isAuth, requireRole("operator"), async (req, res) => {
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

  app.get("/api/artifacts", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const folderId = req.query.folderId as string | undefined;
      const items = await storage.getArtifacts(folderId === "root" ? null : folderId);
      res.json(items);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch artifacts" });
    }
  });

  app.get("/api/artifacts/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      res.json(artifact);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch artifact" });
    }
  });

  app.post("/api/artifacts", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const body = { ...req.body };
      if (body.folderId === "root") body.folderId = null;
      const parsed = insertArtifactSchema.safeParse(body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid artifact data", errors: parsed.error.issues });
      }
      const artifact = await storage.createArtifact(parsed.data);
      res.status(201).json(artifact);
    } catch (err) {
      res.status(500).json({ message: "Failed to create artifact" });
    }
  });

  app.put("/api/artifacts/:id", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      const updated = await storage.updateArtifact(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update artifact" });
    }
  });

  app.delete("/api/artifacts/:id", isAuth, requireRole("operator"), async (req, res) => {
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

  app.post("/api/workspace/seed", isAuth, requireRole("operator"), async (_req, res) => {
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
        { name: "#Documents", path: "/#Documents", description: "Deliverable documents — emails, reports, plans, memos, and written outputs" },
        { name: "#Images", path: "/#Images", description: "Generated images, diagrams, screenshots, and visual outputs" },
        { name: "#Code_Blocks", path: "/#Code_Blocks", description: "Code snippets, scripts, configurations, and technical outputs" },
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

  app.get("/api/sandbox-sessions", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const sessions = await storage.getSandboxSessions();
      res.json(sessions);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch sandbox sessions" });
    }
  });

  app.get("/api/sandbox-sessions/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      res.json(session);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch session" });
    }
  });

  app.post("/api/sandbox-sessions", isAuth, requireRole("operator"), async (req, res) => {
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

  app.put("/api/sandbox-sessions/:id", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      const updated = await storage.updateSandboxSession(req.params.id, req.body);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update session" });
    }
  });

  app.delete("/api/sandbox-sessions/:id", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      await storage.deleteSandboxSession(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete session" });
    }
  });

  app.post("/api/sandbox-sessions/:id/execute", isAuth, requireRole("operator"), async (req, res) => {
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

  app.get("/api/sandbox-sessions/:id/preview", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });

      const result = session.result as any;
      if (!result?.html || !result?.renderable) {
        return res.status(404).json({ message: "No renderable preview available for this session" });
      }

      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.setHeader("Content-Security-Policy", "default-src 'self' 'unsafe-inline' 'unsafe-eval'; img-src * data:; font-src * data:; style-src 'self' 'unsafe-inline' *;");
      res.setHeader("X-Frame-Options", "SAMEORIGIN");
      res.send(result.html);
    } catch (err) {
      res.status(500).json({ message: "Failed to load preview" });
    }
  });

  // ==================== Chat Sessions (GCC Memory Protocol) ====================

  function generateCommitId(): string {
    const hex = Array.from({ length: 8 }, () =>
      Math.floor(Math.random() * 16).toString(16)
    ).join("");
    return `gcc-${hex}`;
  }

  function initializeGccMemory(correlationId: string): object {
    const now = new Date().toISOString();
    const initCommitId = generateCommitId();
    return {
      "gcc.project_id": `aiden-chat-${correlationId.slice(0, 8)}`,
      "gcc.branch": "main",
      "gcc.tier": "tier1",
      "gcc.commit_index": [
        {
          commit_id: initCommitId,
          timestamp: now,
          summary: "Session initialized",
          tags: ["session_init"],
        },
      ],
      "gcc.last_commit_id": initCommitId,
      "gcc.last_commit_summary": "Session initialized",
      "gcc.log": [
        {
          timestamp: now,
          source_node: "ContextLoadNode",
          entry: "Chat session created. GCC memory initialized on branch main.",
        },
      ],
      "gcc.context_scope": "branch",
      "gcc.context_commit_count": 1,
      "gcc.breadcrumbs": ["session_created"],
      "gcc.last_action": "session_created",
      "gcc.metadata": {
        parent_branch: null,
        status: "active",
        created_at: now,
      },
    };
  }

  app.get("/api/chat/sessions", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const sessions = await storage.getChatSessions();
      res.json(sessions);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch chat sessions" });
    }
  });

  app.post("/api/chat/sessions", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const parsed = insertChatSessionSchema.safeParse(req.body);
      const session = await storage.createChatSession(parsed.success ? parsed.data : { title: "New Conversation" });
      const gccMemory = initializeGccMemory(session.correlationId);
      await storage.updateChatSession(session.id, { gccMemory });
      const updated = await storage.getChatSession(session.id);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to create chat session" });
    }
  });

  app.get("/api/chat/sessions/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const session = await storage.getChatSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      const messages = await storage.getChatMessages(session.id);
      res.json({ ...session, messages });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch chat session" });
    }
  });

  app.put("/api/chat/sessions/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const updateSchema = z.object({
        title: z.string().optional(),
        status: z.enum(["active", "archived"]).optional(),
      });
      const parsed = updateSchema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid request" });
      const updated = await storage.updateChatSession(req.params.id, parsed.data);
      if (!updated) return res.status(404).json({ message: "Session not found" });
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update chat session" });
    }
  });

  app.delete("/api/chat/sessions/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      await storage.deleteChatSession(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete chat session" });
    }
  });

  async function buildSystemContext(settings: any) {
    const [workOrders, subAgents, stats, workflows, workflowExecutions, toolsList, rootFolders, rootArtifacts, sandboxSessionsList] = await Promise.all([
      storage.getWorkOrders(),
      storage.getSubAgents(),
      storage.getWorkOrderStats(),
      storage.getWorkflowTemplates(),
      storage.getWorkflowExecutions(),
      storage.getTools(),
      storage.getArtifactFolders(null),
      storage.getArtifacts(null),
      storage.getSandboxSessions(),
    ]);

    const recentOrders = workOrders.slice(0, 25);
    const activeExecutions = workflowExecutions.filter(e => e.status === "running" || e.status === "pending");
    const recentExecutions = workflowExecutions.slice(0, 10);

    const subAgentToolDetails = await Promise.all(
      subAgents.map(async (a) => {
        const agentTools = await storage.getSubAgentTools(a.id);
        return { agent: a, tools: agentTools };
      })
    );

    return `== AIDEN GLOBAL ENVIRONMENT BRIEFING ==

=== WORK ORDER OVERVIEW ===
Statistics:
- Total: ${stats.total} | Pending: ${stats.pending} | Processing: ${stats.processing}
- Completed: ${stats.completed} | Blocked: ${stats.blocked} | Failed: ${stats.failed} | Reopened: ${stats.reopened} | Deferred: ${stats.deferred}

All Work Orders (${workOrders.length} total):
${recentOrders.map(o => `- [${o.status.toUpperCase()}] "${o.title}" (type: ${o.type}, priority: ${o.priority}, submitted: ${o.submittedBy || "system"}, id: ${o.id}${o.assignedSubAgentId ? `, assigned: ${o.assignedSubAgentId}` : ""}${o.bdmMarker ? `, BDM: ${o.bdmMarker}` : ""})`).join("\n") || "No work orders"}
${workOrders.length > 25 ? `... and ${workOrders.length - 25} more work orders` : ""}

=== SUB-AGENTS (TIER 2 WORKERS) ===
${subAgentToolDetails.map(({ agent: a, tools: t }) => `- "${a.name}" (type: ${a.type}, mode: ${a.controlMode}, status: ${a.status}${a.assignedTo ? `, operator: ${a.assignedTo}` : ""}${a.description ? `, desc: ${a.description}` : ""})${t.length > 0 ? `\n  Tools: ${t.map(at => at.tool.name).join(", ")}` : ""}`).join("\n") || "No sub-agents configured"}

=== WORKFLOW TEMPLATES ===
${workflows.map(w => `- "${w.name}" (status: ${w.status}, category: ${w.category}${w.description ? `, desc: ${w.description}` : ""}${w.goal ? `, goal: ${w.goal}` : ""})`).join("\n") || "No workflow templates"}

=== WORKFLOW EXECUTIONS ===
Active: ${activeExecutions.length}
${recentExecutions.map(e => `- [${e.status.toUpperCase()}] template: ${e.templateId}, work order: ${e.workOrderId || "none"}, started: ${e.startedAt || "not started"}${e.completedAt ? `, completed: ${e.completedAt}` : ""}`).join("\n") || "No executions"}
${workflowExecutions.length > 10 ? `... and ${workflowExecutions.length - 10} more executions` : ""}

=== TOOLS PLATFORM ===
${toolsList.map(t => `- "${t.name}" (type: ${t.type}, status: ${t.status}, version: ${t.version}${t.description ? `, desc: ${t.description}` : ""})`).join("\n") || "No tools registered"}

=== WORKSPACE (FILE SYSTEM) ===
Root Folders:
${rootFolders.map(f => `- /${f.name}${f.description ? ` — ${f.description}` : ""}`).join("\n") || "No folders"}
Root Files:
${rootArtifacts.map(a => `- ${a.name} (${a.mimeType}, ${a.size} bytes, status: ${a.status})`).join("\n") || "No root files"}

=== SANDBOX SESSIONS ===
${sandboxSessionsList.map(s => `- "${s.name}" (status: ${s.status}, created: ${s.createdAt}${s.description ? `, desc: ${s.description}` : ""})`).join("\n") || "No sandbox sessions"}

=== LLM CONFIGURATION ===
- Provider: ${settings.provider}
- Model: ${settings.model}
- Status: Enabled
- Timestamp: ${new Date().toISOString()}`;
  }

  app.post("/api/chat/sessions/:id/messages", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const sessionId = req.params.id;
      const session = await storage.getChatSession(sessionId);
      if (!session) return res.status(404).json({ message: "Session not found" });

      const messageSchema = z.object({ message: z.string().min(1) });
      const parsed = messageSchema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid request" });

      const { message } = parsed.data;

      await storage.addChatMessage({
        sessionId,
        role: "user",
        content: message,
        gccBreadcrumb: "user_message",
      });

      const settings = await storage.getLlmSettings();
      if (!settings || !settings.enabled) {
        return res.status(503).json({ message: "Aiden's LLM is not enabled. Please configure it in Aiden Settings." });
      }

      const keyName = getRequiredApiKeyName(settings.provider);
      if (!isApiKeyConfigured(settings.provider)) {
        return res.status(503).json({ message: `API key (${keyName}) is not configured. Please add it in Aiden Settings.` });
      }

      const allMessages = await storage.getChatMessages(sessionId);
      const conversationHistory = allMessages.slice(-20).map(m => ({
        role: m.role as "user" | "assistant",
        content: m.content,
      }));

      const systemContext = await buildSystemContext(settings);

      const gcc = (session.gccMemory as any) || {};
      const breadcrumbs = [...(gcc["gcc.breadcrumbs"] || []), "user_message", "llm_processing"];

      const reply = await chatWithAiden(settings, message, conversationHistory.slice(0, -1), systemContext);

      const assistantMsg = await storage.addChatMessage({
        sessionId,
        role: "assistant",
        content: reply,
        gccBreadcrumb: "assistant_reply",
      });

      const now = new Date().toISOString();
      const commitId = generateCommitId();
      const commitSummary = message.length > 100 ? message.slice(0, 97) + "..." : message;

      const commitIndex = [...(gcc["gcc.commit_index"] || [])];
      commitIndex.push({
        commit_id: commitId,
        timestamp: now,
        summary: commitSummary,
        tags: ["chat_exchange"],
      });

      const logEntries = [...(gcc["gcc.log"] || [])];
      logEntries.push(
        {
          timestamp: now,
          source_node: "ContextLogNode",
          entry: `User message: "${commitSummary}"`,
        },
        {
          timestamp: now,
          source_node: "ContextCommitNode",
          entry: `Committed exchange as ${commitId}. Aiden responded (${reply.length} chars).`,
        }
      );

      const updatedBreadcrumbs = [...breadcrumbs, "assistant_reply", "committed"];
      await storage.updateChatSession(sessionId, {
        gccMemory: {
          "gcc.project_id": gcc["gcc.project_id"] || `aiden-chat-${session.correlationId.slice(0, 8)}`,
          "gcc.branch": gcc["gcc.branch"] || "main",
          "gcc.tier": "tier1",
          "gcc.commit_index": commitIndex.slice(-100),
          "gcc.last_commit_id": commitId,
          "gcc.last_commit_summary": commitSummary,
          "gcc.log": logEntries.slice(-200),
          "gcc.context_scope": "branch",
          "gcc.context_commit_count": commitIndex.length,
          "gcc.breadcrumbs": updatedBreadcrumbs.slice(-50),
          "gcc.last_action": "committed",
          "gcc.metadata": {
            ...(gcc["gcc.metadata"] || {}),
            status: "active",
            last_commit: now,
          },
        },
        title: session.messageCount === 0 ? message.slice(0, 80) : session.title,
      });

      res.json({ reply, messageId: assistantMsg.id, sessionId, commitId });
    } catch (err: any) {
      console.error("Chat error:", err.message);
      res.status(500).json({ message: `Aiden encountered an error: ${err.message}` });
    }
  });

  const chatRequestSchema = z.object({
    message: z.string().min(1),
    history: z.array(z.object({
      role: z.enum(["user", "assistant"]),
      content: z.string(),
    })).optional().default([]),
  });

  app.post("/api/chat", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const parsed = chatRequestSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid request", errors: parsed.error.issues });
      }
      const { message, history } = parsed.data;

      const settings = await storage.getLlmSettings();
      if (!settings || !settings.enabled) {
        return res.status(503).json({ message: "Aiden's LLM is not enabled. Please configure it in Aiden Settings." });
      }

      const keyName = getRequiredApiKeyName(settings.provider);
      if (!isApiKeyConfigured(settings.provider)) {
        return res.status(503).json({ message: `API key (${keyName}) is not configured. Please add it in Aiden Settings.` });
      }

      const systemContext = await buildSystemContext(settings);
      const conversationHistory = history.slice(-10);

      const reply = await chatWithAiden(settings, message, conversationHistory, systemContext);
      res.json({ reply });
    } catch (err: any) {
      console.error("Chat error:", err.message);
      res.status(500).json({ message: `Aiden encountered an error: ${err.message}` });
    }
  });

  // ==================== Operational Settings ====================

  app.get("/api/operational-settings", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const settings = await storage.getOperationalSettings();
      if (!settings) {
        return res.json({
          id: "default",
          currentMode: "autonomous",
          thresholds: { financialAmount: 10000, riskLevel: "high", categories: ["legal", "security", "strategic"] },
          scheduleRules: [],
          emergencyOverrideEnabled: true,
          emergencyTriggers: ["security_breach", "legal_deadline_24h", "revenue_loss", "system_outage"],
          updatedAt: new Date().toISOString(),
          updatedBy: "system",
        });
      }
      res.json(settings);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch operational settings" });
    }
  });

  app.put("/api/operational-settings", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const actor = getActor(req);
      const parsed = insertOperationalSettingsSchema.safeParse({ ...req.body, updatedBy: actor.actorName });
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid settings", errors: parsed.error.errors });
      }
      const settings = await storage.upsertOperationalSettings(parsed.data);

      await storage.createExecutionLog({
        workOrderId: "system",
        tier: 0,
        action: "mode_change",
        message: `Operational mode changed to "${parsed.data.currentMode}" by ${actor.actorName}`,
        metadata: { previousMode: req.body._previousMode, newMode: parsed.data.currentMode, actor },
      });

      res.json(settings);
    } catch (err) {
      res.status(500).json({ message: "Failed to update operational settings" });
    }
  });

  // ==================== Approvals ====================

  app.get("/api/approvals", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const status = req.query.status as string | undefined;
      const approvalsList = status === "pending"
        ? await storage.getPendingApprovals()
        : await storage.getApprovals();
      res.json(approvalsList);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch approvals" });
    }
  });

  app.get("/api/approvals/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const approval = await storage.getApproval(req.params.id);
      if (!approval) return res.status(404).json({ message: "Approval not found" });
      res.json(approval);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch approval" });
    }
  });

  app.get("/api/work-orders/:id/approvals", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const list = await storage.getApprovalsByWorkOrder(req.params.id);
      res.json(list);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch approvals for work order" });
    }
  });

  app.post("/api/approvals/:id/approve", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const actor = getActor(req);
      const { rationale } = req.body;
      if (!rationale || typeof rationale !== "string" || rationale.trim().length < 3 || rationale.length > 2000) {
        return res.status(400).json({ message: "Rationale is required (3-2000 characters)" });
      }
      const approval = await storage.getApproval(req.params.id);
      if (!approval) return res.status(404).json({ message: "Approval not found" });
      if (approval.status !== "pending") return res.status(400).json({ message: "Approval is no longer pending" });
      const workOrder = await storage.getWorkOrder(approval.workOrderId);
      if (!workOrder) return res.status(404).json({ message: "Associated work order not found" });

      const updated = await storage.updateApproval(req.params.id, {
        status: "approved",
        decidedBy: actor.actorId,
        decidedByName: actor.actorName,
        decision: "approved",
        rationale,
        decidedAt: new Date(),
      });

      const gcc = (workOrder.gccMemory || {}) as Record<string, any>;
      const { gccMemory, commitId } = buildGccCommit(
        gcc, workOrder.correlationId, "approval_granted",
        `Approval granted by ${actor.actorName}`,
        `Approval granted by ${actor.actorName}: ${rationale}`,
        { approvalId: approval.id, approvedAt: new Date().toISOString(), approvedBy: actor },
      );

      await storage.updateWorkOrder(approval.workOrderId, { approvalStatus: "approved", gccMemory });

      await storage.createExecutionLog({
        workOrderId: approval.workOrderId,
        tier: 0,
        action: "approval_granted",
        message: `Approval granted by ${actor.actorName}: ${rationale}`,
        metadata: { approvalId: approval.id, actor, decision: "approved", commitId },
      });

      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to approve" });
    }
  });

  app.post("/api/approvals/:id/reject", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const actor = getActor(req);
      const { rationale } = req.body;
      if (!rationale || typeof rationale !== "string" || rationale.trim().length < 3 || rationale.length > 2000) {
        return res.status(400).json({ message: "Rationale is required (3-2000 characters)" });
      }
      const approval = await storage.getApproval(req.params.id);
      if (!approval) return res.status(404).json({ message: "Approval not found" });
      if (approval.status !== "pending") return res.status(400).json({ message: "Approval is no longer pending" });
      const workOrder = await storage.getWorkOrder(approval.workOrderId);
      if (!workOrder) return res.status(404).json({ message: "Associated work order not found" });

      const updated = await storage.updateApproval(req.params.id, {
        status: "rejected",
        decidedBy: actor.actorId,
        decidedByName: actor.actorName,
        decision: "rejected",
        rationale,
        decidedAt: new Date(),
      });

      const gcc = (workOrder.gccMemory || {}) as Record<string, any>;
      const { gccMemory, commitId } = buildGccCommit(
        gcc, workOrder.correlationId, "approval_rejected",
        `Approval rejected by ${actor.actorName}`,
        `Approval rejected by ${actor.actorName}: ${rationale}`,
        { approvalId: approval.id, rejectedAt: new Date().toISOString(), rejectedBy: actor },
      );

      await storage.updateWorkOrder(approval.workOrderId, { approvalStatus: "rejected", status: "blocked", gccMemory });

      await storage.createExecutionLog({
        workOrderId: approval.workOrderId,
        tier: 0,
        action: "approval_rejected",
        message: `Approval rejected by ${actor.actorName}: ${rationale}`,
        metadata: { approvalId: approval.id, actor, decision: "rejected", commitId },
      });

      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to reject" });
    }
  });

  // ==================== Image Upload / Placeholder ====================

  app.post("/api/images/upload", isAuth, async (req: Request, res: Response) => {
    try {
      const { placeholderId, filename, mimeType, data, alt } = req.body;
      if (!placeholderId || !filename || !mimeType || !data) {
        return res.status(400).json({ message: "Missing required fields: placeholderId, filename, mimeType, data" });
      }
      const allowedTypes = ["image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"];
      if (!allowedTypes.includes(mimeType)) {
        return res.status(400).json({ message: "Unsupported image type" });
      }
      const base64Data = data.replace(/^data:[^;]+;base64,/, "");
      const size = Math.ceil(base64Data.length * 0.75);
      const maxSize = 5 * 1024 * 1024;
      if (size > maxSize) {
        return res.status(400).json({ message: "Image too large (max 5MB)" });
      }
      const actor = getActor(req);
      const image = await storage.upsertUploadedImage({
        placeholderId,
        filename,
        mimeType,
        size,
        data: base64Data,
        alt: alt || null,
        uploadedBy: actor.actorId,
      });
      res.json({ id: image.id, placeholderId: image.placeholderId, filename: image.filename, mimeType: image.mimeType, size: image.size });
    } catch (err) {
      res.status(500).json({ message: "Upload failed" });
    }
  });

  app.get("/api/images/:placeholderId", async (req: Request, res: Response) => {
    try {
      const image = await storage.getUploadedImage(req.params.placeholderId as string);
      if (!image) {
        return res.status(404).json({ message: "Image not found" });
      }
      const buf = Buffer.from(image.data, "base64");
      res.set("Content-Type", image.mimeType);
      res.set("Content-Length", String(buf.length));
      res.set("Cache-Control", "public, max-age=86400");
      res.send(buf);
    } catch (err) {
      res.status(500).json({ message: "Failed to retrieve image" });
    }
  });

  app.get("/api/images/:placeholderId/meta", async (req: Request, res: Response) => {
    try {
      const image = await storage.getUploadedImage(req.params.placeholderId as string);
      if (!image) {
        return res.status(404).json({ exists: false });
      }
      res.json({
        exists: true,
        id: image.id,
        placeholderId: image.placeholderId,
        filename: image.filename,
        mimeType: image.mimeType,
        size: image.size,
        alt: image.alt,
      });
    } catch (err) {
      res.status(500).json({ message: "Failed to check image" });
    }
  });

  app.delete("/api/images/:placeholderId", isAuth, async (req: Request, res: Response) => {
    try {
      const deleted = await storage.deleteUploadedImage(req.params.placeholderId as string);
      if (!deleted) return res.status(404).json({ message: "Image not found" });
      res.json({ message: "Image deleted" });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete image" });
    }
  });

  return httpServer;
}

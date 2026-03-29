import type { Express, Request, Response, NextFunction } from "express";
import { createServer, type Server } from "http";
import { z } from "zod";
import { storage } from "./storage";
import { APP_VERSION, BUILD_ID } from "./version";
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
  insertGammaSettingsSchema,
} from "@shared/schema";
import type { LlmSettings } from "@shared/schema";
import { processWorkOrder, processWorkOrderSafe, isStaleProcessing, startWorkflowExecution, advanceWorkflowExecution, recoverStuckStepRuns, getWatchdogStatus } from "./orchestration";
import { autoImportSkillsForDescription } from "./skill-auto-import";
import { isApiKeyConfigured, getRequiredApiKeyName, testLLMConnection, fetchAvailableModels, chatWithAiden, resolveSubAgentLlmConfig, extractWorkOrderFromChat } from "./llm-client";
import { publishToGitHubPages, unpublishFromGitHubPages, isValidSlug, slugify } from "./publish";
import * as fs from "fs";
import * as path from "path";

const startTime = Date.now();

function isValidJson(s: string): boolean {
  try { JSON.parse(s); return true; } catch { return false; }
}

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
  // Startup validation — warn early if 21st.dev key is missing
  if (!process.env.TWENTY_FIRST_API_KEY) {
    console.warn(
      "[startup] TWENTY_FIRST_API_KEY is not set — 21st.dev Magic MCP tool will fail at runtime. " +
      "Set it in .env to enable UI component generation for Mark/Tom sub-agents."
    );
  }

  app.get("/api/health", async (_req, res) => {
    try {
      const uptime = Math.floor((Date.now() - startTime) / 1000);

      // DB check — actually query the database
      let dbHealthy = false;
      try {
        await storage.getWorkOrderStats();
        dbHealthy = true;
      } catch {}

      // LLM check — are provider keys configured?
      const llmSettings = await storage.getLlmSettings().catch(() => null);
      const llmEnabled = llmSettings?.enabled === true;
      const hasGroq = !!process.env.GROQ_API_KEY;
      const hasOpenRouter = !!process.env.OPENROUTER_API_KEY;
      const llmAvailable = llmEnabled && (hasGroq || hasOpenRouter);

      // Gamma check — is the API key set?
      const gammaConfigured = !!process.env.GAMMA_API_KEY;

      // Session check — is SESSION_SECRET set?
      const sessionConfigured = !!process.env.SESSION_SECRET;

      const allHealthy = dbHealthy && llmAvailable && sessionConfigured;

      res.json({
        status: allHealthy ? "ok" : "degraded",
        timestamp: new Date().toISOString(),
        version: APP_VERSION,
        uptime,
        services: {
          database: dbHealthy ? "healthy" : "unhealthy",
          tier1: llmAvailable ? "active" : "unavailable",
          tier1_5: llmAvailable ? "active" : "unavailable",
          tier2: llmAvailable ? "active" : "unavailable",
          gccMemory: "active",
          gamma: gammaConfigured ? "active" : "not configured",
        },
        checks: {
          api: true,
          database: dbHealthy,
          llm: llmAvailable,
          gamma: gammaConfigured,
          session: sessionConfigured,
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

  app.get("/api/work-orders", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const includeArchived = req.query.includeArchived === "true";
      const orders = await storage.getWorkOrders(includeArchived);
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
      const allowedStatuses = ["pending", "reopened"];
      const stale = isStaleProcessing(order);
      if (!allowedStatuses.includes(order.status) && !stale) {
        return res.status(400).json({ message: `Cannot process order in '${order.status}' status` });
      }
      const actor = getActor(req);
      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: stale ? "Processing Re-initiated (Stale Recovery)" : "Processing Initiated",
        message: stale
          ? `Work order was stuck in "processing" — re-initiated by ${actor.actorName}`
          : `Processing started by ${actor.actorName}`,
        metadata: { actor, staleRecovery: stale },
      });
      await storage.updateWorkOrder(req.params.id, { status: "processing" });
      res.json({ message: "Processing started", status: "processing", workOrderId: req.params.id });
      processWorkOrderSafe(req.params.id);
    } catch (err) {
      res.status(500).json({ message: "Failed to initiate processing" });
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
        workflowExecutionId: null,
        gccMemory,
      });

      // Reset linked workflow execution so stale linkage doesn't contaminate the fresh run
      if (order.workflowExecutionId) {
        try {
          await storage.updateWorkflowExecution(order.workflowExecutionId, {
            status: "superseded_by_retry",
          });
        } catch (_) { /* audit-only — don't block retry */ }
      }

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Retry Initiated",
        message: `Work order reset and resubmitted by ${actor.actorName}`,
        metadata: { previousStatus: order.status, actor, commitId, previousWorkflowExecutionId: order.workflowExecutionId || null },
      });

      await storage.updateWorkOrder(req.params.id, { status: "processing" });
      res.json({ message: "Retry processing started", status: "processing", workOrderId: req.params.id });
      processWorkOrderSafe(req.params.id);
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
      const fullDeliverable = previousOutput?.deliverable || "";
      const deliverableType = previousOutput?.deliverableType || "document";
      const isHtml = /^<!DOCTYPE\s+html|^<html[\s>]/i.test(fullDeliverable.trim());
      const deliverableFormat = isHtml ? "html" : deliverableType;
      const previousDeliverableSummary = previousOutput
        ? `[Previous output message: "${previousOutput.message || "N/A"}"] [Previous deliverable title: "${previousOutput.deliverableTitle || "N/A"}"] [Previous deliverable type: "${previousOutput.deliverableType || "N/A"}"] [Format: ${deliverableFormat}] [Previous deliverable — COMPLETE]:\n${fullDeliverable}`
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

      const reopenIteration = ((gcc["gcc.metadata"]?.reopenCount || 0) + 1);
      await storage.updateWorkOrder(req.params.id, {
        status: "reopened",
        bdmMarker: null,
        tier1Result: null,
        tier2Result: null,
        assignedSubAgentId: null,
        executionMode: null,
        workflowExecutionId: null,
        gccMemory,
      });

      // Reset linked workflow execution so the UI shows fresh progression on reprocess
      if (order.workflowExecutionId) {
        try {
          await storage.updateWorkflowExecution(order.workflowExecutionId, {
            status: "reset_on_reopen",
            finalWorkProduct: null,
            executiveReview: null,
            completedAt: null,
            currentStepKey: null,
          });
          const stepRuns = await storage.getWorkflowStepRuns(order.workflowExecutionId);
          for (const run of stepRuns) {
            await storage.updateWorkflowStepRun(run.id, {
              status: "reset_on_reopen",
              output: null,
              pmReview: null,
              error: null,
              completedAt: null,
            });
          }
        } catch (wfErr: any) {
          console.error("[reopen] Failed to reset workflow execution:", wfErr.message);
        }
      }

      storage.createChecklistItem({
        workOrderId: req.params.id,
        phase: "tier1_gate",
        summary: `Reopened (iteration ${reopenIteration}) — ${parsed.data.reason}`,
        addedBy: "operator",
        status: "done",
        iteration: reopenIteration,
      }).catch(err => console.error("[2DO] reopen hook error:", err.message));

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
      const unblockableStatuses = ["blocked", "deferred", "awaiting_operator", "failed"];
      if (!unblockableStatuses.includes(order.status)) {
        return res.status(400).json({ message: `Cannot unblock order in '${order.status}' status — only blocked, deferred, awaiting_operator, or failed orders can be re-issued` });
      }

      const bdmSnapshot = order.bdmMarker;
      const now = new Date().toISOString();
      const gcc = (order.gccMemory || {}) as Record<string, any>;

      const commitId = `gcc-${Math.random().toString(16).slice(2, 10)}`;
      const breadcrumbLabel = order.bdmMarker ? "hitl_unblock" : `hitl_reissue_from_${order.status}`;
      const breadcrumbs = [...(gcc["gcc.breadcrumbs"] || gcc.breadcrumbs || []), breadcrumbLabel];
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
          bdmCleared: !!bdmSnapshot,
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

      // BUG-043: If the WO was escalated due to low exec review score (quality gate),
      // do NOT allow completion without reprocessing. Force reprocess to ensure the
      // deliverable is revised before it can be marked complete.
      const wasQualityEscalation = (gcc["gcc.breadcrumbs"] || []).includes("hitl_reissue_from_awaiting_operator")
        || (order.gccMemory as any)?.["gcc.last_action"] === "hitl_resolved"
        || ((order.tier2Result as any)?.pocketflow?.convergenceScore < 0.5);
      const execLogs = await storage.getExecutionLogs(req.params.id);
      const qualityEscalationLog = execLogs.find((l: any) =>
        l.action?.includes("Low-Quality Escalation") || l.action?.includes("Escalated to Operator")
      );
      const forceReprocess = !reprocess && !!qualityEscalationLog;

      if (reprocess || forceReprocess) {
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
          action: forceReprocess ? "Re-process (Quality Gate)" : "Re-process after HITL Unblock",
          message: forceReprocess
            ? "Work order was escalated due to low quality score. Reprocessing is required — direct completion is not allowed for quality-escalated deliverables."
            : "Work order re-submitted for Tier 2 execution after human intervention.",
          metadata: { commitId, forceReprocess },
        });

        res.json({ message: forceReprocess ? "Quality-escalated WO must be reprocessed" : "Re-processing started after HITL unblock", status: "processing", workOrderId: req.params.id, unblocked: true, reprocessed: true, forceReprocess });
        processWorkOrderSafe(req.params.id);
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

        if (updated) {
          try {
            const { fileWorkOrderOutput } = await import("./workspace-filing");
            await fileWorkOrderOutput(updated);
          } catch (fileErr: any) {
            console.error("Workspace filing after accept failed:", fileErr.message);
          }
        }

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

  // ==================== Archive / Unarchive ====================

  const archiveSchema = z.object({
    reason: z.string().min(1, "Reason is required").max(500),
  });

  app.post("/api/work-orders/:id/archive", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const parsed = archiveSchema.safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid request", errors: parsed.error.flatten().fieldErrors });
      }
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      if (order.isArchived) return res.status(400).json({ message: "Work order is already archived" });

      const actor = getActor(req);
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      const { gccMemory, commitId } = buildGccCommit(
        gcc, order.correlationId, "archived",
        `Archived by ${actor.actorName}`,
        `Work order archived by ${actor.actorName}. Reason: ${parsed.data.reason}`,
        { archivedAt: new Date().toISOString(), archivedBy: actor, archiveReason: parsed.data.reason },
      );

      await storage.updateWorkOrder(req.params.id, {
        isArchived: true,
        archivedAt: new Date(),
        archivedBy: actor.actorName,
        archivedReason: parsed.data.reason,
        gccMemory,
      });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Archived",
        message: `Work order archived by ${actor.actorName}. Reason: ${parsed.data.reason}`,
        metadata: { actor, reason: parsed.data.reason, commitId },
      });

      const updated = await storage.getWorkOrder(req.params.id);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to archive work order" });
    }
  });

  app.post("/api/work-orders/:id/unarchive", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      if (!order.isArchived) return res.status(400).json({ message: "Work order is not archived" });

      const actor = getActor(req);
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      const { gccMemory, commitId } = buildGccCommit(
        gcc, order.correlationId, "unarchived",
        `Unarchived by ${actor.actorName}`,
        `Work order restored from archive by ${actor.actorName}`,
        { unarchivedAt: new Date().toISOString(), unarchivedBy: actor },
      );

      await storage.updateWorkOrder(req.params.id, {
        isArchived: false,
        archivedAt: null,
        archivedBy: null,
        archivedReason: null,
        gccMemory,
      });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Unarchived",
        message: `Work order restored from archive by ${actor.actorName}`,
        metadata: { actor, commitId },
      });

      const updated = await storage.getWorkOrder(req.params.id);
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to unarchive work order" });
    }
  });

  // ==================== Kill Work Order ====================

  app.post("/api/work-orders/:id/kill", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const parsed = z.object({
        reason: z.string().min(1, "Reason is required").max(500),
      }).safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid request", errors: parsed.error.flatten().fieldErrors });
      }
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      if (order.status === "completed" && order.isArchived) {
        return res.status(400).json({ message: "Work order is already completed and archived" });
      }

      const actor = getActor(req);
      const previousStatus = order.status;
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      const { gccMemory, commitId } = buildGccCommit(
        gcc, order.correlationId, "killed",
        `Killed by ${actor.actorName}`,
        `Work order killed by ${actor.actorName}. Previous status: ${previousStatus}. Reason: ${parsed.data.reason}`,
        { killedAt: new Date().toISOString(), killedBy: actor, previousStatus, killReason: parsed.data.reason },
      );

      const existingTags = (order.tags as string[] | null) || [];
      const updatedTags = existingTags.includes("Killed") ? existingTags : [...existingTags, "Killed"];

      await storage.updateWorkOrder(req.params.id, {
        status: "killed",
        isArchived: true,
        archivedAt: new Date(),
        archivedBy: actor.actorName,
        archivedReason: `KILLED: ${parsed.data.reason}`,
        tags: updatedTags,
        gccMemory,
      });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Killed",
        message: `Work order killed by ${actor.actorName}. Previous status: ${previousStatus}. Reason: ${parsed.data.reason}. Auto-archived with "Killed" tag.`,
        metadata: { actor, reason: parsed.data.reason, previousStatus, commitId, tags: updatedTags },
      });

      const updated = await storage.getWorkOrder(req.params.id);
      res.json(updated);
    } catch (err) {
      console.error("Kill work order error:", err);
      res.status(500).json({ message: "Failed to kill work order" });
    }
  });

  // ==================== Admin Repair Route =====================

  app.post("/api/work-orders/:id/repair", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const parsed = z.object({
        action: z.enum(["retry", "complete", "fail"]),
        reason: z.string().min(1).max(500),
        deliverable: z.string().optional(),
        deliverableType: z.string().optional(),
        deliverableTitle: z.string().optional(),
      }).safeParse(req.body);

      if (!parsed.success) return res.status(400).json({ message: "Invalid request", errors: parsed.error.flatten().fieldErrors });

      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });

      const actor = getActor(req);
      const { action, reason } = parsed.data;
      const crypto = await import("crypto");
      const invalidationId = crypto.randomUUID();

      if (action === "fail") {
        await storage.updateWorkOrder(req.params.id, {
          status: "failed",
          processingAttemptId: invalidationId,
          heartbeatAt: null,
          processingStartedAt: null,
        });
        await recoverStuckStepRuns(order);
        await storage.createExecutionLog({
          workOrderId: req.params.id, tier: 1,
          action: "Admin: Repair (fail)",
          message: `Admin ${actor.actorName} forced work order to failed: ${reason}`,
          metadata: { actor, reason, invalidationId },
        });
        return res.json(await storage.getWorkOrder(req.params.id));
      }

      if (action === "retry") {
        // Reset workflow linkage so fresh run starts clean
        if (order.workflowExecutionId) {
          try {
            await storage.updateWorkflowExecution(order.workflowExecutionId, {
              status: "superseded_by_retry",
            });
          } catch (_) { /* audit-only — don't block repair retry */ }
        }
        await storage.updateWorkOrder(req.params.id, {
          status: "pending",
          processingAttemptId: invalidationId,
          heartbeatAt: null,
          processingStartedAt: null,
          bdmMarker: null,
          tier1Result: null,
          tier2Result: null,
          workflowExecutionId: null,
        });
        await recoverStuckStepRuns(order);
        await storage.createExecutionLog({
          workOrderId: req.params.id, tier: 1,
          action: "Admin: Repair (retry)",
          message: `Admin ${actor.actorName} initiated repair retry: ${reason}`,
          metadata: { actor, reason, invalidationId },
        });
        // Actually re-trigger processing
        processWorkOrderSafe(req.params.id);
        return res.json({ message: "Repair retry initiated", workOrderId: req.params.id });
      }

      if (action === "complete") {
        if (!parsed.data.deliverable) return res.status(400).json({ message: "deliverable required for complete action" });
        const { fileWorkOrderOutput } = await import("./workspace-filing");
        const completedOrder = await storage.updateWorkOrder(req.params.id, {
          status: "completed",
          processingAttemptId: invalidationId,
          heartbeatAt: null,
          processingStartedAt: null,
          tier2Result: {
            blocked: false, reason: null, handler: null,
            output: {
              message: `Admin repair: ${reason}`,
              deliverable: parsed.data.deliverable,
              deliverableType: parsed.data.deliverableType || "markdown",
              deliverableTitle: parsed.data.deliverableTitle || order.title,
            },
          },
        });
        if (completedOrder) {
          fileWorkOrderOutput(completedOrder).catch(err =>
            console.error("Auto-filing error (admin-repair):", err.message)
          );
        }
        await storage.createExecutionLog({
          workOrderId: req.params.id, tier: 1,
          action: "Admin: Repair (complete)",
          message: `Admin ${actor.actorName} force-completed with deliverable: ${reason}`,
          metadata: { actor, reason, invalidationId },
        });
        return res.json(await storage.getWorkOrder(req.params.id));
      }
    } catch (err: any) {
      console.error("Repair error:", err);
      res.status(500).json({ message: `Repair failed: ${err.message}` });
    }
  });

  // ==================== Ops Health Route ======================

  app.get("/api/ops/health", isAuth, requireRole("admin"), async (_req, res) => {
    try {
      const allOrders = await storage.getWorkOrders();
      const processingOrders = allOrders.filter(o => o.status === "processing");
      const now = Date.now();

      const stuckWorkOrders = processingOrders.map(o => {
        const wo = o as any;
        const heartbeatTs = wo.heartbeatAt ? new Date(wo.heartbeatAt).getTime() : null;
        const updatedTs = o.updatedAt ? new Date(o.updatedAt).getTime() : now;
        const lastActivity = heartbeatTs || updatedTs;
        const elapsedSeconds = Math.round((now - lastActivity) / 1000);
        return {
          id: o.id,
          title: o.title,
          status: o.status,
          attemptId: wo.processingAttemptId,
          lastHeartbeat: wo.heartbeatAt,
          processingStartedAt: wo.processingStartedAt,
          elapsedSeconds,
          likelyStuck: elapsedSeconds > 60,
        };
      });

      res.json({
        watchdog: getWatchdogStatus(),
        processingWorkOrders: stuckWorkOrders,
        totalProcessing: processingOrders.length,
      });
    } catch (err: any) {
      res.status(500).json({ message: `Ops health check failed: ${err.message}` });
    }
  });

  // ==================== 2DO Checklist Routes ====================

  app.get("/api/work-orders/:id/checklist", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      const items = await storage.getChecklistItems(req.params.id);
      res.json(items);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch checklist" });
    }
  });

  app.post("/api/work-orders/:id/checklist", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      const parsed = z.object({
        summary: z.string().min(1).max(500),
        phase: z.enum(["tier1_gate", "tier2_exec", "quality_review", "filing", "deployment"]).optional(),
        status: z.enum(["pending", "in_progress", "done", "failed", "skipped"]).optional(),
      }).safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid checklist item", errors: parsed.error.flatten().fieldErrors });
      }
      const item = await storage.createChecklistItem({
        workOrderId: req.params.id,
        workflowExecutionId: order.workflowExecutionId || undefined,
        summary: parsed.data.summary,
        phase: parsed.data.phase || "tier2_exec",
        status: parsed.data.status || "pending",
        addedBy: "operator",
      });
      res.status(201).json(item);
    } catch (err) {
      res.status(500).json({ message: "Failed to create checklist item" });
    }
  });

  app.patch("/api/checklist-items/:id", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const parsed = z.object({
        status: z.enum(["pending", "in_progress", "done", "failed", "skipped"]).optional(),
        summary: z.string().min(1).max(500).optional(),
      }).safeParse(req.body);
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid update", errors: parsed.error.flatten().fieldErrors });
      }
      const updated = await storage.updateChecklistItem(req.params.id, parsed.data);
      if (!updated) return res.status(404).json({ message: "Checklist item not found" });
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update checklist item" });
    }
  });

  app.get("/api/workflow-executions/:id/checklist", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Workflow execution not found" });
      const items = await storage.getChecklistItemsByWorkflow(req.params.id);
      res.json(items);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch workflow checklist" });
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

      const apiKey = config.directApiKey || process.env[config.apiKeyEnvVar];
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
        updatedAt: new Date(),
      };

      const result = await testLLMConnection(testSettings, config.directApiKey);
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
      const { templateId, workOrderId, goal, context, pmSubAgentId } = req.body;
      if (!templateId) {
        return res.status(400).json({ message: "templateId is required" });
      }
      const template = await storage.getWorkflowTemplate(templateId);
      if (!template) return res.status(404).json({ message: "Template not found" });

      // Auto-create a tracking WO if none was provided, so operator can see it immediately
      let effectiveWoId = workOrderId || null;
      if (!effectiveWoId) {
        const actor = getActor(req);
        const trackingWo = await storage.createWorkOrder({
          title: `WF: ${template.name}`,
          description: goal || template.goal || `Workflow execution of "${template.name}"`,
          type: template.category || "operations",
          priority: "medium",
          status: "processing",
          submittedBy: actor?.name || "Local Admin",
        });
        effectiveWoId = trackingWo.id;
        await storage.updateWorkOrder(trackingWo.id, {
          gccMemory: {
            "gcc.log": [{ type: "COMMIT", detail: `Auto-created work order to track workflow "${template.name}"`, commit_id: `gcc-${trackingWo.id.slice(0, 8)}`, timestamp: new Date().toISOString() }],
            "gcc.tier": "tier1",
            "gcc.branch": "main",
            "gcc.metadata": { submittedBy: { source: "workflow_run", actorId: actor?.id || "local-admin", actorName: actor?.name || "Local Admin" } },
            "gcc.breadcrumbs": ["created_for_workflow"],
            "gcc.last_action": "created_for_workflow",
          },
        });
      }

      // Return execution immediately, advance in background
      const execution = await startWorkflowExecution(templateId, effectiveWoId, goal || template.goal, context || {}, pmSubAgentId || undefined, { skipAdvance: true });
      res.status(201).json(execution);
      // Advance workflow asynchronously (don't block the HTTP response)
      const { advanceWorkflowExecution } = await import("./orchestration");
      advanceWorkflowExecution(execution.id).catch(err =>
        console.error(`[workflow] Background advance failed for ${execution.id}:`, err.message)
      );
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

  app.get("/api/workflow-executions/:id/work-product", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Execution not found" });
      res.json({
        finalWorkProduct: execution.finalWorkProduct,
        executiveReview: execution.executiveReview,
        pmSubAgentId: execution.pmSubAgentId,
        executionMode: execution.executionMode,
        status: execution.status,
      });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to fetch work product" });
    }
  });

  app.post("/api/workflow-executions/:id/step-runs/:stepRunId/retry", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Execution not found" });
      const stepRuns = await storage.getWorkflowStepRuns(req.params.id);
      const stepRun = stepRuns.find(r => r.id === req.params.stepRunId);
      if (!stepRun) return res.status(404).json({ message: "Step run not found" });
      if (stepRun.status !== "failed" && stepRun.status !== "awaiting_operator") {
        return res.status(400).json({ message: `Cannot retry step in '${stepRun.status}' status` });
      }
      await storage.updateWorkflowStepRun(stepRun.id, {
        status: "pending", startedAt: null, completedAt: null, error: null,
        revisionAttempt: (stepRun.revisionAttempt || 0) + 1,
      });
      if (execution.status !== "running") {
        await storage.updateWorkflowExecution(req.params.id, { status: "running" });
      }
      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { status: "processing" });
        await storage.createExecutionLog({
          workOrderId: execution.workOrderId, tier: 1,
          action: `HITL: Step Retry`,
          message: `Operator retried step "${stepRun.stepName}" (attempt ${(stepRun.revisionAttempt || 0) + 1})`,
          metadata: { stepRunId: stepRun.id, stepKey: stepRun.stepKey, revisionAttempt: (stepRun.revisionAttempt || 0) + 1 },
        });
      }
      const result = await advanceWorkflowExecution(req.params.id);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to retry step" });
    }
  });

  app.post("/api/workflow-executions/:id/step-runs/:stepRunId/skip", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Execution not found" });
      const stepRuns = await storage.getWorkflowStepRuns(req.params.id);
      const stepRun = stepRuns.find(r => r.id === req.params.stepRunId);
      if (!stepRun) return res.status(404).json({ message: "Step run not found" });
      await storage.updateWorkflowStepRun(stepRun.id, { status: "skipped", completedAt: new Date() });
      if (execution.status !== "running") {
        await storage.updateWorkflowExecution(req.params.id, { status: "running" });
      }
      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { status: "processing" });
        await storage.createExecutionLog({
          workOrderId: execution.workOrderId, tier: 1,
          action: `HITL: Step Skipped`,
          message: `Operator skipped step "${stepRun.stepName}"`,
          metadata: { stepRunId: stepRun.id, stepKey: stepRun.stepKey },
        });
      }
      const result = await advanceWorkflowExecution(req.params.id);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to skip step" });
    }
  });

  app.post("/api/workflow-executions/:id/step-runs/:stepRunId/resolve", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Execution not found" });
      const stepRuns = await storage.getWorkflowStepRuns(req.params.id);
      const stepRun = stepRuns.find(r => r.id === req.params.stepRunId);
      if (!stepRun) return res.status(404).json({ message: "Step run not found" });
      if (stepRun.status !== "awaiting_operator") {
        return res.status(400).json({ message: `Step is not awaiting operator (status: ${stepRun.status})` });
      }
      const { resolution, output } = req.body;
      await storage.updateWorkflowStepRun(stepRun.id, {
        status: "completed", completedAt: new Date(),
        output: output || { message: resolution || "Resolved by operator", resolvedBy: "operator" },
      });
      if (execution.status !== "running") {
        await storage.updateWorkflowExecution(req.params.id, { status: "running" });
      }
      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { status: "processing" });
        await storage.createExecutionLog({
          workOrderId: execution.workOrderId, tier: 1,
          action: `HITL: Step Resolved`,
          message: `Operator resolved step "${stepRun.stepName}": ${resolution || "Manual resolution"}`,
          metadata: { stepRunId: stepRun.id, resolution },
        });
      }
      const result = await advanceWorkflowExecution(req.params.id);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to resolve step" });
    }
  });

  // Cancel a running or blocked workflow execution
  app.post("/api/workflow-executions/:id/cancel", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const execution = await storage.getWorkflowExecution(req.params.id);
      if (!execution) return res.status(404).json({ message: "Execution not found" });

      const cancellableStatuses = ["running", "awaiting_operator", "pending", "blocked"];
      if (!cancellableStatuses.includes(execution.status)) {
        return res.status(400).json({
          message: `Cannot cancel execution with status "${execution.status}". Only running, awaiting_operator, pending, or blocked executions can be cancelled.`,
        });
      }

      const updated = await storage.updateWorkflowExecution(req.params.id, {
        status: "cancelled" as any,
        completedAt: new Date(),
      });

      if (execution.workOrderId) {
        await storage.updateWorkOrder(execution.workOrderId, { status: "cancelled" as any });
        await storage.createExecutionLog({
          workOrderId: execution.workOrderId,
          tier: 1,
          action: "Aiden: Workflow Cancelled",
          message: `Workflow execution cancelled by operator. Previous status: ${execution.status}.`,
          metadata: { executionId: req.params.id, cancelledBy: (req.user as any)?.email || "admin" },
        });
      }

      res.json(updated);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to cancel execution" });
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

  app.get("/api/skills/available", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const skillsDir = path.resolve(".local/skills");
      if (!fs.existsSync(skillsDir)) {
        return res.json([]);
      }
      const dirs = fs.readdirSync(skillsDir, { withFileTypes: true })
        .filter(d => d.isDirectory());

      const existingTools = await storage.getTools();
      const existingSlugs = new Set(existingTools.map(t => t.slug));

      // Category mapping for known Anthropic official skills
      const categoryMap: Record<string, string> = {
        "docx": "document", "pdf": "document", "pptx": "document", "xlsx": "document",
        "algorithmic-art": "creative", "canvas-design": "creative", "frontend-design": "creative",
        "brand-guidelines": "creative", "theme-factory": "creative", "slack-gif-creator": "creative",
        "mcp-builder": "development", "webapp-testing": "development",
        "web-artifacts-builder": "development", "skill-creator": "development",
        "internal-comms": "productivity", "doc-coauthoring": "productivity",
      };

      // Helper to parse YAML frontmatter values (handles quoted multi-line strings)
      const parseFrontmatterValue = (fm: string, key: string): string => {
        // Try quoted value first (single or double quotes, possibly multi-line)
        const quotedMatch = fm.match(new RegExp(`^${key}:\\s*"([\\s\\S]*?)"`, "m"))
          || fm.match(new RegExp(`^${key}:\\s*'([\\s\\S]*?)'`, "m"));
        if (quotedMatch) return quotedMatch[1].replace(/\s+/g, " ").trim();
        // Fall back to unquoted single-line
        const lineMatch = fm.match(new RegExp(`^${key}:\\s*(.+)$`, "m"));
        if (lineMatch) return lineMatch[1].trim();
        return "";
      };

      const skills: Array<{
        name: string;
        dirName: string;
        slug: string;
        description: string;
        content: string;
        alreadyImported: boolean;
        hasReferences: boolean;
        referenceFiles: string[];
        category: string;
        source: string;
        fileCount: number;
        hasScripts: boolean;
      }> = [];

      for (const dir of dirs) {
        const skillMdPath = path.join(skillsDir, dir.name, "SKILL.md");
        if (!fs.existsSync(skillMdPath)) continue;

        const content = fs.readFileSync(skillMdPath, "utf-8");

        let skillName = dir.name;
        let description = "";
        const frontmatterMatch = content.match(/^---\s*\n([\s\S]*?)\n---/);
        if (frontmatterMatch) {
          const fm = frontmatterMatch[1];
          skillName = parseFrontmatterValue(fm, "name") || dir.name;
          description = parseFrontmatterValue(fm, "description");
        }

        const slug = `skill-${dir.name.replace(/[^a-z0-9]/gi, "-").toLowerCase()}`;

        const refsDir = path.join(skillsDir, dir.name, "references");
        const hasReferences = fs.existsSync(refsDir);
        let referenceFiles: string[] = [];
        if (hasReferences) {
          referenceFiles = fs.readdirSync(refsDir).filter(f => f.endsWith(".md"));
        }
        const additionalFiles = fs.readdirSync(path.join(skillsDir, dir.name))
          .filter(f => f !== "SKILL.md" && f.endsWith(".md"));
        referenceFiles = [...referenceFiles, ...additionalFiles];

        // Count all files and detect scripts
        const allFiles = fs.readdirSync(path.join(skillsDir, dir.name), { recursive: true }) as string[];
        const hasScripts = allFiles.some((f: string) => f.toString().includes("scripts/") || f.toString().endsWith(".py") || f.toString().endsWith(".sh"));

        skills.push({
          name: skillName,
          dirName: dir.name,
          slug,
          description,
          content,
          alreadyImported: existingSlugs.has(slug),
          hasReferences,
          referenceFiles,
          category: categoryMap[dir.name] || "general",
          source: "anthropic",
          fileCount: allFiles.length,
          hasScripts,
        });
      }

      // Sort: not-imported first, then alphabetical
      skills.sort((a, b) => {
        if (a.alreadyImported !== b.alreadyImported) return a.alreadyImported ? 1 : -1;
        return a.name.localeCompare(b.name);
      });

      res.json(skills);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to scan skills" });
    }
  });

  app.post("/api/tools/import-skill", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const { dirName, nameOverride, descriptionOverride } = req.body;
      if (!dirName || typeof dirName !== "string") {
        return res.status(400).json({ message: "dirName is required" });
      }

      if (/[\/\\]|\.\./.test(dirName)) {
        return res.status(400).json({ message: "Invalid skill directory name" });
      }

      const skillsDir = path.resolve(".local/skills");
      const skillDir = path.join(skillsDir, dirName);
      const resolved = path.resolve(skillDir);
      if (!resolved.startsWith(skillsDir + path.sep)) {
        return res.status(400).json({ message: "Invalid skill directory name" });
      }
      const skillMdPath = path.join(skillDir, "SKILL.md");

      if (!fs.existsSync(skillMdPath)) {
        return res.status(404).json({ message: `Skill not found: ${dirName}` });
      }

      const content = fs.readFileSync(skillMdPath, "utf-8");

      let skillName = dirName;
      let description = "";
      const frontmatterMatch = content.match(/^---\s*\n([\s\S]*?)\n---/);
      if (frontmatterMatch) {
        const fm = frontmatterMatch[1];
        const nameMatch = fm.match(/^name:\s*(.+)$/m);
        const descMatch = fm.match(/^description:\s*(.+)$/m);
        if (nameMatch) skillName = nameMatch[1].trim();
        if (descMatch) description = descMatch[1].trim();
      }

      const refsDir = path.join(skillDir, "references");
      let fullContent = content;
      if (fs.existsSync(refsDir)) {
        const refFiles = fs.readdirSync(refsDir).filter(f => f.endsWith(".md"));
        for (const refFile of refFiles) {
          const refContent = fs.readFileSync(path.join(refsDir, refFile), "utf-8");
          fullContent += `\n\n---\n## Reference: ${refFile}\n${refContent}`;
        }
      }
      const additionalFiles = fs.readdirSync(skillDir)
        .filter(f => f !== "SKILL.md" && f.endsWith(".md"));
      for (const addFile of additionalFiles) {
        const addContent = fs.readFileSync(path.join(skillDir, addFile), "utf-8");
        fullContent += `\n\n---\n## Reference: ${addFile}\n${addContent}`;
      }

      const slug = `skill-${dirName.replace(/[^a-z0-9]/gi, "-").toLowerCase()}`;

      const existingTools = await storage.getTools();
      if (existingTools.some(t => t.slug === slug)) {
        return res.status(409).json({ message: `Skill "${dirName}" is already imported as tool "${slug}"` });
      }

      const finalName = nameOverride || skillName.split(/[-_]/).map((w: string) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
      const finalDescription = descriptionOverride || description;

      const tool = await storage.createTool({
        name: finalName,
        slug,
        description: finalDescription,
        type: "skill",
        category: "general",
        status: "active",
        version: "1.0.0",
        skillContent: fullContent,
        executionMode: "prompt_injection",
        accessTier: "any",
        maxConcurrent: 0,
        defaultLeaseSeconds: 300,
        maxLeaseSeconds: 3600,
      });

      res.status(201).json(tool);
    } catch (err: any) {
      res.status(500).json({ message: err.message || "Failed to import skill" });
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

  app.get("/api/sub-agents/:id/tool-history", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      const directLeases = await storage.getToolLeases({ agentId: req.params.id });
      const woLeases = await storage.getToolLeasesBySubAgent(req.params.id);
      const leaseMap = new Map<string, any>();
      [...directLeases, ...woLeases].forEach(l => leaseMap.set(l.id, l));
      const merged = Array.from(leaseMap.values()).sort(
        (a: any, b: any) => new Date(b.issuedAt).getTime() - new Date(a.issuedAt).getTime()
      );
      res.json(merged);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch tool history" });
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

  app.put("/api/sub-agents/:id/tools/:toolId/toggle", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const agent = await storage.getSubAgent(req.params.id);
      if (!agent) return res.status(404).json({ message: "Sub-agent not found" });
      const { enabled } = req.body;
      if (typeof enabled !== "boolean") return res.status(400).json({ message: "enabled (boolean) is required" });

      const existing = await storage.getSubAgentTools(req.params.id);
      const assignment = existing.find(a => a.toolId === req.params.toolId);

      if (assignment) {
        await storage.updateSubAgentTool(assignment.id, { enabled });
        res.json({ ...assignment, enabled });
      } else {
        const tool = await storage.getTool(req.params.toolId);
        if (!tool) return res.status(404).json({ message: "Tool not found" });
        const created = await storage.assignToolToSubAgent({
          subAgentId: req.params.id,
          toolId: req.params.toolId,
          enabled,
          config: {},
        });
        res.json(created);
      }
    } catch (err) {
      res.status(500).json({ message: "Failed to toggle tool" });
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

  // ==================== MCP Server Routes ====================

  app.post("/api/locker/mcp/test", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const { mcpConfig } = req.body;
      if (!mcpConfig) return res.status(400).json({ message: "mcpConfig is required" });
      const { testConnection } = await import("./mcp-client");
      const result = await testConnection(mcpConfig);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ success: false, message: `MCP test failed: ${err.message}`, tools: [] });
    }
  });

  app.post("/api/locker/mcp/list-tools", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const { mcpConfig } = req.body;
      if (!mcpConfig) return res.status(400).json({ message: "mcpConfig is required" });
      const { connectAndListTools } = await import("./mcp-client");
      const result = await connectAndListTools(mcpConfig);
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ message: `Failed to list MCP tools: ${err.message}` });
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
      const sourceId = req.query.sourceId as string | undefined;
      const items = await storage.getArtifacts(sourceId ? undefined : (folderId === "root" ? null : folderId), sourceId);
      res.json(items);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch artifacts" });
    }
  });

  app.get("/api/artifacts/published", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const items = await storage.getPublishedArtifacts();
      res.json(items.map(a => ({
        id: a.id,
        name: a.name,
        slug: a.publishedSlug,
        publicUrl: a.publishedUrl,
        policy: a.publishPolicy,
        publishedAt: a.publishedAt,
      })));
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch published artifacts" });
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

  app.get("/api/artifacts/:id/download", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      if (!artifact.content) return res.status(404).json({ message: "Artifact has no content" });

      const mimeType = artifact.mimeType || "application/octet-stream";
      const ext = (artifact.name || "").split(".").pop()?.toLowerCase() || "";
      const binaryExts = ["pptx", "ppt", "docx", "doc", "xlsx", "xls", "pdf", "zip", "gz", "tar", "7z", "rar", "png", "jpg", "jpeg", "gif", "webp"];
      const isBinary = binaryExts.includes(ext) ||
        mimeType.includes("vnd.openxmlformats") || mimeType.includes("octet-stream") ||
        mimeType.includes("pdf") || mimeType.includes("zip") || mimeType.includes("gzip") ||
        mimeType.includes("msword") || mimeType.includes("ms-excel") || mimeType.includes("ms-powerpoint") ||
        mimeType.startsWith("image/");

      res.setHeader("Content-Disposition", `attachment; filename="${artifact.name}"`);
      res.setHeader("Content-Type", mimeType);

      if (isBinary) {
        const buffer = Buffer.from(artifact.content, "base64");
        res.setHeader("Content-Length", buffer.length);
        res.send(buffer);
      } else {
        res.setHeader("Content-Length", Buffer.byteLength(artifact.content, "utf-8"));
        res.send(artifact.content);
      }
    } catch (err) {
      res.status(500).json({ message: "Failed to download artifact" });
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
          content: "# CLAUDE - Configuration & Context\n\nThis file provides context and configuration for AI-assisted operations.\n\n## System Context\n\n- Platform: AIDEN_IWO Orchestration Engine\n- Architecture: 2-Tier (Aiden Manager + Sub-Agent Workers)\n- Workflow Engine: Multi-step with dependency resolution\n\n## Operating Guidelines\n\n1. Follow established SOPs in `01_Directive-SOP/`\n2. Store outputs in `02_Execution/` or `05_Artifacts/`\n3. Log test results in `06_Tests/`\n4. Reference resources from `04_Resources/`\n",
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

  // ==================== Workspace File Upload ====================

  app.post("/api/workspace/upload", isAuth, requireRole("operator"), async (req: Request, res: Response) => {
    try {
      const { name, mimeType, data, folderId } = req.body;

      if (!name || !mimeType || !data) {
        return res.status(400).json({ message: "Missing required fields: name, mimeType, data" });
      }

      const allowedTypes = [
        "text/markdown", "text/plain", "text/html", "text/css", "text/javascript", "text/typescript",
        "application/json",
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
        "image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml",
      ];
      if (!allowedTypes.includes(mimeType)) {
        return res.status(400).json({ message: `Unsupported file type: ${mimeType}` });
      }

      const isTextType = mimeType.startsWith("text/") || mimeType === "application/json";
      const sizeBytes = isTextType
        ? Buffer.byteLength(data, "utf8")
        : Math.ceil(data.length * 0.75);

      const maxSize = 10 * 1024 * 1024;
      if (sizeBytes > maxSize) {
        return res.status(400).json({ message: "File too large (max 10MB)" });
      }

      const actor = getActor(req);
      const artifact = await storage.createArtifact({
        name,
        folderId: folderId || null,
        type: "file",
        mimeType,
        content: data,
        size: sizeBytes,
        createdBy: actor.actorId,
      });

      res.status(201).json(artifact);
    } catch (err) {
      res.status(500).json({ message: "Upload failed" });
    }
  });

  // ==================== Know-How Retrieval Routes ====================

  app.get("/api/code-blocks", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const { language, sourceId, tag } = req.query;
      const filters: { language?: string; sourceId?: string; tags?: string[] } = {};
      if (typeof language === "string") filters.language = language;
      if (typeof sourceId === "string") filters.sourceId = sourceId;
      if (typeof tag === "string") filters.tags = [tag];
      const blocks = await storage.getCodeBlocks(filters);
      res.json(blocks);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch code blocks" });
    }
  });

  app.get("/api/code-blocks/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const block = await storage.getCodeBlock(req.params.id);
      if (!block) return res.status(404).json({ message: "Code block not found" });
      res.json(block);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch code block" });
    }
  });

  app.post("/api/code-blocks", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const { name, language, content, description, tags, sourceType, sourceId, sourceName } = req.body;
      if (!name || !content) return res.status(400).json({ message: "name and content are required" });
      const block = await storage.createCodeBlock({
        name,
        language: language || "text",
        content,
        description: description || null,
        tags: tags || [],
        sourceType: sourceType || "manual",
        sourceId: sourceId || null,
        sourceName: sourceName || null,
        createdBy: (req as any).appUser?.username || "operator",
      });
      res.status(201).json(block);
    } catch (err) {
      res.status(500).json({ message: "Failed to create code block" });
    }
  });

  app.post("/api/knowhow/resolve", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const { KnowHowService } = await import("./knowhow");
      const { LocalWorkspaceProvider } = await import("./workspace-provider");
      const service = new KnowHowService(new LocalWorkspaceProvider());
      const pack = await service.resolve(req.body, req.body.gccMemory);
      res.json(pack);
    } catch (err: any) {
      res.status(500).json({ message: "Know-How retrieval failed", error: err.message });
    }
  });

  app.get("/api/knowhow/retrievals", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      // Simple audit log query — returns most recent 50
      const { contextRetrievals: crTable } = await import("@shared/schema");
      const { db } = await import("./db");
      const { desc } = await import("drizzle-orm");
      const records = await db.select().from(crTable).orderBy(desc(crTable.createdAt)).limit(50);
      res.json(records);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch retrieval records" });
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

      // P0-D: B+ Hardening — LLM-generated HTML only.
      // Tight CSP: no external CDNs, no unsafe-eval.
      // Set SANDBOX_ALLOW_CUSTOM_HTML=true in dev to restore permissive mode.
      const allowCustomHtml = process.env.SANDBOX_ALLOW_CUSTOM_HTML === "true" && process.env.NODE_ENV !== "production";
      const csp = allowCustomHtml
        ? "default-src 'self' 'unsafe-inline' 'unsafe-eval' blob:; script-src 'self' 'unsafe-inline' 'unsafe-eval' blob: https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://unpkg.com https://cdn.pyodide.org https://pyodide-cdn2.iodide.io; img-src * data: blob:; font-src * data:; style-src * 'unsafe-inline'; connect-src * data: blob:; media-src * blob:; worker-src 'self' blob:;"
        : "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src https://fonts.googleapis.com https://fonts.gstatic.com; frame-ancestors 'self';";

      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.setHeader("Content-Security-Policy", csp);
      res.setHeader("X-Frame-Options", "SAMEORIGIN");
      res.setHeader("X-Content-Type-Options", "nosniff");
      res.send(result.html);
    } catch (err) {
      res.status(500).json({ message: "Failed to load preview" });
    }
  });

  app.post("/api/sandbox-sessions/:id/rerender", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });

      const env = session.environment as any;
      const workOrderId = env?.sourceId;
      if (!workOrderId) {
        return res.status(400).json({ message: "No linked work order found for this session" });
      }

      const order = await storage.getWorkOrder(workOrderId);
      if (!order) {
        return res.status(404).json({ message: "Linked work order not found" });
      }

      const tier2 = (order.tier2Result as any) || {};
      const deliverable = tier2.output?.deliverable || null;
      if (!deliverable) {
        return res.status(400).json({ message: "Work order has no deliverable content" });
      }

      const { extractHtmlFromDeliverable, extractCodeBlocksFromDeliverable, buildCodePreviewHtml, buildMarkdownPreviewHtml, detectUnfencedCode } = await import("./workspace-filing");
      const title = env?.deliverableTitle || order.title;

      let newHtml: string | null = extractHtmlFromDeliverable(deliverable);
      if (!newHtml) {
        const codeBlocks = extractCodeBlocksFromDeliverable(deliverable);
        if (codeBlocks.length > 0) {
          newHtml = buildCodePreviewHtml(title, codeBlocks, deliverable);
        }
      }

      if (!newHtml) {
        const unfencedBlocks = detectUnfencedCode(deliverable);
        if (unfencedBlocks.length > 0) {
          newHtml = buildCodePreviewHtml(title, unfencedBlocks, deliverable);
        }
      }

      if (!newHtml && deliverable.length > 50) {
        newHtml = buildMarkdownPreviewHtml(title, deliverable);
      }

      if (!newHtml) {
        return res.status(400).json({ message: "No renderable content found in deliverable" });
      }

      const reRenderLog = {
        timestamp: new Date().toISOString(),
        command: "re-render",
        input: { workOrderId: order.id, title: order.title },
        output: { message: `Preview re-rendered with updated engine`, status: "success" },
      };

      const existingLogs = Array.isArray(session.logs) ? session.logs : [];
      await storage.updateSandboxSession(session.id, {
        result: { html: newHtml, renderable: true, title },
        logs: [...existingLogs, reRenderLog],
      });

      const updated = await storage.getSandboxSession(session.id);
      res.json(updated);
    } catch (err: any) {
      res.status(500).json({ message: "Failed to re-render preview", error: err.message });
    }
  });

  /**
   * POST /api/sandbox-sessions/:id/publish — One-click publish sandbox HTML to GitHub Pages.
   * Creates an artifact from the session HTML (or reuses existing), publishes it, returns public URL.
   * Body: { slug?: string } — auto-generated from session name if omitted.
   */
  app.post("/api/sandbox-sessions/:id/publish", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const session = await storage.getSandboxSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });

      const result = session.result as any;
      if (!result?.html || !result?.renderable) {
        return res.status(400).json({ message: "Session has no renderable HTML to publish" });
      }

      const htmlContent: string = result.html;
      const sessionName = session.name || `sandbox-${session.id.slice(0, 8)}`;
      const slug = req.body.slug || slugify(sessionName);

      if (!isValidSlug(slug)) {
        return res.status(400).json({ message: "Invalid slug. Use 3-128 chars: lowercase, numbers, hyphens." });
      }

      // Check slug uniqueness
      const existing = await storage.getArtifactBySlug(slug);
      if (existing) {
        // Re-publish: update the existing artifact's content and re-push
        await storage.updateArtifact(existing.id, {
          content: htmlContent,
          name: `${sessionName}.html`,
        });
        const pubResult = await publishToGitHubPages(slug, htmlContent, `Update: ${sessionName}`);
        if (!pubResult.success) {
          return res.status(502).json({ message: "Failed to publish to GitHub Pages", error: pubResult.error });
        }
        await storage.updateArtifact(existing.id, {
          publishedAt: new Date(),
          publishedUrl: pubResult.publicUrl!,
        });
        return res.json({
          message: "Updated and re-published",
          publicUrl: pubResult.publicUrl,
          slug,
          artifactId: existing.id,
        });
      }

      // Create a new artifact from the sandbox HTML
      const artifact = await storage.createArtifact({
        name: `${sessionName}.html`,
        type: "file",
        mimeType: "text/html",
        content: htmlContent,
        sourceType: "sandbox",
        sourceId: session.id,
        tags: ["html", "sandbox", "published"],
        createdBy: "system",
      });

      // Publish to GitHub Pages
      const pubResult = await publishToGitHubPages(slug, htmlContent, `Publish: ${sessionName}`);
      if (!pubResult.success) {
        return res.status(502).json({ message: "Failed to publish to GitHub Pages", error: pubResult.error });
      }

      // Update artifact with publish metadata
      await storage.updateArtifact(artifact.id, {
        publishedSlug: slug,
        publishedAt: new Date(),
        publishedUrl: pubResult.publicUrl!,
        publishPolicy: "public",
      });

      res.json({
        message: "Published successfully",
        publicUrl: pubResult.publicUrl,
        slug,
        artifactId: artifact.id,
      });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to publish sandbox session", error: err.message });
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

  app.get("/api/chat/groups", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const groups = await storage.getChatGroups();
      res.json(groups);
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch chat groups" });
    }
  });

  app.post("/api/chat/groups", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const schema = z.object({
        name: z.string().min(1),
        parentId: z.string().nullable().optional(),
        color: z.string().nullable().optional(),
        sortOrder: z.number().optional(),
        isCollapsed: z.boolean().optional(),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid request" });
      const group = await storage.createChatGroup(parsed.data);
      res.json(group);
    } catch (err) {
      res.status(500).json({ message: "Failed to create chat group" });
    }
  });

  app.put("/api/chat/groups/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const schema = z.object({
        name: z.string().min(1).optional(),
        parentId: z.string().nullable().optional(),
        color: z.string().nullable().optional(),
        sortOrder: z.number().optional(),
        isCollapsed: z.boolean().optional(),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid request" });
      const updated = await storage.updateChatGroup(req.params.id, parsed.data);
      if (!updated) return res.status(404).json({ message: "Group not found" });
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update chat group" });
    }
  });

  app.delete("/api/chat/groups/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      await storage.deleteChatGroup(req.params.id);
      res.json({ success: true });
    } catch (err) {
      res.status(500).json({ message: "Failed to delete chat group" });
    }
  });

  app.get("/api/chat/sessions", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const includeArchived = req.query.includeArchived === "true";
      const sessions = await storage.getChatSessions(includeArchived);
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
        groupId: z.string().nullable().optional(),
        isArchived: z.boolean().optional(),
      });
      const parsed = updateSchema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid request" });
      const updates: any = { ...parsed.data };
      if (parsed.data.isArchived === true) {
        updates.archivedAt = new Date();
      } else if (parsed.data.isArchived === false) {
        updates.archivedAt = null;
      }
      const updated = await storage.updateChatSession(req.params.id, updates);
      if (!updated) return res.status(404).json({ message: "Session not found" });
      res.json(updated);
    } catch (err) {
      res.status(500).json({ message: "Failed to update chat session" });
    }
  });

  app.post("/api/chat/sessions/bulk-update", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const schema = z.object({
        sessionIds: z.array(z.string()),
        groupId: z.string().nullable().optional(),
        isArchived: z.boolean().optional(),
      });
      const parsed = schema.safeParse(req.body);
      if (!parsed.success) return res.status(400).json({ message: "Invalid request" });
      const updates: any = {};
      if (parsed.data.groupId !== undefined) updates.groupId = parsed.data.groupId;
      if (parsed.data.isArchived !== undefined) {
        updates.isArchived = parsed.data.isArchived;
        updates.archivedAt = parsed.data.isArchived ? new Date() : null;
      }
      const results = await Promise.all(
        parsed.data.sessionIds.map(id => storage.updateChatSession(id, updates))
      );
      res.json({ updated: results.filter(Boolean).length });
    } catch (err) {
      res.status(500).json({ message: "Failed to bulk update sessions" });
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
    // Lean context: only load what chat routing actually needs
    const [subAgents, stats, workflows, toolsList, gammaConfig, gammaRegistryEntries] = await Promise.all([
      storage.getSubAgents(),
      storage.getWorkOrderStats(),
      storage.getWorkflowTemplates(),
      storage.getTools(),
      storage.getGammaSettings(),
      storage.getGammaTemplates(),
    ]);

    // Only show active/blocked work orders (not the full history)
    const allOrders = await storage.getWorkOrders();
    const activeOrders = allOrders.filter(o =>
      o.status === "pending" || o.status === "processing" || o.status === "blocked" || o.status === "reopened"
    ).slice(0, 10);

    return `== AIDEN ENVIRONMENT BRIEFING ==

=== WORK ORDER STATUS ===
Total: ${stats.total} | Pending: ${stats.pending} | Processing: ${stats.processing} | Completed: ${stats.completed} | Blocked: ${stats.blocked} | Failed: ${stats.failed}
${activeOrders.length > 0 ? `\nActive Orders (${activeOrders.length}):\n${activeOrders.map(o =>
      `- [${o.status.toUpperCase()}] "${o.title}" (${o.type}, ${o.priority}, id: ${o.id}${o.assignedSubAgentId ? `, assigned: ${o.assignedSubAgentId}` : ""}${o.bdmMarker ? `, BDM: ${o.bdmMarker}` : ""})`
    ).join("\n")}` : "No active orders."}

=== SUB-AGENTS ===
${subAgents.map(a => {
      const llm = a.llmEnabled
        ? `${a.llmProvider || "?"}/${a.llmModel || "?"}`
        : `inherits ${settings.provider}/${settings.model}`;
      return `- "${a.name}" (${a.controlMode}, ${a.status}, LLM: ${llm}${a.description ? ` — ${a.description.slice(0, 120)}` : ""})`;
    }).join("\n") || "No sub-agents configured"}

=== WORKFLOWS ===
${workflows.map(w => `- "${w.name}" (${w.status}, ${w.category})`).join("\n") || "No workflow templates"}

=== TOOLS ===
${toolsList.map(t => `- "${t.name}" (${t.type}${t.description ? ` — ${t.description.slice(0, 80)}` : ""})`).join("\n") || "No tools registered"}

=== GAMMA ENGINE (PPTX + PDF) ===
${(() => {
      const gammaKeySet = !!process.env.GAMMA_API_KEY;
      if (!gammaConfig || !gammaConfig.enabled) {
        return `Status: DISABLED (using local pipelines for PPTX and PDF)${gammaKeySet ? "\nGamma API key: configured in .env" : "\nGamma API key: NOT configured"}`;
      }
      const registryLines = gammaRegistryEntries.length > 0
        ? `\nRegistered Templates:\n${gammaRegistryEntries.map((t: any) => `- "${t.name}" (${t.templateKey}) — ${t.outputFormat.toUpperCase()}, ${t.mode}, ${t.status}`).join("\n")}`
        : "\nNo registered templates (using legacy gammaId routing)";
      return `Status: ENABLED | Mode: ${gammaConfig.mode} | Fallback to local: ${gammaConfig.fallbackToLocal ? "yes" : "no"}
API key: ${gammaKeySet ? "configured" : "NOT configured"}${registryLines}
Supported formats: PPTX and PDF (both routed through Gamma when enabled)
Routing: templateKey resolved via registry → format-matched → gammaId sent to Gamma API. Locked templates block fallback on failure.
Both PPTX and PDF work orders route through Gamma when enabled. Gamma produces Klear.ai-themed, professionally designed output.
Users configure via Settings > Gamma or API (GET/PUT /api/gamma-settings). Registry: GET/POST /api/gamma-templates.
Candidate Review: Workflow templates with gammaDeliveryPolicy="candidate_review" produce multiple Gamma candidates. Operator selects preferred version via /api/work-orders/:id/candidates/:recordId/select.
Template Precedence: WO-level gammaTemplateKey > workflow template default > global default.`;
    })()}

=== LLM ===
Provider: ${settings.provider} | Model: ${settings.model} | ${new Date().toISOString()}

=== PLATFORM IDENTITY ===
Platform: IOWA (Intelligent Work Orchestration) v${APP_VERSION}
You are Aiden, version ${APP_VERSION}. Do NOT reference older version numbers like v0.3.8, v0.6.9, or v0.8.9 — those are historical. Your current version is ${APP_VERSION}.

${await buildWorkspaceIndex()}`;
  }

  /**
   * Build a lightweight workspace directory index for the Chat system context.
   * Gives Aiden awareness of all folders, subfolders, and recent artifacts so it can:
   *  - Answer "what's in folder X?" directly without Know-How
   *  - Guide users to the correct path when they reference content by partial name
   *  - Self-resolve ambiguous references (e.g., "RH2026_Klearai" → KlearContent_Demo)
   *
   * This is intentionally compact — folder names + descriptions + artifact names only,
   * no content. Keeps the system prompt lean (~500-1500 tokens for a typical workspace).
   */
  async function buildWorkspaceIndex(): Promise<string> {
    try {
      const allFolders = await storage.getArtifactFolders();
      if (allFolders.length === 0) return "";

      // Build parent→children map
      const childMap = new Map<string | null, typeof allFolders>();
      for (const f of allFolders) {
        const pid = f.parentId ?? null;
        if (!childMap.has(pid)) childMap.set(pid, []);
        childMap.get(pid)!.push(f);
      }

      const lines: string[] = ["=== WORKSPACE DIRECTORY (your folders and files — reference these paths when the operator asks about content) ==="];

      // Show top-level folders with their direct children and artifact counts
      const topLevel = childMap.get(null) || [];
      for (const folder of topLevel.slice(0, 20)) {
        const path = (folder as any).path || folder.name;
        const desc = folder.description ? ` — ${folder.description}` : "";
        lines.push(`\n📁 ${path}${desc}`);

        // List direct children (subfolders)
        const children = childMap.get(folder.id) || [];
        for (const child of children.slice(0, 15)) {
          const childDesc = child.description ? ` — ${child.description}` : "";
          lines.push(`  📂 ${child.name}${childDesc}`);

          // List artifacts in child folder (name only, no content)
          const arts = await storage.getArtifacts(child.id);
          for (const a of arts.slice(0, 10)) {
            const mime = a.mimeType ? ` [${a.mimeType}]` : "";
            lines.push(`    📄 ${a.name}${mime}`);
          }

          // Show grandchildren count if any
          const grandchildren = childMap.get(child.id) || [];
          if (grandchildren.length > 0) {
            lines.push(`    (${grandchildren.length} subfolder${grandchildren.length === 1 ? "" : "s"})`);
          }
        }

        // List artifacts directly in this top-level folder
        const directArts = await storage.getArtifacts(folder.id);
        for (const a of directArts.slice(0, 5)) {
          lines.push(`  📄 ${a.name}`);
        }
      }

      lines.push("");
      lines.push(`IMPORTANT — WORKSPACE CONTENT RULES:
1. You have DIRECT ACCESS to ALL files listed above via your Know-How retrieval system. Their content is automatically injected into your context when the operator references them.
2. NEVER say "I don't have access to that file" — you DO have access. If the content appears in your context (look for "=== KNOW-HOW CONTEXT ===" sections), USE it to answer directly.
3. When the operator asks about a file's content, ANSWER FROM THE INJECTED CONTEXT — do NOT create a work order unless the operator explicitly asks for one.
4. If a file name doesn't exactly match, search the directory listing above for the closest match.
5. When referencing files back to the operator, use the full path from the directory listing (e.g., "04_Resources/Demo_Content/KlearContent_Demo/RH2026_Klearai.pdf").
6. ONLY the content under "=== KNOW-HOW CONTEXT ===" with "GROUNDING RULES" is from actual source documents. Do NOT fabricate statistics, percentages, or claims not found in that grounded content.`);

      return lines.join("\n");
    } catch (err: any) {
      console.warn("[buildWorkspaceIndex] Failed:", err.message);
      return "";
    }
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

      let systemContext = await buildSystemContext(settings);

      // Manager reporting: inject factual report data for operational questions
      const { isManagerQuestion, generateManagerReport, formatReportForChat, createReportingGap } = await import("./manager-reporting");
      if (isManagerQuestion(message)) {
        try {
          const report = await generateManagerReport("today");
          systemContext += "\n\n" + formatReportForChat(report);
        } catch (err: any) {
          console.warn("[chat] Manager report injection failed:", err.message);
          systemContext += "\n\n=== MANAGER REPORTING ===\nOperational report unavailable. If asked for daily counts or operational summaries, respond: \"I don't have that information at this time.\"";
        }
      }

      // Web Research: search + scrape for questions needing current/real-world data
      const webSearchPatterns = /\b(what(?:'s| is| are| was| were| happened)|who(?:'s| is| are| was)|when(?:'s| is| did| was)|where(?:'s| is| are)|how (?:much|many|does|did|is|are|do)|latest|current|today|tomorrow|yesterday|recent|news|score|price|stock|weather|forecast|update|happening|trending|right now|as of|this week|this month)\b/i;
      const urlPattern = /https?:\/\/[^\s,\n]+/g;
      const foundUrls = message.match(urlPattern);
      const needsWebSearch = webSearchPatterns.test(message) && !isManagerQuestion(message);
      if (needsWebSearch || (foundUrls && foundUrls.length > 0)) {
        const { executeBuiltInWebSearch, executeBuiltInWebScrape } = await import("./tool-executor");
        const webResults: string[] = [];
        if (needsWebSearch) {
          try {
            const searchQuery = message.replace(urlPattern, "").trim().slice(0, 200);
            if (searchQuery.length >= 3) {
              console.log(`[chat] Web search triggered for chat query`);
              const searchResult = await executeBuiltInWebSearch(searchQuery);
              if (searchResult && searchResult.length > 100) {
                webResults.push("### Web Search Results\n" + searchResult.slice(0, 6000));
              }
            }
          } catch (err: any) {
            console.warn("[chat] Web search failed:", err.message);
          }
        }
        if (foundUrls && foundUrls.length > 0) {
          try {
            console.log(`[chat] Web scrape triggered for ${foundUrls.length} URL(s)`);
            const scrapeResult = await executeBuiltInWebScrape(foundUrls.slice(0, 3).join(" "));
            if (scrapeResult && scrapeResult.length > 50) {
              webResults.push("### Web Page Content\n" + scrapeResult.slice(0, 8000));
            }
          } catch (err: any) {
            console.warn("[chat] Web scrape failed:", err.message);
          }
        }
        if (webResults.length > 0) {
          systemContext += "\n\n=== LIVE WEB RESEARCH (retrieved just now — use this data to answer accurately) ===\n" + webResults.join("\n\n");
        }
      }

      const gcc = (session.gccMemory as any) || {};
      const breadcrumbs = [...(gcc["gcc.breadcrumbs"] || []), "user_message", "llm_processing"];

      // Know-How Retrieval: inject workspace context when message references workspace content
      // Also triggers on "know how", "knowhow", and bare ##_FolderName workspace paths
      // Bounded by a 15s timeout — if extraction/resolve takes longer, Chat proceeds without context.
      const knowHowTrigger = /\b(from|in|using|folder|artifact|code\s*block|snippet|workspace|look\s*up|find|search|retrieve|reference|know\s*-?\s*how)\b|\b\d{2}_[A-Za-z]|\b[A-Z][A-Za-z0-9]*_[A-Za-z]/;
      if (knowHowTrigger.test(message)) {
        try {
          const { KnowHowService, parseContextRequestFromChat } = await import("./knowhow");
          const { LocalWorkspaceProvider } = await import("./workspace-provider");
          const ctxReq = parseContextRequestFromChat(message);
          if (ctxReq) {
            console.log("[chat] Know-How triggered, parsed request:", JSON.stringify(ctxReq));
            const service = new KnowHowService(new LocalWorkspaceProvider());
            const resolveStart = Date.now();
            const pack = await Promise.race([
              service.resolve(ctxReq, gcc),
              new Promise<null>((resolve) => setTimeout(() => resolve(null), 15_000)),
            ]);
            const resolveMs = Date.now() - resolveStart;
            if (pack && pack.sources.length > 0) {
              console.log(`[chat] Know-How resolved: ${pack.sources.length} sources, ~${pack.tokensUsed} tokens in ${resolveMs}ms`);
              systemContext += "\n\n" + service.formatForLLM(pack);
            } else if (!pack) {
              console.warn(`[chat] Know-How retrieval timed out after ${resolveMs}ms — proceeding without context`);
            } else {
              console.log(`[chat] Know-How resolved but 0 sources in ${resolveMs}ms`);
            }
          }
        } catch (err: any) {
          console.warn("[chat] Know-How retrieval failed:", err.message);
        }
      }

      let reply = await chatWithAiden(settings, message, conversationHistory.slice(0, -1), systemContext, gcc);

      const actionResults: Array<{ type: string; workOrderId?: string; executionId?: string; correlationId?: string; autoProcessed?: boolean }> = [];
      const actor = getActor(req);
      const userRole = (req as any).appUser?.role || "viewer";
      const canCreateOrders = userRole === "admin" || userRole === "operator";

      const validTypes = ["general", "technical", "creative", "research", "compliance", "financial", "hr", "operations", "strategic", "process documentation", "process_documentation", "training", "security", "infrastructure"];
      const validPriorities = ["low", "medium", "high", "critical"];

      const lines = reply.split("\n");
      const actionLines: string[] = [];
      const workflowActionLines: string[] = [];
      const contentLines: string[] = [];
      const actionLineRegex = /^<!--\s*AIDEN_ACTION:CREATE_WORK_ORDER:(\{.*\})\s*-->$/;
      const workflowActionLineRegex = /^<!--\s*AIDEN_ACTION:EXECUTE_WORKFLOW:(\{.*\})\s*-->$/;
      for (const line of lines) {
        const woMatch = line.trim().match(actionLineRegex);
        const wfMatch = line.trim().match(workflowActionLineRegex);
        if (woMatch) {
          actionLines.push(woMatch[1]);
        } else if (wfMatch) {
          workflowActionLines.push(wfMatch[1]);
        } else {
          contentLines.push(line);
        }
      }
      let extractionMethod = actionLines.length > 0 ? "action_block" : "none";

      const userWantsWO = /\b(create|open|submit|make|start|raise|file|assign)\b.*\b(work\s*order|wo|ticket|order|task)\b/i.test(message) ||
        /\b(work\s*order|wo|ticket)\b.*\b(for|to|about)\b/i.test(message);
      const aidenConfirmsWO = /\b(creat|submit|open|rais|draft)\w*\b.*\b(work\s*order|order|ticket)\b/i.test(reply);
      const workOrderIntentDetected = userWantsWO || aidenConfirmsWO;

      if (actionLines.length === 0 && canCreateOrders && workOrderIntentDetected) {
        const titleMatch = reply.match(/\*\*Title\*\*\s*\|\s*(.+?)(?:\s*\||\s*$)/im) ||
          reply.match(/\bTitle\b[:\s]+([^\n|]+)/im);
        const descMatch = reply.match(/\*\*Description\s*(?:\/\s*Prompt)?\*\*\s*\|\s*(.+?)(?:\s*\||\s*$)/im) ||
          reply.match(/\bDescription\b[:\s]+([^\n|]+)/im);
        const typeMatch = reply.match(/\*\*Type\*\*\s*\|\s*\*?\*?([^\n|*]+)/im) ||
          reply.match(/\bType\b[:\s]+([^\n|]+)/im);
        const priorityMatch = reply.match(/\*\*Priority\*\*\s*\|\s*\*?\*?([^\n|*]+)/im) ||
          reply.match(/\bPriority\b[:\s]+([^\n|]+)/im);

        if (titleMatch) {
          const cleanField = (s: string) => s.replace(/\*+/g, "").replace(/\(.*?\)/g, "").replace(/[\u2013\u2014\u2015–—].*/g, "").trim();
          const extracted = {
            title: cleanField(titleMatch[1]),
            description: descMatch ? cleanField(descMatch[1]) : "",
            type: typeMatch ? cleanField(typeMatch[1]).toLowerCase().replace(/\s+/g, "_") : "general",
            priority: priorityMatch ? cleanField(priorityMatch[1]).toLowerCase() : "medium",
            submittedBy: "aiden",
            autoProcess: true,
          };
          if (extracted.title.length >= 3) {
            actionLines.push(JSON.stringify(extracted));
            extractionMethod = "regex_fallback";
            console.log("[Chat Action T2 Regex] Extracted work order:", extracted.title);
          }
        }
      }

      // T3 LLM extraction: only run when NO workflow action is queued (to avoid duplicate WOs)
      // When a workflow IS present, keep any T1 action-block WOs (they were explicit), but skip T3
      if (workflowActionLines.length === 0) {
        if (actionLines.length === 0 && canCreateOrders && workOrderIntentDetected) {
          console.log("[Chat Action T3 LLM] Intent detected but T1/T2 missed, running extraction call...");
          try {
            const extracted = await extractWorkOrderFromChat(settings, message, reply);
            if (extracted && extracted.shouldCreate) {
              actionLines.push(JSON.stringify({
                ...extracted,
                submittedBy: "aiden",
                autoProcess: true,
              }));
              extractionMethod = "llm_extraction";
              console.log("[Chat Action T3 LLM] Extracted work order:", extracted.title);
            } else {
              console.log("[Chat Action T3 LLM] Extraction returned shouldCreate=false, skipping.");
            }
          } catch (extractErr) {
            console.error("[Chat Action T3 LLM] Extraction call failed:", extractErr);
          }
        }
      } else {
        // Workflow action present — skip T3 extraction but keep any T1-detected WO action lines
        console.log(`[Chat Action] Workflow action present — skipping T3 extraction (${actionLines.length} T1 WO action(s) preserved)`);
      }

      if (actionLines.length > 0 && canCreateOrders) {
        console.log(`[Chat Action] Creating ${actionLines.length} work order(s) via ${extractionMethod}`);
        for (const actionJson of actionLines.slice(0, 3)) {
          try {
            const actionData = JSON.parse(actionJson);
            const safeTitle = String(actionData.title || "Untitled Work Order").slice(0, 200);
            const safeDescription = String(actionData.description || "").slice(0, 5000);
            const normalizedType = String(actionData.type || "general").toLowerCase().replace(/\s+/g, "_");
            const safeType = validTypes.includes(normalizedType) || validTypes.includes(normalizedType.replace(/_/g, " ")) ? normalizedType : "general";
            const safePriority = validPriorities.includes(String(actionData.priority || "").toLowerCase()) ? String(actionData.priority).toLowerCase() : "medium";

            const preferredAgent = actionData.preferredAgent ? String(actionData.preferredAgent) : null;

            const { gccMemory: initialGcc, commitId: woCommitId } = buildGccCommit(
              preferredAgent ? { "gcc.preferredAgent": preferredAgent } : {},
              "new", "created_via_chat",
              `Work order created via chat by ${actor.actorName}`,
              `Aiden created work order "${safeTitle}" during chat session ${sessionId}${preferredAgent ? ` — operator requested sub-agent: ${preferredAgent}` : ""}`,
              { submittedBy: { ...actor, source: "aiden_chat" }, chatSessionId: sessionId, extractionMethod, preferredAgent },
            );

            const orderData = {
              title: safeTitle,
              description: safeDescription,
              type: safeType,
              priority: safePriority,
              submittedBy: actor.actorName || "aiden",
            };
            const newOrder = await storage.createWorkOrder(orderData);
            await storage.updateWorkOrder(newOrder.id, { gccMemory: initialGcc });
            await storage.createExecutionLog({
              workOrderId: newOrder.id,
              tier: 1,
              action: "Submitted via Chat",
              message: `Work order created by Aiden during chat with ${actor.actorName} [${extractionMethod}]`,
              metadata: { actor, chatSessionId: sessionId, source: "aiden_chat", commitId: woCommitId, extractionMethod },
            });

            let autoProcessed = false;
            if (actionData.autoProcess) {
              try {
                processWorkOrderSafe(newOrder.id);
                autoProcessed = true;
                await storage.createExecutionLog({
                  workOrderId: newOrder.id,
                  tier: 1,
                  action: "Auto-Processing Initiated",
                  message: `Auto-processing triggered from chat action`,
                  metadata: { source: "aiden_chat", chatSessionId: sessionId },
                });
              } catch (procErr: any) {
                console.error("Auto-process failed for chat-created order:", procErr);
                await storage.createExecutionLog({
                  workOrderId: newOrder.id,
                  tier: 1,
                  action: "Auto-Processing Failed",
                  message: `Auto-processing failed: ${procErr?.message || "Unknown error"}`,
                  metadata: { source: "aiden_chat", error: procErr?.message },
                });
              }
            }

            actionResults.push({
              type: "CREATE_WORK_ORDER",
              workOrderId: newOrder.id,
              correlationId: newOrder.correlationId,
              autoProcessed,
            });

            reply = contentLines.join("\n");
            reply = reply.replaceAll("{{WORK_ORDER_ID}}", newOrder.id);
            reply = reply.replaceAll("{{CORRELATION_ID}}", newOrder.correlationId);
          } catch (parseErr) {
            console.error("Failed to parse/create chat action:", parseErr);
          }
        }
      } else {
        reply = contentLines.join("\n");
      }

      // ── EXECUTE_WORKFLOW action handler ────────────────────────────────────
      if (workflowActionLines.length > 0 && canCreateOrders) {
        // Always strip action blocks from visible reply, even if workflow creation fails
        reply = contentLines.join("\n");
        console.log(`[Chat Workflow] Creating workflow from chat action`);
        for (const actionJson of workflowActionLines.slice(0, 1)) {
          try {
            // Sanitize: LLMs sometimes emit trailing `}}` instead of `}` — strip extras
            let sanitizedJson = actionJson.trim();
            while (sanitizedJson.endsWith("}}") && !isValidJson(sanitizedJson)) {
              sanitizedJson = sanitizedJson.slice(0, -1);
            }
            const actionData = JSON.parse(sanitizedJson);
            const templateName = String(actionData.name || "Aiden Chat Workflow").slice(0, 200);
            const templateGoal = String(actionData.goal || actionData.name || "").slice(0, 2000);
            const templateCategory = String(actionData.category || "general");
            const steps = Array.isArray(actionData.steps) ? actionData.steps : [];
            if (steps.length === 0) {
              console.warn("[Chat Workflow] No steps defined — skipping workflow creation");
              continue;
            }

            const activeSubAgents = await storage.getActiveSubAgents();

            const template = await storage.createWorkflowTemplate({
              name: templateName,
              description: templateGoal,
              goal: templateGoal,
              category: templateCategory,
              executionMode: "autonomous",
              status: "active",
            });

            for (let i = 0; i < steps.length; i++) {
              const step = steps[i];
              const assignTo: string | null = step.assignTo || step.agent || null;
              let assignedSubAgentId: string | null = null;
              if (assignTo) {
                const lower = assignTo.toLowerCase();
                // 1. Exact name substring match (both directions)
                let matched = activeSubAgents.find(a =>
                  a.name.toLowerCase().includes(lower) ||
                  lower.includes(a.name.toLowerCase().split(" ")[0])
                );
                // 2. If no name match, try matching against agent descriptions
                if (!matched) {
                  matched = activeSubAgents.find(a =>
                    (a.description || "").toLowerCase().includes(lower) ||
                    lower.split(/\s+/).some(w => w.length > 3 && (a.description || "").toLowerCase().includes(w))
                  );
                }
                if (matched) {
                  console.log(`[Chat Workflow] Step "${step.name}" assignTo "${assignTo}" → matched agent "${matched.name}"`);
                }
                assignedSubAgentId = matched?.id || null;
              }
              const stepDesc = String(step.description || "");
              const stepName = String(step.name || `Step ${i + 1}`);
              const autoToolIds = await autoImportSkillsForDescription(stepDesc, stepName);
              const explicitToolIds: string[] = Array.isArray(step.tools) ? step.tools : [];
              const mergedToolIds = Array.from(new Set([...explicitToolIds, ...autoToolIds]));
              if (autoToolIds.length > 0) {
                console.log(`[Chat Workflow] Auto-imported ${autoToolIds.length} skill(s) for step "${stepName}": ${autoToolIds.join(", ")}`);
              }

              await storage.createWorkflowStep({
                templateId: template.id,
                stepKey: String(step.stepKey || `step_${i + 1}`),
                name: stepName.slice(0, 200),
                description: stepDesc.slice(0, 2000),
                order: Number(step.order ?? i + 1),
                stepType: "internal",
                assignedSubAgentId,
                toolIds: mergedToolIds,
              });
            }

            // ── Create parent Work Order to track this workflow ──
            // Check if a WO was already created from a T1 action block in the same response
            const existingWoAction = actionResults.find(a => a.type === "CREATE_WORK_ORDER");
            let parentWorkOrderId: string;
            let parentCorrelationId: string;

            if (existingWoAction?.workOrderId) {
              parentWorkOrderId = existingWoAction.workOrderId;
              parentCorrelationId = existingWoAction.correlationId || existingWoAction.workOrderId;
              console.log(`[Chat Workflow] Linking to existing WO ${parentWorkOrderId}`);
            } else {
              // Auto-create a tracking Work Order for this workflow
              const { gccMemory: woGcc, commitId: woCommitId } = buildGccCommit(
                {}, "new", "created_for_workflow",
                `Tracking WO for workflow "${templateName}"`,
                `Auto-created work order to track chat-triggered workflow in session ${sessionId}`,
                { submittedBy: { ...actor, source: "aiden_chat_workflow" }, chatSessionId: sessionId },
              );
              const trackingWo = await storage.createWorkOrder({
                title: `WF: ${templateName}`.slice(0, 200),
                description: templateGoal || `Workflow: ${templateName}`,
                type: "operations",
                priority: "medium",
                submittedBy: actor.actorName || "aiden",
              });
              await storage.updateWorkOrder(trackingWo.id, { gccMemory: woGcc });
              parentWorkOrderId = trackingWo.id;
              parentCorrelationId = trackingWo.correlationId;
              console.log(`[Chat Workflow] Created tracking WO ${parentWorkOrderId} for workflow "${templateName}"`);

              actionResults.push({
                type: "CREATE_WORK_ORDER",
                workOrderId: parentWorkOrderId,
                correlationId: parentCorrelationId,
                autoProcessed: true,
              });
            }

            // Start workflow with full setup (PM selection, WO linking, execution logs)
            // but skipAdvance so the chat response returns immediately.
            const execution = await startWorkflowExecution(
              template.id,
              parentWorkOrderId,
              templateGoal,
              { source: "chat", sessionId, actor: actor.actorName },
              undefined,
              { skipAdvance: true }
            );

            if (!execution) {
              console.error("[Chat Workflow] startWorkflowExecution returned null — aborting");
              continue;
            }

            // Advance the first step asynchronously so the HTTP response returns fast
            setImmediate(async () => {
              try {
                await advanceWorkflowExecution(execution.id);
              } catch (advErr) {
                console.error("[Chat Workflow] Failed to advance first step:", advErr);
                // Sync tracking WO status so the UI reflects the failure
                try {
                  await storage.updateWorkOrder(parentWorkOrderId, { status: "failed" });
                  await storage.createExecutionLog({
                    workOrderId: parentWorkOrderId,
                    tier: 1,
                    action: "Workflow Advance Failed",
                    message: `Failed to start first step of workflow "${templateName}": ${advErr instanceof Error ? advErr.message : String(advErr)}`,
                    metadata: { executionId: execution.id, error: String(advErr) },
                  });
                } catch (syncErr) {
                  console.error("[Chat Workflow] Failed to sync WO status after advance error:", syncErr);
                }
              }
            });

            actionResults.push({
              type: "EXECUTE_WORKFLOW",
              workOrderId: parentWorkOrderId,
              executionId: execution.id,
              correlationId: parentCorrelationId,
              autoProcessed: true,
            });

            reply = reply.replaceAll("{{WORKFLOW_EXECUTION_ID}}", execution.id);
            reply = reply.replaceAll("{{WORKFLOW_ID}}", execution.id);
            reply = reply.replaceAll("{{WORK_ORDER_ID}}", parentWorkOrderId);

            await storage.createExecutionLog({
              workOrderId: parentWorkOrderId,
              tier: 1,
              action: "Workflow Started via Chat",
              message: `Workflow "${templateName}" (${steps.length} steps) started from chat session ${sessionId}`,
              metadata: { source: "aiden_chat", chatSessionId: sessionId, executionId: execution.id, templateId: template.id },
            });

            console.log(`[Chat Workflow] Workflow "${templateName}" created. Execution ID: ${execution.id}. Parent WO: ${parentWorkOrderId}. Steps: ${steps.length}.`);

          } catch (wfErr: any) {
            console.error("[Chat Workflow] Failed to create/start workflow:", wfErr);
          }
        }
      }
      // ── end EXECUTE_WORKFLOW handler ────────────────────────────────────────

      reply = reply.trimEnd();

      // Encode action metadata into breadcrumb so frontend can restore trackers on page refresh
      const workflowAction = actionResults.find(a => a.type === "EXECUTE_WORKFLOW");
      const breadcrumbValue = workflowAction
        ? `assistant_reply:workflow:${JSON.stringify({ executionId: workflowAction.executionId || workflowAction.workOrderId, workOrderId: workflowAction.workOrderId })}`
        : "assistant_reply";

      const assistantMsg = await storage.addChatMessage({
        sessionId,
        role: "assistant",
        content: reply,
        gccBreadcrumb: breadcrumbValue,
      });

      const now = new Date().toISOString();
      const commitId = generateCommitId();
      const commitSummary = message.length > 100 ? message.slice(0, 97) + "..." : message;

      const commitIndex = [...(gcc["gcc.commit_index"] || [])];
      const commitTags = ["chat_exchange"];
      if (actionResults.length > 0) commitTags.push("chat_action_executed");
      commitIndex.push({
        commit_id: commitId,
        timestamp: now,
        summary: commitSummary,
        tags: commitTags,
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
          entry: `Committed exchange as ${commitId}. Aiden responded (${reply.length} chars).${actionResults.length > 0 ? ` Actions executed: ${actionResults.map(a => a.type).join(", ")}` : ""}`,
        }
      );

      if (actionResults.length > 0) {
        logEntries.push({
          timestamp: now,
          source_node: "ChatActionNode",
          entry: `Chat actions executed: ${JSON.stringify(actionResults)}`,
        });
      }

      const updatedBreadcrumbs = [...breadcrumbs, "assistant_reply", ...(actionResults.length > 0 ? ["action_executed"] : []), "committed"];
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
          "gcc.last_action": actionResults.length > 0 ? "action_executed" : "committed",
          "gcc.metadata": {
            ...(gcc["gcc.metadata"] || {}),
            status: "active",
            last_commit: now,
            ...(actionResults.length > 0 ? { lastActions: actionResults } : {}),
          },
        },
        title: session.messageCount === 0 ? message.slice(0, 80) : session.title,
      });

      res.json({ reply, messageId: assistantMsg.id, sessionId, commitId, actions: actionResults.length > 0 ? actionResults : undefined });
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

      let systemContext = await buildSystemContext(settings);
      const conversationHistory = history.slice(-10);

      const webSearchPatterns = /\b(what(?:'s| is| are| was| were| happened)|who(?:'s| is| are| was)|when(?:'s| is| did| was)|where(?:'s| is| are)|how (?:much|many|does|did|is|are|do)|latest|current|today|tomorrow|yesterday|recent|news|score|price|stock|weather|forecast|update|happening|trending|right now|as of|this week|this month)\b/i;
      const urlPattern = /https?:\/\/[^\s,\n]+/g;
      const foundUrls = message.match(urlPattern);
      const { isManagerQuestion: isManagerQ } = await import("./manager-reporting");
      const needsSearch = webSearchPatterns.test(message) && !isManagerQ(message);
      if (needsSearch || (foundUrls && foundUrls.length > 0)) {
        const { executeBuiltInWebSearch, executeBuiltInWebScrape } = await import("./tool-executor");
        const webResults: string[] = [];
        if (needsSearch) {
          try {
            const sq = message.replace(urlPattern, "").trim().slice(0, 200);
            if (sq.length >= 3) {
              const sr = await executeBuiltInWebSearch(sq);
              if (sr && sr.length > 100) webResults.push("### Web Search Results\n" + sr.slice(0, 6000));
            }
          } catch (err: any) { console.warn("[chat] Web search failed:", err.message); }
        }
        if (foundUrls && foundUrls.length > 0) {
          try {
            const sr = await executeBuiltInWebScrape(foundUrls.slice(0, 3).join(" "));
            if (sr && sr.length > 50) webResults.push("### Web Page Content\n" + sr.slice(0, 8000));
          } catch (err: any) { console.warn("[chat] Web scrape failed:", err.message); }
        }
        if (webResults.length > 0) {
          systemContext += "\n\n=== LIVE WEB RESEARCH (retrieved just now — use this data to answer accurately) ===\n" + webResults.join("\n\n");
        }
      }

      const reply = await chatWithAiden(settings, message, conversationHistory, systemContext);
      res.json({ reply });
    } catch (err: any) {
      console.error("Chat error:", err.message);
      res.status(500).json({ message: `Aiden encountered an error: ${err.message}` });
    }
  });

  // ==================== GCC Memory Retrieval ====================

  app.get("/api/gcc/session/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const session = await storage.getChatSession(req.params.id);
      if (!session) return res.status(404).json({ message: "Session not found" });
      const gcc = (session.gccMemory || {}) as Record<string, any>;
      res.json({
        entityType: "chat_session",
        entityId: session.id,
        correlationId: session.correlationId,
        projectId: gcc["gcc.project_id"],
        branch: gcc["gcc.branch"] || "main",
        tier: gcc["gcc.tier"] || "tier1",
        lastAction: gcc["gcc.last_action"] || gcc.lastAction,
        lastCommitId: gcc["gcc.last_commit_id"],
        lastCommitSummary: gcc["gcc.last_commit_summary"],
        commitCount: gcc["gcc.context_commit_count"] || 0,
        breadcrumbs: gcc["gcc.breadcrumbs"] || gcc.breadcrumbs || [],
        commitIndex: gcc["gcc.commit_index"] || [],
        log: gcc["gcc.log"] || [],
        metadata: gcc["gcc.metadata"] || {},
        raw: gcc,
      });
    } catch (err) {
      res.status(500).json({ message: "Failed to retrieve GCC memory" });
    }
  });

  app.get("/api/gcc/workorder/:id", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      const gcc = (order.gccMemory || {}) as Record<string, any>;
      res.json({
        entityType: "work_order",
        entityId: order.id,
        correlationId: order.correlationId,
        status: order.status,
        projectId: gcc["gcc.project_id"],
        branch: gcc["gcc.branch"] || "main",
        tier: gcc["gcc.tier"] || "tier1",
        lastAction: gcc["gcc.last_action"] || gcc.lastAction,
        lastCommitId: gcc["gcc.last_commit_id"],
        lastCommitSummary: gcc["gcc.last_commit_summary"],
        commitCount: gcc["gcc.context_commit_count"] || 0,
        breadcrumbs: gcc["gcc.breadcrumbs"] || gcc.breadcrumbs || [],
        commitIndex: gcc["gcc.commit_index"] || [],
        log: gcc["gcc.log"] || [],
        metadata: gcc["gcc.metadata"] || {},
        raw: gcc,
      });
    } catch (err) {
      res.status(500).json({ message: "Failed to retrieve GCC memory" });
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
          executionProfile: "safe",
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

  // ==================== Execution Profiles (Phase 3) ====================

  app.get("/api/execution-profiles", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const { getAllProfiles, resolveProfile } = await import("./run-context");
      const opSettings = await storage.getOperationalSettings().catch(() => null);
      const active = resolveProfile(opSettings?.executionProfile);
      res.json({
        active: active.name,
        profiles: getAllProfiles(),
      });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch execution profiles" });
    }
  });

  app.put("/api/execution-profiles", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const { profile } = req.body;
      const validProfiles = ["safe", "balanced", "fast"];
      if (!profile || !validProfiles.includes(profile)) {
        return res.status(400).json({ message: `Invalid profile. Must be one of: ${validProfiles.join(", ")}` });
      }
      const settings = await storage.upsertOperationalSettings({ executionProfile: profile } as any);
      const { resolveProfile } = await import("./run-context");
      const resolved = resolveProfile(settings.executionProfile);

      const actor = getActor(req);
      await storage.createExecutionLog({
        workOrderId: "system",
        tier: 0,
        action: "profile_change",
        message: `Execution profile changed to "${profile}" by ${actor.actorName}`,
        metadata: { profile, actor },
      });

      console.log(`[perf] Execution profile changed to "${profile}" by ${actor.actorName}`);
      res.json({ active: resolved.name, profile: resolved });
    } catch (err) {
      res.status(500).json({ message: "Failed to update execution profile" });
    }
  });

  // ==================== Manager Reporting ====================

  app.get("/api/manager/report", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const window = (req.query.window as string) || "today";
      const customStart = req.query.start as string | undefined;
      const customEnd = req.query.end as string | undefined;

      if (!["today", "last_24h", "custom"].includes(window)) {
        return res.status(400).json({ message: "Invalid window. Use: today, last_24h, or custom (with start/end params)" });
      }

      const { generateManagerReport } = await import("./manager-reporting");
      const report = await generateManagerReport(window as any, customStart, customEnd);
      return res.json(report);
    } catch (err: any) {
      console.error("Manager report error:", err.message);
      return res.status(500).json({ message: "Failed to generate report" });
    }
  });

  // ==================== Gamma Settings ====================

  app.get("/api/gamma-settings", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const settings = await storage.getGammaSettings();
      if (!settings) {
        return res.json({
          settings: {
            id: "default",
            enabled: false,
            mode: "generate",
            themeId: null,
            gammaId: null,
            fallbackToLocal: true,
            numCards: null,
            updatedAt: new Date().toISOString(),
            updatedBy: "system",
          },
          apiKeyConfigured: !!process.env.GAMMA_API_KEY,
        });
      }
      res.json({ settings, apiKeyConfigured: !!process.env.GAMMA_API_KEY });
    } catch (err) {
      res.status(500).json({ message: "Failed to fetch Gamma settings" });
    }
  });

  app.put("/api/gamma-settings", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const actor = getActor(req);
      const parsed = insertGammaSettingsSchema.safeParse({ ...req.body, updatedBy: actor.actorName });
      if (!parsed.success) {
        return res.status(400).json({ message: "Invalid settings", errors: parsed.error.errors });
      }
      const settings = await storage.upsertGammaSettings(parsed.data);
      res.json({ settings, apiKeyConfigured: !!process.env.GAMMA_API_KEY });
    } catch (err) {
      res.status(500).json({ message: "Failed to update Gamma settings" });
    }
  });

  app.post("/api/gamma-settings/test", isAuth, requireRole("admin"), async (_req, res) => {
    try {
      const { testGammaConnection } = await import("./gamma-client");
      const result = await testGammaConnection();
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ success: false, message: err.message });
    }
  });

  // ==================== Gamma Template Registry ====================

  app.get("/api/gamma-templates", isAuth, requireRole("viewer"), async (_req, res) => {
    try {
      const templates = await storage.getGammaTemplates();
      res.json(templates);
    } catch (err: any) {
      res.status(500).json({ message: "Failed to fetch Gamma templates" });
    }
  });

  app.get("/api/gamma-templates/:key", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const entry = await storage.getGammaTemplateByKey(req.params.key);
      if (!entry) return res.status(404).json({ message: "Template not found" });
      res.json(entry);
    } catch (err: any) {
      res.status(500).json({ message: "Failed to fetch Gamma template" });
    }
  });

  app.post("/api/gamma-templates", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const { templateKey, gammaId, name, description, outputFormat, contentContract, mode, status, owner, allowedWoTypes } = req.body;
      if (!templateKey || !gammaId || !name) {
        return res.status(400).json({ message: "templateKey, gammaId, and name are required" });
      }
      const entry = await storage.createGammaTemplate({
        templateKey, gammaId, name,
        description: description || null,
        outputFormat: outputFormat || "pptx",
        contentContract: contentContract || null,
        mode: mode || "template_locked",
        status: status || "approved",
        owner: owner || null,
        allowedWoTypes: allowedWoTypes || null,
      });
      res.status(201).json(entry);
    } catch (err: any) {
      if (err.message?.includes("unique") || err.code === "23505") {
        return res.status(409).json({ message: `Template key "${req.body.templateKey}" already exists` });
      }
      res.status(500).json({ message: "Failed to create Gamma template" });
    }
  });

  app.put("/api/gamma-templates/:id", isAuth, requireRole("admin"), async (req, res) => {
    try {
      const updated = await storage.updateGammaTemplate(req.params.id, req.body);
      if (!updated) return res.status(404).json({ message: "Template not found" });
      res.json(updated);
    } catch (err: any) {
      res.status(500).json({ message: "Failed to update Gamma template" });
    }
  });

  // ==================== Gamma Generation Records ====================

  app.get("/api/gamma-generations", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const workOrderId = req.query.workOrderId as string;
      if (!workOrderId) return res.status(400).json({ message: "workOrderId query parameter is required" });
      const records = await storage.getGammaGenerationRecords(workOrderId);
      res.json(records);
    } catch (err: any) {
      res.status(500).json({ message: "Failed to fetch generation records" });
    }
  });

  // ==================== Gamma Candidate Review ====================

  // List candidates for a work order (all statuses, grouped by candidateGroup)
  app.get("/api/work-orders/:id/candidates", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const allRecords = await storage.getGammaGenerationRecords(req.params.id);
      const candidates = allRecords.filter(r => r.candidateStatus != null);

      // Group by candidateGroup for batch display
      const groups: Record<string, typeof candidates> = {};
      for (const c of candidates) {
        const group = c.candidateGroup || "_ungrouped";
        if (!groups[group]) groups[group] = [];
        groups[group].push(c);
      }

      res.json({ candidates, groups, activeCandidates: candidates.filter(c => c.candidateStatus === "candidate").length });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to fetch candidates" });
    }
  });

  // Select a candidate — marks it as selected, rejects others, resumes WO completion
  app.post("/api/work-orders/:id/candidates/:recordId/select", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const workOrderId = req.params.id;
      const order = await storage.getWorkOrder(workOrderId);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      if (order.status !== "awaiting_operator") return res.status(400).json({ message: "Work order is not awaiting operator review" });

      // Pre-flight: verify candidate exists and file is present BEFORE mutating state
      const fs = await import("fs");
      const path = await import("path");
      const candidateRecord = await storage.getGammaGenerationRecord(req.params.recordId);
      if (!candidateRecord || candidateRecord.workOrderId !== workOrderId) {
        return res.status(404).json({ message: "Candidate not found or does not belong to this work order" });
      }
      if (!candidateRecord.artifactFiledPath || !fs.existsSync(candidateRecord.artifactFiledPath)) {
        return res.status(409).json({ message: "Candidate file no longer exists on disk. Selection aborted — work order remains in awaiting_operator." });
      }

      const selectedBy = (req as any).user?.username || "operator";
      const selected = await storage.selectGammaCandidate(workOrderId, req.params.recordId, selectedBy);
      if (!selected) return res.status(404).json({ message: "Candidate selection failed" });

      // Copy selected candidate to a temp path for filing (so filing deletes the copy, not the durable original)
      // artifactFiledPath was validated in pre-flight above
      const artifactPath = selected.artifactFiledPath!;
      const ext = selected.exportFormat === "pdf" ? "pdf" : "pptx";
      const tmpCopy = path.join(path.dirname(artifactPath), `selected_${selected.id.slice(0, 8)}.${ext}`);
      fs.copyFileSync(artifactPath, tmpCopy);

      const tier2 = order.tier2Result as any;
      if (tier2?.output) {
        const mime = selected.exportFormat === "pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.presentationml.presentation";
        tier2.output.postProcessedFile = {
          path: tmpCopy, // filing deletes this copy, original stays for download
          mimeType: mime,
          size: selected.fileSize || fs.statSync(tmpCopy).size,
        };
      }
      await storage.updateWorkOrder(workOrderId, { tier2Result: tier2 });

      await storage.createExecutionLog({
        workOrderId,
        tier: 1,
        action: "Operator: Candidate Selected",
        message: `Operator selected candidate ${selected.id} (${selected.exportFormat}, ${selected.templateKey}). Resuming completion flow.`,
        metadata: { selectedRecordId: selected.id, selectedBy, exportFormat: selected.exportFormat, templateKey: selected.templateKey },
      });

      // Resume completion: set status to completed and trigger filing
      const completedOrder = await storage.updateWorkOrder(workOrderId, { status: "completed" });
      if (completedOrder) {
        const { fileWorkOrderOutput } = await import("./workspace-filing");
        fileWorkOrderOutput(completedOrder).catch(err => console.error("Filing error after candidate selection:", err.message));
      }

      res.json({ message: "Candidate selected", selected, workOrder: completedOrder });
    } catch (err: any) {
      res.status(500).json({ message: `Failed to select candidate: ${err.message}` });
    }
  });

  // Reject a single candidate
  app.post("/api/work-orders/:id/candidates/:recordId/reject", isAuth, requireRole("operator"), async (req, res) => {
    try {
      // Ownership-validated: rejectGammaCandidate checks recordId belongs to this workOrderId
      const rejected = await storage.rejectGammaCandidate(req.params.id, req.params.recordId);
      if (!rejected) return res.status(404).json({ message: "Candidate not found or does not belong to this work order" });
      res.json({ message: "Candidate rejected", rejected });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to reject candidate" });
    }
  });

  // Reject all candidates
  app.post("/api/work-orders/:id/candidates/reject-all", isAuth, requireRole("operator"), async (req, res) => {
    try {
      await storage.rejectAllGammaCandidates(req.params.id);
      res.json({ message: "All candidates rejected" });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to reject candidates" });
    }
  });

  // Cancel a candidate-review work order (escape hatch when all candidates rejected)
  app.post("/api/work-orders/:id/candidates/cancel", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      if (order.status !== "awaiting_operator") return res.status(400).json({ message: "Work order is not awaiting operator review" });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Operator: Candidate Review Cancelled",
        message: "Operator cancelled work order during candidate review. No deliverable selected.",
        metadata: { cancelledBy: (req as any).user?.username || "operator" },
      });

      const updated = await storage.updateWorkOrder(req.params.id, { status: "cancelled" as any });
      res.json({ message: "Work order cancelled", workOrder: updated });
    } catch (err: any) {
      res.status(500).json({ message: `Failed to cancel work order: ${err.message}` });
    }
  });

  // Request more candidates — re-runs PocketFlow for another generation cycle
  app.post("/api/work-orders/:id/candidates/request-more", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const order = await storage.getWorkOrder(req.params.id);
      if (!order) return res.status(404).json({ message: "Work order not found" });
      if (order.status !== "awaiting_operator") return res.status(400).json({ message: "Work order is not awaiting operator review" });

      await storage.createExecutionLog({
        workOrderId: req.params.id,
        tier: 1,
        action: "Operator: Request More Candidates",
        message: "Operator requested additional Gamma candidate generation. Re-processing work order.",
        metadata: {},
      });

      // Set back to pending so processWorkOrder picks it up again
      await storage.updateWorkOrder(req.params.id, { status: "pending" });
      const { processWorkOrder } = await import("./orchestration");
      processWorkOrder(req.params.id).catch(err => console.error("Re-process error:", err.message));

      res.json({ message: "Requesting more candidates — work order re-queued for processing" });
    } catch (err: any) {
      res.status(500).json({ message: `Failed to request more candidates: ${err.message}` });
    }
  });

  // Download/preview a candidate file (ownership-scoped to work order)
  app.get("/api/work-orders/:id/candidates/:recordId/download", isAuth, requireRole("viewer"), async (req, res) => {
    try {
      const record = await storage.getGammaGenerationRecord(req.params.recordId);
      if (!record || record.workOrderId !== req.params.id) return res.status(404).json({ message: "Candidate not found or does not belong to this work order" });
      if (!record.artifactFiledPath) return res.status(404).json({ message: "Candidate file path not recorded" });

      const fs = await import("fs");
      if (!fs.existsSync(record.artifactFiledPath)) return res.status(404).json({ message: "Candidate file no longer exists on disk" });

      const mime = record.exportFormat === "pdf" ? "application/pdf" : "application/vnd.openxmlformats-officedocument.presentationml.presentation";
      const ext = record.exportFormat === "pdf" ? "pdf" : "pptx";
      res.setHeader("Content-Type", mime);
      res.setHeader("Content-Disposition", `attachment; filename="candidate_${record.id.slice(0, 8)}.${ext}"`);
      fs.createReadStream(record.artifactFiledPath).pipe(res);
    } catch (err: any) {
      res.status(500).json({ message: "Failed to download candidate" });
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

      // If the work order is already completed, trigger workspace filing now
      if (workOrder.status === "completed") {
        try {
          const refreshed = await storage.getWorkOrder(approval.workOrderId);
          if (refreshed) {
            const { fileWorkOrderOutput } = await import("./workspace-filing");
            await fileWorkOrderOutput(refreshed);
          }
        } catch (fileErr: any) {
          console.error("Workspace filing after approval failed:", fileErr.message);
        }
      }

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

  app.get("/api/images/:placeholderId", isAuth, async (req: Request, res: Response) => {
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

  app.get("/api/images/:placeholderId/meta", isAuth, async (req: Request, res: Response) => {
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

  // ==================== Publish / Public Preview ====================

  /**
   * POST /api/artifacts/:id/publish — Publish an HTML artifact to GitHub Pages.
   * Body: { slug?: string, policy?: "public" | "unlisted" }
   */
  app.post("/api/artifacts/:id/publish", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      if (artifact.mimeType !== "text/html") {
        return res.status(400).json({ message: "Only HTML artifacts can be published" });
      }
      if (!artifact.content) {
        return res.status(400).json({ message: "Artifact has no content" });
      }

      const slug = req.body.slug || slugify(artifact.name || artifact.id);
      if (!isValidSlug(slug)) {
        return res.status(400).json({ message: "Invalid slug. Use 3-128 chars: lowercase, numbers, hyphens." });
      }

      // Check slug uniqueness
      const existing = await storage.getArtifactBySlug(slug);
      if (existing && existing.id !== artifact.id) {
        return res.status(409).json({ message: `Slug "${slug}" is already in use by another artifact` });
      }

      const policy = req.body.policy || "public";
      if (!["public", "unlisted"].includes(policy)) {
        return res.status(400).json({ message: "Policy must be 'public' or 'unlisted'" });
      }

      // Push to GitHub Pages
      const result = await publishToGitHubPages(slug, artifact.content, `Publish: ${artifact.name || slug}`);
      if (!result.success) {
        return res.status(502).json({ message: "Failed to publish to GitHub Pages", error: result.error });
      }

      // Update artifact record
      const updated = await storage.updateArtifact(artifact.id, {
        publishedSlug: slug,
        publishedAt: new Date(),
        publishedUrl: result.publicUrl!,
        publishPolicy: policy,
      });

      res.json({
        message: "Published successfully",
        publicUrl: result.publicUrl,
        slug,
        policy,
        artifact: updated,
      });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to publish artifact", error: err.message });
    }
  });

  /**
   * POST /api/artifacts/:id/unpublish — Remove from GitHub Pages and mark private.
   */
  app.post("/api/artifacts/:id/unpublish", isAuth, requireRole("operator"), async (req, res) => {
    try {
      const artifact = await storage.getArtifact(req.params.id);
      if (!artifact) return res.status(404).json({ message: "Artifact not found" });
      if (!artifact.publishedSlug) {
        return res.status(400).json({ message: "Artifact is not published" });
      }

      const result = await unpublishFromGitHubPages(artifact.publishedSlug);
      if (!result.success) {
        return res.status(502).json({ message: "Failed to unpublish from GitHub Pages", error: result.error });
      }

      const updated = await storage.updateArtifact(artifact.id, {
        publishedSlug: null as any,
        publishedAt: null as any,
        publishedUrl: null as any,
        publishPolicy: "private",
      });

      res.json({ message: "Unpublished successfully", artifact: updated });
    } catch (err: any) {
      res.status(500).json({ message: "Failed to unpublish artifact", error: err.message });
    }
  });

  /**
   * GET /p/:slug — Public unauthenticated route. Serves published HTML directly.
   * This is the shareable link: https://your-domain.com/p/my-landing-page
   * Falls back to local DB serving (useful before GitHub Pages propagates, or for unlisted).
   */
  app.get("/p/:slug", async (req, res) => {
    try {
      const artifact = await storage.getArtifactBySlug(req.params.slug);
      if (!artifact || !artifact.publishedAt || !artifact.content) {
        return res.status(404).send("<!DOCTYPE html><html><body><h1>404 — Not Found</h1><p>This deliverable does not exist or has been unpublished.</p></body></html>");
      }

      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.setHeader("Cache-Control", "public, max-age=300");
      res.send(artifact.content);
    } catch (err) {
      res.status(500).send("Internal server error");
    }
  });

  return httpServer;
}

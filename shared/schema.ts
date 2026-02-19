import { sql } from "drizzle-orm";
import { pgTable, text, varchar, timestamp, jsonb, integer, boolean } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod";

export const workOrders = pgTable("work_orders", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  correlationId: varchar("correlation_id").notNull().default(sql`gen_random_uuid()`),
  title: text("title").notNull(),
  description: text("description").notNull(),
  type: text("type").notNull().default("standard"),
  priority: text("priority").notNull().default("medium"),
  status: text("status").notNull().default("pending"),
  tier1Result: jsonb("tier1_result"),
  tier2Result: jsonb("tier2_result"),
  gccMemory: jsonb("gcc_memory").default(sql`'{}'::jsonb`),
  bdmMarker: jsonb("bdm_marker"),
  submittedBy: text("submitted_by").default("system"),
  createdAt: timestamp("created_at").defaultNow().notNull(),
  updatedAt: timestamp("updated_at").defaultNow().notNull(),
});

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
  tier1Result: true,
  tier2Result: true,
  gccMemory: true,
  bdmMarker: true,
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
    `You are Aiden, an intelligent work order orchestration engine. You operate within a 2-tier architecture:

Tier 1 (Manager): You evaluate incoming work orders against policy rules. You decide whether to approve or block them, and which handler to route approved orders to.

Tier 2 (Worker): You validate the work order schema and execute the work. You may emit a BDM (Blocked Decision Marker) if execution cannot proceed.

Rules:
- Critical deployments should be blocked at Tier 1 for manual review
- Critical incidents should be carefully evaluated - block if escalation is needed
- Always provide clear reasoning for your decisions
- Never allow Tier 2 to Tier 2 direct chaining
- Use GCC memory for routing context and correlation IDs only`
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

export const users = pgTable("users", {
  id: varchar("id").primaryKey().default(sql`gen_random_uuid()`),
  username: text("username").notNull().unique(),
  password: text("password").notNull(),
});

export const insertUserSchema = createInsertSchema(users).pick({
  username: true,
  password: true,
});

export type InsertUser = z.infer<typeof insertUserSchema>;
export type User = typeof users.$inferSelect;

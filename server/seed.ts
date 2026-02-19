import { storage } from "./storage";
import { db } from "./db";
import { workOrders } from "@shared/schema";
import { sql } from "drizzle-orm";

export async function seedDatabase() {
  const existing = await db.select({ count: sql<number>`count(*)` }).from(workOrders);
  if (Number(existing[0].count) > 0) return;

  const orders = [
    {
      title: "Deploy API gateway v2.4.1",
      description: "Rolling deployment of the API gateway to version 2.4.1 across staging and production clusters. Includes new rate limiting middleware and updated TLS certificates.",
      type: "deployment",
      priority: "high",
      submittedBy: "platform-team",
    },
    {
      title: "Database index optimization",
      description: "Add composite indexes to the work_orders table for faster queries on status and priority columns. Expected to reduce query latency by 40%.",
      type: "maintenance",
      priority: "medium",
      submittedBy: "dba-team",
    },
    {
      title: "Investigate elevated error rates on auth service",
      description: "Auth service showing 5% error rate increase over the past 2 hours. Possible connection pool exhaustion. Needs immediate triage and root cause analysis.",
      type: "incident",
      priority: "high",
      submittedBy: "oncall-engineer",
    },
    {
      title: "Update webhook signature validation",
      description: "Migrate webhook signature validation from HMAC-SHA256 to HMAC-SHA512 as part of security hardening initiative. All channel connectors need updating.",
      type: "change_request",
      priority: "medium",
      submittedBy: "security-team",
    },
    {
      title: "Provision staging environment for QA",
      description: "Set up a fresh staging environment with latest schema changes for the QA team to run regression tests before the next release cycle.",
      type: "standard",
      priority: "low",
      submittedBy: "qa-lead",
    },
  ];

  for (const order of orders) {
    await storage.createWorkOrder(order);
  }

  console.log("Database seeded with sample work orders");
}

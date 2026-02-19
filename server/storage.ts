import {
  type WorkOrder,
  type InsertWorkOrder,
  type ExecutionLog,
  type InsertExecutionLog,
  type User,
  type InsertUser,
  workOrders,
  executionLogs,
  users,
} from "@shared/schema";
import { db } from "./db";
import { eq, desc, sql } from "drizzle-orm";

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
}

export const storage = new DatabaseStorage();

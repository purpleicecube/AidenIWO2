import { users, clientMemberships, type User, type UpsertUser } from "@shared/models/auth";
import { db } from "../../db";
import { eq, count, desc } from "drizzle-orm";

/**
 * Node Storage Adaptation Darkmode (2026-05-11) — IWO2→IWO3 auth-layer
 * adaptation. `users.role` no longer exists in IWO3; roles live
 * per-tenant in `client_memberships`. `setUserRole` writes/updates the
 * membership row for a single-tenant V1 (the operator's first
 * client_membership wins). `upsertUser` no longer touches
 * first_name/last_name/profile_image_url (those columns were removed
 * in the IWO3 Loop 1 users redesign).
 */

export interface IAuthStorage {
  getUser(id: string): Promise<User | undefined>;
  getUserByEmail(email: string): Promise<User | undefined>;
  upsertUser(user: UpsertUser): Promise<User>;
  setUserRole(id: string, role: string): Promise<void>;
  /**
   * Path A-prime helper: derive the operator's effective role across
   * all their `client_memberships` rows. Returns the highest-privilege
   * role found, or "viewer" if none. Used by `server/routes.ts`
   * `requireRole` to gate sandbox + admin routes.
   */
  getUserEffectiveRole(id: string): Promise<string>;
}

const ROLE_RANK: Record<string, number> = {
  owner: 5,
  admin: 4,
  agent_system: 3,
  operator: 3,
  reviewer: 2,
  viewer: 1,
};

class AuthStorage implements IAuthStorage {
  async getUser(id: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.id, id));
    return user;
  }

  async getUserByEmail(email: string): Promise<User | undefined> {
    const [user] = await db.select().from(users).where(eq(users.email, email));
    return user;
  }

  async setUserRole(id: string, role: string): Promise<void> {
    // IWO3: role lives in client_memberships, not on users.
    // V1 single-tenant assumption: update the FIRST membership row,
    // or insert one against the first available client if none exists.
    // Long-term multi-tenant role surgery is a Path B follow-on.
    const [existing] = await db
      .select()
      .from(clientMemberships)
      .where(eq(clientMemberships.userId, id))
      .orderBy(desc(clientMemberships.createdAt))
      .limit(1);
    if (existing) {
      await db
        .update(clientMemberships)
        .set({ role, updatedAt: new Date() })
        .where(eq(clientMemberships.id, existing.id));
    } else {
      console.warn(
        `[authStorage.setUserRole] user ${id} has no client_memberships row — role '${role}' not persisted (membership-creation deferred to a follow-on loop)`
      );
    }
  }

  async getUserEffectiveRole(id: string): Promise<string> {
    const rows = await db
      .select({ role: clientMemberships.role })
      .from(clientMemberships)
      .where(eq(clientMemberships.userId, id));
    if (rows.length === 0) return "viewer";
    let best = "viewer";
    let bestRank = ROLE_RANK[best] ?? 0;
    for (const r of rows) {
      const rank = ROLE_RANK[r.role] ?? 0;
      if (rank > bestRank) {
        best = r.role;
        bestRank = rank;
      }
    }
    return best;
  }

  async upsertUser(userData: UpsertUser): Promise<User> {
    // IWO3-shape adaptation: only persist columns that exist on the
    // IWO3 users table. Caller may still supply firstName/lastName/
    // profileImageUrl (legacy callers); we map them into displayName
    // on a best-effort basis.
    const incoming = userData as UpsertUser & {
      firstName?: string | null;
      lastName?: string | null;
      profileImageUrl?: string | null;
    };
    const composedName =
      [incoming.firstName, incoming.lastName]
        .filter((s) => typeof s === "string" && s.length > 0)
        .join(" ") || null;
    const displayName = incoming.displayName ?? composedName;

    const existing = userData.id ? await this.getUser(userData.id) : undefined;
    if (existing) {
      const [user] = await db
        .update(users)
        .set({
          email: userData.email,
          displayName,
          updatedAt: new Date(),
        })
        .where(eq(users.id, userData.id!))
        .returning();
      return user;
    }

    const [user] = await db
      .insert(users)
      .values({
        id: userData.id,
        email: userData.email,
        displayName,
        passwordHash: userData.passwordHash,
        status: userData.status ?? "active",
      })
      .returning();
    return user;
  }
}

export const authStorage = new AuthStorage();

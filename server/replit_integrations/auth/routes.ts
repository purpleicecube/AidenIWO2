import type { Express } from "express";
import { authStorage } from "./storage";
import { isAuthenticated } from "./replitAuth";

const IWO3_ROLE_TO_LEGACY: Record<string, "admin" | "operator" | "viewer"> = {
  owner: "admin",
  admin: "admin",
  operator: "operator",
  agent_system: "operator",
  reviewer: "viewer",
  viewer: "viewer",
};

export function registerAuthRoutes(app: Express): void {
  app.get("/api/auth/user", isAuthenticated, async (req: any, res) => {
    try {
      const userId = req.user.claims.sub;
      const user = await authStorage.getUser(userId);
      if (!user) {
        return res.status(404).json({ message: "User not found" });
      }
      const effectiveRole = await authStorage.getUserEffectiveRole(userId);
      const legacyRole = IWO3_ROLE_TO_LEGACY[effectiveRole] ?? "viewer";
      res.json({ ...user, role: legacyRole, effectiveRole });
    } catch (error) {
      console.error("Error fetching user:", error);
      res.status(500).json({ message: "Failed to fetch user" });
    }
  });

  app.get("/api/auth/success", (req, res) => {
    res.send(`<!DOCTYPE html>
<html><head><title>Login Successful</title>
<style>body{font-family:system-ui,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;background:#0f172a;color:#e2e8f0;}
.card{text-align:center;padding:3rem;border-radius:1rem;background:#1e293b;box-shadow:0 4px 24px rgba(0,0,0,.3);}
h1{color:#22c55e;margin-bottom:.5rem;}
p{color:#94a3b8;margin-bottom:1.5rem;}
.hint{font-size:.85rem;color:#64748b;}</style></head>
<body><div class="card">
<h1>Login Successful</h1>
<p>You are now signed in. You can close this tab.</p>
<p class="hint">Your app will update automatically.</p>
</div></body></html>`);
  });
}

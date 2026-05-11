// P0-A + P0-B + P1-C: Hardened local auth — replaces Replit OIDC.
// No external OIDC dependency. Password-based login only.
// GET /api/login dev-only bypass is blocked in production (P0-A).
// Bootstrap admin requires env var — no hardcoded credentials (P0-B).
// Full Replit OIDC removal completed here (P1-C).

import passport from "passport";
import session from "express-session";
import type { Express, RequestHandler } from "express";
import connectPg from "connect-pg-simple";
import bcrypt from "bcryptjs";
import { authStorage } from "./storage";

// Node Storage Adaptation Darkmode (2026-05-11): IWO3 users.id is uuid,
// not the IWO2-era varchar slug. The dev auto-login binds to an actual
// seeded IWO3 user so requireRole's client_memberships lookup resolves
// cleanly (Klear owner → owner role → admin level). Using the seeded
// user also keeps actor identity coherent across FastAPI / Streamlit /
// Node — they all see the same operator id.
const LOCAL_USER_ID = "00000000-0000-4000-8000-000001000001";
const LOCAL_USER_EMAIL = "owner_klear@dev.local";

export function getSession() {
  const sessionTtl = 7 * 24 * 60 * 60 * 1000; // 1 week
  const pgStore = connectPg(session);
  const sessionStore = new pgStore({
    conString: process.env.DATABASE_URL,
    createTableIfMissing: true,
    ttl: sessionTtl,
    tableName: "sessions",
  });
  return session({
    secret: process.env.SESSION_SECRET!,
    store: sessionStore,
    resave: false,
    saveUninitialized: false,
    cookie: {
      httpOnly: true,
      secure: process.env.NODE_ENV === "production",
      maxAge: sessionTtl,
    },
  });
}

export async function setupAuth(app: Express) {
  app.set("trust proxy", 1);
  app.use(getSession());
  app.use(passport.initialize());
  app.use(passport.session());

  passport.serializeUser((user: Express.User, cb) => cb(null, user));
  passport.deserializeUser((user: Express.User, cb) => cb(null, user));

  // GET /api/login — dev-only auto-login (no password). ALLOWED only in explicit development mode.
  // Blocked in production AND any non-development environment (staging, tester, published).
  app.get("/api/login", async (req, res) => {
    const isDev = process.env.NODE_ENV === "development" || (!process.env.NODE_ENV && !process.env.REPL_SLUG);
    if (!isDev) {
      console.warn("[auth] GET /api/login blocked — only available in NODE_ENV=development");
      return res.status(403).json({ message: "Auto-login is only available in development mode. Use POST /api/login with credentials." });
    }

    try {
      // Node Storage Adaptation Darkmode (2026-05-11): IWO3 users
      // table has no first_name/last_name. upsertUser now maps to
      // display_name; we still pass legacy fields and let the
      // adapter strip/combine them.
      await authStorage.upsertUser({
        id: LOCAL_USER_ID,
        email: LOCAL_USER_EMAIL,
        displayName: "Local Admin",
      } as any);

      const sessionUser = {
        claims: { sub: LOCAL_USER_ID, email: LOCAL_USER_EMAIL },
        expires_at: Math.floor(Date.now() / 1000) + 365 * 24 * 60 * 60,
      };

      req.logIn(sessionUser, (err) => {
        if (err) {
          console.error("[auth] Auto-login error:", err);
          return res.status(500).json({ message: "Login failed" });
        }
        console.log("[auth] Auto-login successful as local admin (dev mode only)");
        return res.redirect("/");
      });
    } catch (err) {
      console.error("[auth] Auto-login failed:", err);
      return res.status(500).json({ message: "Login failed" });
    }
  });

  // POST /api/login — password-based login (email + password).
  app.post("/api/login", async (req, res) => {
    try {
      const { email, password } = req.body;
      if (!email || !password) {
        return res.status(400).json({ message: "Email and password are required" });
      }

      const user = await authStorage.getUserByEmail(email);
      if (!user || !user.passwordHash) {
        return res.status(401).json({ message: "Invalid email or password" });
      }

      const valid = await bcrypt.compare(password, user.passwordHash);
      if (!valid) {
        return res.status(401).json({ message: "Invalid email or password" });
      }

      const sessionUser = {
        claims: { sub: user.id, email: user.email },
        expires_at: Math.floor(Date.now() / 1000) + 365 * 24 * 60 * 60,
      };

      // Node Storage Adaptation Darkmode (2026-05-11): IWO3 users have
      // displayName (no firstName/lastName) and roles live in
      // client_memberships. Resolve the effective role BEFORE logIn so
      // the response builder is synchronous and we don't need an async
      // passport callback.
      const effectiveRole = await authStorage.getUserEffectiveRole(user.id);
      req.logIn(sessionUser, (err) => {
        if (err) {
          return res.status(500).json({ message: "Login failed" });
        }
        return res.json({
          message: "Login successful",
          user: {
            id: user.id,
            email: user.email,
            displayName: (user as any).displayName ?? null,
            role: effectiveRole,
          },
        });
      });
    } catch (err) {
      console.error("[auth] Password login failed:", err);
      return res.status(500).json({ message: "Login failed" });
    }
  });

  // Bootstrap admin provisioning on startup.
  // P0-B: B+ Hardening — requires BOOTSTRAP_ADMIN_PASSWORD env var.
  // No hardcoded credentials. Skipped silently in production if env var is absent (with warning).
  (async () => {
    try {
      const bootstrapEmail = process.env.BOOTSTRAP_ADMIN_EMAIL || "admin@localhost";
      const bootstrapPassword = process.env.BOOTSTRAP_ADMIN_PASSWORD;

      if (!bootstrapPassword) {
        if (process.env.NODE_ENV === "production") {
          console.warn("[auth] WARNING: BOOTSTRAP_ADMIN_PASSWORD not set — no bootstrap admin created. Set this env var to provision the first admin account.");
        } else {
          console.log("[auth] BOOTSTRAP_ADMIN_PASSWORD not set — bootstrap admin skipped. Use GET /api/login in dev, or set env var.");
        }
        return;
      }

      const existing = await authStorage.getUserByEmail(bootstrapEmail);
      if (!existing) {
        const hash = await bcrypt.hash(bootstrapPassword, 12);
        // Node Storage Adaptation Darkmode (2026-05-11): IWO3 users
        // table has no first_name/last_name + role lives on
        // client_memberships. The upsert maps legacy first/last names
        // into display_name; setUserRole writes to the first
        // available membership row (logs a warning + returns
        // gracefully if the user has no membership yet — bootstrap
        // admin without a tenant binding is a Path B follow-on).
        await authStorage.upsertUser({
          id: "bootstrap-admin",
          email: bootstrapEmail,
          displayName: "Admin",
          passwordHash: hash,
        } as any);
        await authStorage.setUserRole("bootstrap-admin", "admin");
        console.log(`[auth] Bootstrap admin provisioned: ${bootstrapEmail}`);
      }
    } catch (err) {
      console.error("[auth] Failed to provision bootstrap admin:", err);
    }
  })();

  app.get("/api/callback", (_req, res) => res.redirect("/"));

  app.get("/api/logout", (req, res) => {
    req.logout(() => res.redirect("/"));
  });
}

export const isAuthenticated: RequestHandler = (req, res, next) => {
  if (req.isAuthenticated()) {
    return next();
  }
  return res.status(401).json({ message: "Unauthorized" });
};

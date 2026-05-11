/**
 * Express → FastAPI proxy middleware — Aiden Evaluator Parity Loop (2026-05-11).
 *
 * INTENTIONALLY EVALUATOR-BOUNDED.
 *
 * The IWO2-inherited React work-order detail page is the primary
 * operator evaluator surface. Its mutation paths (`POST /api/work-orders/:id/reopen`,
 * etc.) historically hit Express handlers wired to the IWO2-shape
 * Node `server/storage.ts` which 500s on IWO3 schema. Path B-b
 * deferred broad Node-storage adaptation; this proxy routes the
 * evaluator-critical paths through to FastAPI's IWO3-native
 * implementations instead.
 *
 * Auth posture (per D-AEP-3 (b) Express proxy lock):
 *   - operator authenticates with Express session cookies (existing
 *     React pattern unchanged)
 *   - this middleware translates `req.user.claims.sub` →
 *     `X-IWO3-User` + first-membership client_id →
 *     `X-IWO3-Client` dev-auth headers
 *   - FastAPI receives the dev-auth headers and runs as if invoked
 *     by an authenticated operator
 *
 * Tenant binding posture (per D-BB-4 carry-forward):
 *   - V1 uses the operator's first client_membership row
 *   - hosted-deploy loop MUST replace this with explicit tenant
 *     binding (session.environment.clientId OR per-request
 *     X-IWO3-Client surfaced through the UI)
 *   - this local-only assumption is recorded as a hard hosted-deploy
 *     pre-condition in ADR-035 §Residual debt #6
 *
 * Scope-lock: this module proxies ONLY evaluator-path endpoints
 * (work-order read + reopen/edit/redispatch/accept + candidate
 * select/reject + evaluator_summary). It is NOT a generic
 * Node↔FastAPI request router. Adding more endpoints here without
 * explicit scope authorization is a stop-and-escalate trigger.
 */

import type { Request, Response } from "express";
import { db } from "./db";
import { clientMemberships } from "@shared/models/auth";
import { eq } from "drizzle-orm";

/**
 * FastAPI base URL — defaults to localhost dev. Hosted deploys must
 * override via `IWO3_FASTAPI_BASE_URL` env var (same lookup as the
 * sandbox cross-service helper).
 */
function getFastApiBaseUrl(): string {
  return (
    process.env.IWO3_FASTAPI_BASE_URL ||
    process.env.FASTAPI_BASE_URL ||
    "http://127.0.0.1:8000"
  );
}

/**
 * Look up the operator's primary client_id. V1 single-tenant
 * assumption: the FIRST membership wins (same as
 * `authStorage.getUserEffectiveRole` and
 * `server/sandbox-crossservice.ts`).
 */
async function getUserPrimaryClientId(userId: string): Promise<string | null> {
  const [row] = await db
    .select({ clientId: clientMemberships.clientId })
    .from(clientMemberships)
    .where(eq(clientMemberships.userId, userId))
    .limit(1);
  return row?.clientId ?? null;
}

interface ProxyOpts {
  /** HTTP method to use against FastAPI (default: same as inbound). */
  method?: "GET" | "POST" | "PUT" | "DELETE" | "PATCH";
}

/**
 * Build an Express middleware that forwards the request to a FastAPI
 * path with dev-auth headers translated from the session.
 *
 * `fastapiPathFn` may be a static string or a function that derives
 * the FastAPI path from `req.params` (e.g., `req.params.id`).
 */
export function proxyToFastApi(
  fastapiPathFn: string | ((req: Request) => string),
  opts: ProxyOpts = {}
) {
  return async (req: Request, res: Response): Promise<void> => {
    const userId = (req as any).user?.claims?.sub;
    if (!userId) {
      res.status(401).json({ message: "Unauthorized" });
      return;
    }
    const clientId = await getUserPrimaryClientId(userId);
    if (!clientId) {
      res.status(400).json({
        message:
          "Actor has no client_memberships row; cannot tenant-scope the FastAPI proxy.",
        kind: "no_tenant",
      });
      return;
    }
    const fastapiPath =
      typeof fastapiPathFn === "function" ? fastapiPathFn(req) : fastapiPathFn;
    const baseUrl = getFastApiBaseUrl();
    const url = `${baseUrl.replace(/\/$/, "")}${fastapiPath}`;
    const method = opts.method || (req.method as ProxyOpts["method"]) || "GET";

    const headers: Record<string, string> = {
      "X-IWO3-User": userId,
      "X-IWO3-Client": clientId,
      Accept: "application/json",
    };
    let body: string | undefined;
    if (method !== "GET" && method !== "DELETE") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(req.body ?? {});
    }

    let resp: Response | globalThis.Response;
    try {
      resp = await fetch(url, { method, headers, body }) as any;
    } catch (err: any) {
      res.status(502).json({
        message: "FastAPI unreachable",
        error: err?.message ?? String(err),
        kind: "fastapi_unreachable",
        base_url: baseUrl,
      });
      return;
    }

    const status = (resp as globalThis.Response).status;
    const text = await (resp as globalThis.Response).text();
    // Pass through the body verbatim (text or JSON). Set the same
    // status code FastAPI returned so error shapes propagate cleanly.
    res.status(status);
    const ct =
      (resp as globalThis.Response).headers.get("content-type") ||
      "application/json";
    res.setHeader("Content-Type", ct);
    res.send(text);
  };
}

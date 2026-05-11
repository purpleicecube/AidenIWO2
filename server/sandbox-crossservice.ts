/**
 * Sandbox cross-service adapter — Path B-b (Darkmode 2026-05-11).
 *
 * INTENTIONALLY SANDBOX-BOUNDED.
 *
 * This module exists for one purpose: replace the sandbox rerender
 * route's direct IWO2-shaped read of `work_orders.tier2_result` with
 * a narrow read of an IWO3 artifact via the FastAPI workspace surface.
 * It must not become a generic Node↔FastAPI data-access layer.
 *
 * Hard scope locks (per CODEX disposition on ADR-035 §Path B-b):
 *
 *   - sandbox-only callers — do NOT export helpers from here to
 *     non-sandbox routes
 *   - rerender (read) + publish (write outcome record) only
 *   - no generic work-order service abstraction
 *   - no generic artifact-write service abstraction
 *   - no auth bridge — uses the FastAPI dev-auth headers
 *     (X-IWO3-User + X-IWO3-Client) which are the only seam that
 *     doesn't require a session-cookie ↔ bearer-token bridge
 *
 * Hosted-deploy auth-bridge concern: the dev-header path will need to
 * be replaced with a real bearer-token bridge before this seam can
 * run hosted. That replacement is the hosted-deploy loop's problem,
 * NOT B-b's problem. ADR-035 records this; the handback re-asserts it.
 */

import { db } from "./db";
import { clientMemberships } from "@shared/models/auth";
import { eq } from "drizzle-orm";

/**
 * FastAPI base URL — defaults to localhost dev. Hosted deploys must
 * override via `IWO3_FASTAPI_BASE_URL` env var.
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
 * assumption: the FIRST membership wins. This is the same pragmatic
 * assumption as `authStorage.getUserEffectiveRole`.
 *
 * Sandbox-bounded — do not use this for non-sandbox tenant selection.
 */
async function getUserPrimaryClientId(userId: string): Promise<string | null> {
  const [row] = await db
    .select({ clientId: clientMemberships.clientId })
    .from(clientMemberships)
    .where(eq(clientMemberships.userId, userId))
    .limit(1);
  return row?.clientId ?? null;
}

export interface SandboxArtifactContent {
  id: string;
  filename: string;
  mimeType: string;
  encoding: "utf-8" | "base64" | "ref";
  content: string | null;
  storageRef?: string | null;
  truncated?: boolean;
  sizeBytes?: number;
}

export interface SandboxArtifactReadError {
  status: number;
  kind:
    | "invalid_uuid"
    | "not_found"
    | "no_tenant"
    | "fastapi_unreachable"
    | "fastapi_error";
  detail: string;
}

/**
 * Fetch a workspace artifact's text content via FastAPI's existing
 * `GET /workspace/files/:id/content` endpoint. The operator's primary
 * client_id is resolved from `client_memberships` and passed via the
 * `X-IWO3-Client` dev-auth header.
 *
 * Returns either the content shape or an error object so the caller
 * (sandbox rerender route) can render an honest 400/404/500 with the
 * specific kind. No exceptions thrown for expected failure paths.
 */
export async function fetchSandboxArtifactContent(
  artifactId: string,
  actorUserId: string
): Promise<SandboxArtifactContent | SandboxArtifactReadError> {
  const clientId = await getUserPrimaryClientId(actorUserId);
  if (!clientId) {
    return {
      status: 400,
      kind: "no_tenant",
      detail:
        "Actor has no client_memberships row; cannot tenant-scope the artifact read.",
    };
  }

  const baseUrl = getFastApiBaseUrl();
  const url = `${baseUrl.replace(/\/$/, "")}/workspace/files/${encodeURIComponent(artifactId)}/content`;

  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "X-IWO3-User": actorUserId,
        "X-IWO3-Client": clientId,
      },
    });
  } catch (err: any) {
    return {
      status: 502,
      kind: "fastapi_unreachable",
      detail: `FastAPI at ${baseUrl} unreachable: ${err?.message ?? err}`,
    };
  }

  if (resp.status === 400) {
    return {
      status: 400,
      kind: "invalid_uuid",
      detail:
        "Sandbox session.environment.sourceId is not a valid artifact UUID.",
    };
  }
  if (resp.status === 404) {
    return {
      status: 404,
      kind: "not_found",
      detail: `Artifact ${artifactId} not found (or not visible to this tenant).`,
    };
  }
  if (!resp.ok) {
    let body = "";
    try {
      body = await resp.text();
    } catch {
      /* noop */
    }
    return {
      status: resp.status,
      kind: "fastapi_error",
      detail: `FastAPI returned ${resp.status}: ${body.slice(0, 300)}`,
    };
  }

  const data = (await resp.json()) as {
    id: string;
    filename: string;
    mime_type: string;
    encoding: string;
    content: string | null;
    storage_ref?: string | null;
    truncated?: boolean;
    size_bytes?: number;
  };

  return {
    id: data.id,
    filename: data.filename,
    mimeType: data.mime_type,
    encoding: data.encoding as "utf-8" | "base64" | "ref",
    content: data.content ?? null,
    storageRef: data.storage_ref ?? null,
    truncated: data.truncated,
    sizeBytes: data.size_bytes,
  };
}

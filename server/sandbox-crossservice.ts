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
// CODEX follow-up: use IWO3-native artifacts schema (has client_id),
// not the legacy IWO2-shape one in shared/schema.ts which doesn't.
import { artifacts as iwo3Artifacts } from "../db/schema/artifacts";
import { outputPackages } from "../db/schema/output_packages";
import { and, eq } from "drizzle-orm";

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
 * Tenant-resolution error shape — surfaced to callers so they can
 * render an honest 400/403/404 with the specific kind.
 */
export interface SandboxTenantResolutionError {
  status: number;
  kind:
    | "invalid_uuid"
    | "not_found"
    | "forbidden"
    | "no_tenant";
  detail: string;
}

/**
 * Sandbox + Markdown Review Layer (2026-05-18) — CODEX architect
 * follow-up: resolve tenant from the RESOURCE, not from "first
 * membership wins."
 *
 * The previous pattern (`getUserPrimaryClientId(userId)` returning the
 * first arbitrary `client_memberships` row) silently picked the wrong
 * tenant for multi-membership operators — wrong brand applied to
 * preview, or 404 on export if the resolved tenant didn't own the
 * package.
 *
 * These resolvers read the resource's authoritative `client_id`
 * directly via Drizzle (Node-side iwo3 superuser pool, NOT RLS-scoped
 * — that's the point; we're resolving WHICH tenant), then verify the
 * actor has membership in that tenant before returning the value.
 *
 * Sandbox-bounded — same scope locks as the rest of this module.
 */
export async function resolvePackageTenant(
  packageId: string,
  actorUserId: string,
): Promise<{ clientId: string } | SandboxTenantResolutionError> {
  let pkg: { clientId: string } | undefined;
  try {
    [pkg] = await db
      .select({ clientId: outputPackages.clientId })
      .from(outputPackages)
      .where(eq(outputPackages.id, packageId))
      .limit(1);
  } catch (err: any) {
    return {
      status: 400,
      kind: "invalid_uuid",
      detail: `invalid package id ${packageId}: ${err?.message ?? err}`,
    };
  }
  if (!pkg) {
    return {
      status: 404,
      kind: "not_found",
      detail: `output_package ${packageId} not found`,
    };
  }
  const ok = await _actorHasMembership(actorUserId, pkg.clientId);
  if (!ok) {
    return {
      status: 403,
      kind: "forbidden",
      detail: `actor ${actorUserId} has no membership in tenant ${pkg.clientId} that owns package ${packageId}`,
    };
  }
  return { clientId: pkg.clientId };
}

export async function resolveArtifactTenant(
  artifactId: string,
  actorUserId: string,
): Promise<{ clientId: string } | SandboxTenantResolutionError> {
  let art: { clientId: string } | undefined;
  try {
    [art] = await db
      .select({ clientId: iwo3Artifacts.clientId })
      .from(iwo3Artifacts)
      .where(eq(iwo3Artifacts.id, artifactId))
      .limit(1);
  } catch (err: any) {
    return {
      status: 400,
      kind: "invalid_uuid",
      detail: `invalid artifact id ${artifactId}: ${err?.message ?? err}`,
    };
  }
  if (!art) {
    return {
      status: 404,
      kind: "not_found",
      detail: `artifact ${artifactId} not found`,
    };
  }
  const ok = await _actorHasMembership(actorUserId, art.clientId);
  if (!ok) {
    return {
      status: 403,
      kind: "forbidden",
      detail: `actor ${actorUserId} has no membership in tenant ${art.clientId} that owns artifact ${artifactId}`,
    };
  }
  return { clientId: art.clientId };
}

async function _actorHasMembership(
  actorUserId: string,
  clientId: string,
): Promise<boolean> {
  const [row] = await db
    .select({ clientId: clientMemberships.clientId })
    .from(clientMemberships)
    .where(
      and(
        eq(clientMemberships.userId, actorUserId),
        eq(clientMemberships.clientId, clientId),
      ),
    )
    .limit(1);
  return !!row;
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
  /**
   * Sandbox Everywhere Darkmode (2026-05-11): set to the source mime
   * when `content` is plain text extracted from a binary source
   * (PDF/PPTX/etc.). Lets the rerender route distinguish "native md/
   * html/code" from "extracted text from a binary" so it can pick the
   * right preview builder.
   */
  extractedFrom?: string | null;
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
 * `GET /workspace/files/:id/content` endpoint.
 *
 * CODEX architect follow-up (2026-05-18): tenant context is now an
 * EXPLICIT parameter, not inferred from "first membership wins."
 * Callers are expected to resolve `clientId` via `resolveArtifactTenant`
 * (or carry it from session/package context).
 *
 * Returns either the content shape or an error object so the caller
 * (sandbox rerender route) can render an honest 400/404/500 with the
 * specific kind. No exceptions thrown for expected failure paths.
 */
export async function fetchSandboxArtifactContent(
  artifactId: string,
  actorUserId: string,
  clientId: string,
): Promise<SandboxArtifactContent | SandboxArtifactReadError> {
  if (!clientId) {
    return {
      status: 400,
      kind: "no_tenant",
      detail:
        "Explicit clientId required — sandbox cross-service callers must resolve tenant from the resource (resolveArtifactTenant / resolvePackageTenant) before invoking content fetch.",
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
    extracted_from?: string | null;
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
    extractedFrom: data.extracted_from ?? null,
  };
}


/**
 * Sandbox + Markdown Review Layer (2026-05-18) — fetch the active
 * tenant's brand profile so the sandbox preview can apply tenant
 * palette + fonts at render time without mutating the markdown
 * source. The markdown is canonical; this is the presentation layer.
 *
 * CODEX architect follow-up (2026-05-18): tenant context is now an
 * EXPLICIT parameter. Resolve it from the resource (the artifact or
 * package being previewed/exported) BEFORE calling this helper.
 *
 * Best-effort: returns null when the FastAPI surface is unreachable
 * or returns an error, so the preview falls back to the default
 * theme rather than failing the entire rerender chain.
 */
export async function fetchSandboxTenantBrand(
  actorUserId: string,
  clientId: string,
): Promise<import("./workspace-filing").TenantBrand | null> {
  if (!clientId) return null;

  const baseUrl = getFastApiBaseUrl();
  const url = `${baseUrl.replace(/\/$/, "")}/workspace/brand`;

  try {
    const resp = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
        "X-IWO3-User": actorUserId,
        "X-IWO3-Client": clientId,
      },
    });
    if (!resp.ok) return null;
    return (await resp.json()) as import("./workspace-filing").TenantBrand;
  } catch {
    return null;
  }
}

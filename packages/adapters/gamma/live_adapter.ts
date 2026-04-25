/**
 * Loop 9 Phase 9.2 — real Gamma HTTP adapter.
 *
 * Replaces the Loop 3 Phase 3.4 test-double behind the
 * `GAMMA_LIVE_ENABLED=true` opt-in. The registry decides which
 * implementation to bind under `adapter_key="gamma"` at module load;
 * see `packages/contracts/adapter/registry.ts`.
 *
 * I/O shape (ADR-012 AdapterContract):
 *   submit()       POST /generations | /generations/from-template
 *   pollStatus()   GET  /generations/{id}
 *   fetchResult()  GET  /generations/{id}  (mapped to final result)
 *
 * Auth: X-API-KEY. Key resolved at I/O time from
 *   ctx.credentialRef = "credential_ref:env:GAMMA_API_KEY_KLEAR"
 *   process.env["GAMMA_API_KEY_KLEAR"]
 * Raw keys never persist to the DB (IWO3_LOOP_8_3_CODEX_DECISIONS §Q2).
 *
 * Pure request/response shaping lives in `request_shape.ts` with a
 * Python parity mirror. This class owns network plumbing only.
 */

import type {
  AdapterContract,
  AdapterDescription,
  AdapterExecutionResult,
  AdapterPollContext,
  AdapterPollResult,
  AdapterSubmissionContext,
  AdapterSubmissionResult,
  AdapterValidationResult,
} from "../../contracts/adapter/types";
import type { OutputPackage } from "../../../db/schema/output_packages";
import {
  GammaPackageInvalidError,
  GammaSubmitResponseInvalidError,
  buildGammaRequestBody,
  parseGammaPollResponse,
  parseGammaSubmitResponse,
  type GammaRequestShape,
} from "./request_shape";

const DEFAULT_BASE_URL = "https://public-api.gamma.app/v1.0";
const DEFAULT_FETCH_TIMEOUT_MS = 30_000;

const SUPPORTED_OUTPUT_KINDS = ["gamma_pptx", "gamma_pdf"] as const;
const SUPPORTED_ACTIONS = [
  "generate",
  "render_from_template",
  "export_pptx",
  "export_pdf",
] as const;

export type GammaAdapterErrorKind =
  | "credential_invalid"
  | "rate_limited"
  | "server_error"
  | "package_invalid"
  | "network_error"
  | "response_invalid";

export class GammaAdapterError extends Error {
  readonly kind: GammaAdapterErrorKind;
  readonly httpStatus: number | null;
  readonly body: string | null;

  constructor(
    kind: GammaAdapterErrorKind,
    message: string,
    httpStatus: number | null = null,
    body: string | null = null
  ) {
    super(message);
    this.name = "GammaAdapterError";
    this.kind = kind;
    this.httpStatus = httpStatus;
    this.body = body;
  }
}

export interface GammaLiveAdapterOptions {
  /** Injectable for tests — defaults to global fetch. */
  fetchImpl?: typeof fetch;
  /** Override for tests / local mocks. */
  baseUrl?: string;
  /** Per-request timeout. */
  fetchTimeoutMs?: number;
  /** Environment accessor, for tests. Defaults to process.env. */
  env?: NodeJS.ProcessEnv;
}

/** Parse "credential_ref:env:GAMMA_API_KEY_KLEAR" → "GAMMA_API_KEY_KLEAR". */
function envVarFromCredentialRef(ref: string): string | null {
  const m = ref.match(/^credential_ref:env:([A-Za-z0-9_]+)$/);
  return m ? m[1] : null;
}

export class GammaLiveAdapter implements AdapterContract {
  readonly adapterKey = "gamma";
  private readonly fetchImpl: typeof fetch;
  private readonly baseUrl: string;
  private readonly fetchTimeoutMs: number;
  private readonly env: NodeJS.ProcessEnv;

  constructor(opts: GammaLiveAdapterOptions = {}) {
    this.fetchImpl = opts.fetchImpl ?? fetch;
    this.baseUrl = opts.baseUrl ?? DEFAULT_BASE_URL;
    this.fetchTimeoutMs = opts.fetchTimeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS;
    this.env = opts.env ?? process.env;
  }

  describe(): AdapterDescription {
    return {
      adapterKey: this.adapterKey,
      contractVersion: "v0",
      supportedOutputKinds: SUPPORTED_OUTPUT_KINDS,
      supportedActions: SUPPORTED_ACTIONS,
      isLive: true,
      envFlagName: "GAMMA_LIVE_ENABLED",
    };
  }

  validatePackage(pkg: OutputPackage): AdapterValidationResult {
    try {
      // Structural validation — same rules as request_shape's builder,
      // without the template_external_ref resolution.
      buildGammaRequestBody({
        outputKind: pkg.outputKind,
        title: pkg.title,
        summary: pkg.summary,
        contentBlocks: (pkg.contentBlocks as Record<string, unknown>) ?? {},
        templateExternalRef: null, // generate mode for validation
      });
      return { ok: true, errors: [] };
    } catch (err) {
      if (err instanceof GammaPackageInvalidError) {
        return { ok: false, errors: err.errors };
      }
      throw err;
    }
  }

  async submit(
    pkg: OutputPackage,
    ctx: AdapterSubmissionContext
  ): Promise<AdapterSubmissionResult> {
    const apiKey = this.resolveApiKey(ctx.credentialRef ?? null);

    let shape: GammaRequestShape;
    try {
      shape = buildGammaRequestBody({
        outputKind: pkg.outputKind,
        title: pkg.title,
        summary: pkg.summary,
        contentBlocks: (pkg.contentBlocks as Record<string, unknown>) ?? {},
        templateExternalRef: ctx.templateExternalRef ?? null,
      });
    } catch (err) {
      if (err instanceof GammaPackageInvalidError) {
        throw new GammaAdapterError(
          "package_invalid",
          err.message,
          null,
          err.errors.join("; ")
        );
      }
      throw err;
    }

    const raw = await this.httpPost(shape.endpoint, shape.body, apiKey);
    let parsed;
    try {
      parsed = parseGammaSubmitResponse(raw);
    } catch (err) {
      if (err instanceof GammaSubmitResponseInvalidError) {
        throw new GammaAdapterError("response_invalid", err.message);
      }
      throw err;
    }

    return {
      externalReference: parsed.generationId,
      externalDestination: parsed.gammaUrl ?? `gamma://${parsed.generationId}`,
      handoffPayloadRef: `gamma://generations/${parsed.generationId}`,
    };
  }

  async pollStatus(
    externalReference: string,
    ctx?: AdapterPollContext
  ): Promise<AdapterPollResult> {
    const apiKey = this.resolveApiKey(ctx?.credentialRef ?? null);
    const raw = await this.httpGet(`/generations/${externalReference}`, apiKey);
    const parsed = parseGammaPollResponse(externalReference, raw);
    return {
      externalReference,
      status:
        parsed.status === "completed" || parsed.status === "failed"
          ? parsed.status
          : parsed.status === "running"
          ? "running"
          : "pending",
      progress: parsed.progress,
    };
  }

  async fetchResult(
    externalReference: string,
    ctx?: AdapterPollContext
  ): Promise<AdapterExecutionResult> {
    const apiKey = this.resolveApiKey(ctx?.credentialRef ?? null);
    const raw = await this.httpGet(`/generations/${externalReference}`, apiKey);
    const parsed = parseGammaPollResponse(externalReference, raw);

    if (parsed.status === "completed") {
      const payloadRef =
        parsed.exportUrls.length > 0
          ? parsed.exportUrls[0]
          : parsed.gammaUrl ?? null;
      return {
        externalReference,
        status: "success",
        payloadRef: payloadRef ?? undefined,
        metadata: {
          gammaUrl: parsed.gammaUrl,
          exportUrls: parsed.exportUrls,
          adapter: "gamma-live",
        },
      };
    }
    if (parsed.status === "failed") {
      return {
        externalReference,
        status: "failed",
        errorMessage: parsed.errorMessage ?? "unknown gamma failure",
        metadata: { adapter: "gamma-live" },
      };
    }
    // pending / running — surface as "unknown" per AdapterExecutionStatus.
    return {
      externalReference,
      status: "unknown",
      metadata: { adapter: "gamma-live", pollStatus: parsed.status },
    };
  }

  private resolveApiKey(ref: string | null): string {
    // Fall back to the legacy GAMMA_API_KEY global when no credential_ref
    // is supplied (tests, Phase 9.3 poll path until credential-threading
    // reaches pollStatus/fetchResult).
    if (!ref) {
      const fallback = this.env["GAMMA_API_KEY"];
      if (fallback && fallback.length > 0) return fallback;
      throw new GammaAdapterError(
        "credential_invalid",
        "no credential_ref supplied and GAMMA_API_KEY not set"
      );
    }
    const envName = envVarFromCredentialRef(ref);
    if (!envName) {
      throw new GammaAdapterError(
        "credential_invalid",
        `credential_ref must match credential_ref:env:NAME (got ${JSON.stringify(ref)})`
      );
    }
    const value = this.env[envName];
    if (!value || value.length === 0) {
      throw new GammaAdapterError(
        "credential_invalid",
        `env var ${envName} is not set`
      );
    }
    return value;
  }

  private async httpPost(
    path: string,
    body: unknown,
    apiKey: string
  ): Promise<Record<string, unknown>> {
    const res = await this.doFetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-KEY": apiKey,
      },
      body: JSON.stringify(body),
    });
    return this.readJsonOrThrow(res);
  }

  private async httpGet(
    path: string,
    apiKey: string
  ): Promise<Record<string, unknown>> {
    const res = await this.doFetch(path, {
      method: "GET",
      headers: {
        "X-API-KEY": apiKey,
      },
    });
    return this.readJsonOrThrow(res);
  }

  private async doFetch(path: string, init: RequestInit): Promise<Response> {
    try {
      return await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        signal: AbortSignal.timeout(this.fetchTimeoutMs),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      throw new GammaAdapterError("network_error", message);
    }
  }

  private async readJsonOrThrow(
    res: Response
  ): Promise<Record<string, unknown>> {
    const bodyText = await res.text();
    if (res.ok) {
      try {
        return JSON.parse(bodyText);
      } catch {
        throw new GammaAdapterError(
          "response_invalid",
          `non-JSON body from Gamma (${res.status})`,
          res.status,
          bodyText.slice(0, 500)
        );
      }
    }
    const kind: GammaAdapterErrorKind =
      res.status === 401 || res.status === 403
        ? "credential_invalid"
        : res.status === 429
        ? "rate_limited"
        : res.status >= 500
        ? "server_error"
        : "response_invalid";
    throw new GammaAdapterError(
      kind,
      `gamma returned HTTP ${res.status}`,
      res.status,
      bodyText.slice(0, 500)
    );
  }
}

export const gammaLive = new GammaLiveAdapter();

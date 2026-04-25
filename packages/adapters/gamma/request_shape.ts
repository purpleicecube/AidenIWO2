/**
 * Loop 9 Phase 9.2 — pure payload builders + response parsers for Gamma.
 *
 * No I/O, no side effects. The TS canonical is mirrored byte-for-byte
 * by `apps/api-fastapi/adapter/gamma_request_shape.py` so the FastAPI
 * side can validate the same packet shapes without running the full
 * adapter. The network layer (`live_adapter.ts`) composes these.
 *
 * Gamma API reference (public, v1.0):
 *   POST /generations              — generate from prompt
 *   POST /generations/from-template — render from a template id
 *   GET  /generations/{generationId} — poll / fetch final state
 *
 * Auth: `X-API-KEY` header (not Bearer). The raw key is resolved at
 * the HTTP layer from `credential_ref:env:*`; the builders here are
 * auth-agnostic.
 */

export type GammaRequestMode = "generate" | "from_template";

export type GammaExportFormat = "pptx" | "pdf";

export interface GammaRequestShapeInput {
  /** OutputPackage fields the builder reads. */
  outputKind: string;
  title: string;
  summary: string | null;
  contentBlocks: Record<string, unknown>;
  /** Resolved by the dispatcher when template_profile.external_ref is set. */
  templateExternalRef: string | null;
}

export interface GammaRequestShape {
  /** "/generations" or "/generations/from-template". */
  endpoint: string;
  mode: GammaRequestMode;
  exportAs: GammaExportFormat;
  body: Record<string, unknown>;
}

export class GammaPackageInvalidError extends Error {
  readonly errors: readonly string[];
  constructor(errors: readonly string[]) {
    super(`gamma package invalid: ${errors.join("; ")}`);
    this.name = "GammaPackageInvalidError";
    this.errors = errors;
  }
}

function exportAsFromOutputKind(outputKind: string): GammaExportFormat {
  if (outputKind === "gamma_pptx") return "pptx";
  if (outputKind === "gamma_pdf") return "pdf";
  throw new GammaPackageInvalidError([
    `output_kind=${JSON.stringify(outputKind)} is not a gamma_* kind`,
  ]);
}

/**
 * Pull the prompt text out of content_blocks. Accepts three shapes
 * the upstream producers already use:
 *   - `{"prompt": "..."}` (Mark-style content brief)
 *   - `{"inputText": "..."}` (Gamma-native)
 *   - `{"body": "..."}` (generic text body)
 * Returns null if no text is present; the builder then throws.
 */
function extractPromptText(
  blocks: Record<string, unknown>
): string | null {
  for (const key of ["prompt", "inputText", "body", "content"]) {
    const v = blocks[key];
    if (typeof v === "string" && v.trim().length > 0) return v;
  }
  return null;
}

export function buildGammaRequestBody(
  input: GammaRequestShapeInput
): GammaRequestShape {
  const errors: string[] = [];

  const exportAs = exportAsFromOutputKind(input.outputKind);

  if (!input.title || input.title.trim().length === 0) {
    errors.push("title must be non-empty");
  }

  const promptText = extractPromptText(input.contentBlocks);
  if (!promptText) {
    errors.push(
      "content_blocks must carry prompt/inputText/body/content text"
    );
  }

  if (errors.length > 0) {
    throw new GammaPackageInvalidError(errors);
  }

  const mode: GammaRequestMode =
    input.templateExternalRef && input.templateExternalRef.length > 0
      ? "from_template"
      : "generate";

  if (mode === "from_template") {
    return {
      endpoint: "/generations/from-template",
      mode,
      exportAs,
      body: {
        gammaId: input.templateExternalRef,
        prompt: promptText,
        exportAs,
      },
    };
  }

  return {
    endpoint: "/generations",
    mode,
    exportAs,
    body: {
      inputText: promptText,
      textMode: "generate",
      format: exportAs === "pptx" ? "presentation" : "document",
      exportAs,
    },
  };
}

// ──────────────────────────────────────────────────────────────────────
// Response parsers
// ──────────────────────────────────────────────────────────────────────

export interface GammaSubmitParsed {
  generationId: string;
  gammaUrl: string | null;
}

export class GammaSubmitResponseInvalidError extends Error {
  constructor(detail: string) {
    super(`gamma submit response invalid: ${detail}`);
    this.name = "GammaSubmitResponseInvalidError";
  }
}

export function parseGammaSubmitResponse(
  raw: Record<string, unknown>
): GammaSubmitParsed {
  const generationId = raw["generationId"];
  if (typeof generationId !== "string" || generationId.length === 0) {
    throw new GammaSubmitResponseInvalidError(
      "generationId missing or not a string"
    );
  }
  const gammaUrl =
    typeof raw["gammaUrl"] === "string" ? (raw["gammaUrl"] as string) : null;
  return { generationId, gammaUrl };
}

export type GammaTerminalStatus = "completed" | "failed";

export interface GammaPollParsed {
  generationId: string;
  status: "pending" | "running" | GammaTerminalStatus;
  progress?: number;
  exportUrls: readonly string[];
  gammaUrl: string | null;
  errorMessage: string | null;
}

function asString(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

export function extractGammaExportUrls(
  raw: Record<string, unknown>
): readonly string[] {
  const out: string[] = [];
  for (const key of ["exportUrl", "pptxUrl", "pdfUrl", "fileUrl", "downloadUrl"]) {
    const v = raw[key];
    if (typeof v === "string" && v.length > 0) out.push(v);
  }
  const exportsObj = raw["exports"];
  if (exportsObj && typeof exportsObj === "object") {
    for (const v of Object.values(exportsObj as Record<string, unknown>)) {
      if (typeof v === "string" && v.startsWith("http")) out.push(v);
    }
  }
  const urlsArr = raw["exportUrls"];
  if (Array.isArray(urlsArr)) {
    for (const v of urlsArr) {
      if (typeof v === "string") out.push(v);
      else if (v && typeof v === "object" && typeof (v as Record<string, unknown>)["url"] === "string") {
        out.push((v as Record<string, unknown>)["url"] as string);
      }
    }
  }
  const files = raw["files"];
  if (Array.isArray(files)) {
    for (const v of files) {
      if (typeof v === "string") out.push(v);
      else if (v && typeof v === "object" && typeof (v as Record<string, unknown>)["url"] === "string") {
        out.push((v as Record<string, unknown>)["url"] as string);
      }
    }
  }
  return out;
}

export function parseGammaPollResponse(
  generationId: string,
  raw: Record<string, unknown>
): GammaPollParsed {
  const rawStatus = asString(raw["status"]) ?? "pending";
  // Map Gamma statuses to the adapter contract's pending/running/completed/failed.
  const normalised: GammaPollParsed["status"] =
    rawStatus === "completed"
      ? "completed"
      : rawStatus === "failed" || rawStatus === "error"
      ? "failed"
      : rawStatus === "running" || rawStatus === "processing"
      ? "running"
      : "pending";

  const exportUrls =
    normalised === "completed" ? extractGammaExportUrls(raw) : [];

  const errObj = raw["error"];
  const errorMessage =
    normalised === "failed"
      ? asString(
          typeof errObj === "object" && errObj !== null
            ? (errObj as Record<string, unknown>)["message"]
            : undefined
        ) ?? asString(raw["message"]) ?? "unknown gamma error"
      : null;

  const progress =
    typeof raw["progress"] === "number" ? (raw["progress"] as number) : undefined;

  return {
    generationId,
    status: normalised,
    progress,
    exportUrls,
    gammaUrl: asString(raw["gammaUrl"]),
    errorMessage,
  };
}

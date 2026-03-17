/**
 * Gamma REST API client for PPTX generation.
 *
 * Supports two modes:
 *   - "generate": POST /v1.0/generations (prompt + optional themeId)
 *   - "from_template": POST /v1.0/generations/from-template (gammaId + prompt)
 *
 * Polls GET /v1.0/generations/{generationId} until complete, then downloads
 * the exported PPTX file. Export URLs expire — downloaded immediately.
 */

import fs from "fs";
import path from "path";

const GAMMA_BASE = "https://public-api.gamma.app/v1.0";
const POLL_INTERVAL_MS = 5000;
const POLL_TIMEOUT_MS = 120_000;

export interface GammaGenerateOptions {
  inputText: string;
  mode: "generate" | "from_template";
  themeId?: string | null;
  gammaId?: string | null;
  exportAs?: "pptx" | "pdf";
  title?: string;
  numCards?: number | null;
  format?: "presentation" | "document";
}

export interface GammaResult {
  success: boolean;
  filePath?: string;
  fileSize?: number;
  gammaUrl?: string;
  generationId?: string;
  creditsDeducted?: number;
  creditsRemaining?: number;
  error?: string;
}

function getApiKey(): string {
  const key = process.env.GAMMA_API_KEY;
  if (!key) throw new Error("GAMMA_API_KEY not set in environment");
  return key;
}

const FETCH_TIMEOUT_MS = 30_000; // 30s per individual HTTP request

async function gammaFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const apiKey = getApiKey();
  return fetch(`${GAMMA_BASE}${path}`, {
    ...options,
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    headers: {
      "Content-Type": "application/json",
      "X-API-KEY": apiKey,
      ...(options.headers || {}),
    },
  });
}

interface PollResult {
  status: string;
  gammaUrl?: string;
  generationId: string;
  exportUrls?: string[];
  // The Gamma API response may contain export URLs under varying field names.
  // We capture the full response to discover the field at runtime.
  raw: Record<string, any>;
}

async function pollGeneration(generationId: string, onHeartbeat?: () => void): Promise<PollResult> {
  const startTime = Date.now();

  while (Date.now() - startTime < POLL_TIMEOUT_MS) {
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));

    // BUG-041: Emit heartbeat on each poll so watchdog knows we're alive
    if (onHeartbeat) {
      try { onHeartbeat(); } catch { /* best-effort */ }
    }

    const res = await gammaFetch(`/generations/${generationId}`);
    if (!res.ok) {
      throw new Error(`Gamma poll returned ${res.status}: ${await res.text()}`);
    }

    const data = await res.json() as Record<string, any>;

    if (data.status === "completed") {
      // Extract export URLs from whichever field Gamma uses
      const exportUrls = extractExportUrls(data);
      return {
        status: "completed",
        gammaUrl: data.gammaUrl,
        generationId,
        exportUrls,
        raw: data,
      };
    }

    if (data.status === "failed" || data.status === "error") {
      const errMsg = data.error?.message || data.message || "unknown error";
      throw new Error(`Gamma generation failed: ${errMsg}`);
    }

    // Still pending — continue polling
    console.log(`[gamma] Generation ${generationId} status: ${data.status}`);
  }

  throw new Error(`Gamma generation timed out after ${POLL_TIMEOUT_MS / 1000}s`);
}

/**
 * Extract export file URLs from the Gamma poll response.
 * The exact field is not well-documented — check known patterns.
 */
function extractExportUrls(data: Record<string, any>): string[] {
  const urls: string[] = [];

  // Check common field patterns
  for (const key of ["exportUrl", "pptxUrl", "pdfUrl", "fileUrl", "downloadUrl"]) {
    if (typeof data[key] === "string") urls.push(data[key]);
  }

  // Check nested exports object
  if (data.exports && typeof data.exports === "object") {
    for (const val of Object.values(data.exports)) {
      if (typeof val === "string" && val.startsWith("http")) urls.push(val);
    }
  }

  // Check exportUrls array
  if (Array.isArray(data.exportUrls)) {
    for (const url of data.exportUrls) {
      if (typeof url === "string") urls.push(url);
      else if (url?.url) urls.push(url.url);
    }
  }

  // Check files array
  if (Array.isArray(data.files)) {
    for (const f of data.files) {
      if (typeof f === "string") urls.push(f);
      else if (f?.url) urls.push(f.url);
    }
  }

  return urls;
}

async function downloadFile(url: string, outputPath: string): Promise<number> {
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to download from Gamma: ${res.status} ${res.statusText}`);
  }
  const buffer = Buffer.from(await res.arrayBuffer());
  fs.writeFileSync(outputPath, buffer);
  return buffer.length;
}

export async function generateWithGamma(
  options: GammaGenerateOptions,
  outputDir: string,
  onHeartbeat?: () => void,
): Promise<GammaResult> {
  try {
    // 1. Kick off generation
    let endpoint: string;
    let body: Record<string, any>;

    if (options.mode === "from_template" && options.gammaId) {
      endpoint = "/generations/from-template";
      body = {
        gammaId: options.gammaId,
        prompt: options.inputText,
        exportAs: options.exportAs || "pptx",
      };
      if (options.themeId) body.themeId = options.themeId;
    } else {
      endpoint = "/generations";
      body = {
        inputText: options.inputText,
        textMode: "generate",
        format: options.format || "presentation",
        exportAs: options.exportAs || "pptx",
      };
      if (options.themeId) body.themeId = options.themeId;
      if (options.numCards) body.numCards = options.numCards;
    }

    console.log(`[gamma] Starting generation (${options.mode}) via ${endpoint}`);
    const createRes = await gammaFetch(endpoint, {
      method: "POST",
      body: JSON.stringify(body),
    });

    if (!createRes.ok) {
      const errText = await createRes.text();
      return { success: false, error: `Gamma API ${createRes.status}: ${errText}` };
    }

    const createData = await createRes.json() as Record<string, any>;
    const generationId = createData.generationId;
    if (!generationId) {
      return { success: false, error: "Gamma did not return a generationId", generationId: undefined };
    }

    console.log(`[gamma] Generation created: ${generationId} — polling...`);

    // 2. Poll for completion (BUG-041: pass heartbeat to keep watchdog alive)
    const pollResult = await pollGeneration(generationId, onHeartbeat);

    // 3. Download the exported file
    fs.mkdirSync(outputDir, { recursive: true });
    const outputPath = path.join(outputDir, `gamma-${generationId}.pptx`);

    if (pollResult.exportUrls && pollResult.exportUrls.length > 0) {
      // Download from the first available export URL
      const exportUrl = pollResult.exportUrls[0];
      console.log(`[gamma] Downloading PPTX from export URL...`);
      const fileSize = await downloadFile(exportUrl, outputPath);

      return {
        success: true,
        filePath: outputPath,
        fileSize,
        gammaUrl: pollResult.gammaUrl,
        generationId,
        creditsDeducted: pollResult.raw.credits?.deducted,
        creditsRemaining: pollResult.raw.credits?.remaining,
      };
    }

    // No export URL found — log the full response for debugging
    console.warn(`[gamma] No export URL found in response. Full response keys: ${Object.keys(pollResult.raw).join(", ")}`);
    console.warn(`[gamma] Full response: ${JSON.stringify(pollResult.raw).slice(0, 500)}`);

    return {
      success: false,
      error: `Generation completed but no export URL found. gammaUrl: ${pollResult.gammaUrl}. Response keys: ${Object.keys(pollResult.raw).join(", ")}`,
      gammaUrl: pollResult.gammaUrl,
      generationId,
    };
  } catch (err: any) {
    console.error(`[gamma] Error:`, err.message);
    return { success: false, error: err.message };
  }
}

/**
 * Quick connectivity test — fetches available themes.
 */
export async function testGammaConnection(): Promise<{ success: boolean; message: string; themes?: any[] }> {
  try {
    const res = await gammaFetch("/themes");
    if (res.ok) {
      const themes = await res.json();
      return {
        success: true,
        message: `Connected. ${Array.isArray(themes) ? themes.length : 0} themes available.`,
        themes: Array.isArray(themes) ? themes : [],
      };
    }
    return { success: false, message: `Gamma API returned ${res.status}: ${await res.text()}` };
  } catch (err: any) {
    return { success: false, message: err.message };
  }
}

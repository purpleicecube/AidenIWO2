/**
 * Text Extraction Service — Universal binary-to-text conversion for Know-How retrieval.
 *
 * Extensible by MIME type. Each extractor converts a base64-encoded binary artifact
 * into plain text that the LLM can reason about. New formats are added by registering
 * an extractor function — no changes needed to the workspace provider or Know-How service.
 *
 * Supported formats:
 *   - PDF  (.pdf)            — via pdf-parse
 *   - DOCX (.docx)           — via mammoth (raw text extraction, no formatting)
 *   - PPTX (.pptx)           — via JSZip + XML parsing (slide text + speaker notes)
 *   - XLSX (.xlsx)            — planned (Phase 2)
 *   - Plain text / markdown   — passthrough (no extraction needed)
 */

type ExtractorFn = (base64Content: string) => Promise<string | null>;

const registry = new Map<string, ExtractorFn>();

/**
 * Register an extractor for one or more MIME types.
 */
export function registerExtractor(mimeTypes: string[], fn: ExtractorFn): void {
  for (const mime of mimeTypes) {
    registry.set(mime, fn);
  }
}

/**
 * Check if a MIME type has a registered extractor.
 */
export function canExtract(mimeType: string): boolean {
  return registry.has(mimeType) || isTextMime(mimeType);
}

/**
 * Check if a MIME type is natively text-readable (no extraction needed).
 */
function isTextMime(mimeType: string): boolean {
  if (mimeType.startsWith("text/")) return true;
  if (mimeType === "application/json") return true;
  if (mimeType === "application/javascript") return true;
  return false;
}

/**
 * Extract readable text from an artifact's content.
 *
 * For text MIME types: returns content as-is (passthrough).
 * For binary MIME types: looks up a registered extractor and runs it.
 * Returns null if no extractor is available or extraction fails.
 */
export async function extractText(
  content: string,
  mimeType: string,
): Promise<string | null> {
  // Passthrough for text content
  if (isTextMime(mimeType)) {
    return content;
  }

  const extractor = registry.get(mimeType);
  if (!extractor) {
    return null;
  }

  try {
    return await extractor(content);
  } catch (err: any) {
    console.warn(`[text-extractor] ${mimeType} extraction failed:`, err.message);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Built-in extractors
// ---------------------------------------------------------------------------

/**
 * PDF extractor — uses pdf-parse lib directly (bypasses index.js ESM bug).
 */
async function extractPdf(base64Content: string): Promise<string | null> {
  const pdfParse =
    (await import("pdf-parse/lib/pdf-parse.js")).default ??
    (await import("pdf-parse/lib/pdf-parse.js"));
  const buffer = Buffer.from(base64Content, "base64");
  const data = await (pdfParse as any)(buffer);
  const text = (data.text || "").trim();
  if (text.length === 0) {
    return "[PDF contained no extractable text — may be image-only or scanned]";
  }
  console.log(`[text-extractor] PDF: ${text.length} chars extracted`);
  return text;
}

/**
 * DOCX extractor — uses mammoth for raw text extraction.
 * Extracts document body as plain text (no formatting, no images).
 */
async function extractDocx(base64Content: string): Promise<string | null> {
  const mammoth = await import("mammoth");
  const buffer = Buffer.from(base64Content, "base64");
  const result = await mammoth.extractRawText({ buffer });
  const text = (result.value || "").trim();
  if (text.length === 0) {
    return "[DOCX contained no extractable text]";
  }
  console.log(`[text-extractor] DOCX: ${text.length} chars extracted`);
  return text;
}

/**
 * PPTX extractor — unzips the .pptx (which is a ZIP of XML files),
 * parses each slide's XML to extract text from <a:t> elements and
 * speaker notes from notesSlides.
 */
async function extractPptx(base64Content: string): Promise<string | null> {
  // PPTX is a ZIP containing XML slides
  const { Readable } = await import("stream");
  const { createUnzip } = await import("zlib");

  // Use a lightweight approach: unzip and parse XML text nodes
  // We'll use a simple regex-based XML text extraction since we don't
  // need full DOM parsing — just the <a:t> text content.
  const JSZip = (await import("jszip")).default ?? (await import("jszip"));
  const buffer = Buffer.from(base64Content, "base64");
  let zip: any;
  try {
    zip = await JSZip.loadAsync(buffer);
  } catch {
    return null;
  }

  const slideTexts: string[] = [];

  // Sort slide files numerically
  const slideFiles = Object.keys(zip.files)
    .filter((f) => f.match(/^ppt\/slides\/slide\d+\.xml$/))
    .sort((a, b) => {
      const numA = parseInt(a.match(/slide(\d+)/)?.[1] || "0");
      const numB = parseInt(b.match(/slide(\d+)/)?.[1] || "0");
      return numA - numB;
    });

  for (const slidePath of slideFiles) {
    const xml = await zip.files[slidePath].async("string");
    // Extract text from <a:t> elements
    const texts: string[] = [];
    const regex = /<a:t[^>]*>([\s\S]*?)<\/a:t>/g;
    let match;
    while ((match = regex.exec(xml)) !== null) {
      const t = match[1].trim();
      if (t) texts.push(t);
    }
    if (texts.length > 0) {
      const slideNum = slidePath.match(/slide(\d+)/)?.[1] || "?";
      slideTexts.push(`--- Slide ${slideNum} ---\n${texts.join(" ")}`);
    }
  }

  // Also extract speaker notes
  const noteFiles = Object.keys(zip.files)
    .filter((f) => f.match(/^ppt\/notesSlides\/notesSlide\d+\.xml$/))
    .sort();

  for (const notePath of noteFiles) {
    const xml = await zip.files[notePath].async("string");
    const texts: string[] = [];
    const regex = /<a:t[^>]*>([\s\S]*?)<\/a:t>/g;
    let match;
    while ((match = regex.exec(xml)) !== null) {
      const t = match[1].trim();
      // Skip common boilerplate
      if (t && t !== "Click to edit Master text styles" && !t.match(/^\d+$/)) {
        texts.push(t);
      }
    }
    if (texts.length > 0) {
      const noteNum = notePath.match(/notesSlide(\d+)/)?.[1] || "?";
      slideTexts.push(`--- Speaker Notes (Slide ${noteNum}) ---\n${texts.join(" ")}`);
    }
  }

  if (slideTexts.length === 0) {
    return "[PPTX contained no extractable text]";
  }

  const text = slideTexts.join("\n\n");
  console.log(
    `[text-extractor] PPTX: ${text.length} chars from ${slideFiles.length} slides`,
  );
  return text;
}

// ---------------------------------------------------------------------------
// Register built-in extractors
// ---------------------------------------------------------------------------

registerExtractor(["application/pdf"], extractPdf);

registerExtractor(
  [
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
  ],
  extractDocx,
);

registerExtractor(
  [
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
  ],
  extractPptx,
);

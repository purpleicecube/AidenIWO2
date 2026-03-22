/**
 * PPTX Quality — Preflight Validation, Contract Parsing & Compliance
 *
 * BUG-038 remediation: stop weak slide content from reaching Gamma,
 * parse contentContract into runtime checks, log post-Gamma compliance.
 *
 * Safe, minimal, deterministic. No new DB tables. No pipeline redesign.
 */

import fs from "fs";

// ─── Types ───────────────────────────────────────────────────────────────────

export interface PreflightResult {
  ok: boolean;
  hardFailures: string[];
  softWarnings: string[];
  derivedSlideCount: number;
  /** Summary for logs/checklist */
  summary: string;
}

export interface ParsedContract {
  minSlides: number;
  maxSlides: number;
  requiredSections: string[];
  maxBulletsPerSlide: number | null;
}

export interface GammaComplianceResult {
  ok: boolean;
  hardFailures: string[];
  softWarnings: string[];
  fileExists: boolean;
  fileSizeBytes: number;
  mimeConsistent: boolean;
  estimatedSlideCount: number | null;
  contractSlideRange: { min: number; max: number } | null;
  slideCountCompliant: boolean | null;
  /** Summary for logs/checklist */
  summary: string;
}

// ─── Contract Parser ─────────────────────────────────────────────────────────

const DEFAULT_CONTRACT: ParsedContract = {
  minSlides: 3,
  maxSlides: 20,
  requiredSections: [],
  maxBulletsPerSlide: null,
};

/**
 * Parse a contentContract text string into runtime-checkable rules.
 * Tolerant: unparseable contracts fall back to defaults.
 */
export function parseContentContract(contractText: string | null | undefined): ParsedContract {
  if (!contractText || contractText.trim().length === 0) {
    return { ...DEFAULT_CONTRACT };
  }

  const text = contractText.toLowerCase();
  const result: ParsedContract = { ...DEFAULT_CONTRACT };

  // Parse slide count range — patterns: "Slides: 5-8", "5 to 8 slides", "between 5 and 8"
  const slideRangeMatch = text.match(/slides?\s*:?\s*(\d+)\s*[-–to]+\s*(\d+)/i)
    || text.match(/between\s+(\d+)\s+and\s+(\d+)\s+slides?/i)
    || text.match(/(\d+)\s*[-–]\s*(\d+)\s+slides?/i);
  if (slideRangeMatch) {
    result.minSlides = parseInt(slideRangeMatch[1], 10);
    result.maxSlides = parseInt(slideRangeMatch[2], 10);
  }

  // Parse exact slide count — "exactly 5 slides", "Slides: 5"
  if (!slideRangeMatch) {
    const exactMatch = text.match(/(?:exactly\s+)?(\d+)\s+slides?/i)
      || text.match(/slides?\s*:?\s*(\d+)(?!\s*[-–to])/i);
    if (exactMatch) {
      const n = parseInt(exactMatch[1], 10);
      result.minSlides = n;
      result.maxSlides = n + 2; // small tolerance
    }
  }

  // Parse required sections — "Required sections: Cover, Executive Summary, ..."
  // Strip parenthetical annotations: "Cover (title + subtitle + date)" → "cover"
  // Loop 14 Patch B: "cover" and "thank you" are optional by default — they are
  // common deck conventions but not hard requirements. Only enforce sections that
  // represent real content obligations (executive summary, roadmap, etc.).
  const OPTIONAL_BY_DEFAULT = new Set(["cover", "title slide", "thank you", "thanks", "closing slide", "q&a"]);
  const sectionsMatch = contractText.match(/required\s+sections?\s*:?\s*([^\n]+)/i);
  if (sectionsMatch) {
    result.requiredSections = sectionsMatch[1]
      .split(/[,;]/)
      .map(s => s.replace(/\s*\([^)]*\)/g, "").trim().toLowerCase()) // strip (...)
      .filter(s => s.length > 0 && s.length < 50 && !/^\d/.test(s)) // drop numeric-prefixed like "2-4 content slides"
      .filter(s => !OPTIONAL_BY_DEFAULT.has(s)); // Loop 14: don't hard-require cover/thank you
  }

  // Parse max bullets — "max 5 bullets per slide"
  const bulletsMatch = text.match(/max\s+(\d+)\s+bullets?\s+per\s+slide/i);
  if (bulletsMatch) {
    result.maxBulletsPerSlide = parseInt(bulletsMatch[1], 10);
  }

  return result;
}

// ─── Slide Structure Detection ───────────────────────────────────────────────

/** Common slide delimiter patterns in markdown deliverables */
const SLIDE_DELIMITERS = [
  /^---\s*$/gm,                              // horizontal rule
  /^#{1,2}\s+(?:slide|Slide)\s+\d+/gm,      // "# Slide 1", "## Slide 2"
  /^#{1,2}\s+.+/gm,                          // any H1/H2 heading as slide break
];

/**
 * Estimate slide count from markdown deliverable.
 * Returns the count from the strongest signal.
 */
export function estimateSlideCount(deliverable: string): number {
  if (!deliverable || deliverable.trim().length === 0) return 0;

  // Best signal: explicit "Slide N" headings
  const explicitSlides = deliverable.match(/^#{1,2}\s+(?:slide|Slide)\s+\d+/gm);
  if (explicitSlides && explicitSlides.length >= 2) {
    return explicitSlides.length;
  }

  // Second signal: horizontal rules as slide delimiters
  const hrDelimiters = deliverable.match(/^---\s*$/gm);
  if (hrDelimiters && hrDelimiters.length >= 2) {
    return hrDelimiters.length + 1; // N delimiters = N+1 slides
  }

  // Third signal: H1/H2 headings as implicit slide breaks
  const headings = deliverable.match(/^#{1,2}\s+.+/gm);
  if (headings && headings.length >= 2) {
    return headings.length;
  }

  // Fallback: count substantial text blocks (>50 chars) separated by blank lines
  const blocks = deliverable.split(/\n\s*\n/).filter(b => b.trim().length > 50);
  return Math.max(1, blocks.length);
}

/**
 * Check if a section name is present in the deliverable (case-insensitive).
 * Uses fuzzy matching for common section synonyms (e.g., "cover" matches
 * "title slide", "slide 1", "opening", etc.).
 */
const SECTION_SYNONYMS: Record<string, string[]> = {
  cover: ["cover", "title slide", "title page", "opening slide", "opening", "slide 1"],
  "executive summary": ["executive summary", "exec summary", "overview", "summary"],
  conclusion: ["conclusion", "closing", "wrap-up", "wrap up", "next steps", "key takeaways"],
  "thank you": ["thank you", "thanks", "thank-you", "closing slide", "contact", "q&a"],
};

function sectionPresent(deliverable: string, section: string): boolean {
  const lower = deliverable.toLowerCase();
  // Check for heading with section name
  const headingPattern = new RegExp(`^#{1,3}\\s+.*${escapeRegex(section)}`, "im");
  if (headingPattern.test(deliverable)) return true;
  // Check for bold/emphasized section name
  if (lower.includes(section)) return true;
  // Check synonyms for common sections
  const synonyms = SECTION_SYNONYMS[section.toLowerCase()];
  if (synonyms) {
    for (const syn of synonyms) {
      if (syn === section.toLowerCase()) continue; // already checked
      const synPattern = new RegExp(`^#{1,3}\\s+.*${escapeRegex(syn)}`, "im");
      if (synPattern.test(deliverable)) return true;
      if (lower.includes(syn)) return true;
    }
  }
  // For "cover": also match if the first heading/slide exists (slide 1 is implicitly the cover)
  if (section.toLowerCase() === "cover") {
    const firstHeading = deliverable.match(/^#{1,3}\s+.+/m);
    const firstSlideDelim = deliverable.match(/^---\s*$/m);
    if (firstHeading || firstSlideDelim) return true;
  }
  return false;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// ─── Preflight Validator ─────────────────────────────────────────────────────

/**
 * Validate PPTX-bound deliverable BEFORE sending to Gamma.
 * Returns structured result. If !ok, caller should NOT invoke Gamma.
 */
export function validatePptxPreflight(
  deliverable: string,
  contract: ParsedContract | null,
): PreflightResult {
  const hardFailures: string[] = [];
  const softWarnings: string[] = [];

  // Gate 1: Non-empty
  if (!deliverable || deliverable.trim().length === 0) {
    return {
      ok: false,
      hardFailures: ["Deliverable is empty — nothing to send to Gamma"],
      softWarnings: [],
      derivedSlideCount: 0,
      summary: "Preflight FAILED: empty deliverable",
    };
  }

  const trimmed = deliverable.trim();

  // Gate 2: Minimum content length (slides need substance)
  if (trimmed.length < 200) {
    hardFailures.push(`Deliverable too short for slides (${trimmed.length} chars, minimum 200)`);
  }

  // Gate 3: Reject placeholder/shell output
  const lines = trimmed.split("\n").filter(l => l.trim().length > 0);
  const todoLines = lines.filter(l => /^\s*(?:\/\/|#|<!--)\s*(?:TODO|FIXME|PLACEHOLDER|STUB)/i.test(l));
  if (todoLines.length > lines.length * 0.4) {
    hardFailures.push("Deliverable is mostly placeholder/TODO content");
  }

  // Gate 4: Reject raw JSON or escaped payloads
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    const looksLikeJson = /^\s*[\[{]/.test(trimmed) && /[\]}]\s*$/.test(trimmed);
    if (looksLikeJson) {
      hardFailures.push("Deliverable is raw JSON — not slide content");
    }
  }
  if (/\\n.*\\n.*\\n/s.test(trimmed.slice(0, 500))) {
    hardFailures.push("Deliverable contains escaped newlines — not rendered content");
  }

  // Gate 5: Must have slide structure (headings, delimiters, or sections)
  const derivedSlideCount = estimateSlideCount(trimmed);

  // Detect single-slide intent: if only 1 segment but the content has structure
  // (headings, emphasis, bullets), treat it as a valid single-slide deliverable.
  // Single-slide WOs should not be forced through full-deck validation.
  const isSingleSlide = derivedSlideCount <= 1
    && (/^#{1,3}\s+/m.test(trimmed) || /^\*\*[^*]+\*\*/m.test(trimmed) || /^\s*[-*•]\s/m.test(trimmed))
    && trimmed.length >= 200;

  if (derivedSlideCount < 2 && !isSingleSlide) {
    hardFailures.push(`No slide structure detected (found ${derivedSlideCount} segment(s), need at least 2)`);
  }

  // Gate 6: Reject prose blobs with no segmentation
  const hasAnyStructure = /^#{1,3}\s+/m.test(trimmed) || /^---\s*$/m.test(trimmed) || /^\*\*[^*]+\*\*/m.test(trimmed);
  if (!hasAnyStructure && trimmed.length > 500) {
    hardFailures.push("Deliverable is an unsegmented prose blob — no headings, delimiters, or emphasis markers");
  }

  // Contract-based checks (only if contract exists)
  // Skip contract enforcement for single-slide deliverables — contract rules
  // (min slides, required sections) are deck-level concerns that don't apply.
  if (contract && !isSingleSlide) {
    // Slide count range
    if (derivedSlideCount < contract.minSlides) {
      hardFailures.push(`Slide count ${derivedSlideCount} is below contract minimum ${contract.minSlides}`);
    }
    if (derivedSlideCount > contract.maxSlides + 3) {
      // Allow some tolerance above max
      softWarnings.push(`Slide count ${derivedSlideCount} exceeds contract maximum ${contract.maxSlides}`);
    }

    // Required sections
    for (const section of contract.requiredSections) {
      if (!sectionPresent(trimmed, section)) {
        hardFailures.push(`Required section "${section}" not found in deliverable`);
      }
    }

    // Bullet density (soft warning only)
    if (contract.maxBulletsPerSlide) {
      const bulletHeavySlides = trimmed.split(/^#{1,2}\s+/m)
        .filter(segment => {
          const bullets = (segment.match(/^\s*[-*•]\s/gm) || []).length;
          return bullets > contract.maxBulletsPerSlide!;
        });
      if (bulletHeavySlides.length > 0) {
        softWarnings.push(`${bulletHeavySlides.length} slide(s) exceed ${contract.maxBulletsPerSlide} bullets`);
      }
    }
  } else if (contract && isSingleSlide) {
    softWarnings.push("Single-slide deliverable — deck-level contract checks skipped");
  }

  const ok = hardFailures.length === 0;
  const summary = ok
    ? `Preflight passed: ${derivedSlideCount} slides detected${contract ? ` (contract: ${contract.minSlides}-${contract.maxSlides})` : ""}`
    : `Preflight FAILED: ${hardFailures[0]}`;

  return { ok, hardFailures, softWarnings, derivedSlideCount, summary };
}

// ─── Post-Gamma Compliance ───────────────────────────────────────────────────

/**
 * Verify Gamma output after generation. Lightweight — no heavyweight PPTX parsing.
 * Checks file existence, size, MIME consistency, and contract compliance where possible.
 */
export function checkGammaCompliance(
  filePath: string,
  expectedMime: string,
  contract: ParsedContract | null,
  preflightSlideCount: number,
): GammaComplianceResult {
  const hardFailures: string[] = [];
  const softWarnings: string[] = [];

  // Check 1: File exists
  const fileExists = fs.existsSync(filePath);
  if (!fileExists) {
    return {
      ok: false,
      hardFailures: ["Generated PPTX file does not exist at expected path"],
      softWarnings: [],
      fileExists: false,
      fileSizeBytes: 0,
      mimeConsistent: false,
      estimatedSlideCount: null,
      contractSlideRange: contract ? { min: contract.minSlides, max: contract.maxSlides } : null,
      slideCountCompliant: null,
      summary: "Compliance FAILED: file missing",
    };
  }

  // Check 2: File size (PPTX should be at least ~10KB for even a minimal deck)
  const stats = fs.statSync(filePath);
  const fileSizeBytes = stats.size;
  if (fileSizeBytes < 5_000) {
    hardFailures.push(`PPTX file suspiciously small (${fileSizeBytes} bytes) — likely corrupt or empty`);
  }
  if (fileSizeBytes < 20_000) {
    softWarnings.push(`PPTX file is only ${(fileSizeBytes / 1024).toFixed(0)}KB — may have minimal content`);
  }

  // Check 3: Extension/MIME consistency
  const ext = filePath.split(".").pop()?.toLowerCase();
  const mimeConsistent = ext === "pptx" && expectedMime.includes("presentation");

  if (!mimeConsistent) {
    softWarnings.push(`File extension "${ext}" may not match expected MIME "${expectedMime}"`);
  }

  // Check 4: Slide count estimation from preflight
  // Phase 1: we don't parse the PPTX binary — use preflight estimate
  const estimatedSlideCount = preflightSlideCount > 0 ? preflightSlideCount : null;
  let slideCountCompliant: boolean | null = null;
  let contractSlideRange: { min: number; max: number } | null = null;

  if (contract && estimatedSlideCount !== null) {
    contractSlideRange = { min: contract.minSlides, max: contract.maxSlides };
    slideCountCompliant = estimatedSlideCount >= contract.minSlides && estimatedSlideCount <= contract.maxSlides + 3;
    if (!slideCountCompliant) {
      softWarnings.push(`Estimated ${estimatedSlideCount} slides vs contract range ${contract.minSlides}-${contract.maxSlides}`);
    }
  }

  const ok = hardFailures.length === 0;
  const summary = ok
    ? `Gamma compliance passed: ${(fileSizeBytes / 1024).toFixed(0)}KB${estimatedSlideCount ? `, ~${estimatedSlideCount} slides` : ""}${slideCountCompliant === false ? " (slide count warning)" : ""}`
    : `Gamma compliance FAILED: ${hardFailures[0]}`;

  return {
    ok,
    hardFailures,
    softWarnings,
    fileExists,
    fileSizeBytes,
    mimeConsistent,
    estimatedSlideCount,
    contractSlideRange,
    slideCountCompliant,
    summary,
  };
}

// ─── PPTX Review Supplement ──────────────────────────────────────────────────

/**
 * Build a PPTX-specific supplement for Aiden's quality review prompt.
 * Gives the LLM additional context about slide structure quality
 * so it can reject weak source even when a binary exists.
 */
export function buildPptxReviewSupplement(
  preflight: PreflightResult | null,
  compliance: GammaComplianceResult | null,
  contract: ParsedContract | null,
): string {
  const parts: string[] = [];

  parts.push("\n=== PPTX QUALITY SUPPLEMENT (evaluate slide-presentation fitness) ===");

  if (preflight) {
    parts.push(`Source preflight: ${preflight.ok ? "PASSED" : "FAILED"} — ${preflight.derivedSlideCount} slides detected.`);
    if (preflight.hardFailures.length > 0) {
      parts.push(`Preflight issues: ${preflight.hardFailures.join("; ")}`);
    }
    if (preflight.softWarnings.length > 0) {
      parts.push(`Preflight warnings: ${preflight.softWarnings.join("; ")}`);
    }
  }

  if (compliance) {
    parts.push(`Gamma output: ${compliance.ok ? "PASSED" : "FAILED"} — ${(compliance.fileSizeBytes / 1024).toFixed(0)}KB file.`);
    if (compliance.softWarnings.length > 0) {
      parts.push(`Compliance warnings: ${compliance.softWarnings.join("; ")}`);
    }
  }

  if (contract) {
    parts.push(`Content contract: ${contract.minSlides}-${contract.maxSlides} slides required.`);
    if (contract.requiredSections.length > 0) {
      parts.push(`Required sections: ${contract.requiredSections.join(", ")}`);
    }
  }

  parts.push("CRITICAL: Even though a PPTX binary exists, you MUST evaluate whether the SOURCE CONTENT is fit for slide presentation. Look for:");
  parts.push("- Adequate slide pacing (not too dense, not too sparse)");
  parts.push("- Clear section structure (title, body, transitions)");
  parts.push("- No text wall slides (>6 bullets or >100 words per slide)");
  parts.push("- No empty/placeholder slides");
  parts.push("If the source content would produce poor slides, recommend request_revision and describe the issues.");

  return parts.join("\n");
}

// ─── Slide Source Shaper ─────────────────────────────────────────────────────
// Restructures flat/messy LLM output into clean slide-segmented markdown
// suitable for Gamma. Runs between nodeBuildResponse and nodePostProcess.
//
// This is NOT an LLM call — it's deterministic text restructuring.

export interface ShapedResult {
  shaped: string;
  slideCount: number;
  actions: string[];
}

/**
 * Shape a raw deliverable into clean slide-segmented markdown for Gamma.
 *
 * What it does:
 * - Normalizes slide delimiters to consistent `---` separators
 * - Enforces one H1/H2 heading per slide
 * - Truncates bullet-heavy slides to max bullets
 * - Strips duplicate/redundant slide content
 * - Caps total slides to contract max (or 12 if no contract)
 * - Ensures a cover slide and closing slide exist
 *
 * What it does NOT do:
 * - Generate new content (no LLM call)
 * - Rewrite bullet text
 * - Change the order of sections
 */
export function shapeSlideSource(
  deliverable: string,
  contract: ParsedContract | null,
): ShapedResult {
  const actions: string[] = [];
  const maxSlides = contract?.maxSlides || 12;
  const maxBullets = contract?.maxBulletsPerSlide || 6;

  if (!deliverable || deliverable.trim().length < 50) {
    return { shaped: deliverable || "", slideCount: 0, actions: ["no-op: deliverable too short to shape"] };
  }

  // Step 1: Split into slide segments
  let segments = splitIntoSlides(deliverable);
  actions.push(`parsed ${segments.length} raw segments`);

  // Step 2: Deduplicate slides with similar titles
  segments = deduplicateSlides(segments, actions);

  // Step 3: Ensure cover slide
  if (segments.length > 0 && !looksLikeCover(segments[0])) {
    // Promote first slide to cover by adding "Cover" context if missing
    const first = segments[0];
    if (!first.heading.toLowerCase().includes("cover") && !first.heading.toLowerCase().includes("title")) {
      segments[0] = { ...first, heading: first.heading || "Cover" };
      actions.push("promoted first segment to cover slide");
    }
  }

  // Step 4: Enforce max bullets per slide
  for (let i = 0; i < segments.length; i++) {
    const trimmed = trimBullets(segments[i], maxBullets);
    if (trimmed.trimmedCount > 0) {
      segments[i] = trimmed.segment;
      actions.push(`slide ${i + 1}: trimmed ${trimmed.trimmedCount} excess bullets`);
    }
  }

  // Step 5: Cap total slide count
  if (segments.length > maxSlides) {
    const removed = segments.length - maxSlides;
    segments = segments.slice(0, maxSlides);
    actions.push(`capped from ${segments.length + removed} to ${maxSlides} slides`);
  }

  // Step 6: Ensure closing slide exists
  if (segments.length > 1) {
    const last = segments[segments.length - 1];
    const hasClosing = /thank|closing|contact|cta|call to action|next steps/i.test(last.heading + " " + last.body);
    if (!hasClosing) {
      // Don't fabricate — just note it
      actions.push("no closing slide detected (not fabricating)");
    }
  }

  // Step 7: Reassemble into clean slide-delimited markdown
  const shaped = segments.map(seg => {
    const heading = seg.heading ? `# ${seg.heading}\n\n` : "";
    return heading + seg.body.trim();
  }).join("\n\n---\n\n");

  actions.push(`shaped output: ${segments.length} slides`);

  return {
    shaped,
    slideCount: segments.length,
    actions,
  };
}

// ─── Internal shaper helpers ─────────────────────────────────────────────────

interface SlideSegment {
  heading: string;
  body: string;
}

/**
 * Split deliverable into slide segments using multiple delimiter strategies.
 */
function splitIntoSlides(text: string): SlideSegment[] {
  const trimmed = text.trim();

  // Strategy 1: Explicit "# Slide N:" headings
  const explicitSlidePattern = /^#{1,2}\s+(?:slide\s+)?\d+\s*[:.–—-]\s*/gim;
  if (explicitSlidePattern.test(trimmed)) {
    return splitByPattern(trimmed, /^#{1,2}\s+(?:slide\s+)?\d+\s*[:.–—-]\s*/gim);
  }

  // Strategy 2: HR delimiters (---)
  if (/^---\s*$/m.test(trimmed)) {
    const parts = trimmed.split(/^---\s*$/m).filter(p => p.trim().length > 0);
    return parts.map(part => {
      const headingMatch = part.trim().match(/^#{1,2}\s+(.+)/m);
      return {
        heading: headingMatch ? headingMatch[1].trim() : "",
        body: headingMatch ? part.trim().replace(/^#{1,2}\s+.+\n*/, "") : part.trim(),
      };
    });
  }

  // Strategy 3: H1/H2 headings as slide breaks
  const headingPattern = /^#{1,2}\s+.+$/gm;
  const headings = trimmed.match(headingPattern);
  if (headings && headings.length >= 2) {
    return splitByPattern(trimmed, /^#{1,2}\s+/gm);
  }

  // Strategy 4: Bold headings as slide breaks ("**Section Title**")
  const boldPattern = /^\*\*[^*]+\*\*\s*$/gm;
  const boldHeadings = trimmed.match(boldPattern);
  if (boldHeadings && boldHeadings.length >= 2) {
    return splitByBoldHeadings(trimmed);
  }

  // Fallback: treat entire text as one segment
  return [{ heading: "", body: trimmed }];
}

function splitByPattern(text: string, pattern: RegExp): SlideSegment[] {
  const lines = text.split("\n");
  const segments: SlideSegment[] = [];
  let currentHeading = "";
  let currentBody: string[] = [];

  for (const line of lines) {
    const isHeading = /^#{1,2}\s+/.test(line);
    if (isHeading) {
      if (currentHeading || currentBody.length > 0) {
        segments.push({ heading: currentHeading, body: currentBody.join("\n") });
      }
      currentHeading = line.replace(/^#{1,2}\s+/, "").replace(/^(?:slide\s+)?\d+\s*[:.–—-]\s*/i, "").trim();
      currentBody = [];
    } else {
      currentBody.push(line);
    }
  }
  if (currentHeading || currentBody.length > 0) {
    segments.push({ heading: currentHeading, body: currentBody.join("\n") });
  }

  return segments.filter(s => s.heading.length > 0 || s.body.trim().length > 0);
}

function splitByBoldHeadings(text: string): SlideSegment[] {
  const lines = text.split("\n");
  const segments: SlideSegment[] = [];
  let currentHeading = "";
  let currentBody: string[] = [];

  for (const line of lines) {
    const boldMatch = line.match(/^\*\*([^*]+)\*\*\s*$/);
    if (boldMatch) {
      if (currentHeading || currentBody.length > 0) {
        segments.push({ heading: currentHeading, body: currentBody.join("\n") });
      }
      currentHeading = boldMatch[1].trim();
      currentBody = [];
    } else {
      currentBody.push(line);
    }
  }
  if (currentHeading || currentBody.length > 0) {
    segments.push({ heading: currentHeading, body: currentBody.join("\n") });
  }

  return segments.filter(s => s.heading.length > 0 || s.body.trim().length > 0);
}

function looksLikeCover(seg: SlideSegment): boolean {
  const text = `${seg.heading} ${seg.body}`.toLowerCase();
  return /cover|title\s*slide|introduction|overview/i.test(text) && seg.body.trim().split("\n").length <= 5;
}

function deduplicateSlides(segments: SlideSegment[], actions: string[]): SlideSegment[] {
  const seen = new Set<string>();
  const result: SlideSegment[] = [];

  for (const seg of segments) {
    const key = seg.heading.toLowerCase().replace(/\s+/g, " ").trim();
    // Skip empty headings from dedup (they're structural)
    if (key.length > 3 && seen.has(key)) {
      actions.push(`removed duplicate slide: "${seg.heading}"`);
      continue;
    }
    if (key.length > 3) seen.add(key);
    result.push(seg);
  }

  return result;
}

function trimBullets(seg: SlideSegment, maxBullets: number): { segment: SlideSegment; trimmedCount: number } {
  const lines = seg.body.split("\n");
  const bulletLines: number[] = [];
  const nonBulletLines: number[] = [];

  lines.forEach((line, i) => {
    if (/^\s*[-*•]\s/.test(line) || /^\s*\d+[.)]\s/.test(line)) {
      bulletLines.push(i);
    } else {
      nonBulletLines.push(i);
    }
  });

  if (bulletLines.length <= maxBullets) {
    return { segment: seg, trimmedCount: 0 };
  }

  // Keep first maxBullets bullet lines, all non-bullet lines
  const keepBullets = new Set(bulletLines.slice(0, maxBullets));
  const keepNonBullets = new Set(nonBulletLines);
  const kept = lines.filter((_, i) => keepBullets.has(i) || keepNonBullets.has(i));

  return {
    segment: { heading: seg.heading, body: kept.join("\n") },
    trimmedCount: bulletLines.length - maxBullets,
  };
}

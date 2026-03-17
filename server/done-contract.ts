/**
 * Done Contract — Phase 1 Closeout Evaluator
 *
 * Deterministic closeout layer for IWO2 Work Orders and Workflows.
 * Four artifact tracks: Static Web Page, Software Artifact, Document, PPTX.
 * Governed HITL "Wrap It Up" override mode.
 *
 * Spec refs:
 *   AIDEN_IWO2_DONE_CONTRACT_CORE_SPEC_v0.1.0
 *   AIDEN_IWO2_STATIC_WEB_PAGE_DOD_v0.1.0
 *   AIDEN_IWO2_SOFTWARE_ARTIFACT_DOD_v0.1.0
 *   AIDEN_IWO2_DOCUMENT_DOD_v0.1.0
 *   AIDEN_IWO2_PPTX_DOD_v0.1.0
 *   AIDEN_IWO2_DONE_CONTRACT_IMPLEMENTATION_BRIEF_v0.1.0
 */

// ─── Types ───────────────────────────────────────────────────────────────────

export type ArtifactClass = "static_web_page" | "software_artifact" | "document" | "pptx" | "other";

export type StaticWebPageTier = "render_complete" | "interaction_complete";
export type SoftwareArtifactTier = "source_complete" | "preview_complete" | "build_complete" | "runtime_complete";
export type DocumentTier = "document_rendered" | "document_native";
export type PptxTier = "pptx_local" | "pptx_gamma";
export type ValidationTier = StaticWebPageTier | SoftwareArtifactTier | DocumentTier | PptxTier | "default";

export type TerminalState = "completed" | "awaiting_operator" | "blocked" | "failed";
export type RequiredNextAction = "none" | "request_revision" | "operator_review" | "candidate_selection" | "filing_retry" | "preview_retry";

export interface CloseoutEvidence {
  deliverablePresent: boolean;
  postProcessedFilePresent: boolean;
  qualityReviewResolved: boolean;
  candidateReviewPending: boolean;
  filingResolved: boolean;
  previewResolved: boolean;
  /** For software artifacts: does build/runtime evidence exist? */
  buildEvidencePresent?: boolean;
  runtimeEvidencePresent?: boolean;
  /** For document/PPTX: MIME type of postProcessedFile */
  postProcessedFileMimeType?: string;
  /** For PPTX/document: Gamma generation state */
  gammaState?: "none" | "success" | "candidate_review" | "failed";
}

export interface DoneDecision {
  scope: "work_order" | "workflow";
  artifactClass: ArtifactClass;
  validationTier: ValidationTier;
  done: boolean;
  terminalState: TerminalState;
  hardFailures: string[];
  softWarnings: string[];
  requiredNextAction: RequiredNextAction;
  closeoutReason: string;
  evidence: CloseoutEvidence;
  /** Present only when Wrap It Up was invoked */
  wrapItUp?: WrapItUpAudit;
}

/** Audit record for Wrap It Up decisions */
export interface WrapItUpAudit {
  invoked: true;
  operatorId: string;
  originalTier: ValidationTier;
  acceptedTier: ValidationTier;
  bypassed: string[];
  hardBlocksRetained: string[];
  reason: string;
}

/** Context object fed into the evaluator — built from existing runtime data. */
export interface CloseoutContext {
  scope: "work_order" | "workflow";
  /** Work order or workflow title / description for classification */
  title: string;
  description: string;
  /** The primary deliverable text (tier2Result.output.deliverable or workflow work product) */
  deliverable: string | null;
  deliverableType: string | null;
  /** Whether a postProcessedFile was generated */
  postProcessedFilePresent: boolean;
  /** MIME type of the postProcessedFile, if present */
  postProcessedFileMimeType?: string;
  /** Quality review outcome — null means not yet reviewed */
  qualityReview: { score: number; recommendation: string; issues: string[] } | null;
  /** Whether quality review explicitly blocked */
  qualityBlocked: boolean;
  /** Whether candidate review is still pending (awaiting_operator for Gamma candidates) */
  candidateReviewPending: boolean;
  /** Whether filing has been resolved (artifact exists or will be filed) */
  filingResolved: boolean;
  /** Sandbox/preview result if one exists */
  previewResult: { renderable?: boolean; error?: string } | null;
  /** Filed artifact records count */
  filedArtifactCount: number;
  /** For workflows: assembly output present */
  workflowAssemblyPresent?: boolean;
  /** For workflows: executive review resolved */
  executiveReviewResolved?: boolean;
  /** Gamma generation state for PPTX/document tracks */
  gammaState?: "none" | "success" | "candidate_review" | "failed";
  /** Whether Gamma fallback is blocked by locked template policy */
  gammaFallbackBlocked?: boolean;
  /** BUG-038: Gamma compliance result — false means hard compliance failure */
  gammaComplianceOk?: boolean;
  /** BUG-038: Gamma compliance hard failures */
  gammaComplianceFailures?: string[];
  /** BUG-042: Quality/executive review score — if below threshold, block completion */
  qualityScore?: number;
}

/** Options for Wrap It Up override mode */
export interface WrapItUpOptions {
  enabled: true;
  operatorId: string;
  reason: string;
}

// ─── Artifact Classification ─────────────────────────────────────────────────

const STATIC_WEB_PAGE_TRIGGERS = [
  "landing page", "mini-web page", "microsite", "marketing page",
  "single page site", "splash page", "promo page", "static page",
  "static web page", "mini web", "one-page site",
];

const SOFTWARE_ARTIFACT_TRIGGERS = [
  "web app", "webapp", "interactive website", "mobile app",
  "game", "simulation", "multi-route", "multi-screen",
  "dashboard app", "portal", "saas", "crud app",
  "interactive app", "application",
];

const PPTX_TRIGGERS = [
  "presentation", "slide deck", "pitch deck", "pptx",
  "powerpoint", "slides", "keynote deck",
];

const DOCUMENT_TRIGGERS = [
  "pdf", "report", "proposal", "briefing", "memo",
  "document", "whitepaper", "white paper", "brief",
  "docx", "written deliverable",
];

/**
 * Classify the artifact class from work order/workflow title + description.
 * Conservative: defaults to "other" if no strong signal.
 * Priority: software_artifact > pptx > document > static_web_page > other
 */
export function classifyArtifactClass(title: string, description: string): ArtifactClass {
  const text = `${title} ${description}`.toLowerCase();

  // Check software artifact triggers first (most specific)
  for (const trigger of SOFTWARE_ARTIFACT_TRIGGERS) {
    if (text.includes(trigger)) return "software_artifact";
  }

  // PPTX before document (PPTX is a dedicated class, not a generic document)
  for (const trigger of PPTX_TRIGGERS) {
    if (text.includes(trigger)) return "pptx";
  }

  // Document
  for (const trigger of DOCUMENT_TRIGGERS) {
    if (text.includes(trigger)) return "document";
  }

  // Static web page
  for (const trigger of STATIC_WEB_PAGE_TRIGGERS) {
    if (text.includes(trigger)) return "static_web_page";
  }

  return "other";
}

// ─── Validation Tier Resolution ──────────────────────────────────────────────

const INTERACTION_TRIGGERS = [
  "cta behavior", "nav behavior", "form interaction",
  "accordion", "tab reveal", "interactive element",
  "click handler", "form submit", "navigation menu",
];

const PREVIEW_TRIGGERS = ["preview", "demo", "prototype", "show me the interface", "visual demo"];
const BUILD_TRIGGERS = ["build", "compile", "production build", "bundled"];
const RUNTIME_TRIGGERS = ["run", "working app", "playable", "simulation works", "runnable", "executable"];

const NATIVE_DOC_TRIGGERS = [".doc", ".docx", "docx", "native document", "word document", "microsoft word"];

/**
 * Resolve the validation tier based on artifact class and prompt text.
 * Conservative: defaults to the lowest safe tier.
 */
export function resolveValidationTier(artifactClass: ArtifactClass, title: string, description: string): ValidationTier {
  const text = `${title} ${description}`.toLowerCase();

  if (artifactClass === "static_web_page") {
    for (const trigger of INTERACTION_TRIGGERS) {
      if (text.includes(trigger)) return "interaction_complete";
    }
    return "render_complete";
  }

  if (artifactClass === "software_artifact") {
    for (const trigger of RUNTIME_TRIGGERS) {
      if (text.includes(trigger)) return "runtime_complete";
    }
    for (const trigger of BUILD_TRIGGERS) {
      if (text.includes(trigger)) return "build_complete";
    }
    for (const trigger of PREVIEW_TRIGGERS) {
      if (text.includes(trigger)) return "preview_complete";
    }
    return "source_complete";
  }

  if (artifactClass === "document") {
    for (const trigger of NATIVE_DOC_TRIGGERS) {
      if (text.includes(trigger)) return "document_native";
    }
    return "document_rendered";
  }

  if (artifactClass === "pptx") {
    return "pptx_local"; // Gamma awareness is handled by evidence, not by tier name
  }

  return "default";
}

// ─── Structural Validators ───────────────────────────────────────────────────

/** Check if deliverable is a full HTML document (not just markdown describing one). */
export function isValidHtmlDeliverable(deliverable: string): boolean {
  if (!deliverable || deliverable.trim().length === 0) return false;

  const trimmed = deliverable.trim();

  const hasDoctype = trimmed.toLowerCase().startsWith("<!doctype");
  const hasHtmlTag = /<html[\s>]/i.test(trimmed);
  const hasBodyTag = /<body[\s>]/i.test(trimmed);

  if (hasDoctype || (hasHtmlTag && hasBodyTag)) {
    const bodyMatch = trimmed.match(/<body[^>]*>([\s\S]*)<\/body>/i);
    if (bodyMatch) {
      const bodyContent = bodyMatch[1].replace(/\s+/g, " ").trim();
      return bodyContent.length > 50;
    }
    return true;
  }

  return false;
}

/** Check if deliverable is placeholder/prose-only (not actual code/HTML). */
export function isPlaceholderOrProseOnly(deliverable: string): boolean {
  if (!deliverable || deliverable.trim().length === 0) return true;

  const trimmed = deliverable.trim();

  if (trimmed.length < 100) return true;

  const hasCodeBlock = /```[\s\S]+```/.test(trimmed);
  const hasHtmlTags = /<[a-z][a-z0-9]*[\s>]/i.test(trimmed);
  const hasCodePatterns = /(?:function\s|const\s|let\s|var\s|import\s|export\s|class\s|def\s|return\s)/i.test(trimmed);

  if (!hasCodeBlock && !hasHtmlTags && !hasCodePatterns) {
    return true;
  }

  const lines = trimmed.split("\n").filter(l => l.trim().length > 0);
  const todoLines = lines.filter(l => /^\s*(?:\/\/|#|<!--)\s*(?:TODO|FIXME|PLACEHOLDER|STUB)/i.test(l));
  if (todoLines.length > lines.length * 0.5) return true;

  return false;
}

/** Check for required HTML sections (conservative: only when prompt explicitly names them). */
export function checkRequiredSections(deliverable: string, title: string, description: string): string[] {
  const missing: string[] = [];
  const text = `${title} ${description}`.toLowerCase();
  const html = deliverable.toLowerCase();

  const sectionChecks: Array<{ trigger: string; patterns: RegExp[] }> = [
    { trigger: "hero", patterns: [/class="[^"]*hero/i, /id="[^"]*hero/i, /<section[^>]*hero/i, /<header/i] },
    { trigger: "cta", patterns: [/class="[^"]*cta/i, /id="[^"]*cta/i, /<button/i, /<a[^>]*class="[^"]*btn/i] },
    { trigger: "footer", patterns: [/<footer/i] },
    { trigger: "pricing", patterns: [/pric/i] },
    { trigger: "features", patterns: [/feature/i] },
  ];

  for (const check of sectionChecks) {
    if (text.includes(check.trigger)) {
      const found = check.patterns.some(p => p.test(html));
      if (!found) missing.push(check.trigger);
    }
  }

  return missing;
}

/** Check for primary interactions (CTA, nav, form) in HTML. */
export function checkPrimaryInteractions(deliverable: string, title: string, description: string): string[] {
  const missing: string[] = [];
  const text = `${title} ${description}`.toLowerCase();
  const html = deliverable.toLowerCase();

  if (text.includes("cta") || text.includes("call to action")) {
    const hasCta = /<button/i.test(html) || /<a[^>]*class="[^"]*btn/i.test(html) || /onclick/i.test(html);
    if (!hasCta) missing.push("CTA button");
  }

  if (text.includes("form")) {
    const hasForm = /<form/i.test(html) || /<input/i.test(html);
    if (!hasForm) missing.push("form");
  }

  if (text.includes("nav")) {
    const hasNav = /<nav/i.test(html) || /class="[^"]*nav/i.test(html);
    if (!hasNav) missing.push("navigation");
  }

  return missing;
}

/** Check if software output has minimum structure (entry file, app shell). */
export function hasSoftwareStructure(deliverable: string): boolean {
  if (!deliverable || deliverable.trim().length < 100) return false;

  const patterns = [
    /(?:function|const|let|var|class|def|import|export|require)\s/,
    /<[a-z][a-z0-9]*[\s>]/i,
    /\{[\s\S]*\}/,
  ];

  const matchCount = patterns.filter(p => p.test(deliverable)).length;
  return matchCount >= 1;
}

/** Check if deliverable has real document content (headings, paragraphs, structure). */
export function hasDocumentContent(deliverable: string): boolean {
  if (!deliverable || deliverable.trim().length < 100) return false;

  const trimmed = deliverable.trim();

  // Markdown headings
  const hasHeadings = /^#{1,3}\s+\S/m.test(trimmed);
  // Multiple paragraphs (2+ non-empty lines separated by blank lines)
  const paragraphs = trimmed.split(/\n\s*\n/).filter(p => p.trim().length > 30);
  const hasParagraphs = paragraphs.length >= 2;
  // Structured content: lists, tables, blockquotes
  const hasLists = /^[\s]*[-*]\s/m.test(trimmed) || /^\d+\.\s/m.test(trimmed);

  return (hasHeadings && hasParagraphs) || (hasParagraphs && hasLists) || paragraphs.length >= 3;
}

/** Check MIME type matches expected binary format */
function mimeMatchesPptx(mime: string | undefined): boolean {
  if (!mime) return false;
  return mime.includes("presentation") || mime.includes("pptx") || mime.includes("powerpoint");
}

function mimeMatchesPdf(mime: string | undefined): boolean {
  if (!mime) return false;
  return mime.includes("pdf");
}

function mimeMatchesNativeDoc(mime: string | undefined): boolean {
  if (!mime) return false;
  return mime.includes("msword") || mime.includes("wordprocessingml") || mime.includes("docx") || mime.includes("doc");
}

// ─── Static Web Page Evaluator ───────────────────────────────────────────────

function evaluateStaticWebPage(ctx: CloseoutContext, tier: StaticWebPageTier): Partial<DoneDecision> {
  const hardFailures: string[] = [];
  const softWarnings: string[] = [];

  if (!ctx.deliverable) {
    hardFailures.push("No deliverable output present");
  } else {
    if (!isValidHtmlDeliverable(ctx.deliverable)) {
      if (!ctx.filedArtifactCount && !ctx.postProcessedFilePresent) {
        hardFailures.push("Output is not a valid HTML document and no filed HTML artifact exists");
      }
    }

    if (isPlaceholderOrProseOnly(ctx.deliverable) && !ctx.postProcessedFilePresent && !ctx.filedArtifactCount) {
      hardFailures.push("Output is prose/placeholder — not an actual web page");
    }

    if (ctx.deliverable && isValidHtmlDeliverable(ctx.deliverable)) {
      const missingSections = checkRequiredSections(ctx.deliverable, ctx.title, ctx.description);
      if (missingSections.length > 0) {
        hardFailures.push(`Required section(s) missing: ${missingSections.join(", ")}`);
      }
    }

    if (tier === "interaction_complete" && ctx.deliverable) {
      const missingInteractions = checkPrimaryInteractions(ctx.deliverable, ctx.title, ctx.description);
      if (missingInteractions.length > 0) {
        hardFailures.push(`Required interaction(s) missing: ${missingInteractions.join(", ")}`);
      }
    }
  }

  if (!ctx.filingResolved) {
    hardFailures.push("Filing not yet resolved");
  }

  return { hardFailures, softWarnings };
}

// ─── Software Artifact Evaluator ─────────────────────────────────────────────

function evaluateSoftwareArtifact(ctx: CloseoutContext, tier: SoftwareArtifactTier): Partial<DoneDecision> {
  const hardFailures: string[] = [];
  const softWarnings: string[] = [];

  if (!ctx.deliverable) {
    hardFailures.push("No source output present");
  } else {
    if (isPlaceholderOrProseOnly(ctx.deliverable) && !ctx.postProcessedFilePresent && !ctx.filedArtifactCount) {
      hardFailures.push("Output is prose/placeholder — not actual software");
    }
    if (!hasSoftwareStructure(ctx.deliverable) && !ctx.postProcessedFilePresent && !ctx.filedArtifactCount) {
      hardFailures.push("Output lacks minimum software structure");
    }
  }

  if (tier === "preview_complete") {
    const hasPreview = ctx.previewResult?.renderable || ctx.filedArtifactCount > 0;
    if (!hasPreview) {
      hardFailures.push("Preview requested but no preview evidence exists");
    }
  }

  if (tier === "build_complete") {
    hardFailures.push("Build validation requested but no build evidence available in phase 1");
  }

  if (tier === "runtime_complete") {
    hardFailures.push("Runtime validation requested but no runtime evidence available in phase 1");
  }

  if (!ctx.filingResolved) {
    hardFailures.push("Filing not yet resolved");
  }

  return { hardFailures, softWarnings };
}

// ─── Document Evaluator ──────────────────────────────────────────────────────

function evaluateDocument(ctx: CloseoutContext, tier: DocumentTier): Partial<DoneDecision> {
  const hardFailures: string[] = [];
  const softWarnings: string[] = [];

  // Gate 1: Content deliverable must exist
  if (!ctx.deliverable) {
    hardFailures.push("No document content present");
  } else {
    // Check for placeholder / structurally invalid content
    if (isPlaceholderOrProseOnly(ctx.deliverable) && !ctx.postProcessedFilePresent && !ctx.filedArtifactCount) {
      // For documents, "prose" IS the content — but it must have real structure
      if (!hasDocumentContent(ctx.deliverable)) {
        hardFailures.push("Output is placeholder/shell — not a real document");
      }
    }
  }

  // Gate 2: Format-specific evidence
  if (tier === "document_rendered") {
    // PDF or rendered format required — check for binary evidence
    const textForPdf = `${ctx.title} ${ctx.description}`.toLowerCase();
    const explicitlyPdf = textForPdf.includes("pdf");

    if (explicitlyPdf) {
      // Must have a PDF binary
      const hasPdfBinary = ctx.postProcessedFilePresent && mimeMatchesPdf(ctx.postProcessedFileMimeType);
      const hasPdfArtifact = ctx.filedArtifactCount > 0; // filed artifact may be the PDF
      if (!hasPdfBinary && !hasPdfArtifact) {
        hardFailures.push("PDF explicitly required but no PDF binary exists");
      }
    }
    // If not explicitly PDF, markdown/HTML document content is sufficient
  }

  if (tier === "document_native") {
    // Must have a native DOC/DOCX file
    const hasNativeFile = ctx.postProcessedFilePresent && mimeMatchesNativeDoc(ctx.postProcessedFileMimeType);
    if (!hasNativeFile) {
      hardFailures.push("Native DOC/DOCX explicitly required but no native file evidence exists");
    }
  }

  // Gate 3: Gamma candidate review (for Gamma-generated documents)
  if (ctx.gammaState === "candidate_review" && ctx.candidateReviewPending) {
    // Already handled by shared gate, but reinforce
  }
  if (ctx.gammaState === "failed" && ctx.gammaFallbackBlocked) {
    hardFailures.push("Gamma generation failed and fallback is blocked by locked template policy");
  }

  // Gate 4: Filing
  if (!ctx.filingResolved) {
    hardFailures.push("Filing not yet resolved");
  }

  return { hardFailures, softWarnings };
}

// ─── PPTX Evaluator ─────────────────────────────────────────────────────────

function evaluatePptx(ctx: CloseoutContext): Partial<DoneDecision> {
  const hardFailures: string[] = [];
  const softWarnings: string[] = [];

  // Gate 1: Slide content must exist
  if (!ctx.deliverable) {
    hardFailures.push("No slide content present");
  } else {
    if (isPlaceholderOrProseOnly(ctx.deliverable) && !ctx.postProcessedFilePresent && !ctx.filedArtifactCount) {
      hardFailures.push("Output is placeholder/shell — not valid slide content");
    }
  }

  // Gate 2: PPTX binary must exist
  const hasPptxBinary = ctx.postProcessedFilePresent && mimeMatchesPptx(ctx.postProcessedFileMimeType);
  const hasPptxArtifact = ctx.filedArtifactCount > 0; // filed artifact may be the PPTX

  if (!hasPptxBinary && !hasPptxArtifact) {
    hardFailures.push("PPTX binary missing — markdown exists but no PPTX file was generated");
  }

  // Gate 3: Gamma-specific rules
  if (ctx.gammaState === "failed" && ctx.gammaFallbackBlocked) {
    hardFailures.push("Gamma generation failed and fallback is blocked by locked template policy");
  }

  // Gate 4: BUG-038 — Gamma compliance evidence
  if (ctx.gammaComplianceOk === false && ctx.gammaComplianceFailures?.length) {
    for (const f of ctx.gammaComplianceFailures) {
      hardFailures.push(`Gamma compliance: ${f}`);
    }
  }

  // Gate 5: Filing
  if (!ctx.filingResolved) {
    hardFailures.push("Filing not yet resolved");
  }

  return { hardFailures, softWarnings };
}

// ─── Shared Closeout Logic ───────────────────────────────────────────────────

function resolveTerminalState(hardFailures: string[], ctx: CloseoutContext): { terminalState: TerminalState; requiredNextAction: RequiredNextAction } {
  if (hardFailures.length === 0) {
    return { terminalState: "completed", requiredNextAction: "none" };
  }

  // Candidate review pending → awaiting_operator
  if (ctx.candidateReviewPending) {
    return { terminalState: "awaiting_operator", requiredNextAction: "candidate_selection" };
  }

  // Quality block → blocked
  if (ctx.qualityBlocked) {
    return { terminalState: "blocked", requiredNextAction: "request_revision" };
  }

  // Gamma failed with locked policy → blocked
  if (ctx.gammaState === "failed" && ctx.gammaFallbackBlocked) {
    return { terminalState: "blocked", requiredNextAction: "operator_review" };
  }

  // Filing failure → failed if unrecoverable
  const filingFailure = hardFailures.some(f => f.includes("Filing"));
  if (filingFailure && !ctx.deliverable) {
    return { terminalState: "failed", requiredNextAction: "filing_retry" };
  }

  // Runtime/build/preview evidence missing → awaiting_operator
  const evidenceMissing = hardFailures.some(f =>
    f.includes("preview evidence") || f.includes("build evidence") || f.includes("runtime evidence")
  );
  if (evidenceMissing) {
    return { terminalState: "awaiting_operator", requiredNextAction: "operator_review" };
  }

  // Missing required binary (PDF/PPTX/DOCX) → awaiting_operator
  const binaryMissing = hardFailures.some(f =>
    f.includes("PDF binary") || f.includes("PPTX binary") || f.includes("native file evidence") || f.includes("no PDF") || f.includes("no PPTX")
  );
  if (binaryMissing) {
    return { terminalState: "awaiting_operator", requiredNextAction: "operator_review" };
  }

  // BUG-042: Low quality score → awaiting_operator
  const qualityScoreFailure = hardFailures.some(f => f.includes("Quality score"));
  if (qualityScoreFailure) {
    return { terminalState: "awaiting_operator", requiredNextAction: "operator_review" };
  }

  // Structural / section failures → awaiting_operator
  const structuralFailure = hardFailures.some(f =>
    f.includes("not a valid HTML") || f.includes("prose/placeholder") ||
    f.includes("section(s) missing") || f.includes("interaction(s) missing") ||
    f.includes("lacks minimum software structure") ||
    f.includes("placeholder/shell")
  );
  if (structuralFailure) {
    return { terminalState: "awaiting_operator", requiredNextAction: "request_revision" };
  }

  // Unresolved filing with deliverable present → awaiting_operator
  if (filingFailure) {
    return { terminalState: "awaiting_operator", requiredNextAction: "filing_retry" };
  }

  return { terminalState: "failed", requiredNextAction: "operator_review" };
}

// ─── Wrap It Up ──────────────────────────────────────────────────────────────

/**
 * Hard-block categories that Wrap It Up must NEVER bypass.
 * These are policy/safety blocks, not quality preferences.
 */
const WRAP_IT_UP_HARD_BLOCKS = [
  "Quality review blocked",
  "Candidate review still pending",
  "Gamma generation failed and fallback is blocked",
  "No deliverable output present",
  "No source output present",
  "No document content present",
  "No slide content present",
];

/**
 * Determines if a hard failure is a policy/safety block that Wrap It Up cannot bypass.
 */
function isHardPolicyBlock(failure: string): boolean {
  return WRAP_IT_UP_HARD_BLOCKS.some(block => failure.includes(block));
}

/**
 * For software artifacts: find the best viable tier that can actually be satisfied.
 * Walks down from the requested tier to the lowest (source_complete).
 */
function findViableSoftwareTier(ctx: CloseoutContext, requestedTier: SoftwareArtifactTier): SoftwareArtifactTier {
  const tierOrder: SoftwareArtifactTier[] = ["runtime_complete", "build_complete", "preview_complete", "source_complete"];
  const requestedIdx = tierOrder.indexOf(requestedTier);

  for (let i = requestedIdx; i < tierOrder.length; i++) {
    const tier = tierOrder[i];
    if (tier === "source_complete") return tier; // always viable if source exists
    if (tier === "preview_complete" && (ctx.previewResult?.renderable || ctx.filedArtifactCount > 0)) return tier;
    // build_complete and runtime_complete have no phase-1 evidence path — skip
  }

  return "source_complete";
}

/**
 * For documents: find the best viable format based on what actually exists.
 */
function findViableDocumentTier(ctx: CloseoutContext, requestedTier: DocumentTier): DocumentTier {
  if (requestedTier === "document_native") {
    // If native file exists, keep it
    if (ctx.postProcessedFilePresent && mimeMatchesNativeDoc(ctx.postProcessedFileMimeType)) {
      return "document_native";
    }
    // Fall back to rendered if there's a PDF or deliverable content
    if (ctx.postProcessedFilePresent || ctx.filedArtifactCount > 0 || ctx.deliverable) {
      return "document_rendered";
    }
  }
  return requestedTier;
}

/**
 * Apply Wrap It Up override to a normal DoneDecision.
 * Returns a new decision with bypassed soft/non-critical failures and an audit trail.
 */
function applyWrapItUp(
  normalDecision: DoneDecision,
  ctx: CloseoutContext,
  options: WrapItUpOptions,
): DoneDecision {
  // If already completed, nothing to do
  if (normalDecision.done) {
    return {
      ...normalDecision,
      wrapItUp: {
        invoked: true,
        operatorId: options.operatorId,
        originalTier: normalDecision.validationTier,
        acceptedTier: normalDecision.validationTier,
        bypassed: [],
        hardBlocksRetained: [],
        reason: `${options.reason} (already completed — no override needed)`,
      },
    };
  }

  // Separate policy blocks from bypassable failures
  const policyBlocks = normalDecision.hardFailures.filter(isHardPolicyBlock);
  const bypassable = normalDecision.hardFailures.filter(f => !isHardPolicyBlock(f));

  // If policy blocks remain, Wrap It Up cannot complete
  if (policyBlocks.length > 0) {
    return {
      ...normalDecision,
      wrapItUp: {
        invoked: true,
        operatorId: options.operatorId,
        originalTier: normalDecision.validationTier,
        acceptedTier: normalDecision.validationTier,
        bypassed: [],
        hardBlocksRetained: policyBlocks,
        reason: `${options.reason} — blocked by non-bypassable policy: ${policyBlocks[0]}`,
      },
    };
  }

  // Try to find a viable lower tier for software artifacts
  let acceptedTier = normalDecision.validationTier;
  if (normalDecision.artifactClass === "software_artifact") {
    acceptedTier = findViableSoftwareTier(ctx, normalDecision.validationTier as SoftwareArtifactTier);
  }

  // Try to find a viable format for documents
  if (normalDecision.artifactClass === "document") {
    acceptedTier = findViableDocumentTier(ctx, normalDecision.validationTier as DocumentTier);
  }

  // For PPTX: if binary is missing, Wrap It Up cannot pretend it exists
  if (normalDecision.artifactClass === "pptx") {
    const pptxBinaryMissing = bypassable.some(f => f.includes("PPTX binary"));
    if (pptxBinaryMissing && !ctx.postProcessedFilePresent && !ctx.filedArtifactCount) {
      return {
        ...normalDecision,
        wrapItUp: {
          invoked: true,
          operatorId: options.operatorId,
          originalTier: normalDecision.validationTier,
          acceptedTier: normalDecision.validationTier,
          bypassed: [],
          hardBlocksRetained: ["PPTX binary missing — cannot pretend file exists"],
          reason: `${options.reason} — PPTX binary does not exist, cannot force completion`,
        },
      };
    }
  }

  // Re-evaluate with bypassed failures removed
  // Filing-not-resolved is bypassable if filing is about to happen
  const remainingFailures = bypassable.filter(f => {
    // Tier-evidence failures are bypassable if we accepted a lower tier
    if (f.includes("preview evidence") && acceptedTier === "source_complete") return false;
    if (f.includes("build evidence") && (acceptedTier === "source_complete" || acceptedTier === "preview_complete")) return false;
    if (f.includes("runtime evidence") && acceptedTier !== "runtime_complete") return false;
    // Section/interaction failures are bypassable (non-critical)
    if (f.includes("section(s) missing")) return false;
    if (f.includes("interaction(s) missing")) return false;
    // Missing PDF binary when we accept rendered format
    if (f.includes("PDF") && acceptedTier === "document_rendered") return false;
    // Missing native doc evidence when we accept rendered
    if (f.includes("native file evidence") && acceptedTier === "document_rendered") return false;
    // Structural warnings for documents where content exists
    if (f.includes("placeholder/shell") && ctx.deliverable && ctx.deliverable.trim().length > 200) return false;
    return true;
  });

  const bypassed = bypassable.filter(f => !remainingFailures.includes(f));

  if (remainingFailures.length > 0) {
    // Still can't complete even with Wrap It Up
    return {
      ...normalDecision,
      terminalState: "awaiting_operator" as TerminalState,
      wrapItUp: {
        invoked: true,
        operatorId: options.operatorId,
        originalTier: normalDecision.validationTier,
        acceptedTier,
        bypassed,
        hardBlocksRetained: remainingFailures,
        reason: `${options.reason} — remaining issues: ${remainingFailures[0]}`,
      },
    };
  }

  // All failures bypassed — complete
  return {
    ...normalDecision,
    done: true,
    terminalState: "completed",
    hardFailures: [], // cleared by override
    requiredNextAction: "none",
    validationTier: acceptedTier,
    closeoutReason: `Wrap It Up: operator ${options.operatorId} accepted ${normalDecision.artifactClass} at ${acceptedTier} (original: ${normalDecision.validationTier})`,
    wrapItUp: {
      invoked: true,
      operatorId: options.operatorId,
      originalTier: normalDecision.validationTier,
      acceptedTier,
      bypassed,
      hardBlocksRetained: [],
      reason: options.reason,
    },
  };
}

// ─── Main Evaluator ──────────────────────────────────────────────────────────

/**
 * Evaluate the Done Contract for a Work Order or Workflow.
 * Returns a deterministic closeout decision.
 *
 * When wrapItUp is provided, the evaluator runs the normal contract first,
 * then applies the governed HITL override.
 */
export function evaluateDoneContract(ctx: CloseoutContext, wrapItUp?: WrapItUpOptions): DoneDecision {
  // Step 1: Classify artifact
  const artifactClass = classifyArtifactClass(ctx.title, ctx.description);

  // Step 2: Resolve validation tier
  const validationTier = resolveValidationTier(artifactClass, ctx.title, ctx.description);

  // Step 3: Build evidence snapshot
  const evidence: CloseoutEvidence = {
    deliverablePresent: !!ctx.deliverable && ctx.deliverable.trim().length > 0,
    postProcessedFilePresent: ctx.postProcessedFilePresent,
    qualityReviewResolved: ctx.qualityReview !== null && !ctx.qualityBlocked,
    candidateReviewPending: ctx.candidateReviewPending,
    filingResolved: ctx.filingResolved,
    previewResolved: ctx.previewResult ? (ctx.previewResult.renderable === true) : true,
    postProcessedFileMimeType: ctx.postProcessedFileMimeType,
    gammaState: ctx.gammaState,
  };

  // Step 4: Shared hard-failure checks
  let hardFailures: string[] = [];
  let softWarnings: string[] = [];

  if (ctx.qualityBlocked) {
    hardFailures.push("Quality review blocked the artifact");
  }
  if (ctx.candidateReviewPending) {
    hardFailures.push("Candidate review still pending");
  }
  // BUG-042: Block completion when quality/exec review score is below threshold
  const DONE_CONTRACT_MIN_SCORE = 0.50;
  if (ctx.qualityScore !== undefined && ctx.qualityScore < DONE_CONTRACT_MIN_SCORE) {
    hardFailures.push(`Quality score ${ctx.qualityScore.toFixed(2)} is below minimum ${DONE_CONTRACT_MIN_SCORE} for completion`);
  }

  // Step 5: Artifact-specific evaluation
  if (artifactClass === "static_web_page") {
    const result = evaluateStaticWebPage(ctx, validationTier as StaticWebPageTier);
    hardFailures.push(...(result.hardFailures || []));
    softWarnings.push(...(result.softWarnings || []));
  } else if (artifactClass === "software_artifact") {
    const result = evaluateSoftwareArtifact(ctx, validationTier as SoftwareArtifactTier);
    hardFailures.push(...(result.hardFailures || []));
    softWarnings.push(...(result.softWarnings || []));
  } else if (artifactClass === "document") {
    const result = evaluateDocument(ctx, validationTier as DocumentTier);
    hardFailures.push(...(result.hardFailures || []));
    softWarnings.push(...(result.softWarnings || []));
  } else if (artifactClass === "pptx") {
    const result = evaluatePptx(ctx);
    hardFailures.push(...(result.hardFailures || []));
    softWarnings.push(...(result.softWarnings || []));
  } else {
    // "other" — minimal shared checks only
    if (!ctx.deliverable && !ctx.postProcessedFilePresent && !ctx.filedArtifactCount) {
      hardFailures.push("No deliverable output present");
    }
    if (!ctx.filingResolved) {
      hardFailures.push("Filing not yet resolved");
    }
  }

  // Step 6: Workflow-specific gates
  if (ctx.scope === "workflow") {
    if (ctx.workflowAssemblyPresent === false) {
      hardFailures.push("Workflow assembly not yet complete");
    }
    if (ctx.executiveReviewResolved === false) {
      hardFailures.push("Executive review not yet resolved");
    }
  }

  // Deduplicate
  hardFailures = [...new Set(hardFailures)];

  // Step 7: Terminal state resolution
  const { terminalState, requiredNextAction } = resolveTerminalState(hardFailures, ctx);
  const done = terminalState === "completed";

  const closeoutReason = done
    ? `Closeout passed: ${artifactClass} at ${validationTier}`
    : `Closeout blocked: ${hardFailures[0] || "unknown"}`;

  const normalDecision: DoneDecision = {
    scope: ctx.scope,
    artifactClass,
    validationTier,
    done,
    terminalState,
    hardFailures,
    softWarnings,
    requiredNextAction,
    closeoutReason,
    evidence,
  };

  // Step 8: Apply Wrap It Up if requested
  if (wrapItUp) {
    return applyWrapItUp(normalDecision, ctx, wrapItUp);
  }

  return normalDecision;
}

// ─── Context Builder Helpers ─────────────────────────────────────────────────

/**
 * Build a CloseoutContext from a work order's existing runtime data.
 * Designed to be called from orchestration.ts with data already in hand.
 */
export function buildWorkOrderCloseoutContext(
  order: {
    title: string;
    description: string;
    tier2Result: any;
    status: string;
  },
  extra: {
    filedArtifactCount: number;
    candidateReviewPending: boolean;
    previewResult?: { renderable?: boolean; error?: string } | null;
    /** True when filing is guaranteed to happen next (e.g. inside completeAndFileWorkOrder) */
    filingWillResolve?: boolean;
    /** Gamma generation state */
    gammaState?: "none" | "success" | "candidate_review" | "failed";
    /** Whether Gamma fallback is blocked by locked template */
    gammaFallbackBlocked?: boolean;
    /** BUG-038: Gamma compliance result */
    gammaComplianceOk?: boolean;
    gammaComplianceFailures?: string[];
    /** BUG-042: Quality/exec review score */
    qualityScore?: number;
  }
): CloseoutContext {
  const tier2 = order.tier2Result;
  const output = tier2?.output;
  const qr = tier2?.qualityReview || null;
  const ppf = output?.postProcessedFile;

  return {
    scope: "work_order",
    title: order.title || "",
    description: order.description || "",
    deliverable: output?.deliverable || null,
    deliverableType: output?.deliverableType || null,
    postProcessedFilePresent: !!ppf,
    postProcessedFileMimeType: ppf?.mimeType || undefined,
    qualityReview: qr,
    qualityBlocked: qr?.recommendation === "block",
    candidateReviewPending: extra.candidateReviewPending,
    filingResolved: extra.filingWillResolve || extra.filedArtifactCount > 0 || order.status === "completed",
    previewResult: extra.previewResult || null,
    filedArtifactCount: extra.filedArtifactCount,
    gammaState: extra.gammaState || "none",
    gammaFallbackBlocked: extra.gammaFallbackBlocked || false,
    gammaComplianceOk: extra.gammaComplianceOk,
    gammaComplianceFailures: extra.gammaComplianceFailures,
    qualityScore: extra.qualityScore,
  };
}

/**
 * Build a CloseoutContext from workflow completion data.
 */
export function buildWorkflowCloseoutContext(
  order: {
    title: string;
    description: string;
  },
  workProduct: {
    deliverable: string;
    deliverableType: string;
    deliverableTitle: string;
    summary?: string;
  } | null,
  extra: {
    postProcessedFilePresent: boolean;
    postProcessedFileMimeType?: string;
    filedArtifactCount: number;
    candidateReviewPending: boolean;
    executiveReviewResolved: boolean;
    previewResult?: { renderable?: boolean; error?: string } | null;
    gammaState?: "none" | "success" | "candidate_review" | "failed";
    gammaFallbackBlocked?: boolean;
  }
): CloseoutContext {
  return {
    scope: "workflow",
    title: order.title || "",
    description: order.description || "",
    deliverable: workProduct?.deliverable || null,
    deliverableType: workProduct?.deliverableType || null,
    postProcessedFilePresent: extra.postProcessedFilePresent,
    postProcessedFileMimeType: extra.postProcessedFileMimeType,
    qualityReview: null,
    qualityBlocked: false,
    candidateReviewPending: extra.candidateReviewPending,
    filingResolved: extra.filedArtifactCount > 0 || true,
    previewResult: extra.previewResult || null,
    filedArtifactCount: extra.filedArtifactCount,
    workflowAssemblyPresent: workProduct !== null,
    executiveReviewResolved: extra.executiveReviewResolved,
    gammaState: extra.gammaState || "none",
    gammaFallbackBlocked: extra.gammaFallbackBlocked || false,
  };
}

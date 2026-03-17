/**
 * PPTX Quality — BUG-038 Tests
 *
 * Covers: preflight rejection, contract parsing, Gamma compliance,
 * review supplement, Done Contract interaction, preview labeling.
 */

import { describe, it, expect } from "vitest";
import {
  validatePptxPreflight,
  parseContentContract,
  estimateSlideCount,
  checkGammaCompliance,
  buildPptxReviewSupplement,
  shapeSlideSource,
  type PreflightResult,
  type GammaComplianceResult,
  type ParsedContract,
} from "../pptx-quality.js";

import { evaluateDoneContract, type CloseoutContext } from "../done-contract.js";

// ─── Fixtures ────────────────────────────────────────────────────────────────

const GOOD_SLIDE_MD = `# Slide 1: Cover

**Klear.ai** — AI-Powered Workforce Intelligence

---

# Slide 2: What We Do

- Consolidates workforce data into a single platform
- Predictive analytics boost fill rates by 40%
- Revenue intelligence surfaces margin erosion

---

# Slide 3: Key Metrics

- ARR: $12M
- Customers: 500+
- Churn: 1.8%

---

# Slide 4: Call to Action

Schedule a live demo today.
Contact: sales@klear.ai
`;

const WEAK_SLIDE_MD = "Make a presentation about our company.";

const PROSE_BLOB = `Klear.ai is a workforce intelligence platform that helps staffing organizations consolidate their data, leverage predictive analytics, and improve operational efficiency. The company was founded in 2020 and has grown to serve over 500 customers. Revenue has been growing at 20% quarter over quarter. The platform integrates with existing staffing tech stacks and provides automated compliance monitoring that reduces audit effort by 70%. The team consists of over 200 employees across three offices. Recent awards include Best Workforce Analytics Platform 2025.`;

const JSON_PAYLOAD = `{"slides": [{"title": "Cover", "content": "Klear.ai"}, {"title": "Features", "content": "Analytics"}]}`;

const TODO_CONTENT = `// TODO: Add slide 1 content
// PLACEHOLDER: Cover slide
// TODO: Add features section
// STUB: Pricing slide
// FIXME: Need real data
// TODO: Call to action
const slides = [];`;

const KLEAR_CONTRACT = `Slides: 5-8
Required sections: Cover, Executive Summary, 2-4 content slides, Thank You
Max 5 bullets per slide`;

// ─── Contract Parser ─────────────────────────────────────────────────────────

describe("parseContentContract()", () => {
  it("parses slide range from 'Slides: 5-8'", () => {
    const result = parseContentContract(KLEAR_CONTRACT);
    expect(result.minSlides).toBe(5);
    expect(result.maxSlides).toBe(8);
  });

  it("parses required sections", () => {
    const result = parseContentContract(KLEAR_CONTRACT);
    expect(result.requiredSections).toContain("cover");
    expect(result.requiredSections).toContain("executive summary");
    expect(result.requiredSections).toContain("thank you");
  });

  it("parses max bullets per slide", () => {
    const result = parseContentContract(KLEAR_CONTRACT);
    expect(result.maxBulletsPerSlide).toBe(5);
  });

  it("returns defaults for null contract", () => {
    const result = parseContentContract(null);
    expect(result.minSlides).toBe(3);
    expect(result.maxSlides).toBe(20);
    expect(result.requiredSections).toEqual([]);
  });

  it("returns defaults for empty string", () => {
    const result = parseContentContract("");
    expect(result.minSlides).toBe(3);
    expect(result.maxSlides).toBe(20);
  });

  it("parses 'between 3 and 6 slides'", () => {
    const result = parseContentContract("between 3 and 6 slides");
    expect(result.minSlides).toBe(3);
    expect(result.maxSlides).toBe(6);
  });

  it("strips parenthetical annotations from section names", () => {
    const result = parseContentContract("Required sections: Cover (title + subtitle + date), Executive Summary (key metrics), Thank You (contact info)");
    expect(result.requiredSections).toContain("cover");
    expect(result.requiredSections).toContain("executive summary");
    expect(result.requiredSections).toContain("thank you");
    expect(result.requiredSections.some(s => s.includes("("))).toBe(false);
  });

  it("drops numeric-prefixed entries like '2-4 content slides'", () => {
    const result = parseContentContract(KLEAR_CONTRACT);
    expect(result.requiredSections).not.toContain("2-4 content slides");
    expect(result.requiredSections).toContain("cover");
  });
});

// ─── Slide Count Estimation ──────────────────────────────────────────────────

describe("estimateSlideCount()", () => {
  it("counts explicit Slide N headings", () => {
    expect(estimateSlideCount(GOOD_SLIDE_MD)).toBe(4);
  });

  it("returns 0 for empty string", () => {
    expect(estimateSlideCount("")).toBe(0);
  });

  it("counts HR delimiters as slide breaks", () => {
    const md = "Content A\n---\nContent B\n---\nContent C";
    expect(estimateSlideCount(md)).toBe(3);
  });

  it("counts H1/H2 headings when no explicit slide markers", () => {
    const md = "# Intro\nSome text\n# Body\nMore text\n# Conclusion\nEnd";
    expect(estimateSlideCount(md)).toBe(3);
  });
});

// ─── Preflight Validation ────────────────────────────────────────────────────

describe("validatePptxPreflight()", () => {
  it("passes good slide markdown", () => {
    const result = validatePptxPreflight(GOOD_SLIDE_MD, null);
    expect(result.ok).toBe(true);
    expect(result.derivedSlideCount).toBeGreaterThanOrEqual(3);
    expect(result.hardFailures).toHaveLength(0);
  });

  it("rejects empty deliverable", () => {
    const result = validatePptxPreflight("", null);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("empty"))).toBe(true);
  });

  it("rejects too-short deliverable", () => {
    const result = validatePptxPreflight(WEAK_SLIDE_MD, null);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("too short"))).toBe(true);
  });

  it("rejects raw JSON payload", () => {
    const result = validatePptxPreflight(JSON_PAYLOAD, null);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("JSON"))).toBe(true);
  });

  it("rejects placeholder/TODO content", () => {
    const result = validatePptxPreflight(TODO_CONTENT, null);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("placeholder") || f.includes("TODO"))).toBe(true);
  });

  it("rejects unsegmented prose blob", () => {
    const result = validatePptxPreflight(PROSE_BLOB, null);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("prose blob") || f.includes("slide structure"))).toBe(true);
  });

  it("catches escaped newlines", () => {
    const escaped = 'Slide 1:\\nContent here\\nMore content\\nEven more';
    const result = validatePptxPreflight(escaped, null);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("escaped"))).toBe(true);
  });

  // Contract-based preflight
  it("rejects deliverable below contract minimum slide count", () => {
    const contract = parseContentContract("Slides: 5-8");
    const twoSlides = "# Slide 1\nContent\n---\n# Slide 2\nContent";
    const result = validatePptxPreflight(twoSlides, contract);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("below contract minimum"))).toBe(true);
  });

  it("rejects deliverable missing required section from contract", () => {
    const contract = parseContentContract("Slides: 3-6\nRequired sections: Cover, Thank You");
    const noThankYou = "# Slide 1: Cover\nWelcome\n---\n# Slide 2: Features\nStuff\n---\n# Slide 3: Pricing\nData";
    const result = validatePptxPreflight(noThankYou, contract);
    expect(result.ok).toBe(false);
    expect(result.hardFailures.some(f => f.includes("thank you"))).toBe(true);
  });

  it("passes deliverable meeting all contract requirements", () => {
    const contract = parseContentContract("Slides: 5-8\nRequired sections: Cover, Executive Summary, Thank You");
    const fullDeck = `# Slide 1: Cover
Welcome to Klear.ai

---

# Slide 2: Executive Summary
Key highlights from Q1

---

# Slide 3: Platform Features
- Unified data
- Predictive analytics

---

# Slide 4: Metrics
- ARR: $12M
- Growth: 20%

---

# Slide 5: Thank You
Contact us at sales@klear.ai`;
    const result = validatePptxPreflight(fullDeck, contract);
    expect(result.ok).toBe(true);
  });
});

// ─── Post-Gamma Compliance ───────────────────────────────────────────────────

describe("checkGammaCompliance()", () => {
  it("fails when file does not exist", () => {
    const result = checkGammaCompliance(
      "/nonexistent/path.pptx",
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      null,
      4,
    );
    expect(result.ok).toBe(false);
    expect(result.fileExists).toBe(false);
    expect(result.hardFailures.some(f => f.includes("does not exist"))).toBe(true);
  });

  // Note: We can't test real file existence in unit tests without fixtures,
  // but we can test the logic paths via the missing-file case above.
});

// ─── Review Supplement ───────────────────────────────────────────────────────

describe("buildPptxReviewSupplement()", () => {
  it("includes preflight data when provided", () => {
    const preflight: PreflightResult = {
      ok: true,
      hardFailures: [],
      softWarnings: ["1 slide exceeds 5 bullets"],
      derivedSlideCount: 6,
      summary: "Preflight passed",
    };
    const supplement = buildPptxReviewSupplement(preflight, null, null);
    expect(supplement).toContain("6 slides detected");
    expect(supplement).toContain("PPTX QUALITY SUPPLEMENT");
    expect(supplement).toContain("slide presentation");
  });

  it("includes compliance data when provided", () => {
    const compliance: GammaComplianceResult = {
      ok: true,
      hardFailures: [],
      softWarnings: ["Estimated 4 slides vs contract range 5-8"],
      fileExists: true,
      fileSizeBytes: 150_000,
      mimeConsistent: true,
      estimatedSlideCount: 4,
      contractSlideRange: { min: 5, max: 8 },
      slideCountCompliant: false,
      summary: "Compliance passed",
    };
    const supplement = buildPptxReviewSupplement(null, compliance, null);
    expect(supplement).toContain("146KB");
    expect(supplement).toContain("Compliance warnings");
  });

  it("includes contract info when provided", () => {
    const contract: ParsedContract = { minSlides: 5, maxSlides: 8, requiredSections: ["cover", "thank you"], maxBulletsPerSlide: 5 };
    const supplement = buildPptxReviewSupplement(null, null, contract);
    expect(supplement).toContain("5-8 slides");
    expect(supplement).toContain("cover");
  });
});

// ─── Done Contract Interaction ───────────────────────────────────────────────

describe("Done Contract + PPTX compliance", () => {
  function makePptxCtx(overrides: Partial<CloseoutContext> = {}): CloseoutContext {
    return {
      scope: "work_order",
      title: "Create a presentation",
      description: "Q1 investor slide deck",
      deliverable: GOOD_SLIDE_MD,
      deliverableType: "code",
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      qualityReview: { score: 0.85, recommendation: "approve", issues: [] },
      qualityBlocked: false,
      candidateReviewPending: false,
      filingResolved: true,
      previewResult: null,
      filedArtifactCount: 1,
      gammaState: "success",
      gammaFallbackBlocked: false,
      gammaComplianceOk: true,
      gammaComplianceFailures: [],
      ...overrides,
    };
  }

  it("allows completion when Gamma compliance passes", () => {
    const decision = evaluateDoneContract(makePptxCtx());
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
    expect(decision.artifactClass).toBe("pptx");
  });

  it("blocks completion when Gamma compliance has hard failures", () => {
    const decision = evaluateDoneContract(makePptxCtx({
      gammaComplianceOk: false,
      gammaComplianceFailures: ["PPTX file suspiciously small (2000 bytes) — likely corrupt or empty"],
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("Gamma compliance"))).toBe(true);
  });

  it("candidate_review still blocks even with good compliance", () => {
    const decision = evaluateDoneContract(makePptxCtx({
      candidateReviewPending: true,
      gammaState: "candidate_review",
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("awaiting_operator");
  });

  it("does not add compliance failures when gammaComplianceOk is undefined (non-Gamma path)", () => {
    const decision = evaluateDoneContract(makePptxCtx({
      gammaComplianceOk: undefined,
      gammaComplianceFailures: undefined,
    }));
    expect(decision.done).toBe(true);
    expect(decision.hardFailures).toHaveLength(0);
  });
});

// ─── Slide Source Shaper ─────────────────────────────────────────────────────

describe("shapeSlideSource()", () => {
  it("preserves well-structured slide markdown", () => {
    const result = shapeSlideSource(GOOD_SLIDE_MD, null);
    expect(result.slideCount).toBe(4);
    expect(result.shaped).toContain("Klear.ai");
    expect(result.shaped).toContain("---");
  });

  it("splits H1/H2 headings into separate slides", () => {
    const flat = `# Introduction
Welcome to the deck

# Features
- Feature 1
- Feature 2
- Feature 3

# Pricing
$9.99/mo

# Thank You
Contact us`;
    const result = shapeSlideSource(flat, null);
    expect(result.slideCount).toBe(4);
    expect(result.shaped).toContain("---");
  });

  it("splits HR-delimited content into slides", () => {
    const hrDelimited = `Cover content here

---

Second slide content

---

Third slide content`;
    const result = shapeSlideSource(hrDelimited, null);
    expect(result.slideCount).toBe(3);
  });

  it("deduplicates slides with identical headings", () => {
    const duped = `# Cover
Welcome

---

# Features
- Item 1

---

# Features
- Item 1 (duplicate)

---

# Thank You
Bye`;
    const result = shapeSlideSource(duped, null);
    expect(result.slideCount).toBe(3); // Cover, Features (first), Thank You
    expect(result.actions.some(a => a.includes("duplicate"))).toBe(true);
  });

  it("trims excess bullets to contract max", () => {
    const heavy = `# Slide 1: Features

- Bullet 1
- Bullet 2
- Bullet 3
- Bullet 4
- Bullet 5
- Bullet 6
- Bullet 7
- Bullet 8
- Bullet 9
- Bullet 10`;
    const contract = parseContentContract("Max 5 bullets per slide");
    const result = shapeSlideSource(heavy, contract);
    const bulletCount = (result.shaped.match(/^- /gm) || []).length;
    expect(bulletCount).toBeLessThanOrEqual(5);
    expect(result.actions.some(a => a.includes("trimmed"))).toBe(true);
  });

  it("caps slide count to contract max", () => {
    const manySlides = Array.from({ length: 15 }, (_, i) =>
      `# Slide ${i + 1}\nContent for slide ${i + 1}`
    ).join("\n\n---\n\n");
    const contract = parseContentContract("Slides: 5-8");
    const result = shapeSlideSource(manySlides, contract);
    expect(result.slideCount).toBeLessThanOrEqual(8);
    expect(result.actions.some(a => a.includes("capped"))).toBe(true);
  });

  it("handles empty/short input gracefully", () => {
    const result = shapeSlideSource("", null);
    expect(result.slideCount).toBe(0);
    expect(result.shaped).toBe("");
  });

  it("handles prose blob as single segment", () => {
    const result = shapeSlideSource(PROSE_BLOB, null);
    expect(result.slideCount).toBe(1); // single unsplittable segment
  });

  it("splits bold-heading formatted content", () => {
    const boldFormat = `**Company Overview**
We are a workforce intelligence company.

**Key Metrics**
- ARR: $12M
- Customers: 500+

**Call to Action**
Schedule a demo today.`;
    const result = shapeSlideSource(boldFormat, null);
    expect(result.slideCount).toBe(3);
  });

  it("logs shaping actions", () => {
    const result = shapeSlideSource(GOOD_SLIDE_MD, null);
    expect(result.actions.length).toBeGreaterThan(0);
    expect(result.actions.some(a => a.includes("parsed"))).toBe(true);
    expect(result.actions.some(a => a.includes("shaped output"))).toBe(true);
  });
});

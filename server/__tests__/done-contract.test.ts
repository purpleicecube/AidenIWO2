/**
 * Done Contract — Phase 1 Tests
 *
 * Test matrix from:
 *   AIDEN_IWO2_DONE_CONTRACT_IMPLEMENTATION_BRIEF_v0.1.0 §10
 *   AIDEN_IWO2_STATIC_WEB_PAGE_DOD_v0.1.0 §12
 *   AIDEN_IWO2_SOFTWARE_ARTIFACT_DOD_v0.1.0 §12
 *   AIDEN_IWO2_DOCUMENT_DOD_v0.1.0 §12
 *   AIDEN_IWO2_PPTX_DOD_v0.1.0 §11
 */

import { describe, it, expect } from "vitest";
import {
  classifyArtifactClass,
  resolveValidationTier,
  evaluateDoneContract,
  isValidHtmlDeliverable,
  isPlaceholderOrProseOnly,
  hasSoftwareStructure,
  hasDocumentContent,
  checkRequiredSections,
  checkPrimaryInteractions,
  buildWorkOrderCloseoutContext,
  buildWorkflowCloseoutContext,
  type CloseoutContext,
  type WrapItUpOptions,
} from "../done-contract.js";

// ─── Fixtures ────────────────────────────────────────────────────────────────

const VALID_HTML = `<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Landing Page</title></head>
<body>
  <header class="hero"><h1>Welcome to Our Product</h1></header>
  <section class="features"><h2>Features</h2><p>Feature 1, Feature 2, Feature 3</p></section>
  <section class="pricing"><h2>Pricing</h2><p>$9.99/mo</p></section>
  <footer><p>© 2026 Company</p></footer>
  <button class="cta">Get Started</button>
</body>
</html>`;

const VALID_APP_CODE = `
import React from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';

function App() {
  const [count, setCount] = React.useState(0);
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home count={count} setCount={setCount} />} />
        <Route path="/about" element={<About />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
`;

const VALID_DOCUMENT = `# Q1 Revenue Report

## Executive Summary

The company achieved $12M in annual recurring revenue during Q1, representing a 20% increase over the prior quarter. Customer acquisition remained strong with 142 new accounts closed.

## Key Metrics

- Total Revenue: $3.2M
- New Customers: 142
- Churn Rate: 1.8%
- Net Promoter Score: 72

## Analysis

The growth was driven primarily by enterprise segment expansion, which contributed 65% of new ARR. Mid-market accounts showed steady performance at 25%, while SMB contributed the remaining 10%.

## Recommendations

1. Increase enterprise sales team capacity by 2 reps
2. Launch targeted mid-market campaign in Q2
3. Improve onboarding flow to reduce early churn
`;

const VALID_SLIDE_CONTENT = `# Company Overview Deck

## Slide 1: Title
Company Name — Q1 2026 Investor Update

## Slide 2: Market Opportunity
- Total addressable market: $50B
- Current penetration: 0.5%
- Growth rate: 35% YoY

## Slide 3: Product
Our platform delivers automated risk management with AI-driven insights.

## Slide 4: Financials
- ARR: $12M
- Revenue growth: 20% QoQ
- Gross margin: 78%

## Slide 5: Team
- 200+ employees across 3 offices
- 35 engineers
- Leadership team with 80+ years combined experience
`;

const PROSE_ONLY = `
Here is a description of the landing page we should build:
- It should have a hero section with a bold headline
- A features section listing 3 key benefits
- A pricing table with 3 tiers
- A footer with contact information
This page will use modern design principles and responsive layout.
`;

const PLACEHOLDER_CODE = `
// TODO: Implement main app
// PLACEHOLDER: Add routes here
// STUB: Connect to database
// TODO: Add authentication
// FIXME: This is just a skeleton
const app = {};
`;

function makeCtx(overrides: Partial<CloseoutContext> = {}): CloseoutContext {
  return {
    scope: "work_order",
    title: "Create a landing page",
    description: "Build a marketing landing page with hero, features, and CTA",
    deliverable: VALID_HTML,
    deliverableType: "code",
    postProcessedFilePresent: false,
    qualityReview: { score: 0.85, recommendation: "approve", issues: [] },
    qualityBlocked: false,
    candidateReviewPending: false,
    filingResolved: true,
    previewResult: null,
    filedArtifactCount: 1,
    gammaState: "none",
    gammaFallbackBlocked: false,
    ...overrides,
  };
}

const WRAP_IT_UP: WrapItUpOptions = {
  enabled: true,
  operatorId: "darrel",
  reason: "Operator accepts current output",
};

// ─── Artifact Classification ─────────────────────────────────────────────────

describe("classifyArtifactClass()", () => {
  it("classifies landing page as static_web_page", () => {
    expect(classifyArtifactClass("Create a landing page", "Marketing page for product launch")).toBe("static_web_page");
  });

  it("classifies microsite as static_web_page", () => {
    expect(classifyArtifactClass("Build microsite", "Simple one-page microsite")).toBe("static_web_page");
  });

  it("classifies web app as software_artifact", () => {
    expect(classifyArtifactClass("Build a web app", "Interactive dashboard application")).toBe("software_artifact");
  });

  it("classifies game as software_artifact", () => {
    expect(classifyArtifactClass("Create a game", "Browser-based puzzle game")).toBe("software_artifact");
  });

  it("classifies simulation as software_artifact", () => {
    expect(classifyArtifactClass("Physics simulation", "Particle physics simulation")).toBe("software_artifact");
  });

  it("defaults to other for ambiguous requests", () => {
    expect(classifyArtifactClass("Do something", "Generic task")).toBe("other");
  });

  it("prefers software_artifact over static_web_page when both match", () => {
    expect(classifyArtifactClass("Interactive web app landing page", "Dashboard application")).toBe("software_artifact");
  });

  // New: Document and PPTX classification
  it("classifies presentation as pptx", () => {
    expect(classifyArtifactClass("Create a presentation", "Investor pitch deck")).toBe("pptx");
  });

  it("classifies slide deck as pptx", () => {
    expect(classifyArtifactClass("Build slide deck", "Q1 results slides")).toBe("pptx");
  });

  it("classifies report as document", () => {
    expect(classifyArtifactClass("Write a report", "Quarterly financial report")).toBe("document");
  });

  it("classifies PDF as document", () => {
    expect(classifyArtifactClass("Generate PDF", "Client proposal PDF")).toBe("document");
  });

  it("classifies proposal as document", () => {
    expect(classifyArtifactClass("Draft proposal", "RFP response proposal")).toBe("document");
  });

  it("classifies briefing as document", () => {
    expect(classifyArtifactClass("Prepare briefing", "Executive briefing memo")).toBe("document");
  });

  it("prefers pptx over document for pitch deck", () => {
    expect(classifyArtifactClass("Create pitch deck", "Investor pitch slides")).toBe("pptx");
  });
});

// ─── Validation Tier Resolution ──────────────────────────────────────────────

describe("resolveValidationTier()", () => {
  it("defaults static_web_page to render_complete", () => {
    expect(resolveValidationTier("static_web_page", "Landing page", "Simple marketing page")).toBe("render_complete");
  });

  it("upgrades static_web_page to interaction_complete for CTA behavior", () => {
    expect(resolveValidationTier("static_web_page", "Landing page with CTA behavior", "")).toBe("interaction_complete");
  });

  it("defaults software_artifact to source_complete", () => {
    expect(resolveValidationTier("software_artifact", "Create an app", "Simple todo app")).toBe("source_complete");
  });

  it("upgrades software_artifact to preview_complete for demo request", () => {
    expect(resolveValidationTier("software_artifact", "Create a demo", "Visual demo of the app")).toBe("preview_complete");
  });

  it("upgrades software_artifact to build_complete for build request", () => {
    expect(resolveValidationTier("software_artifact", "Production build", "Compile and bundle")).toBe("build_complete");
  });

  it("upgrades software_artifact to runtime_complete for working app", () => {
    expect(resolveValidationTier("software_artifact", "Create a working app", "Fully runnable")).toBe("runtime_complete");
  });

  it("returns default for other artifact class", () => {
    expect(resolveValidationTier("other", "Do something", "")).toBe("default");
  });

  // New: Document and PPTX tiers
  it("defaults document to document_rendered", () => {
    expect(resolveValidationTier("document", "Write a report", "Quarterly summary")).toBe("document_rendered");
  });

  it("upgrades document to document_native for explicit docx", () => {
    expect(resolveValidationTier("document", "Create .docx report", "Word document output")).toBe("document_native");
  });

  it("defaults pptx to pptx_local", () => {
    expect(resolveValidationTier("pptx", "Create presentation", "Slide deck")).toBe("pptx_local");
  });
});

// ─── Structural Validators ───────────────────────────────────────────────────

describe("isValidHtmlDeliverable()", () => {
  it("accepts valid HTML document", () => {
    expect(isValidHtmlDeliverable(VALID_HTML)).toBe(true);
  });

  it("rejects empty string", () => {
    expect(isValidHtmlDeliverable("")).toBe(false);
  });

  it("rejects markdown prose", () => {
    expect(isValidHtmlDeliverable(PROSE_ONLY)).toBe(false);
  });

  it("rejects empty body HTML", () => {
    const emptyBody = `<!DOCTYPE html><html><head></head><body>   </body></html>`;
    expect(isValidHtmlDeliverable(emptyBody)).toBe(false);
  });
});

describe("isPlaceholderOrProseOnly()", () => {
  it("returns true for prose description", () => {
    expect(isPlaceholderOrProseOnly(PROSE_ONLY)).toBe(true);
  });

  it("returns true for placeholder code", () => {
    expect(isPlaceholderOrProseOnly(PLACEHOLDER_CODE)).toBe(true);
  });

  it("returns false for valid HTML", () => {
    expect(isPlaceholderOrProseOnly(VALID_HTML)).toBe(false);
  });

  it("returns false for real app code", () => {
    expect(isPlaceholderOrProseOnly(VALID_APP_CODE)).toBe(false);
  });

  it("returns true for empty string", () => {
    expect(isPlaceholderOrProseOnly("")).toBe(true);
  });

  it("returns true for very short content", () => {
    expect(isPlaceholderOrProseOnly("hello")).toBe(true);
  });
});

describe("hasSoftwareStructure()", () => {
  it("detects real app code", () => {
    expect(hasSoftwareStructure(VALID_APP_CODE)).toBe(true);
  });

  it("detects HTML as having structure", () => {
    expect(hasSoftwareStructure(VALID_HTML)).toBe(true);
  });

  it("rejects empty content", () => {
    expect(hasSoftwareStructure("")).toBe(false);
  });

  it("rejects very short content", () => {
    expect(hasSoftwareStructure("x")).toBe(false);
  });
});

describe("hasDocumentContent()", () => {
  it("accepts structured document with headings and paragraphs", () => {
    expect(hasDocumentContent(VALID_DOCUMENT)).toBe(true);
  });

  it("rejects short placeholder", () => {
    expect(hasDocumentContent("TODO: write report")).toBe(false);
  });

  it("rejects empty string", () => {
    expect(hasDocumentContent("")).toBe(false);
  });
});

describe("checkRequiredSections()", () => {
  it("returns empty when all sections present", () => {
    expect(checkRequiredSections(VALID_HTML, "Landing page with hero and features and pricing and footer", "")).toEqual([]);
  });

  it("detects missing section", () => {
    const noFooter = VALID_HTML.replace(/<footer[\s\S]*?<\/footer>/, "");
    const result = checkRequiredSections(noFooter, "Page with footer", "Must have footer");
    expect(result).toContain("footer");
  });
});

describe("checkPrimaryInteractions()", () => {
  it("returns empty when CTA button present", () => {
    expect(checkPrimaryInteractions(VALID_HTML, "Page with CTA", "")).toEqual([]);
  });

  it("detects missing CTA", () => {
    const noCta = VALID_HTML.replace(/<button[\s\S]*?<\/button>/, "");
    expect(checkPrimaryInteractions(noCta, "Page with CTA", "")).toContain("CTA button");
  });

  it("detects missing form", () => {
    expect(checkPrimaryInteractions(VALID_HTML, "Page with form", "Contact form")).toContain("form");
  });
});

// ─── Static Web Page DoD (§12 test matrix) ───────────────────────────────────

describe("Static Web Page DoD", () => {
  it("valid landing page HTML → completed", () => {
    const decision = evaluateDoneContract(makeCtx());
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
    expect(decision.artifactClass).toBe("static_web_page");
  });

  it("markdown brief about a landing page → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      deliverable: PROSE_ONLY,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).not.toBe("completed");
  });

  it("HTML shell missing major required section → awaiting_operator", () => {
    const noFeatures = VALID_HTML.replace(/<section class="features">[\s\S]*?<\/section>/, "");
    const decision = evaluateDoneContract(makeCtx({
      deliverable: noFeatures,
      title: "Landing page with features section",
      description: "Must include features",
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("features"))).toBe(true);
  });

  it("candidate review pending → awaiting_operator", () => {
    const decision = evaluateDoneContract(makeCtx({
      candidateReviewPending: true,
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("awaiting_operator");
    expect(decision.requiredNextAction).toBe("candidate_selection");
  });

  it("filing unresolved → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      filingResolved: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("Filing"))).toBe(true);
  });

  it("requested CTA interaction absent under interaction_complete → not completed", () => {
    const noCta = VALID_HTML.replace(/<button[\s\S]*?<\/button>/, "");
    const decision = evaluateDoneContract(makeCtx({
      deliverable: noCta,
      title: "Landing page with CTA behavior",
      description: "Must have working CTA",
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("CTA"))).toBe(true);
  });
});

// ─── Software Artifact DoD (§12 test matrix) ────────────────────────────────

describe("Software Artifact DoD", () => {
  it("source-only app request with real code → completed at source_complete", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a web app",
      description: "Simple dashboard application",
      deliverable: VALID_APP_CODE,
    }));
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
    expect(decision.artifactClass).toBe("software_artifact");
    expect(decision.validationTier).toBe("source_complete");
  });

  it("preview-requested web app with preview evidence → completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a web app demo",
      description: "Visual demo of dashboard application",
      deliverable: VALID_APP_CODE,
      previewResult: { renderable: true },
    }));
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
    expect(decision.validationTier).toBe("preview_complete");
  });

  it("preview-requested web app without preview evidence → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a web app demo",
      description: "Visual demo of dashboard application",
      deliverable: VALID_APP_CODE,
      previewResult: null,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("preview"))).toBe(true);
  });

  it("runtime-requested game without runtime evidence → awaiting_operator", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a playable game",
      description: "Browser-based puzzle game simulation",
      deliverable: VALID_APP_CODE,
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("awaiting_operator");
    expect(decision.hardFailures.some(f => f.includes("runtime") || f.includes("Runtime"))).toBe(true);
  });

  it("prose-only response to software request → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Build a web app",
      description: "Interactive dashboard application",
      deliverable: PROSE_ONLY,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
  });

  it("filing unresolved → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Build a web app",
      description: "Simple dashboard application",
      deliverable: VALID_APP_CODE,
      filingResolved: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("Filing"))).toBe(true);
  });
});

// ─── Document DoD (§12 test matrix) ──────────────────────────────────────────

describe("Document DoD", () => {
  it("explicit PDF request with valid PDF binary → completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Generate PDF report",
      description: "Quarterly financial report in PDF",
      deliverable: VALID_DOCUMENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/pdf",
    }));
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
    expect(decision.artifactClass).toBe("document");
    expect(decision.validationTier).toBe("document_rendered");
  });

  it("explicit PDF request with only markdown → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Generate PDF report",
      description: "Client proposal PDF",
      deliverable: VALID_DOCUMENT,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("PDF"))).toBe(true);
  });

  it("Gamma PDF candidate-review pending → awaiting_operator", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Generate PDF report",
      description: "Client proposal PDF",
      deliverable: VALID_DOCUMENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/pdf",
      candidateReviewPending: true,
      gammaState: "candidate_review",
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("awaiting_operator");
    expect(decision.requiredNextAction).toBe("candidate_selection");
  });

  it("Gamma PDF selected and filed → completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Generate PDF report",
      description: "Client proposal PDF",
      deliverable: VALID_DOCUMENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/pdf",
      candidateReviewPending: false,
      gammaState: "success",
      filedArtifactCount: 1,
    }));
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
  });

  it("explicit DOCX request without native file evidence → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create .docx report",
      description: "Word document deliverable",
      deliverable: VALID_DOCUMENT,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("native") || f.includes("DOC"))).toBe(true);
  });

  it("filing unresolved → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Write a report",
      description: "Quarterly document",
      deliverable: VALID_DOCUMENT,
      filingResolved: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("Filing"))).toBe(true);
  });

  it("document_rendered with markdown content (no explicit PDF) → completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Write a report",
      description: "Quarterly financial document",
      deliverable: VALID_DOCUMENT,
    }));
    expect(decision.done).toBe(true);
    expect(decision.artifactClass).toBe("document");
    expect(decision.validationTier).toBe("document_rendered");
  });

  it("Gamma failed with locked template → blocked", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Generate PDF report",
      description: "Client proposal PDF",
      deliverable: VALID_DOCUMENT,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
      gammaState: "failed",
      gammaFallbackBlocked: true,
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("blocked");
  });
});

// ─── PPTX DoD (§11 test matrix) ─────────────────────────────────────────────

describe("PPTX DoD", () => {
  it("local PPTX generated and filed → completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Q1 investor slide deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      filedArtifactCount: 1,
    }));
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
    expect(decision.artifactClass).toBe("pptx");
  });

  it("explicit PPTX request with markdown only and no binary → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Q1 investor slide deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("PPTX binary"))).toBe(true);
  });

  it("Gamma PPTX candidate-review pending → awaiting_operator", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Branded pitch deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      candidateReviewPending: true,
      gammaState: "candidate_review",
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("awaiting_operator");
    expect(decision.requiredNextAction).toBe("candidate_selection");
  });

  it("Gamma PPTX candidate selected and filed → completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Branded pitch deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      candidateReviewPending: false,
      gammaState: "success",
      filedArtifactCount: 1,
    }));
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
  });

  it("Gamma failure with locked template / blocked fallback → blocked", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Branded pitch deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
      gammaState: "failed",
      gammaFallbackBlocked: true,
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("blocked");
  });

  it("filing unresolved → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Slide deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      filingResolved: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("Filing"))).toBe(true);
  });
});

// ─── Shared Closeout (§10.3 test matrix) ────────────────────────────────────

describe("Shared Closeout", () => {
  it("candidate-review pending forces awaiting_operator", () => {
    const decision = evaluateDoneContract(makeCtx({
      candidateReviewPending: true,
    }));
    expect(decision.terminalState).toBe("awaiting_operator");
    expect(decision.requiredNextAction).toBe("candidate_selection");
  });

  it("quality block forces blocked", () => {
    const decision = evaluateDoneContract(makeCtx({
      qualityBlocked: true,
      qualityReview: { score: 0.2, recommendation: "block", issues: ["Critical quality failure"] },
    }));
    expect(decision.terminalState).toBe("blocked");
    expect(decision.requiredNextAction).toBe("request_revision");
  });

  it("no hard failures allows completed", () => {
    const decision = evaluateDoneContract(makeCtx());
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
    expect(decision.hardFailures).toHaveLength(0);
  });

  it("missing deliverable forces failure", () => {
    const decision = evaluateDoneContract(makeCtx({
      deliverable: null,
      filedArtifactCount: 0,
      postProcessedFilePresent: false,
      filingResolved: false,
    }));
    expect(decision.done).toBe(false);
    expect(decision.terminalState).toBe("failed");
  });
});

// ─── Workflow Context ────────────────────────────────────────────────────────

describe("Workflow closeout", () => {
  it("workflow with complete assembly and executive review → completed", () => {
    const ctx = makeCtx({
      scope: "workflow",
      title: "Create a landing page",
      description: "Marketing page via workflow",
      workflowAssemblyPresent: true,
      executiveReviewResolved: true,
    });
    const decision = evaluateDoneContract(ctx);
    expect(decision.done).toBe(true);
    expect(decision.terminalState).toBe("completed");
  });

  it("workflow with missing assembly → not completed", () => {
    const ctx = makeCtx({
      scope: "workflow",
      title: "Create a landing page",
      description: "Marketing page via workflow",
      workflowAssemblyPresent: false,
      executiveReviewResolved: true,
    });
    const decision = evaluateDoneContract(ctx);
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("assembly"))).toBe(true);
  });

  it("workflow with unresolved executive review → not completed", () => {
    const ctx = makeCtx({
      scope: "workflow",
      title: "Create a landing page",
      description: "Marketing page via workflow",
      workflowAssemblyPresent: true,
      executiveReviewResolved: false,
    });
    const decision = evaluateDoneContract(ctx);
    expect(decision.done).toBe(false);
    expect(decision.hardFailures.some(f => f.includes("Executive review"))).toBe(true);
  });
});

// ─── Context Builders ────────────────────────────────────────────────────────

describe("buildWorkOrderCloseoutContext()", () => {
  it("builds context from work order data", () => {
    const ctx = buildWorkOrderCloseoutContext(
      {
        title: "Landing page",
        description: "Marketing page",
        tier2Result: {
          output: {
            deliverable: VALID_HTML,
            deliverableType: "code",
            postProcessedFile: { path: "/tmp/file.pdf", mimeType: "application/pdf", size: 1024 },
          },
          qualityReview: { score: 0.85, recommendation: "approve", issues: [] },
        },
        status: "processing",
      },
      { filedArtifactCount: 2, candidateReviewPending: false }
    );
    expect(ctx.scope).toBe("work_order");
    expect(ctx.deliverable).toBe(VALID_HTML);
    expect(ctx.postProcessedFilePresent).toBe(true);
    expect(ctx.postProcessedFileMimeType).toBe("application/pdf");
    expect(ctx.filedArtifactCount).toBe(2);
    expect(ctx.candidateReviewPending).toBe(false);
  });
});

describe("buildWorkflowCloseoutContext()", () => {
  it("builds context from workflow data", () => {
    const ctx = buildWorkflowCloseoutContext(
      { title: "Landing page workflow", description: "Multi-step landing page" },
      { deliverable: VALID_HTML, deliverableType: "code", deliverableTitle: "Landing Page" },
      { postProcessedFilePresent: false, filedArtifactCount: 1, candidateReviewPending: false, executiveReviewResolved: true }
    );
    expect(ctx.scope).toBe("workflow");
    expect(ctx.deliverable).toBe(VALID_HTML);
    expect(ctx.workflowAssemblyPresent).toBe(true);
    expect(ctx.executiveReviewResolved).toBe(true);
  });
});

// ─── Edge Cases ──────────────────────────────────────────────────────────────

describe("Edge cases", () => {
  it("other artifact class with deliverable → completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Do something generic",
      description: "A generic task",
      deliverable: "# Q1 Report\n\nRevenue was $1M with 20% growth.\n\n## Key Metrics\n\nCustomer count: 500\nChurn: 2%\nARR: $12M",
    }));
    expect(decision.done).toBe(true);
    expect(decision.artifactClass).toBe("other");
  });

  it("other artifact class with no deliverable → not completed", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Do something generic",
      description: "A generic task",
      deliverable: null,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
    }));
    expect(decision.done).toBe(false);
  });

  it("postProcessedFile present compensates for missing HTML in deliverable", () => {
    const decision = evaluateDoneContract(makeCtx({
      deliverable: "Markdown summary of the page generation",
      postProcessedFilePresent: true,
      filedArtifactCount: 1,
    }));
    expect(decision.done).toBe(true);
  });

  it("filed artifacts compensate for prose deliverable in static web page", () => {
    const decision = evaluateDoneContract(makeCtx({
      deliverable: "Description of the landing page that was built",
      filedArtifactCount: 3,
    }));
    expect(decision.done).toBe(true);
  });
});

// ─── Wrap It Up ──────────────────────────────────────────────────────────────

describe("Wrap It Up", () => {
  it("on already-completed decision → passes through with audit", () => {
    const decision = evaluateDoneContract(makeCtx(), WRAP_IT_UP);
    expect(decision.done).toBe(true);
    expect(decision.wrapItUp).toBeDefined();
    expect(decision.wrapItUp!.invoked).toBe(true);
    expect(decision.wrapItUp!.bypassed).toHaveLength(0);
  });

  it("bypasses missing section failures → completed", () => {
    const noFeatures = VALID_HTML.replace(/<section class="features">[\s\S]*?<\/section>/, "");
    const decision = evaluateDoneContract(makeCtx({
      deliverable: noFeatures,
      title: "Landing page with features section",
      description: "Must include features",
    }), WRAP_IT_UP);
    expect(decision.done).toBe(true);
    expect(decision.wrapItUp!.bypassed.length).toBeGreaterThan(0);
    expect(decision.wrapItUp!.bypassed.some(b => b.includes("section"))).toBe(true);
  });

  it("bypasses missing interaction failures → completed", () => {
    const noCta = VALID_HTML.replace(/<button[\s\S]*?<\/button>/, "");
    const decision = evaluateDoneContract(makeCtx({
      deliverable: noCta,
      title: "Landing page with CTA behavior",
      description: "Must have working CTA",
    }), WRAP_IT_UP);
    expect(decision.done).toBe(true);
    expect(decision.wrapItUp!.bypassed.some(b => b.includes("interaction"))).toBe(true);
  });

  it("does NOT bypass quality review block", () => {
    const decision = evaluateDoneContract(makeCtx({
      qualityBlocked: true,
      qualityReview: { score: 0.1, recommendation: "block", issues: ["Severe"] },
    }), WRAP_IT_UP);
    expect(decision.done).toBe(false);
    expect(decision.wrapItUp!.hardBlocksRetained.some(b => b.includes("Quality review blocked"))).toBe(true);
  });

  it("does NOT bypass candidate review pending", () => {
    const decision = evaluateDoneContract(makeCtx({
      candidateReviewPending: true,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(false);
    expect(decision.wrapItUp!.hardBlocksRetained.some(b => b.includes("Candidate review"))).toBe(true);
  });

  it("does NOT bypass missing deliverable", () => {
    const decision = evaluateDoneContract(makeCtx({
      deliverable: null,
      filedArtifactCount: 0,
      postProcessedFilePresent: false,
      filingResolved: false,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(false);
    expect(decision.wrapItUp!.hardBlocksRetained.length).toBeGreaterThan(0);
  });

  // Software artifact: accept lower tier
  it("software artifact: accepts source_complete when runtime was requested", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a playable game",
      description: "Browser-based puzzle game simulation",
      deliverable: VALID_APP_CODE,
      filedArtifactCount: 0,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(true);
    expect(decision.wrapItUp!.originalTier).toBe("runtime_complete");
    expect(decision.wrapItUp!.acceptedTier).toBe("source_complete");
    expect(decision.wrapItUp!.bypassed.length).toBeGreaterThan(0);
  });

  it("software artifact: accepts preview_complete when preview evidence exists", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a playable game",
      description: "Browser-based puzzle game simulation",
      deliverable: VALID_APP_CODE,
      previewResult: { renderable: true },
    }), WRAP_IT_UP);
    expect(decision.done).toBe(true);
    expect(decision.wrapItUp!.acceptedTier).toBe("preview_complete");
  });

  // Document: accept alternate format
  it("document: accepts document_rendered when native DOCX was requested but unavailable", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create .docx report",
      description: "Word document deliverable",
      deliverable: VALID_DOCUMENT,
      filedArtifactCount: 1,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(true);
    expect(decision.wrapItUp!.originalTier).toBe("document_native");
    expect(decision.wrapItUp!.acceptedTier).toBe("document_rendered");
    expect(decision.wrapItUp!.bypassed.length).toBeGreaterThan(0);
  });

  it("document: keeps document_native when native file actually exists", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create .docx report",
      description: "Word document deliverable",
      deliverable: VALID_DOCUMENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      filedArtifactCount: 1,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(true);
    expect(decision.wrapItUp!.acceptedTier).toBe("document_native");
  });

  // PPTX: cannot pretend binary exists
  it("PPTX: does NOT bypass missing binary", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Q1 slide deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(false);
    expect(decision.wrapItUp!.hardBlocksRetained.some(b => b.includes("PPTX binary"))).toBe(true);
  });

  it("PPTX: completes when binary exists but filing was the only issue", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Q1 slide deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      filedArtifactCount: 1,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(true);
  });

  // PPTX: candidate review is non-bypassable
  it("PPTX: does NOT bypass Gamma candidate review pending", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Branded pitch deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: true,
      postProcessedFileMimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      candidateReviewPending: true,
      gammaState: "candidate_review",
    }), WRAP_IT_UP);
    expect(decision.done).toBe(false);
    expect(decision.wrapItUp!.hardBlocksRetained.some(b => b.includes("Candidate review"))).toBe(true);
  });

  // Gamma failed with locked template — non-bypassable
  it("does NOT bypass Gamma failed with locked template", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a presentation",
      description: "Branded pitch deck",
      deliverable: VALID_SLIDE_CONTENT,
      postProcessedFilePresent: false,
      filedArtifactCount: 0,
      gammaState: "failed",
      gammaFallbackBlocked: true,
    }), WRAP_IT_UP);
    expect(decision.done).toBe(false);
    expect(decision.wrapItUp!.hardBlocksRetained.some(b => b.includes("Gamma") || b.includes("PPTX binary"))).toBe(true);
  });

  // Audit trail completeness
  it("always includes operator ID in audit", () => {
    const decision = evaluateDoneContract(makeCtx(), WRAP_IT_UP);
    expect(decision.wrapItUp!.operatorId).toBe("darrel");
  });

  it("always includes reason in audit", () => {
    const decision = evaluateDoneContract(makeCtx(), WRAP_IT_UP);
    expect(decision.wrapItUp!.reason).toContain("Operator accepts");
  });

  it("records original and accepted tiers in audit", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a playable game",
      description: "Browser-based puzzle game simulation",
      deliverable: VALID_APP_CODE,
      filedArtifactCount: 0,
    }), WRAP_IT_UP);
    expect(decision.wrapItUp!.originalTier).toBe("runtime_complete");
    expect(decision.wrapItUp!.acceptedTier).toBe("source_complete");
  });

  it("closeoutReason includes operator ID when wrap-it-up overrides", () => {
    const decision = evaluateDoneContract(makeCtx({
      title: "Create a playable game",
      description: "Browser-based puzzle game simulation",
      deliverable: VALID_APP_CODE,
    }), WRAP_IT_UP);
    expect(decision.closeoutReason).toContain("darrel");
    expect(decision.closeoutReason).toContain("Wrap It Up");
  });
});

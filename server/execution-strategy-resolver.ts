/**
 * Execution Strategy Resolver — Deterministic workflow-template matching
 *
 * Spec: IWO2_EXECUTION_STRATEGY_RESOLVER_SPEC_v0.1.0.md
 *
 * Runs AFTER Tier 1 approval, BEFORE direct sub-agent dispatch.
 * Returns either { strategy: "direct" } or { strategy: "workflow", ... }.
 *
 * No LLM calls, no embeddings, no probabilistic ranking.
 * Prefers false negatives over false positives.
 */

import type { WorkOrder, SubAgent } from "@shared/schema";
import { storage } from "./storage";
import { detectRequiredFormatFromText } from "./pocketflow";

// ─── Output Contract ─────────────────────────────────────────────────────────

export type ResolverResult =
  | { strategy: "direct" }
  | {
      strategy: "workflow";
      templateId: string;
      score: number;
      reason: string;
      matchedSignals: string[];
      rejectedCandidates: Array<{ templateId: string; reason: string }>;
    };

// ─── Constants ───────────────────────────────────────────────────────────────

const SELECTION_THRESHOLD = 8;
const MARGIN_THRESHOLD = 2;

const STOPWORDS = new Set([
  "a", "an", "the", "and", "or", "but", "is", "are", "was", "were", "be",
  "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
  "shall", "should", "may", "might", "can", "could", "to", "of", "in", "for",
  "on", "with", "at", "by", "from", "as", "into", "through", "during", "before",
  "after", "above", "below", "between", "out", "off", "over", "under", "again",
  "further", "then", "once", "here", "there", "when", "where", "why", "how",
  "all", "both", "each", "few", "more", "most", "other", "some", "such", "no",
  "nor", "not", "only", "own", "same", "so", "than", "too", "very", "just",
  "about", "up", "it", "its", "this", "that", "these", "those", "i", "me",
  "my", "we", "our", "you", "your", "he", "him", "his", "she", "her", "they",
  "them", "their", "what", "which", "who", "whom", "if", "else", "while",
  "use", "using", "please", "make", "sure", "also", "get", "need",
]);

// ─── Text Normalization ──────────────────────────────────────────────────────

function normalizeText(text: string): Set<string> {
  const lower = text.toLowerCase();
  const stripped = lower.replace(/[^\w\s-]/g, " ");
  const collapsed = stripped.replace(/\s+/g, " ").trim();
  const tokens = collapsed.split(" ").filter(t => t.length > 0);
  const deduped = new Set<string>();
  for (const token of tokens) {
    if (!STOPWORDS.has(token)) {
      deduped.add(token);
    }
  }
  return deduped;
}

// ─── Explicit Agent Extraction ───────────────────────────────────────────────

/**
 * Extract explicitly named agents from WO text + GCC context.
 * Returns resolved SubAgent records (not raw strings).
 */
function extractExplicitAgents(
  order: WorkOrder,
  activeSubAgents: SubAgent[]
): SubAgent[] {
  const text = `${order.title} ${order.description || ""}`.toLowerCase();
  const gcc = (order.gccMemory || {}) as Record<string, any>;
  const preferredAgent = gcc["gcc.preferredAgent"] || null;

  const matched: SubAgent[] = [];
  const seenIds = new Set<string>();

  for (const agent of activeSubAgents) {
    // Check for agent name mention in WO text
    const nameLower = agent.name.toLowerCase();

    // Extract the persona name (e.g., "HANK" from "A018_WebBuilder ( HANK PERSONA )")
    const personaMatch = nameLower.match(/\(\s*(\w+)\s*persona\s*\)/);
    const personaName = personaMatch ? personaMatch[1] : null;

    // Extract the code prefix (e.g., "a018" from "A018_WebBuilder ( HANK PERSONA )")
    const codeMatch = agent.name.match(/^[A-Z]\d+/i);
    const codeName = codeMatch ? codeMatch[0].toLowerCase() : null;

    const isReferenced =
      (personaName && text.includes(personaName)) ||
      (codeName && text.includes(codeName)) ||
      text.includes(nameLower);

    if (isReferenced && !seenIds.has(agent.id)) {
      matched.push(agent);
      seenIds.add(agent.id);
    }
  }

  // Also check GCC preferredAgent
  if (preferredAgent && typeof preferredAgent === "string") {
    const prefLower = preferredAgent.toLowerCase();
    const found = activeSubAgents.find(a => a.name.toLowerCase() === prefLower || a.id === preferredAgent);
    if (found && !seenIds.has(found.id)) {
      matched.push(found);
      seenIds.add(found.id);
    }
  }

  return matched;
}

// ─── Workflow-Shaped Detection ───────────────────────────────────────────────

const WORKFLOW_SIGNAL_PATTERNS = [
  /\b(design|create|build|deploy)\b.*\b(and|then|to)\b.*\b(publish|preview|sandbox|deploy)\b/i,
  /\b(multi.?step|pipeline|workflow|chain)\b/i,
  /\b(step\s*\d|phase\s*\d)\b/i,
];

function isWorkflowShaped(text: string, explicitAgentCount: number): boolean {
  if (explicitAgentCount >= 2) return true;
  return WORKFLOW_SIGNAL_PATTERNS.some(p => p.test(text));
}

// ─── Scoring ─────────────────────────────────────────────────────────────────

interface ScoredCandidate {
  templateId: string;
  templateName: string;
  score: number;
  signals: string[];
}

async function scoreTemplate(
  template: { id: string; name: string; description: string | null; goal: string | null; category: string; status: string },
  requestTokens: Set<string>,
  requestFormat: "pptx" | "pdf" | null,
  explicitAgents: SubAgent[],
  isWorkflow: boolean,
  activeSubAgents: SubAgent[]
): Promise<ScoredCandidate | { rejected: true; templateId: string; reason: string }> {

  // ── Eligibility gate ──

  if (template.status !== "active") {
    return { rejected: true, templateId: template.id, reason: "template not active" };
  }

  // Format conflict check
  const templateText = `${template.name} ${template.description || ""} ${template.goal || ""}`.toLowerCase();
  const templateFormat = detectRequiredFormatFromText(template.name, template.description || "");
  if (requestFormat && templateFormat && requestFormat !== templateFormat) {
    return { rejected: true, templateId: template.id, reason: `format conflict: request=${requestFormat}, template=${templateFormat}` };
  }

  // Explicit agent coverage check
  if (explicitAgents.length > 0) {
    const steps = await storage.getWorkflowSteps(template.id);
    const stepAgentIds = new Set(steps.map(s => s.assignedSubAgentId).filter(Boolean));

    // Resolve step agent IDs to SubAgent records
    const stepAgents = activeSubAgents.filter(a => stepAgentIds.has(a.id));
    const stepAgentIdSet = new Set(stepAgents.map(a => a.id));

    for (const required of explicitAgents) {
      if (!stepAgentIdSet.has(required.id)) {
        return {
          rejected: true,
          templateId: template.id,
          reason: `missing required agent "${required.name}" in template steps`,
        };
      }
    }
  }

  // ── Scoring ──

  let score = 0;
  const signals: string[] = [];

  // Signal 1: Format compatibility
  if (requestFormat && templateFormat && requestFormat === templateFormat) {
    score += 4;
    signals.push(`format_exact:${requestFormat}`);
  } else {
    score += 1;
    signals.push("format_compatible");
  }

  // Signal 2: Category alignment
  const orderCategory = "marketing"; // WOs default category — future: derive from order.type
  if (template.category === orderCategory) {
    score += 3;
    signals.push(`category_exact:${template.category}`);
  } else if (template.category === "general") {
    score += 1;
    signals.push("category_general");
  }

  // Signal 3: Goal/name/description token overlap
  const templateTokens = normalizeText(`${template.name} ${template.description || ""} ${template.goal || ""}`);
  const intersection: string[] = [];
  requestTokens.forEach(t => { if (templateTokens.has(t)) intersection.push(t); });
  const overlapRatio = requestTokens.size > 0 ? intersection.length / requestTokens.size : 0;

  if (overlapRatio >= 0.35) {
    score += 4;
    signals.push(`overlap_high:${overlapRatio.toFixed(2)} (${intersection.length}/${requestTokens.size})`);
  } else if (overlapRatio >= 0.20) {
    score += 2;
    signals.push(`overlap_moderate:${overlapRatio.toFixed(2)} (${intersection.length}/${requestTokens.size})`);
  } else {
    signals.push(`overlap_low:${overlapRatio.toFixed(2)}`);
  }

  // Signal 4: Workflow-shaped request
  if (isWorkflow) {
    score += 2;
    signals.push("workflow_shaped");
  }

  // Signal 5: Explicit named-agent coverage
  if (explicitAgents.length > 0) {
    // If we got here, all explicit agents are present (eligibility gate passed)
    score += 4;
    signals.push(`agents_covered:${explicitAgents.map(a => a.name).join(",")}`);
  }

  return {
    templateId: template.id,
    templateName: template.name,
    score,
    signals,
  };
}

// ─── Main Resolver ───────────────────────────────────────────────────────────

export async function resolveExecutionStrategy(
  order: WorkOrder,
  activeSubAgents: SubAgent[]
): Promise<ResolverResult> {
  const requestText = `${order.title} ${order.description || ""}`;
  const requestTokens = normalizeText(requestText);
  const requestFormat = detectRequiredFormatFromText(order.title, order.description || "");
  const explicitAgents = extractExplicitAgents(order, activeSubAgents);
  const isWorkflow = isWorkflowShaped(requestText, explicitAgents.length);

  // Fetch all workflow templates
  const templates = await storage.getWorkflowTemplates();
  if (templates.length === 0) {
    console.log("[resolver] No workflow templates found — direct execution");
    return { strategy: "direct" };
  }

  const scored: ScoredCandidate[] = [];
  const rejected: Array<{ templateId: string; reason: string }> = [];

  for (const template of templates) {
    const result = await scoreTemplate(
      template, requestTokens, requestFormat, explicitAgents, isWorkflow, activeSubAgents
    );
    if ("rejected" in result) {
      rejected.push(result);
    } else {
      scored.push(result);
    }
  }

  // Sort by score descending
  scored.sort((a, b) => b.score - a.score);

  const top = scored[0];
  const second = scored[1];

  // Selection threshold check
  if (!top || top.score < SELECTION_THRESHOLD) {
    const reason = top
      ? `top candidate "${top.templateName}" scored ${top.score} < threshold ${SELECTION_THRESHOLD}`
      : "no eligible candidates";
    console.log(`[resolver] ${reason} — direct execution`);
    return { strategy: "direct" };
  }

  // Margin check
  if (second && (top.score - second.score) < MARGIN_THRESHOLD) {
    console.log(`[resolver] top="${top.templateName}" (${top.score}) vs second="${second.templateName}" (${second.score}) — margin < ${MARGIN_THRESHOLD}, direct execution`);
    return { strategy: "direct" };
  }

  console.log(`[resolver] workflow match: "${top.templateName}" (score=${top.score}, signals=[${top.signals.join(", ")}])`);

  return {
    strategy: "workflow",
    templateId: top.templateId,
    score: top.score,
    reason: `Deterministic match: "${top.templateName}" (score=${top.score})`,
    matchedSignals: top.signals,
    rejectedCandidates: rejected,
  };
}

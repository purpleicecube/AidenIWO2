/**
 * web-research.ts — Centralized web-research routing for Chat.
 *
 * Both chat endpoints (session-based and stateless) call resolveWebResearch()
 * instead of duplicating trigger logic, search/scrape calls, and result formatting.
 *
 * Returns a structured WebResearchResult with explicit tool state so the LLM
 * prompt always knows whether research ran, succeeded, or was skipped.
 *
 * Loop 21 (2026-03-29): created — centralized routing.
 * Loop 22 (2026-03-29): WebResearchResult.status injected into prompt context.
 * Loop 24 (2026-03-29): conversational follow-up trigger awareness.
 */

import { executeBuiltInWebSearch, executeBuiltInWebScrape } from "./tool-executor";

// ── Types ────────────────────────────────────────────────────────────────────

export type WebResearchStatus = "not_run" | "ran" | "failed";

export interface WebResearchResult {
  /** Whether web research was attempted and what happened */
  status: WebResearchStatus;
  /** URLs that were actually visited/scraped */
  visitedUrls: string[];
  /** Count of result blocks returned (search results + scraped pages) */
  resultCount: number;
  /** Formatted context block to inject into systemContext (empty string if nothing) */
  contextBlock: string;
  /** Human-readable status line for prompt injection */
  statusLine: string;
}

export interface WebResearchOptions {
  /** The current user message */
  message: string;
  /** Conversation history (for follow-up awareness) */
  conversationHistory?: Array<{ role: string; content: string }>;
  /** Whether this message is a manager/operational question (skip web search) */
  isManagerQuestion?: boolean;
}

// ── Trigger patterns ─────────────────────────────────────────────────────────

/** Direct keyword triggers — questions or real-time data phrases (Loop 32: tightened "how" to exclude greetings) */
const KEYWORD_TRIGGER = /\b(what(?:'s| is| are| was| were| happened)|who(?:'s| is| are| was)|when(?:'s| is| did| was)|where(?:'s| is| are)|how (?:much|many|does|did|do|can|should|would|long|often|far)|latest|current|today|tomorrow|yesterday|recent|news|score|price|stock|weather|forecast|update|happening|trending|right now|as of|this week|this month)\b/i;

/** URL detection */
const URL_PATTERN = /https?:\/\/[^\s,\n]+/g;

/** Follow-up phrases that imply "go look this up externally" */
const FOLLOWUP_TRIGGER = /\b(did you (?:check|look|search|verify|find|visit|read|access|scrape|browse|open)|check (?:the|their|its|that|this)|look (?:up|at|into)|search (?:for|the|their)|go to|visit|can you (?:check|look|search|find|verify|access)|verify (?:on|at|from|via|with)|have you (?:checked|looked|searched|verified))\b/i;

/** Patterns indicating the conversation is about an external entity (company, website, person, org) */
const EXTERNAL_ENTITY_INDICATORS = /\b(website|site|page|company|organization|org|firm|team|leadership|about\s*(?:us|page)|linkedin|twitter|facebook|press\s*release|blog|homepage|investor|career|contact)\b/i;

// ── Core function ────────────────────────────────────────────────────────────

/**
 * Resolve whether web research should run, execute it if so, and return
 * structured results with explicit tool state.
 */
export async function resolveWebResearch(opts: WebResearchOptions): Promise<WebResearchResult> {
  const { message, conversationHistory, isManagerQuestion } = opts;

  // Determine if we need web research
  const foundUrls = message.match(URL_PATTERN);
  const hasKeywordTrigger = KEYWORD_TRIGGER.test(message) && !isManagerQuestion;
  const hasFollowupTrigger = detectFollowupIntent(message, conversationHistory);
  const needsWebSearch = hasKeywordTrigger || hasFollowupTrigger;

  if (!needsWebSearch && (!foundUrls || foundUrls.length === 0)) {
    return {
      status: "not_run",
      visitedUrls: [],
      resultCount: 0,
      contextBlock: "",
      statusLine: "WEB_RESEARCH_STATUS: not_run | No web research was performed for this turn.",
    };
  }

  // Execute web research
  const webResults: string[] = [];
  const visitedUrls: string[] = [];
  let anyFailed = false;

  if (needsWebSearch) {
    try {
      const searchQuery = message.replace(URL_PATTERN, "").trim().slice(0, 200);
      if (searchQuery.length >= 3) {
        console.log(`[web-research] Search triggered — query: "${searchQuery.slice(0, 60)}..."`);
        const searchResult = await executeBuiltInWebSearch(searchQuery);
        if (searchResult && searchResult.length > 100) {
          webResults.push("### Web Search Results\n" + searchResult.slice(0, 6000));
        }
      }
    } catch (err: any) {
      console.warn("[web-research] Search failed:", err.message);
      anyFailed = true;
    }
  }

  if (foundUrls && foundUrls.length > 0) {
    const urlsToScrape = foundUrls.slice(0, 3);
    visitedUrls.push(...urlsToScrape);
    try {
      console.log(`[web-research] Scrape triggered — ${urlsToScrape.length} URL(s)`);
      const scrapeResult = await executeBuiltInWebScrape(urlsToScrape.join(" "));
      if (scrapeResult && scrapeResult.length > 50) {
        webResults.push("### Web Page Content\n" + scrapeResult.slice(0, 8000));
      }
    } catch (err: any) {
      console.warn("[web-research] Scrape failed:", err.message);
      anyFailed = true;
    }
  }

  // Build result
  if (webResults.length > 0) {
    const contextBlock =
      "\n\n=== LIVE WEB RESEARCH (retrieved just now — use this data to answer accurately) ===\n" +
      webResults.join("\n\n");
    const statusLine = `WEB_RESEARCH_STATUS: ran | ${webResults.length} result block(s) returned` +
      (visitedUrls.length > 0 ? ` | URLs visited: ${visitedUrls.join(", ")}` : "");

    return {
      status: "ran",
      visitedUrls,
      resultCount: webResults.length,
      contextBlock,
      statusLine,
    };
  }

  // Research was attempted but produced no usable results
  if (anyFailed) {
    return {
      status: "failed",
      visitedUrls,
      resultCount: 0,
      contextBlock: "",
      statusLine: "WEB_RESEARCH_STATUS: failed | Web research was attempted but returned no usable results.",
    };
  }

  // Triggered but results were empty/too short
  return {
    status: "ran",
    visitedUrls,
    resultCount: 0,
    contextBlock: "",
    statusLine: "WEB_RESEARCH_STATUS: ran | Search executed but returned no substantive results.",
  };
}

// ── Follow-up intent detection ───────────────────────────────────────────────

/**
 * Detect whether the current message is a follow-up request to look something
 * up externally, based on conversation context.
 *
 * Triggers when:
 * 1. The current message uses follow-up phrasing ("did you check", "look up", etc.)
 *    AND
 * 2. The recent conversation references an external entity (company, website, page, etc.)
 *    OR the current message itself references one
 */
function detectFollowupIntent(
  message: string,
  conversationHistory?: Array<{ role: string; content: string }>
): boolean {
  if (!FOLLOWUP_TRIGGER.test(message)) return false;

  // Check if the current message itself references an external entity
  if (EXTERNAL_ENTITY_INDICATORS.test(message)) return true;

  // Check recent conversation history (last 4 messages) for external entity context
  if (conversationHistory && conversationHistory.length > 0) {
    const recentMessages = conversationHistory.slice(-4);
    for (const msg of recentMessages) {
      if (EXTERNAL_ENTITY_INDICATORS.test(msg.content)) return true;
      // Also trigger if prior messages contain URLs
      if (URL_PATTERN.test(msg.content)) return true;
    }
  }

  return false;
}

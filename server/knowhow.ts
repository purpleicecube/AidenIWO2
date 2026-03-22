/**
 * Know-How Retrieval Service — Phase 1: Deterministic Retrieval
 *
 * Shared retrieval engine used by Chat, Work Orders, and Workflows.
 * Resolves workspace content into token-budgeted ContextPacks with provenance.
 *
 * Ranking: explicit path (1.0) > keyword match (0.7) > code block (0.6) > GCC advisory boost (+0.1)
 */

import { randomUUID } from "crypto";
import { storage } from "./storage";
import type { WorkspaceProvider } from "./workspace-provider";
import type {
  ContextRequest,
  ContextPack,
  RetrievedSource,
  RetrievedChunk,
  ContextCitation,
  ContextError,
  ContextSourceType,
  SourceRelationship,
} from "@shared/schema";

const DEFAULT_TOKEN_BUDGET = 8000;
const DEFAULT_MAX_PER_SOURCE = 4000;
const DEFAULT_SOURCE_LIMIT = 10;
const CHARS_PER_TOKEN = 4; // rough estimate

function estimateTokens(text: string): number {
  return Math.ceil(text.length / CHARS_PER_TOKEN);
}

export class KnowHowService {
  constructor(private provider: WorkspaceProvider) {}

  async resolve(
    request: ContextRequest,
    gccMemory?: Record<string, any>
  ): Promise<ContextPack> {
    const requestId = randomUUID();
    const tokenBudget = request.tokenBudget ?? DEFAULT_TOKEN_BUDGET;
    const maxPerSource = request.maxPerSource ?? DEFAULT_MAX_PER_SOURCE;
    const limit = request.limit ?? DEFAULT_SOURCE_LIMIT;
    const errors: ContextError[] = [];
    const sourceMap = new Map<string, RetrievedSource & { _content?: string }>();

    // --- 1. Path resolution (score 1.0) ---
    if (request.paths && request.paths.length > 0) {
      for (const path of request.paths) {
        const entries = await this.provider.listFolder(path);
        if (entries.length === 0) {
          errors.push({
            path,
            message: `Folder "${path}" not found or empty`,
            code: "NOT_FOUND",
          });
          continue;
        }
        for (const entry of entries) {
          if (this.isUnsupportedMime(entry.mimeType)) continue;
          if (request.excludeIds?.includes(entry.id)) continue;
          sourceMap.set(entry.id, {
            id: entry.id,
            name: entry.name,
            sourceType: "artifact",
            mimeType: entry.mimeType || "text/plain",
            folderId: null,
            folderPath: path,
            relationship: "path_targeted",
            createdAt: entry.createdAt,
            updatedAt: entry.updatedAt,
            tags: [],
            score: 1.0,
            totalLength: 0,
            truncated: false,
          });
        }
      }
    }

    // --- 2. Keyword matching (score 0.7 base) ---
    if (request.keywords && request.keywords.length > 0) {
      for (const keyword of request.keywords) {
        const entries = await this.provider.searchByKeyword(keyword);
        for (const entry of entries) {
          if (this.isUnsupportedMime(entry.mimeType)) continue;
          if (request.excludeIds?.includes(entry.id)) continue;
          const existing = sourceMap.get(entry.id);
          if (existing && existing.score >= 0.7) continue; // path-targeted already higher
          let score = 0.7;
          if (entry.name.toLowerCase().includes(keyword.toLowerCase())) score += 0.1;
          sourceMap.set(entry.id, {
            id: entry.id,
            name: entry.name,
            sourceType: "artifact",
            mimeType: entry.mimeType || "text/plain",
            folderId: null,
            folderPath: entry.path,
            relationship: "keyword_matched",
            createdAt: entry.createdAt,
            updatedAt: entry.updatedAt,
            tags: [],
            score: Math.max(existing?.score ?? 0, score),
            totalLength: 0,
            truncated: false,
          });
        }
      }
    }

    // --- 3. Code block resolution (score 0.6 base) ---
    const wantsCodeBlocks =
      request.sourceTypes?.includes("code_block") ||
      (request.codeLanguages && request.codeLanguages.length > 0);
    if (wantsCodeBlocks) {
      const filters: { language?: string; tags?: string[] } = {};
      if (request.codeLanguages && request.codeLanguages.length === 1) {
        filters.language = request.codeLanguages[0];
      }
      const blocks = await storage.getCodeBlocks(filters);
      for (const block of blocks) {
        if (request.excludeIds?.includes(block.id)) continue;
        let score = 0.6;
        if (request.codeLanguages?.includes(block.language)) score += 0.2;
        if (request.keywords?.some(kw =>
          block.name.toLowerCase().includes(kw.toLowerCase()) ||
          (block.tags || []).some(t => t.toLowerCase().includes(kw.toLowerCase()))
        )) {
          score += 0.1;
        }
        const cbId = `cb:${block.id}`;
        sourceMap.set(cbId, {
          id: cbId,
          name: block.name,
          sourceType: "code_block",
          mimeType: `text/${block.language}`,
          folderId: null,
          folderPath: null,
          relationship: "code_block_match",
          createdAt: block.createdAt.toISOString(),
          updatedAt: block.updatedAt?.toISOString(),
          tags: block.tags || [],
          score,
          totalLength: block.content.length,
          truncated: false,
          _content: block.content, // pre-loaded for code blocks
        });
      }
    }

    // --- 4. GCC advisory boost (+0.1, never introduces sources) ---
    if (gccMemory) {
      const breadcrumbs: string[] = gccMemory["gcc.breadcrumbs"] || [];
      const lastAction: string = gccMemory["gcc.last_action"] || "";
      const metaTags: string[] = gccMemory["gcc.metadata"]?.tags || [];
      const signals = [...breadcrumbs, lastAction, ...metaTags]
        .map(s => s.toLowerCase())
        .filter(Boolean);

      if (signals.length > 0) {
        for (const [id, source] of sourceMap) {
          const nameLC = source.name.toLowerCase();
          const sourceTags = (source.tags || []).map(t => t.toLowerCase());
          const overlap = signals.some(
            sig => nameLC.includes(sig) || sourceTags.some(t => t.includes(sig))
          );
          if (overlap) {
            source.score = Math.min(1.0, source.score + 0.1);
          }
        }
      }
    }

    // --- 5. Recency filter ---
    if (request.recencyDays) {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - request.recencyDays);
      const cutoffStr = cutoff.toISOString();
      for (const [id, source] of sourceMap) {
        const sourceDate = source.updatedAt || source.createdAt;
        if (sourceDate < cutoffStr) {
          sourceMap.delete(id);
        }
      }
    }

    // --- 6. Sort by score desc, then updatedAt desc ---
    let sorted = Array.from(sourceMap.values()).sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      const aDate = a.updatedAt || a.createdAt;
      const bDate = b.updatedAt || b.createdAt;
      return bDate.localeCompare(aDate);
    });

    // --- 7. Apply limit ---
    sorted = sorted.slice(0, limit);

    // --- 8. Chunk & budget ---
    const sources: RetrievedSource[] = [];
    const chunks: RetrievedChunk[] = [];
    let tokensUsed = 0;
    let budgetExceeded = false;

    for (const source of sorted) {
      if (budgetExceeded) break;

      // Read content
      let content: string | null = null;
      if ((source as any)._content) {
        content = (source as any)._content;
      } else {
        content = await this.provider.readFile(source.id);
      }

      if (!content || content.trim().length === 0) {
        errors.push({
          path: source.folderPath ?? undefined,
          sourceType: source.sourceType,
          message: `Source "${source.name}" has empty content`,
          code: "EMPTY_CONTENT",
        });
        continue;
      }

      source.totalLength = content.length;

      // Truncate if single source exceeds maxPerSource
      const maxChars = maxPerSource * CHARS_PER_TOKEN;
      let chunkContent = content;
      if (content.length > maxChars) {
        chunkContent = content.slice(0, maxChars) + `\n... [truncated, ${content.length - maxChars} chars omitted]`;
        source.truncated = true;
      }

      const chunkTokens = estimateTokens(chunkContent);
      if (tokensUsed + chunkTokens > tokenBudget) {
        // Try to fit a partial chunk
        const remainingTokens = tokenBudget - tokensUsed;
        if (remainingTokens > 200) {
          const remainingChars = remainingTokens * CHARS_PER_TOKEN;
          chunkContent = content.slice(0, remainingChars) + `\n... [truncated by budget]`;
          source.truncated = true;
          const partialTokens = estimateTokens(chunkContent);
          tokensUsed += partialTokens;
          budgetExceeded = true;
        } else {
          budgetExceeded = true;
          continue;
        }
      } else {
        tokensUsed += chunkTokens;
      }

      // Clean internal field
      delete (source as any)._content;

      sources.push(source);
      chunks.push({
        sourceId: source.id,
        content: chunkContent,
        startOffset: 0,
        endOffset: chunkContent.length,
        language: source.sourceType === "code_block"
          ? source.mimeType.replace("text/", "")
          : undefined,
        tokenEstimate: estimateTokens(chunkContent),
      });
    }

    // --- 9. Build citations ---
    const citations: ContextCitation[] = sources.map(s => ({
      sourceId: s.id,
      sourceName: s.name,
      folderPath: s.folderPath ?? null,
      sourceType: s.sourceType,
      relationship: s.relationship,
    }));

    const pack: ContextPack = {
      requestId,
      sources,
      chunks,
      citations,
      tokenBudget,
      tokensUsed,
      truncated: budgetExceeded,
      resolvedAt: new Date().toISOString(),
      errors,
    };

    // Audit log (fire-and-forget)
    storage.createContextRetrieval({
      requestId,
      consumer: "unknown", // caller sets this
      consumerId: null,
      request: request as any,
      sourceCount: sources.length,
      tokensUsed,
      truncated: budgetExceeded,
      errors: errors as any,
    }).catch(() => {}); // don't block on audit

    return pack;
  }

  /**
   * Format a ContextPack into a string for LLM prompt injection.
   */
  formatForLLM(pack: ContextPack): string {
    if (pack.sources.length === 0) return "";

    const lines: string[] = [];
    lines.push(`=== KNOW-HOW CONTEXT (${pack.sources.length} source${pack.sources.length > 1 ? "s" : ""}, ~${pack.tokensUsed} tokens) ===`);
    lines.push("");
    lines.push("GROUNDING RULES:");
    lines.push("- Use ONLY the facts, data, metrics, and quotes found in the sources below.");
    lines.push("- Do NOT invent, extrapolate, or hallucinate numbers, statistics, or claims not present in the source content.");
    lines.push("- If the source content does not contain specific data you need, say so explicitly rather than fabricating it.");
    lines.push("- Cite which source a fact came from when using it.");
    lines.push("");

    for (const chunk of pack.chunks) {
      const source = pack.sources.find(s => s.id === chunk.sourceId);
      if (!source) continue;
      const loc = source.folderPath ? ` [${source.folderPath}]` : "";
      const lang = chunk.language ? ` (${chunk.language})` : "";
      lines.push(`--- Source: ${source.name}${loc} (${source.relationship})${lang} ---`);
      lines.push(chunk.content);
      lines.push("");
    }

    if (pack.citations.length > 0) {
      lines.push("=== CITATIONS ===");
      for (const c of pack.citations) {
        lines.push(`[${c.sourceId}] ${c.sourceName} (${c.folderPath || "no folder"}, ${c.sourceType})`);
      }
    }

    if (pack.truncated) {
      lines.push("");
      lines.push("[Note: Additional sources were available but omitted due to token budget]");
    }

    if (pack.errors.length > 0) {
      lines.push("");
      lines.push("=== RETRIEVAL WARNINGS ===");
      for (const e of pack.errors) {
        lines.push(`[${e.code}] ${e.message}`);
      }
    }

    lines.push("=== END KNOW-HOW CONTEXT ===");
    return lines.join("\n");
  }

  private isUnsupportedMime(mimeType?: string): boolean {
    if (!mimeType) return false;
    // Allow text/*, JSON, JS, and PDF (text extraction handled by WorkspaceProvider)
    if (mimeType.startsWith("text/")) return false;
    if (mimeType === "application/json") return false;
    if (mimeType === "application/javascript") return false;
    if (mimeType === "application/pdf") return false;
    return true;
  }
}

/**
 * Parse a natural-language chat message into a ContextRequest.
 * Extracts folder references, keywords, and code block intent.
 */
export function parseContextRequestFromChat(message: string): ContextRequest | null {
  const request: ContextRequest = {};
  let hasSignal = false;

  // Loop 14 Patch C: Normalize breadcrumb-style paths before folder detection.
  // "Workspace > 04_Resources > Demo_Content > KlearContent_Demo" → "04_Resources/Demo_Content/KlearContent_Demo"
  let normalizedMessage = message;
  const breadcrumbPattern = /(?:Workspace\s*>\s*)?(\d{2}_[A-Za-z_]+(?:\s*>\s*[A-Za-z0-9_.-]+)+)/gi;
  let bcMatch: RegExpExecArray | null;
  while ((bcMatch = breadcrumbPattern.exec(message)) !== null) {
    const breadcrumb = bcMatch[0];
    const normalized = breadcrumb
      .replace(/^Workspace\s*>\s*/i, "")
      .replace(/\s*>\s*/g, "/");
    normalizedMessage = normalizedMessage.replace(breadcrumb, `from ${normalized}`);
  }

  // Detect folder/path references: "from 05_Artifacts", "in /04_Resources", "folder 02_Execution"
  const folderPattern = /(?:from|in|folder|path|directory|content\s+from)\s+[/"]?(\d{2}_[A-Za-z_]+(?:\/[^\s"]*)?)/gi;
  let match: RegExpExecArray | null;
  const paths: string[] = [];
  while ((match = folderPattern.exec(normalizedMessage)) !== null) {
    paths.push(match[1]);
    hasSignal = true;
  }
  if (paths.length > 0) request.paths = paths;

  // Detect code block intent
  const codePattern = /\b(?:code\s*block|snippet|code\s*for|source\s*code)\b/i;
  if (codePattern.test(message)) {
    request.sourceTypes = ["code_block"];
    hasSignal = true;
  }

  // Detect language hints
  const langPattern = /\b(html|css|javascript|typescript|python|json|sql|bash|go|rust)\b/i;
  const langMatch = langPattern.exec(message);
  if (langMatch && request.sourceTypes?.includes("code_block")) {
    request.codeLanguages = [langMatch[1].toLowerCase()];
  }

  // Extract keywords from "about X", "related to X", "regarding X"
  const keywordPattern = /(?:about|related\s+to|regarding|for|using)\s+(?:the\s+)?["']?([a-zA-Z0-9_.-]+(?:\s+[a-zA-Z0-9_.-]+){0,2})["']?/gi;
  const keywords: string[] = [];
  while ((match = keywordPattern.exec(message)) !== null) {
    const kw = match[1].trim();
    // Skip common filler words
    if (!["the", "a", "an", "it", "this", "that", "my", "our"].includes(kw.toLowerCase())) {
      keywords.push(kw);
      hasSignal = true;
    }
  }
  if (keywords.length > 0) request.keywords = keywords;

  return hasSignal ? request : null;
}

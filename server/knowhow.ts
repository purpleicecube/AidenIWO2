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
import { canExtract } from "./text-extractor";
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

        // Inject a folder directory listing so the LLM can answer "what's in this folder?"
        // This includes child folders + artifacts as a structured overview.
        const dirListing = await this.buildFolderListing(path);
        if (dirListing) {
          const dirId = `dir:${path}`;
          sourceMap.set(dirId, {
            id: dirId,
            name: `Directory: ${path}`,
            sourceType: "artifact",
            mimeType: "text/plain",
            folderId: null,
            folderPath: path,
            relationship: "path_targeted",
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            tags: [],
            score: 1.0,
            totalLength: dirListing.length,
            truncated: false,
            _content: dirListing,
          } as any);
        }

        if (entries.length === 0 && !dirListing) {
          // Path didn't match a folder — fall back to artifact name search.
          // This handles cases like "RH2026_Klearai" which is a file name, not a folder.
          // Uses searchByName (name-only ILIKE) instead of searchByKeyword (name+content ILIKE)
          // to avoid scanning large base64 content blobs which can timeout on big workspaces.
          const nameHits = await this.provider.searchByName(path);
          if (nameHits.length > 0) {
            for (const entry of nameHits) {
              if (this.isUnsupportedMime(entry.mimeType)) continue;
              if (request.excludeIds?.includes(entry.id)) continue;
              // Score source documents higher than WO-generated derivatives.
              // WO outputs (work-product.md, execution-log.md, summaries, Gamma PDFs)
              // live in #Documents, 02_Execution, 00_Planning, or have WO-derived names.
              // Source documents (uploaded originals) live in 04_Resources, 05_Artifacts, etc.
              const score = this.isWoGeneratedArtifact(entry) ? 0.5 : 1.0;
              sourceMap.set(entry.id, {
                id: entry.id,
                name: entry.name,
                sourceType: "artifact",
                mimeType: entry.mimeType || "text/plain",
                folderId: null,
                folderPath: entry.path,
                relationship: score === 1.0 ? "path_targeted" : "keyword_matched",
                createdAt: entry.createdAt,
                updatedAt: entry.updatedAt,
                tags: [],
                score,
                totalLength: 0,
                truncated: false,
              });
            }
          } else {
            errors.push({
              path,
              message: `Folder or artifact "${path}" not found`,
              code: "NOT_FOUND",
            });
          }
          continue;
        }
        for (const entry of entries) {
          if (this.isUnsupportedMime(entry.mimeType)) continue;
          if (request.excludeIds?.includes(entry.id)) continue;
          // WO-generated artifacts (summaries, execution logs) score lower than source documents
          const baseScore = this.isWoGeneratedArtifact(entry) ? 0.5 : 1.0;
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
            score: baseScore,
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
          // WO-generated artifacts deprioritized in keyword results too
          if (this.isWoGeneratedArtifact(entry)) score *= 0.6;
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

  /**
   * Build a structured folder listing for a workspace path.
   * Returns a text overview of child folders and artifacts so the LLM
   * can answer "what's in this folder?" without needing file content.
   */
  private async buildFolderListing(path: string): Promise<string | null> {
    const folder = await storage.getArtifactFolderByPath(path);
    if (!folder) return null;

    const allFolders = await storage.getArtifactFolders();
    const folderPath = (folder as any).path || folder.name;

    // Find direct child folders
    const childFolders = allFolders.filter(f => f.parentId === folder.id);

    // Find direct artifacts
    const directArts = await storage.getArtifacts(folder.id);

    if (childFolders.length === 0 && directArts.length === 0) return null;

    const lines: string[] = [];
    lines.push(`# Folder: ${folderPath}`);
    if (folder.description) lines.push(`Description: ${folder.description}`);
    lines.push("");

    if (childFolders.length > 0) {
      lines.push(`## Subfolders (${childFolders.length})`);
      for (const child of childFolders) {
        const childPath = (child as any).path || child.name;
        const desc = child.description ? ` — ${child.description}` : "";
        // Count artifacts in child folder
        const childArts = await storage.getArtifacts(child.id);
        const artCount = childArts.length > 0 ? ` (${childArts.length} file${childArts.length === 1 ? "" : "s"})` : "";
        lines.push(`- **${child.name}**${artCount}${desc}`);
      }
      lines.push("");
    }

    if (directArts.length > 0) {
      lines.push(`## Files (${directArts.length})`);
      for (const art of directArts) {
        const size = art.size ? ` (${(art.size / 1024).toFixed(0)}KB)` : "";
        const mime = art.mimeType ? ` [${art.mimeType}]` : "";
        lines.push(`- ${art.name}${mime}${size}`);
      }
      lines.push("");
    }

    return lines.join("\n");
  }

  private isUnsupportedMime(mimeType?: string): boolean {
    if (!mimeType) return false;
    // Delegate to the universal text extractor registry — any MIME type with
    // a registered extractor (or natively text-readable) is supported.
    return !canExtract(mimeType);
  }

  /**
   * Detect whether an artifact is a WO-generated derivative rather than an original source.
   * WO outputs contain LLM-generated content that may include hallucinated data —
   * they should be deprioritized in favor of original source documents.
   *
   * WO outputs typically:
   *  - Live in #Documents, 02_Execution, 00_Planning, 01_Directive-SOP, #Code_Blocks
   *  - Have names like work-product.md, execution-log.md
   *  - Have names that start with WO-derived slugs (e.g., "summarize-xxx", "read-and-xxx")
   *
   * Source documents typically:
   *  - Live in 04_Resources, 05_Artifacts (manually uploaded)
   *  - Have original filenames with extensions (e.g., "Company Report.pdf")
   */
  private isWoGeneratedArtifact(entry: { name: string; path: string }): boolean {
    const path = (entry.path || "").toLowerCase();
    const name = (entry.name || "").toLowerCase();

    // WO filing folders
    if (path.includes("#documents/") || path.includes("02_execution/") ||
        path.includes("00_planning/") || path.includes("01_directive") ||
        path.includes("#code_blocks/")) {
      return true;
    }

    // WO-generated artifact names
    if (name === "work-product.md" || name === "execution-log.md") return true;

    // WO-derived slug names (auto-generated from WO titles)
    // These follow the pattern: "wo-title-slug.ext" or "wf-title-slug.ext"
    if (name.match(/^(summarize|read-and-|create-|generate-|build-|write-|draft-|wf-)/)) return true;

    return false;
  }
}

/**
 * Parse a natural-language chat message into a ContextRequest.
 * Extracts folder references, keywords, and code block intent.
 */
/**
 * Normalize a raw path reference from a WO description:
 * - Strip leading "Workspace/" prefix (provider resolves relative to workspace root)
 * - Strip leading "/"
 * - Trim trailing whitespace/punctuation
 */
function normalizePath(raw: string): string {
  return raw
    .replace(/^Workspace\//i, "")
    .replace(/^\//, "")
    .replace(/[,;)\]]+$/, "")
    .replace(/\s+(?:folder|directory|path)$/i, "")
    .trim();
}

export function parseContextRequestFromChat(message: string): ContextRequest | null {
  const request: ContextRequest = {};
  let hasSignal = false;
  const paths: string[] = [];

  // --- Phase 1: Label-colon path extraction ---
  // Catches "Web Style Guide: Design References/Purplegoo_1016-DESIGN.md"
  // and "Content Guide: Workspace/04_Resources/Demo_Content/KlearContent_Demo"
  // Pattern: "Label text: <path containing at least one />"
  // Label allows word chars, spaces, dots, hyphens (e.g., "Klear.ai Content Guide:")
  const labelColonPattern = /^[ \t]*[\w][\w\s.'-]*?:\s*([^\s:][^\n]*\/[^\n]+)$/gm;
  let match: RegExpExecArray | null;
  while ((match = labelColonPattern.exec(message)) !== null) {
    const candidate = normalizePath(match[1]);
    // Must contain a "/" path separator (not just " / " prose), and not be a URL.
    // Require at least one segment that looks like a filename/folder (word chars adjacent to /)
    if (/[\w]\/[\w]/.test(candidate) && !candidate.match(/^https?:\/\//i)) {
      paths.push(candidate);
      hasSignal = true;
    }
  }

  // --- Phase 2: Breadcrumb normalization (legacy) ---
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

  // --- Phase 3: Preposition + path extraction ---
  // Catches "from 05_Artifacts", "in /04_Resources", "folder 02_Execution"
  // Now also matches paths that DON'T start with ##_ (e.g., "from Design References/...")
  // Allows optional articles (the/a/an) between preposition and path
  const folderPattern = /(?:from|in|of|find\s+in|inside|within|folder|path|directory|content\s+from|references?\s+(?:in|at|from)?)\s+(?:the\s+|a\s+|an\s+)?[/"]?([A-Za-z0-9_#][\w-]*(?:\/[^\s"]*)?)/gi;
  while ((match = folderPattern.exec(normalizedMessage)) !== null) {
    const candidate = normalizePath(match[1]);
    // Accept if path-like (contains /) or starts with ##_ or contains an underscore
    // (workspace folders commonly use underscores: Demo_Content, KlearContent_Demo, etc.)
    // The preposition gate ("from", "in", "folder", etc.) already provides intent signal,
    // so an underscore-joined name following a preposition is very likely a folder reference.
    if (candidate.match(/\//) || candidate.match(/^\d{2}_/) || candidate.includes("_")) {
      if (!paths.includes(candidate)) {
        paths.push(candidate);
        hasSignal = true;
      }
    }
  }

  // --- Phase 3b: Bare workspace folder references ---
  // Catches "04_Resources" even without a preposition — standard ##_Name workspace folders
  const bareFolderPattern = /\b(\d{2}_[A-Za-z][A-Za-z0-9_-]*(?:\/[^\s"]*)?)\b/g;
  while ((match = bareFolderPattern.exec(message)) !== null) {
    const candidate = normalizePath(match[1]);
    if (!paths.includes(candidate)) {
      paths.push(candidate);
      hasSignal = true;
    }
  }

  // --- Phase 3c: Bare underscore-joined names ---
  // Catches workspace folder names like "Demo_Content", "KlearContent_Demo", "Do_Not_Use"
  // without a preposition. Requires at least one underscore and starts with a capital letter
  // to avoid matching common programming identifiers.
  const bareUnderscorePattern = /\b([A-Z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?:\/[^\s"]*)?)\b/g;
  while ((match = bareUnderscorePattern.exec(message)) !== null) {
    const candidate = normalizePath(match[1]);
    // Skip common programming/prose words that happen to have underscores
    if (candidate.match(/^(Work_Order|Sub_Agent|Know_How)$/i)) continue;
    if (!paths.includes(candidate)) {
      paths.push(candidate);
      hasSignal = true;
    }
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

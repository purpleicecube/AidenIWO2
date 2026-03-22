/**
 * skill-auto-import.ts
 * Keyword-matches a step description to available skills in .local/skills/,
 * imports any matches into the Tool Locker, and returns their tool IDs.
 */

import fs from "fs";
import path from "path";
import { storage } from "./storage";

// Keyword map: skill dirName → keywords that trigger auto-import
// HARDENED: removed broad single-word triggers ("design", "content", "web", "page", "build",
// "report", "test", "email", "art", "skill") that caused false-positive matches on nearly
// every WO description. Keywords must be specific enough to avoid tool bloat.
const SKILL_KEYWORD_MAP: Record<string, string[]> = {
  "brand-guidelines":      ["brand guidelines", "style guide", "color palette", "brand identity", "brand colors"],
  "canvas-design":         ["canvas design", "visual design document", "graphic design", "poster design", "banner design", "illustration"],
  "doc-coauthoring":       ["coauthor", "co-author", "collaborative document", "document draft"],
  "docx":                  ["docx", "word document", ".docx", "create word"],
  "frontend-design":       ["html page", "css stylesheet", "frontend component", "landing page", "web page", "ui component", "html file", "html5"],
  "internal-comms":        ["internal email", "slack message", "company announcement", "internal memo", "internal comms"],
  "mcp-builder":           ["mcp server", "mcp tool", "model context protocol", "mcp integration"],
  "pdf":                   ["pdf document", "pdf file", "generate pdf", "create pdf"],
  "klearai-pptx":          ["klear.ai deck", "klearai presentation", "klear branded", "klear.ai pptx"],
  "pptx":                  ["pptx", "powerpoint", "slide deck", "presentation deck", "pitch deck"],
  "skill-creator":         ["create skill", "agent skill", "new skill", "skill template"],
  "slack-gif-creator":     ["slack gif", "animated gif", "create gif"],
  "theme-factory":         ["design system", "theme tokens", "design tokens", "theme factory"],
  "webapp-testing":        ["webapp test", "web test", "playwright test", "quality assurance", "qa test"],
  "web-artifacts-builder": ["html artifact", "web artifact", "static site", "multi-component html", "web build"],
  "xlsx":                  ["xlsx", "excel file", "spreadsheet", "create excel", ".xlsx"],
};

const SKILLS_DIR = path.resolve(".local/skills");

/**
 * Given a step description (and optional step name), returns the IDs of all
 * skills that match. Imports any not yet in the Tool Locker.
 *
 * HARDENED: When subAgentId is provided and the agent has tool assignments,
 * auto-imported tools are filtered against the agent's assignment table.
 * Only tools explicitly enabled for this agent are returned.
 * This ensures the UI tool toggle is the single source of truth.
 */
export async function autoImportSkillsForDescription(
  description: string,
  name?: string,
  subAgentId?: string
): Promise<string[]> {
  const text = `${name || ""} ${description}`.toLowerCase();

  const matchedDirs: string[] = [];
  for (const [dirName, keywords] of Object.entries(SKILL_KEYWORD_MAP)) {
    if (keywords.some((kw) => text.includes(kw))) {
      matchedDirs.push(dirName);
    }
  }

  if (matchedDirs.length === 0) return [];

  const toolIds: string[] = [];
  const existingTools = await storage.getTools();

  for (const dirName of matchedDirs) {
    const slug = `skill-${dirName.replace(/[^a-z0-9]/gi, "-").toLowerCase()}`;
    const alreadyImported = existingTools.find((t) => t.slug === slug);
    if (alreadyImported) {
      toolIds.push(alreadyImported.id);
      continue;
    }

    // Import fresh
    const imported = await importSkill(dirName, slug);
    if (imported) toolIds.push(imported);
  }

  // HARDENED: If a sub-agent is specified and has tool assignments,
  // filter auto-imported tools to only those explicitly enabled for this agent.
  if (subAgentId && toolIds.length > 0) {
    const assigned = await storage.getSubAgentTools(subAgentId);
    if (assigned.length > 0) {
      const enabledIds = new Set(assigned.filter(a => a.enabled !== false).map(a => a.toolId));
      const filtered = toolIds.filter(id => enabledIds.has(id));
      if (filtered.length < toolIds.length) {
        console.log(`[skill-auto-import] Agent ${subAgentId}: filtered ${toolIds.length} auto-imports down to ${filtered.length} (respecting tool assignments)`);
      }
      return filtered;
    }
  }

  return toolIds;
}

async function importSkill(dirName: string, slug: string): Promise<string | null> {
  const skillDir = path.join(SKILLS_DIR, dirName);
  const skillMdPath = path.join(skillDir, "SKILL.md");

  if (!fs.existsSync(skillMdPath)) {
    console.warn(`[skill-auto-import] SKILL.md not found for: ${dirName}`);
    return null;
  }

  try {
    const content = fs.readFileSync(skillMdPath, "utf-8");

    let skillName = dirName;
    let description = "";
    const frontmatterMatch = content.match(/^---\s*\n([\s\S]*?)\n---/);
    if (frontmatterMatch) {
      const fm = frontmatterMatch[1];
      const nameMatch = fm.match(/^name:\s*(.+)$/m);
      const descMatch = fm.match(/^description:\s*(.+)$/m);
      if (nameMatch) skillName = nameMatch[1].trim();
      if (descMatch) description = descMatch[1].trim();
    }

    // Concatenate reference files (mirrors import-skill route logic)
    const refsDir = path.join(skillDir, "references");
    let fullContent = content;
    if (fs.existsSync(refsDir)) {
      const refFiles = fs.readdirSync(refsDir).filter((f) => f.endsWith(".md"));
      for (const refFile of refFiles) {
        const refContent = fs.readFileSync(path.join(refsDir, refFile), "utf-8");
        fullContent += `\n\n---\n## Reference: ${refFile}\n${refContent}`;
      }
    }
    const additionalFiles = fs.readdirSync(skillDir).filter((f) => f !== "SKILL.md" && f.endsWith(".md"));
    for (const addFile of additionalFiles) {
      const addContent = fs.readFileSync(path.join(skillDir, addFile), "utf-8");
      fullContent += `\n\n---\n## Reference: ${addFile}\n${addContent}`;
    }

    const finalName = skillName
      .split(/[-_]/)
      .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");

    const tool = await storage.createTool({
      name: finalName,
      slug,
      description,
      type: "skill",
      category: "general",
      status: "active",
      version: "1.0.0",
      skillContent: fullContent,
      executionMode: "prompt_injection",
      accessTier: "any",
      maxConcurrent: 0,
      defaultLeaseSeconds: 300,
      maxLeaseSeconds: 3600,
    });

    console.log(`[skill-auto-import] Imported skill "${finalName}" (${slug}) → tool ID: ${tool.id}`);
    return tool.id;
  } catch (err: any) {
    console.error(`[skill-auto-import] Failed to import ${dirName}:`, err.message);
    return null;
  }
}

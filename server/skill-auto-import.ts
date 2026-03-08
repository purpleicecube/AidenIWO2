/**
 * skill-auto-import.ts
 * Keyword-matches a step description to available skills in .local/skills/,
 * imports any matches into the Tool Locker, and returns their tool IDs.
 */

import fs from "fs";
import path from "path";
import { storage } from "./storage";

// Keyword map: skill dirName → keywords that trigger auto-import
const SKILL_KEYWORD_MAP: Record<string, string[]> = {
  "brand-guidelines":      ["brand", "style guide", "color palette", "typography", "logo", "identity"],
  "canvas-design":         ["design", "visual", "art", "graphic", "poster", "banner", "illustration"],
  "doc-coauthoring":       ["document", "write", "content", "copy", "draft", "article", "report", "blog"],
  "docx":                  ["docx", "word", "word document", ".docx"],
  "frontend-design":       ["html", "css", "frontend", "web", "website", "landing page", "ui", "interface", "page"],
  "internal-comms":        ["email", "slack", "announcement", "internal", "memo", "comms", "communication"],
  "mcp-builder":           ["mcp", "tool builder", "protocol", "integration", "connector"],
  "pdf":                   ["pdf", "portable document"],
  "pptx":                  ["pptx", "powerpoint", "presentation", "slide", "deck"],
  "skill-creator":         ["skill", "agent skill", "capability"],
  "slack-gif-creator":     ["gif", "slack gif", "animated"],
  "theme-factory":         ["theme", "styling", "design system", "tokens"],
  "webapp-testing":        ["test", "qa", "quality assurance", "validation", "verify"],
  "web-artifacts-builder": ["html", "web", "website", "artifact", "build", "page", "static site"],
  "xlsx":                  ["xlsx", "excel", "spreadsheet", "csv", "table data"],
};

const SKILLS_DIR = path.resolve(".local/skills");

/**
 * Given a step description (and optional step name), returns the IDs of all
 * skills that match. Imports any not yet in the Tool Locker.
 */
export async function autoImportSkillsForDescription(
  description: string,
  name?: string
): Promise<string[]> {
  const text = `${name || ""} ${description}`.toLowerCase();

  const matchedDirs: string[] = [];
  for (const [dirName, keywords] of Object.entries(SKILL_KEYWORD_MAP)) {
    if (keywords.some((kw) => text.includes(kw))) {
      matchedDirs.push(dirName);
    }
  }

  if (matchedDirs.length === 0) return [];

  // De-duplicate: if both frontend-design and web-artifacts-builder match,
  // keep both — they serve different purposes.
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

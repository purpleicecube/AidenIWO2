/**
 * Workspace Provider — Abstraction layer for workspace content access.
 * Local implementation wraps the DB-backed storage layer.
 * Swap this for Replit/remote implementation in Phase 3.
 */

import { storage } from "./storage";
import type { Artifact, ArtifactFolder } from "@shared/schema";

export interface WorkspaceEntry {
  id: string;
  name: string;
  path: string;
  type: "file" | "folder";
  mimeType?: string;
  size?: number;
  createdAt: string;
  updatedAt?: string;
}

export interface WorkspaceProvider {
  resolveRoot(): string;
  listFolder(path: string): Promise<WorkspaceEntry[]>;
  readFile(id: string): Promise<string | null>;
  searchByKeyword(keyword: string, folderId?: string): Promise<WorkspaceEntry[]>;
}

function artifactToEntry(a: Artifact, folderPath?: string): WorkspaceEntry {
  return {
    id: a.id,
    name: a.name,
    path: folderPath ? `${folderPath}/${a.name}` : a.name,
    type: "file",
    mimeType: a.mimeType ?? undefined,
    size: a.size ?? undefined,
    createdAt: a.createdAt.toISOString(),
    updatedAt: a.updatedAt?.toISOString(),
  };
}

/**
 * Extract readable text from a base64-encoded PDF.
 * Returns extracted text or a failure message (never throws).
 */
/**
 * Extract readable text from a base64-encoded PDF using pdf-parse v1.x.
 * Returns extracted text or a failure message (never throws).
 */
/**
 * Extract readable text from a base64-encoded PDF.
 * Uses pdf-parse lib directly (bypasses index.js which has a debug-mode file read bug in ESM).
 */
async function extractTextFromPdf(base64Content: string): Promise<string | null> {
  try {
    // Import the lib directly to avoid the index.js debug-mode test file read
    const pdfParse = (await import("pdf-parse/lib/pdf-parse.js")).default
      ?? (await import("pdf-parse/lib/pdf-parse.js"));
    const buffer = Buffer.from(base64Content, "base64");
    const data = await (pdfParse as any)(buffer);
    const text = (data.text || "").trim();
    if (text.length === 0) {
      return "[PDF contained no extractable text — may be image-only or scanned]";
    }
    console.log(`[workspace-provider] PDF text extracted: ${text.length} chars`);
    return text;
  } catch (err: any) {
    console.warn("[workspace-provider] PDF text extraction failed:", err.message);
    return null;
  }
}

export class LocalWorkspaceProvider implements WorkspaceProvider {
  resolveRoot(): string {
    return "/";
  }

  async listFolder(path: string): Promise<WorkspaceEntry[]> {
    // Resolve folder by path or name
    const folder = await storage.getArtifactFolderByPath(path);
    if (!folder) return [];

    const folderPath = (folder as any).path || folder.name;

    // Get artifacts directly in this folder
    const directArts = await storage.getArtifacts(folder.id);
    const entries = directArts.map(a => artifactToEntry(a, folderPath));

    // If no direct artifacts, also check child folders (workspace uses nested date folders)
    if (entries.length === 0) {
      const allFolders = await storage.getArtifactFolders();
      const childFolders = allFolders.filter(f =>
        (f as any).path?.startsWith(folderPath + "/") && f.id !== folder.id
      );
      for (const child of childFolders.slice(0, 20)) { // cap child folder scan
        const childArts = await storage.getArtifacts(child.id);
        const childPath = (child as any).path || child.name;
        entries.push(...childArts.map(a => artifactToEntry(a, childPath)));
      }
    }

    return entries;
  }

  async readFile(id: string): Promise<string | null> {
    const artifact = await storage.getArtifact(id);
    if (!artifact) return null;
    const content = artifact.content ?? null;
    if (!content) return null;

    // PDF: decode base64 and extract text
    if (artifact.mimeType === "application/pdf") {
      return extractTextFromPdf(content);
    }

    return content;
  }

  async searchByKeyword(keyword: string, folderId?: string): Promise<WorkspaceEntry[]> {
    const arts = await storage.searchArtifactsByKeyword(keyword, folderId ?? null);
    return arts.map(a => artifactToEntry(a));
  }
}

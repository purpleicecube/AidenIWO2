/**
 * Workspace Provider — Abstraction layer for workspace content access.
 * Local implementation wraps the DB-backed storage layer.
 * Swap this for Replit/remote implementation in Phase 3.
 *
 * Text extraction from binary artifacts (PDF, DOCX, PPTX) is delegated to
 * the universal TextExtractor service (server/text-extractor.ts). To add
 * support for a new format, register an extractor there — no changes needed here.
 */

import { storage } from "./storage";
import { extractText, canExtract } from "./text-extractor";
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
  searchByName(keyword: string): Promise<WorkspaceEntry[]>;
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
    const mimeType = artifact.mimeType || "text/plain";

    // Delegate to universal text extractor — handles PDF, DOCX, PPTX, and text passthrough
    return extractText(content, mimeType);
  }

  async searchByKeyword(keyword: string, folderId?: string): Promise<WorkspaceEntry[]> {
    const arts = await storage.searchArtifactsByKeyword(keyword, folderId ?? null);
    return arts.map(a => artifactToEntry(a));
  }

  async searchByName(keyword: string): Promise<WorkspaceEntry[]> {
    const arts = await storage.searchArtifactsByName(keyword);
    return arts.map(a => artifactToEntry(a));
  }
}

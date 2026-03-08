import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { queryClient, apiRequest } from "@/lib/queryClient";
import { usePageTitle } from "@/hooks/use-page-title";
import type { ArtifactFolder, Artifact } from "@shared/schema";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/hooks/use-toast";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Folder,
  FileText,
  ChevronRight,
  Home,
  Plus,
  FolderPlus,
  FilePlus,
  Trash2,
  Edit,
  MoreVertical,
  ArrowLeft,
  Download,
  Eye,
  X,
  RefreshCw,
  FileCode,
  FileJson,
  File,
  Save,
  GripVertical,
  FileSpreadsheet,
  FileImage,
  FileArchive,
  Presentation,
  Globe,
} from "lucide-react";
import SplitPane from "@/components/split-pane";
import { ExpandablePanel } from "@/components/expandable-panel";

const FILE_ICONS: Record<string, typeof FileText> = {
  "text/markdown": FileText,
  "text/plain": FileText,
  "application/json": FileJson,
  "text/javascript": FileCode,
  "text/typescript": FileCode,
  "text/html": Globe,
  "text/css": FileCode,
  "application/pdf": FileText,
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": Presentation,
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileText,
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileSpreadsheet,
  "application/msword": FileText,
  "application/vnd.ms-excel": FileSpreadsheet,
  "application/vnd.ms-powerpoint": Presentation,
  "application/zip": FileArchive,
  "application/gzip": FileArchive,
  "application/x-tar": FileArchive,
  "image/png": FileImage,
  "image/jpeg": FileImage,
  "image/gif": FileImage,
  "image/svg+xml": FileImage,
  "image/webp": FileImage,
};

function getFileIcon(mimeType?: string | null) {
  if (!mimeType) return File;
  return FILE_ICONS[mimeType] || File;
}

/** Classify how to render/preview an artifact */
function getFileCategory(name: string, mimeType: string): "binary-download" | "html-preview" | "image-preview" | "text-preview" {
  const ext = name?.split(".").pop()?.toLowerCase() || "";
  // Binary download types
  if (["pptx", "ppt", "docx", "doc", "xlsx", "xls", "pdf", "zip", "gz", "tar", "7z", "rar"].includes(ext)) return "binary-download";
  if (mimeType.includes("vnd.openxmlformats") || mimeType.includes("octet-stream") || mimeType.includes("zip") || mimeType.includes("pdf") || mimeType.includes("msword") || mimeType.includes("ms-excel") || mimeType.includes("ms-powerpoint")) return "binary-download";
  // Images
  if (mimeType.startsWith("image/") || ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) return "image-preview";
  // HTML/CSS self-contained preview
  if (ext === "html" || ext === "htm" || mimeType === "text/html") return "html-preview";
  // Everything else: text/markdown/code/mermaid
  return "text-preview";
}

const FILE_TYPE_LABELS: Record<string, string> = {
  pptx: "PowerPoint", ppt: "PowerPoint", docx: "Word Document", doc: "Word Document",
  xlsx: "Excel Spreadsheet", xls: "Excel Spreadsheet", pdf: "PDF Document",
  zip: "ZIP Archive", gz: "GZip Archive", tar: "TAR Archive", "7z": "7-Zip Archive", rar: "RAR Archive",
  md: "Markdown", html: "HTML", htm: "HTML", css: "Stylesheet", js: "JavaScript", ts: "TypeScript",
  json: "JSON", mmd: "Mermaid Diagram", mermaid: "Mermaid Diagram", svg: "SVG Image",
  png: "PNG Image", jpg: "JPEG Image", jpeg: "JPEG Image", gif: "GIF Image", webp: "WebP Image",
};

function formatDate(dateStr: string | Date) {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatSize(bytes: number | null) {
  if (!bytes || bytes === 0) return "--";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function WorkspacePage() {
  usePageTitle("Workspace");
  const { toast } = useToast();
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [breadcrumbs, setBreadcrumbs] = useState<{ id: string | null; name: string }[]>([
    { id: null, name: "Workspace" },
  ]);
  const [selectedArtifact, setSelectedArtifact] = useState<Artifact | null>(null);
  const [showNewFolderDialog, setShowNewFolderDialog] = useState(false);
  const [showNewFileDialog, setShowNewFileDialog] = useState(false);
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [editingArtifact, setEditingArtifact] = useState<Artifact | null>(null);
  const [showRenameFolderDialog, setShowRenameFolderDialog] = useState(false);
  const [renamingFolder, setRenamingFolder] = useState<ArtifactFolder | null>(null);
  const [newFolderName, setNewFolderName] = useState("");
  const [newFolderDesc, setNewFolderDesc] = useState("");
  const [newFileName, setNewFileName] = useState("");
  const [newFileType, setNewFileType] = useState("text/markdown");
  const [newFileContent, setNewFileContent] = useState("");
  const [editContent, setEditContent] = useState("");
  const [renameFolderName, setRenameFolderName] = useState("");
  const [draggedFileId, setDraggedFileId] = useState<string | null>(null);
  const [dropTargetFolderId, setDropTargetFolderId] = useState<string | null>(null);
  const [isDraggingOverParent, setIsDraggingOverParent] = useState(false);

  const folderQueryKey = currentFolderId
    ? ["/api/artifact-folders", { parentId: currentFolderId }]
    : ["/api/artifact-folders", { parentId: "root" }];

  const artifactQueryKey = currentFolderId
    ? ["/api/artifacts", { folderId: currentFolderId }]
    : ["/api/artifacts", { folderId: "root" }];

  const { data: folders = [], isLoading: foldersLoading } = useQuery<ArtifactFolder[]>({
    queryKey: folderQueryKey,
    queryFn: async () => {
      const pid = currentFolderId || "root";
      const res = await fetch(`/api/artifact-folders?parentId=${pid}`);
      if (!res.ok) throw new Error("Failed to fetch folders");
      return res.json();
    },
  });

  const { data: files = [], isLoading: filesLoading } = useQuery<Artifact[]>({
    queryKey: artifactQueryKey,
    queryFn: async () => {
      const fid = currentFolderId || "root";
      const res = await fetch(`/api/artifacts?folderId=${fid}`);
      if (!res.ok) throw new Error("Failed to fetch files");
      return res.json();
    },
  });

  const seedMutation = useMutation({
    mutationFn: () => apiRequest("POST", "/api/workspace/seed"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifact-folders"] });
      queryClient.invalidateQueries({ queryKey: ["/api/artifacts"] });
      toast({ title: "Workspace initialized", description: "Default folder structure created" });
    },
  });

  const createFolderMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; parentId?: string | null; path: string }) =>
      apiRequest("POST", "/api/artifact-folders", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifact-folders"] });
      setShowNewFolderDialog(false);
      setNewFolderName("");
      setNewFolderDesc("");
      toast({ title: "Folder created" });
    },
  });

  const createFileMutation = useMutation({
    mutationFn: (data: { name: string; folderId?: string | null; type: string; mimeType: string; content: string; size: number }) =>
      apiRequest("POST", "/api/artifacts", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifacts"] });
      setShowNewFileDialog(false);
      setNewFileName("");
      setNewFileContent("");
      toast({ title: "File created" });
    },
  });

  const updateArtifactMutation = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      apiRequest("PUT", `/api/artifacts/${id}`, { content, size: new Blob([content]).size }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifacts"] });
      toast({ title: "File saved" });
    },
  });

  const deleteFolderMutation = useMutation({
    mutationFn: (id: string) => apiRequest("DELETE", `/api/artifact-folders/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifact-folders"] });
      queryClient.invalidateQueries({ queryKey: ["/api/artifacts"] });
      toast({ title: "Folder deleted" });
    },
  });

  const deleteArtifactMutation = useMutation({
    mutationFn: (id: string) => apiRequest("DELETE", `/api/artifacts/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifacts"] });
      setSelectedArtifact(null);
      toast({ title: "File deleted" });
    },
  });

  const renameFolderMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) =>
      apiRequest("PUT", `/api/artifact-folders/${id}`, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifact-folders"] });
      setShowRenameFolderDialog(false);
      setRenamingFolder(null);
      toast({ title: "Folder renamed" });
    },
  });

  const moveFileMutation = useMutation({
    mutationFn: ({ id, folderId }: { id: string; folderId: string | null }) =>
      apiRequest("PUT", `/api/artifacts/${id}`, { folderId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/artifacts"] });
      toast({ title: "File moved" });
    },
    onError: () => {
      toast({ title: "Failed to move file", variant: "destructive" });
    },
  });

  const handleDragStart = (e: React.DragEvent, fileId: string) => {
    e.dataTransfer.setData("text/plain", fileId);
    e.dataTransfer.effectAllowed = "move";
    setDraggedFileId(fileId);
  };

  const handleDragEnd = () => {
    setDraggedFileId(null);
    setDropTargetFolderId(null);
    setIsDraggingOverParent(false);
  };

  const handleFolderDragOver = (e: React.DragEvent, folderId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDropTargetFolderId(folderId);
  };

  const handleFolderDragLeave = () => {
    setDropTargetFolderId(null);
  };

  const handleFolderDrop = (e: React.DragEvent, targetFolderId: string) => {
    e.preventDefault();
    const fileId = e.dataTransfer.getData("text/plain");
    if (fileId) {
      moveFileMutation.mutate({ id: fileId, folderId: targetFolderId });
    }
    setDropTargetFolderId(null);
    setDraggedFileId(null);
  };

  const handleParentDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setIsDraggingOverParent(true);
  };

  const handleParentDragLeave = () => {
    setIsDraggingOverParent(false);
  };

  const handleParentDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const fileId = e.dataTransfer.getData("text/plain");
    if (fileId && breadcrumbs.length > 1) {
      const parentFolderId = breadcrumbs[breadcrumbs.length - 2].id;
      moveFileMutation.mutate({ id: fileId, folderId: parentFolderId });
    }
    setIsDraggingOverParent(false);
    setDraggedFileId(null);
  };

  const navigateToFolder = (folder: ArtifactFolder) => {
    setCurrentFolderId(folder.id);
    setBreadcrumbs((prev) => [...prev, { id: folder.id, name: folder.name }]);
    setSelectedArtifact(null);
  };

  const navigateToBreadcrumb = (index: number) => {
    const crumb = breadcrumbs[index];
    setCurrentFolderId(crumb.id);
    setBreadcrumbs((prev) => prev.slice(0, index + 1));
    setSelectedArtifact(null);
  };

  const handleCreateFolder = () => {
    if (!newFolderName.trim()) return;
    const parentPath = breadcrumbs.map((b) => b.name).join("/");
    createFolderMutation.mutate({
      name: newFolderName.trim(),
      description: newFolderDesc.trim() || undefined,
      parentId: currentFolderId,
      path: `${parentPath}/${newFolderName.trim()}`,
    });
  };

  const handleCreateFile = () => {
    if (!newFileName.trim()) return;
    createFileMutation.mutate({
      name: newFileName.trim(),
      folderId: currentFolderId,
      type: "file",
      mimeType: newFileType,
      content: newFileContent,
      size: new Blob([newFileContent]).size,
    });
  };

  const openEditor = (artifact: Artifact) => {
    setEditingArtifact(artifact);
    setEditContent(artifact.content || "");
    setShowEditDialog(true);
  };

  const handleSaveEdit = () => {
    if (!editingArtifact) return;
    updateArtifactMutation.mutate(
      { id: editingArtifact.id, content: editContent },
      {
        onSuccess: () => {
          setShowEditDialog(false);
          setEditingArtifact(null);
          if (selectedArtifact?.id === editingArtifact.id) {
            setSelectedArtifact({ ...editingArtifact, content: editContent });
          }
        },
      }
    );
  };

  const isLoading = foldersLoading || filesLoading;
  const isEmpty = folders.length === 0 && files.length === 0 && !isLoading;

  const fileBrowserPanel = (
      <div className="flex flex-col min-w-0 h-full">
        <div className="p-4 border-b sticky top-0 z-10 bg-background">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-2 min-w-0 flex-wrap">
              {breadcrumbs.map((crumb, i) => {
                const isLastBreadcrumb = i === breadcrumbs.length - 1;
                const isBreadcrumbDropTarget = draggedFileId && !isLastBreadcrumb;
                return (
                  <div key={i} className="flex items-center gap-1">
                    {i > 0 && <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0" />}
                    <button
                      onClick={() => navigateToBreadcrumb(i)}
                      onDragOver={(e) => {
                        if (isBreadcrumbDropTarget) {
                          e.preventDefault();
                          e.dataTransfer.dropEffect = "move";
                        }
                      }}
                      onDrop={(e) => {
                        if (isBreadcrumbDropTarget) {
                          e.preventDefault();
                          const fileId = e.dataTransfer.getData("text/plain");
                          if (fileId) {
                            moveFileMutation.mutate({ id: fileId, folderId: crumb.id });
                          }
                          setDraggedFileId(null);
                        }
                      }}
                      className={`text-sm hover-elevate rounded px-1.5 py-0.5 truncate max-w-[160px] transition-all duration-150 ${
                        isBreadcrumbDropTarget ? "ring-1 ring-primary/50 bg-primary/5" : ""
                      }`}
                      data-testid={`breadcrumb-${i}`}
                    >
                      {i === 0 ? (
                        <span className="flex items-center gap-1">
                          <Home className="w-3.5 h-3.5" />
                          <span>{crumb.name}</span>
                        </span>
                      ) : (
                        crumb.name
                      )}
                    </button>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center gap-2">
              {breadcrumbs.length > 1 && (
                <Button
                  size="sm"
                  variant={isDraggingOverParent ? "default" : "ghost"}
                  className={`transition-all duration-150 ${
                    isDraggingOverParent ? "ring-2 ring-primary scale-105" : ""
                  }`}
                  onClick={() => navigateToBreadcrumb(breadcrumbs.length - 2)}
                  onDragOver={handleParentDragOver}
                  onDragLeave={handleParentDragLeave}
                  onDrop={handleParentDrop}
                  data-testid="button-go-back"
                >
                  <ArrowLeft className="w-4 h-4 mr-1" />
                  {draggedFileId ? "Drop here to move up" : "Back"}
                </Button>
              )}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button size="sm" data-testid="button-new-item">
                    <Plus className="w-4 h-4 mr-1" />
                    New
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem
                    onClick={() => setShowNewFolderDialog(true)}
                    data-testid="menu-new-folder"
                  >
                    <FolderPlus className="w-4 h-4 mr-2" />
                    New Folder
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => setShowNewFileDialog(true)}
                    data-testid="menu-new-file"
                  >
                    <FilePlus className="w-4 h-4 mr-2" />
                    New File
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              {isEmpty && currentFolderId === null && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => seedMutation.mutate()}
                  disabled={seedMutation.isPending}
                  data-testid="button-init-workspace"
                >
                  <RefreshCw className={`w-4 h-4 mr-1 ${seedMutation.isPending ? "animate-spin" : ""}`} />
                  Initialize Workspace
                </Button>
              )}
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {isLoading ? (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
              {Array.from({ length: 8 }).map((_, i) => (
                <Card key={i} className="p-4 animate-pulse">
                  <div className="w-10 h-10 bg-muted rounded mb-2" />
                  <div className="w-3/4 h-3 bg-muted rounded" />
                </Card>
              ))}
            </div>
          ) : isEmpty ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <Folder className="w-16 h-16 text-muted-foreground mb-4" />
              <h3 className="text-lg font-medium mb-2">Empty Workspace</h3>
              <p className="text-sm text-muted-foreground mb-6 max-w-md">
                {currentFolderId === null
                  ? "Initialize your workspace with the standard folder structure for planning, directives, execution, and artifacts."
                  : "This folder is empty. Create new files or folders to get started."}
              </p>
              {currentFolderId === null && (
                <Button
                  onClick={() => seedMutation.mutate()}
                  disabled={seedMutation.isPending}
                  data-testid="button-init-workspace-empty"
                >
                  <RefreshCw className={`w-4 h-4 mr-2 ${seedMutation.isPending ? "animate-spin" : ""}`} />
                  Initialize Workspace
                </Button>
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
              {folders.map((folder) => (
                <Card
                  key={folder.id}
                  className={`group p-3 hover-elevate cursor-pointer transition-all duration-150 ${
                    dropTargetFolderId === folder.id
                      ? "ring-2 ring-primary bg-primary/10 scale-105"
                      : ""
                  }`}
                  onClick={() => navigateToFolder(folder)}
                  onDragOver={(e) => handleFolderDragOver(e, folder.id)}
                  onDragLeave={handleFolderDragLeave}
                  onDrop={(e) => handleFolderDrop(e, folder.id)}
                  data-testid={`folder-${folder.id}`}
                >
                  <div className="flex items-start justify-between gap-1">
                    <div className="flex flex-col items-center w-full text-center">
                      <Folder className="w-10 h-10 text-primary mb-2 shrink-0" />
                      <span className="text-xs font-medium truncate w-full" title={folder.name}>
                        {folder.name}
                      </span>
                      {folder.description && (
                        <span className="text-[10px] text-muted-foreground mt-0.5 line-clamp-2">
                          {folder.description}
                        </span>
                      )}
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="shrink-0 invisible group-hover:visible"
                          data-testid={`folder-menu-${folder.id}`}
                        >
                          <MoreVertical className="w-3 h-3" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                        <DropdownMenuItem onClick={() => {
                          setRenamingFolder(folder);
                          setRenameFolderName(folder.name);
                          setShowRenameFolderDialog(true);
                        }}>
                          <Edit className="w-4 h-4 mr-2" />
                          Rename
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive"
                          onClick={() => deleteFolderMutation.mutate(folder.id)}
                        >
                          <Trash2 className="w-4 h-4 mr-2" />
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </Card>
              ))}

              {files.map((file) => {
                const IconComponent = getFileIcon(file.mimeType);
                const isSelected = selectedArtifact?.id === file.id;
                const isDragging = draggedFileId === file.id;
                return (
                  <Card
                    key={file.id}
                    className={`group p-3 hover-elevate cursor-pointer transition-all duration-150 ${
                      isSelected ? "ring-2 ring-primary" : ""
                    } ${isDragging ? "opacity-40 scale-95" : ""}`}
                    draggable
                    onDragStart={(e) => handleDragStart(e, file.id)}
                    onDragEnd={handleDragEnd}
                    onClick={() => setSelectedArtifact(file)}
                    data-testid={`file-${file.id}`}
                  >
                    <div className="flex items-start justify-between gap-1">
                      <div className="flex flex-col items-center w-full text-center relative">
                        <GripVertical className="w-3 h-3 text-muted-foreground/40 absolute -left-1 top-3 opacity-0 group-hover:opacity-100 transition-opacity" />
                        <IconComponent className="w-10 h-10 text-muted-foreground mb-2 shrink-0" />
                        <span className="text-xs font-medium truncate w-full" title={file.name}>
                          {file.name}
                        </span>
                        <span className="text-[10px] text-muted-foreground mt-0.5">
                          {formatSize(file.size)}
                        </span>
                      </div>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="shrink-0 invisible group-hover:visible"
                            data-testid={`file-menu-${file.id}`}
                          >
                            <MoreVertical className="w-3 h-3" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                          <DropdownMenuItem onClick={() => setSelectedArtifact(file)}>
                            <Eye className="w-4 h-4 mr-2" />
                            View
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={() => openEditor(file)}>
                            <Edit className="w-4 h-4 mr-2" />
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className="text-destructive"
                            onClick={() => deleteArtifactMutation.mutate(file.id)}
                          >
                            <Trash2 className="w-4 h-4 mr-2" />
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
  );

  const previewPanel = selectedArtifact ? (
        <div className="flex flex-col bg-background h-full" data-testid="panel-file-preview">
          <div className="p-3 border-b flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              {(() => {
                const Icon = getFileIcon(selectedArtifact.mimeType);
                return <Icon className="w-4 h-4 text-muted-foreground shrink-0" />;
              })()}
              <span className="text-sm font-medium truncate">{selectedArtifact.name}</span>
            </div>
            <div className="flex items-center gap-1">
              <ExpandablePanel
                title={selectedArtifact.name}
              >
                <div className="p-6">
                  {getFileCategory(selectedArtifact.name || "", selectedArtifact.mimeType || "") === "binary-download" ? (
                    <div className="flex flex-col items-center gap-4 py-8">
                      <p className="text-sm text-muted-foreground">Binary file — use download button below</p>
                      <a
                        href={`/api/artifacts/${selectedArtifact.id}/download`}
                        download={selectedArtifact.name}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                      >
                        <Download className="w-4 h-4" />
                        Download {selectedArtifact.name?.split(".").pop()?.toUpperCase()}
                      </a>
                    </div>
                  ) : getFileCategory(selectedArtifact.name || "", selectedArtifact.mimeType || "") === "html-preview" ? (
                    <iframe
                      srcDoc={selectedArtifact.content || ""}
                      sandbox="allow-scripts allow-same-origin"
                      className="w-full h-[80vh] rounded-lg border bg-white"
                      title={selectedArtifact.name}
                    />
                  ) : (
                    <pre className="text-sm whitespace-pre-wrap font-mono leading-relaxed" data-testid="text-file-content-expanded">
                      {selectedArtifact.content || "No content"}
                    </pre>
                  )}
                </div>
              </ExpandablePanel>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => openEditor(selectedArtifact)}
                data-testid="button-edit-file"
              >
                <Edit className="w-4 h-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setSelectedArtifact(null)}
                data-testid="button-close-preview"
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </div>
          <div className="p-3 border-b">
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div>
                <span className="text-muted-foreground">Type</span>
                <div>{selectedArtifact.mimeType || "Unknown"}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Size</span>
                <div>{formatSize(selectedArtifact.size)}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Created</span>
                <div>{formatDate(selectedArtifact.createdAt)}</div>
              </div>
              <div>
                <span className="text-muted-foreground">Modified</span>
                <div>{formatDate(selectedArtifact.updatedAt)}</div>
              </div>
            </div>
            {selectedArtifact.tags && (selectedArtifact.tags as string[]).length > 0 && (
              <div className="flex items-center gap-1 mt-2 flex-wrap">
                {(selectedArtifact.tags as string[]).map((tag, i) => (
                  <Badge key={i} variant="secondary" className="text-[10px]">
                    {tag}
                  </Badge>
                ))}
              </div>
            )}
          </div>
          <div className="flex-1 overflow-auto p-3">
            {(() => {
              const mime = selectedArtifact.mimeType || "";
              const name = selectedArtifact.name || "";
              const ext = name.split(".").pop()?.toLowerCase() || "";
              const category = getFileCategory(name, mime);
              const sizeKB = selectedArtifact.size ? (selectedArtifact.size / 1024).toFixed(0) : "?";
              const typeLabel = FILE_TYPE_LABELS[ext] || ext.toUpperCase() || "File";
              const IconComp = getFileIcon(mime);

              // Binary download: .pptx, .docx, .xlsx, .pdf, .zip, etc.
              if (category === "binary-download") {
                return (
                  <div className="flex flex-col items-center justify-center py-12 gap-4" data-testid="binary-file-preview">
                    <div className="w-20 h-20 rounded-xl bg-primary/10 flex items-center justify-center">
                      <IconComp className="w-10 h-10 text-primary" />
                    </div>
                    <div className="text-center">
                      <p className="text-sm font-medium">{name}</p>
                      <p className="text-xs text-muted-foreground mt-1">{typeLabel} — {sizeKB} KB</p>
                    </div>
                    <div className="flex gap-2">
                      <a
                        href={`/api/artifacts/${selectedArtifact.id}/download`}
                        download={name}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors"
                        data-testid="button-download-artifact"
                      >
                        <Download className="w-4 h-4" />
                        Download {typeLabel}
                      </a>
                    </div>
                  </div>
                );
              }

              // Image preview: inline display + download
              if (category === "image-preview" && selectedArtifact.content) {
                const isSvg = ext === "svg" || mime === "image/svg+xml";
                const imgSrc = isSvg
                  ? `data:image/svg+xml;base64,${btoa(selectedArtifact.content)}`
                  : `data:${mime};base64,${selectedArtifact.content}`;
                return (
                  <div className="flex flex-col items-center gap-4" data-testid="image-file-preview">
                    <img src={imgSrc} alt={name} className="max-w-full max-h-[50vh] rounded-lg border" />
                    <a
                      href={`/api/artifacts/${selectedArtifact.id}/download`}
                      download={name}
                      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md border text-xs font-medium hover:bg-accent transition-colors"
                    >
                      <Download className="w-3 h-3" />
                      Download {typeLabel}
                    </a>
                  </div>
                );
              }

              // HTML preview: render in sandboxed iframe + download
              if (category === "html-preview" && selectedArtifact.content) {
                return (
                  <div className="flex flex-col gap-2 h-full" data-testid="html-file-preview">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground flex items-center gap-1">
                        <Globe className="w-3 h-3" /> HTML Preview
                      </span>
                      <a
                        href={`/api/artifacts/${selectedArtifact.id}/download`}
                        download={name}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded border text-[10px] font-medium hover:bg-accent transition-colors"
                      >
                        <Download className="w-3 h-3" />
                        Download
                      </a>
                    </div>
                    <iframe
                      srcDoc={selectedArtifact.content}
                      sandbox="allow-scripts allow-same-origin"
                      className="flex-1 w-full rounded-lg border bg-white"
                      title={name}
                      data-testid="html-preview-iframe"
                    />
                  </div>
                );
              }

              // Text preview: markdown, code, mermaid, JSON, plain text — with download
              if (selectedArtifact.content) {
                return (
                  <div className="flex flex-col gap-2 h-full" data-testid="text-file-preview">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-muted-foreground">{typeLabel}</span>
                      <a
                        href={`/api/artifacts/${selectedArtifact.id}/download`}
                        download={name}
                        className="inline-flex items-center gap-1 px-2 py-1 rounded border text-[10px] font-medium hover:bg-accent transition-colors"
                      >
                        <Download className="w-3 h-3" />
                        Download
                      </a>
                    </div>
                    <pre className="flex-1 text-xs whitespace-pre-wrap font-mono leading-relaxed overflow-auto" data-testid="text-file-content">
                      {selectedArtifact.content}
                    </pre>
                  </div>
                );
              }

              return (
                <div className="text-sm text-muted-foreground text-center py-8">
                  No content
                </div>
              );
            })()}
          </div>
        </div>
  ) : null;

  return (
    <div className="flex h-full" data-testid="page-workspace">
      {selectedArtifact ? (
        <SplitPane
          panes={[
            { defaultSize: 60, minSize: 30, maxSize: 80 },
            { defaultSize: 40, minSize: 20, maxSize: 60 },
          ]}
          storageKey="workspace"
        >
          {fileBrowserPanel}
          {previewPanel}
        </SplitPane>
      ) : (
        fileBrowserPanel
      )}

      <Dialog open={showNewFolderDialog} onOpenChange={setShowNewFolderDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create New Folder</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="Folder name"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              data-testid="input-folder-name"
            />
            <Input
              placeholder="Description (optional)"
              value={newFolderDesc}
              onChange={(e) => setNewFolderDesc(e.target.value)}
              data-testid="input-folder-desc"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewFolderDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreateFolder}
              disabled={!newFolderName.trim() || createFolderMutation.isPending}
              data-testid="button-create-folder"
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showNewFileDialog} onOpenChange={setShowNewFileDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Create New File</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="File name (e.g., README.md)"
              value={newFileName}
              onChange={(e) => setNewFileName(e.target.value)}
              data-testid="input-file-name"
            />
            <Select value={newFileType} onValueChange={setNewFileType}>
              <SelectTrigger data-testid="select-file-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="text/markdown">Markdown (.md)</SelectItem>
                <SelectItem value="text/plain">Plain Text (.txt)</SelectItem>
                <SelectItem value="application/json">JSON (.json)</SelectItem>
                <SelectItem value="text/javascript">JavaScript (.js)</SelectItem>
                <SelectItem value="text/typescript">TypeScript (.ts)</SelectItem>
                <SelectItem value="text/html">HTML (.html)</SelectItem>
                <SelectItem value="text/css">CSS (.css)</SelectItem>
              </SelectContent>
            </Select>
            <Textarea
              placeholder="File content..."
              value={newFileContent}
              onChange={(e) => setNewFileContent(e.target.value)}
              className="min-h-[200px] font-mono text-xs"
              data-testid="textarea-file-content"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewFileDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCreateFile}
              disabled={!newFileName.trim() || createFileMutation.isPending}
              data-testid="button-create-file"
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showEditDialog} onOpenChange={setShowEditDialog}>
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Edit className="w-4 h-4" />
              {editingArtifact?.name}
            </DialogTitle>
          </DialogHeader>
          <Textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            className="flex-1 min-h-[300px] font-mono text-xs"
            data-testid="textarea-edit-content"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEditDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSaveEdit}
              disabled={updateArtifactMutation.isPending}
              data-testid="button-save-file"
            >
              <Save className="w-4 h-4 mr-1" />
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showRenameFolderDialog} onOpenChange={setShowRenameFolderDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Folder</DialogTitle>
          </DialogHeader>
          <Input
            placeholder="New folder name"
            value={renameFolderName}
            onChange={(e) => setRenameFolderName(e.target.value)}
            data-testid="input-rename-folder"
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRenameFolderDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (renamingFolder && renameFolderName.trim()) {
                  renameFolderMutation.mutate({ id: renamingFolder.id, name: renameFolderName.trim() });
                }
              }}
              disabled={!renameFolderName.trim() || renameFolderMutation.isPending}
              data-testid="button-rename-folder"
            >
              Rename
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

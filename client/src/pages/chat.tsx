import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  DropdownMenuSub,
  DropdownMenuSubTrigger,
  DropdownMenuSubContent,
} from "@/components/ui/dropdown-menu";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Send,
  Bot,
  User,
  Loader2,
  Plus,
  MessageSquare,
  Trash2,
  GitBranch,
  FolderPlus,
  Folder,
  FolderOpen,
  ChevronRight,
  ChevronDown,
  MoreHorizontal,
  Archive,
  ArchiveRestore,
  Pencil,
  FolderInput,
} from "lucide-react";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { usePageTitle } from "@/hooks/use-page-title";
import { useToast } from "@/hooks/use-toast";
import type { ChatSession, ChatMessage, ChatGroup } from "@shared/schema";
import SplitPane from "@/components/split-pane";

type SessionWithMessages = ChatSession & { messages: ChatMessage[] };

export default function ChatPage() {
  usePageTitle("Chat with Aiden");
  const { toast } = useToast();
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [showGroupDialog, setShowGroupDialog] = useState(false);
  const [editingGroup, setEditingGroup] = useState<ChatGroup | null>(null);
  const [groupName, setGroupName] = useState("");
  const [groupParentId, setGroupParentId] = useState<string | null>(null);
  const [renamingSessionId, setRenamingSessionId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const [dragSessionId, setDragSessionId] = useState<string | null>(null);
  const [dropTargetGroupId, setDropTargetGroupId] = useState<string | null>(null);
  const [dropTargetUngrouped, setDropTargetUngrouped] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  const groupsQuery = useQuery<ChatGroup[]>({
    queryKey: ["/api/chat/groups"],
  });

  const sessionsQuery = useQuery<ChatSession[]>({
    queryKey: ["/api/chat/sessions", "all"],
    queryFn: async () => {
      const res = await fetch("/api/chat/sessions?includeArchived=true");
      if (!res.ok) throw new Error("Failed to fetch sessions");
      return res.json();
    },
  });

  const activeSessionQuery = useQuery<SessionWithMessages>({
    queryKey: ["/api/chat/sessions", activeSessionId],
    enabled: !!activeSessionId,
  });

  const messages = activeSessionQuery.data?.messages || [];

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const invalidateSessions = () => {
    queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions"] });
  };

  const deleteSessionMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiRequest("DELETE", `/api/chat/sessions/${id}`);
    },
    onSuccess: (_data, id) => {
      if (activeSessionId === id) setActiveSessionId(null);
      invalidateSessions();
    },
  });

  const updateSessionMutation = useMutation({
    mutationFn: async ({ id, ...updates }: { id: string; title?: string; groupId?: string | null; isArchived?: boolean }) => {
      await apiRequest("PUT", `/api/chat/sessions/${id}`, updates);
    },
    onSuccess: () => invalidateSessions(),
  });

  const createGroupMutation = useMutation({
    mutationFn: async (data: { name: string; parentId?: string | null }) => {
      await apiRequest("POST", "/api/chat/groups", data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/groups"] });
      setShowGroupDialog(false);
      setGroupName("");
      setGroupParentId(null);
      setEditingGroup(null);
    },
  });

  const updateGroupMutation = useMutation({
    mutationFn: async ({ id, ...updates }: { id: string; name?: string; parentId?: string | null; isCollapsed?: boolean }) => {
      await apiRequest("PUT", `/api/chat/groups/${id}`, updates);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["/api/chat/groups"] }),
  });

  const deleteGroupMutation = useMutation({
    mutationFn: async (id: string) => {
      await apiRequest("DELETE", `/api/chat/groups/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/groups"] });
      invalidateSessions();
    },
  });

  const chatMutation = useMutation({
    mutationFn: async (message: string) => {
      let sessionId = activeSessionId;
      if (!sessionId) {
        const res = await apiRequest("POST", "/api/chat/sessions", {});
        const newSession: ChatSession = await res.json();
        sessionId = newSession.id;
        setActiveSessionId(sessionId);
        invalidateSessions();
      }
      const res = await apiRequest("POST", `/api/chat/sessions/${sessionId}/messages`, { message });
      return res.json();
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions", activeSessionId || data.sessionId] });
      if (!activeSessionId && data.sessionId) setActiveSessionId(data.sessionId);
      invalidateSessions();
      if (data.actions && data.actions.length > 0) {
        queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
        queryClient.invalidateQueries({ queryKey: ["/api/work-orders?includeArchived=true"] });
        queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
        queryClient.invalidateQueries({ queryKey: ["/api/work-orders/recent"] });
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
          queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
          queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
          queryClient.invalidateQueries({ queryKey: ["/api/work-orders/recent"] });
        }, 15000);
        setTimeout(() => {
          queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
          queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
          queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
        }, 30000);
      }
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/chat/sessions", activeSessionId] });
    },
  });

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed || chatMutation.isPending) return;
    setInput("");
    chatMutation.mutate(trimmed);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleNewChat = () => setActiveSessionId(null);

  const toggleGroupCollapsed = (groupId: string) => {
    setCollapsedGroups(prev => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  const sessions = sessionsQuery.data || [];
  const groups = groupsQuery.data || [];
  const activeSession = activeSessionQuery.data;
  const rawGcc = activeSession?.gccMemory as Record<string, unknown> | null;
  const gccMemory = rawGcc ? (
    rawGcc["gcc.project_id"] ? rawGcc : {
      "gcc.project_id": rawGcc.correlationId ? `aiden-chat-${String(rawGcc.correlationId).slice(0, 8)}` : null,
      "gcc.branch": "main",
      "gcc.tier": "tier1",
      "gcc.last_commit_id": null,
      "gcc.context_commit_count": 0,
      "gcc.last_action": rawGcc.lastAction || rawGcc["lastAction"] || "none",
      ...rawGcc,
    }
  ) : null;

  const activeSessions = sessions.filter(s => !s.isArchived);
  const archivedSessions = sessions.filter(s => s.isArchived);
  const ungroupedSessions = activeSessions.filter(s => !s.groupId);
  const groupedSessions = (groupId: string) => activeSessions.filter(s => s.groupId === groupId);
  const rootGroups = groups.filter(g => !g.parentId);
  const childGroups = (parentId: string) => groups.filter(g => g.parentId === parentId);

  const renderSessionItem = (session: ChatSession) => {
    const isRenaming = renamingSessionId === session.id;

    if (isRenaming) {
      return (
        <div key={session.id} className="flex items-center gap-1 px-2 py-1">
          <Input
            value={renameValue}
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                updateSessionMutation.mutate({ id: session.id, title: renameValue });
                setRenamingSessionId(null);
              }
              if (e.key === "Escape") setRenamingSessionId(null);
            }}
            onBlur={() => {
              if (renameValue.trim()) {
                updateSessionMutation.mutate({ id: session.id, title: renameValue });
              }
              setRenamingSessionId(null);
            }}
            className="h-7 text-xs"
            autoFocus
            data-testid={`input-rename-session-${session.id}`}
          />
        </div>
      );
    }

    return (
      <div
        key={session.id}
        draggable={!session.isArchived}
        onDragStart={(e) => {
          setDragSessionId(session.id);
          e.dataTransfer.effectAllowed = "move";
          e.dataTransfer.setData("text/plain", session.id);
        }}
        onDragEnd={() => {
          setDragSessionId(null);
          setDropTargetGroupId(null);
          setDropTargetUngrouped(false);
        }}
        className={`group flex items-center gap-2 px-3 py-2 rounded-md cursor-pointer text-sm transition-colors ${
          activeSessionId === session.id
            ? "bg-accent text-accent-foreground"
            : "hover:bg-muted/60"
        } ${dragSessionId === session.id ? "opacity-50" : ""}`}
        onClick={() => setActiveSessionId(session.id)}
        data-testid={`session-item-${session.id}`}
      >
        <MessageSquare className="w-3.5 h-3.5 flex-shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate text-xs">
          {session.title || "New Conversation"}
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              size="icon"
              variant="ghost"
              className="h-5 w-5 flex-shrink-0 opacity-50 hover:opacity-100"
              onClick={(e) => e.stopPropagation()}
              data-testid={`button-session-menu-${session.id}`}
            >
              <MoreHorizontal className="w-3 h-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation();
                setRenamingSessionId(session.id);
                setRenameValue(session.title || "");
              }}
              data-testid={`menu-rename-${session.id}`}
            >
              <Pencil className="w-3.5 h-3.5 mr-2" />
              Rename
            </DropdownMenuItem>
            {!session.isArchived && groups.length > 0 && (
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <FolderInput className="w-3.5 h-3.5 mr-2" />
                  Move to Group
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  {session.groupId && (
                    <DropdownMenuItem
                      onClick={(e) => {
                        e.stopPropagation();
                        updateSessionMutation.mutate({ id: session.id, groupId: null });
                      }}
                      data-testid={`menu-ungroup-${session.id}`}
                    >
                      Remove from Group
                    </DropdownMenuItem>
                  )}
                  {session.groupId && groups.length > 0 && <DropdownMenuSeparator />}
                  {groups.map((g) => (
                    <DropdownMenuItem
                      key={g.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        updateSessionMutation.mutate({ id: session.id, groupId: g.id });
                      }}
                      data-testid={`menu-moveto-${g.id}-${session.id}`}
                    >
                      <Folder className="w-3.5 h-3.5 mr-2" />
                      {g.name}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            )}
            <DropdownMenuSeparator />
            {session.isArchived ? (
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation();
                  updateSessionMutation.mutate({ id: session.id, isArchived: false });
                  toast({ title: "Chat unarchived" });
                }}
                data-testid={`menu-unarchive-${session.id}`}
              >
                <ArchiveRestore className="w-3.5 h-3.5 mr-2" />
                Unarchive
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation();
                  updateSessionMutation.mutate({ id: session.id, isArchived: true });
                  if (activeSessionId === session.id) setActiveSessionId(null);
                  toast({ title: "Chat archived" });
                }}
                data-testid={`menu-archive-${session.id}`}
              >
                <Archive className="w-3.5 h-3.5 mr-2" />
                Archive
              </DropdownMenuItem>
            )}
            <DropdownMenuItem
              onClick={(e) => {
                e.stopPropagation();
                deleteSessionMutation.mutate(session.id);
              }}
              className="text-destructive focus:text-destructive"
              data-testid={`button-delete-session-${session.id}`}
            >
              <Trash2 className="w-3.5 h-3.5 mr-2" />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    );
  };

  const renderGroup = (group: ChatGroup, depth: number = 0) => {
    const isCollapsed = collapsedGroups.has(group.id);
    const children = childGroups(group.id);
    const groupSessions = groupedSessions(group.id);
    const hasContent = children.length > 0 || groupSessions.length > 0;

    return (
      <div key={group.id} style={{ paddingLeft: depth > 0 ? `${depth * 12}px` : undefined }}>
        <div
          className={`group flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer text-xs font-medium text-muted-foreground hover:bg-muted/40 transition-colors ${
            dropTargetGroupId === group.id ? "bg-primary/15 ring-1 ring-primary/40" : ""
          }`}
          onClick={() => toggleGroupCollapsed(group.id)}
          onDragOver={(e) => {
            if (!dragSessionId) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "move";
            setDropTargetGroupId(group.id);
            setDropTargetUngrouped(false);
          }}
          onDragEnter={() => {
            if (!dragSessionId) return;
            if (collapsedGroups.has(group.id)) {
              toggleGroupCollapsed(group.id);
            }
          }}
          onDragLeave={(e) => {
            if (dropTargetGroupId === group.id && !e.currentTarget.contains(e.relatedTarget as Node)) {
              setDropTargetGroupId(null);
            }
          }}
          onDrop={(e) => {
            e.preventDefault();
            if (dragSessionId) {
              updateSessionMutation.mutate({ id: dragSessionId, groupId: group.id });
              toast({ title: `Moved to ${group.name}` });
            }
            setDragSessionId(null);
            setDropTargetGroupId(null);
          }}
          data-testid={`group-${group.id}`}
        >
          {hasContent ? (
            isCollapsed ? (
              <ChevronRight className="w-3 h-3 flex-shrink-0" />
            ) : (
              <ChevronDown className="w-3 h-3 flex-shrink-0" />
            )
          ) : (
            <div className="w-3" />
          )}
          {isCollapsed ? (
            <Folder className="w-3.5 h-3.5 flex-shrink-0" style={group.color ? { color: group.color } : undefined} />
          ) : (
            <FolderOpen className="w-3.5 h-3.5 flex-shrink-0" style={group.color ? { color: group.color } : undefined} />
          )}
          <span className="flex-1 truncate">{group.name}</span>
          <span className="text-[10px] text-muted-foreground/50">{groupSessions.length}</span>
          {!hasContent && (
            <Button
              size="icon"
              variant="ghost"
              className="h-5 w-5 flex-shrink-0 opacity-50 hover:opacity-100 text-destructive"
              onClick={(e) => {
                e.stopPropagation();
                deleteGroupMutation.mutate(group.id);
              }}
              title="Delete empty folder"
              data-testid={`button-delete-empty-group-${group.id}`}
            >
              <Trash2 className="w-3 h-3" />
            </Button>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                variant="ghost"
                className="h-5 w-5 flex-shrink-0 opacity-50 hover:opacity-100"
                onClick={(e) => e.stopPropagation()}
                data-testid={`button-group-menu-${group.id}`}
              >
                <MoreHorizontal className="w-3 h-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-44">
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation();
                  setEditingGroup(group);
                  setGroupName(group.name);
                  setGroupParentId(group.parentId);
                  setShowGroupDialog(true);
                }}
                data-testid={`menu-edit-group-${group.id}`}
              >
                <Pencil className="w-3.5 h-3.5 mr-2" />
                Edit Group
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation();
                  setGroupParentId(group.id);
                  setGroupName("");
                  setEditingGroup(null);
                  setShowGroupDialog(true);
                }}
                data-testid={`menu-add-subgroup-${group.id}`}
              >
                <FolderPlus className="w-3.5 h-3.5 mr-2" />
                Add Sub-group
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={(e) => {
                  e.stopPropagation();
                  if (hasContent) {
                    toast({ title: "Cannot delete", description: "Move or remove all chats from this folder first." });
                    return;
                  }
                  deleteGroupMutation.mutate(group.id);
                }}
                className={hasContent ? "text-muted-foreground" : "text-destructive focus:text-destructive"}
                data-testid={`menu-delete-group-${group.id}`}
              >
                <Trash2 className="w-3.5 h-3.5 mr-2" />
                Delete Group
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {!isCollapsed && (
          <div className="ml-2">
            {children.map((child) => renderGroup(child, depth + 1))}
            {groupSessions.map(renderSessionItem)}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="flex h-full" data-testid="page-chat">
      <SplitPane
        panes={[
          { defaultSize: 25, minSize: 15, maxSize: 40 },
          { defaultSize: 75, minSize: 50, maxSize: 85 },
        ]}
        storageKey="chat"
      >
      <div className="flex flex-col bg-muted/30 h-full">
        <div className="p-3 border-b flex items-center justify-between gap-1">
          <span className="text-sm font-medium">History</span>
          <div className="flex items-center gap-0.5">
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={() => {
                setEditingGroup(null);
                setGroupName("");
                setGroupParentId(null);
                setShowGroupDialog(true);
              }}
              title="New Group"
              data-testid="button-new-group"
            >
              <FolderPlus className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              disabled={!activeSessionId}
              onClick={() => {
                if (!activeSessionId) return;
                const session = sessions.find(s => s.id === activeSessionId);
                if (!session) return;
                const archiving = !session.isArchived;
                updateSessionMutation.mutate({ id: activeSessionId, isArchived: archiving });
                if (archiving) setActiveSessionId(null);
                toast({ title: archiving ? "Chat archived" : "Chat unarchived" });
              }}
              title={activeSessionId ? (sessions.find(s => s.id === activeSessionId)?.isArchived ? "Unarchive current chat" : "Archive current chat") : "Select a chat to archive"}
              data-testid="button-archive-current"
            >
              <Archive className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={handleNewChat}
              title="New Chat"
              data-testid="button-new-chat"
            >
              <Plus className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-0.5">
            <div data-testid="archive-folder">
              <div
                className="flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer text-xs font-medium text-muted-foreground hover:bg-muted/40 transition-colors"
                onClick={() => setShowArchived(!showArchived)}
                onDragOver={(e) => {
                  if (!dragSessionId) return;
                  e.preventDefault();
                  e.dataTransfer.dropEffect = "move";
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  if (dragSessionId) {
                    updateSessionMutation.mutate({ id: dragSessionId, isArchived: true, groupId: null });
                    if (activeSessionId === dragSessionId) setActiveSessionId(null);
                    toast({ title: "Chat archived" });
                  }
                  setDragSessionId(null);
                }}
                data-testid="archive-folder-header"
              >
                {showArchived ? (
                  <ChevronDown className="w-3 h-3 flex-shrink-0" />
                ) : (
                  <ChevronRight className="w-3 h-3 flex-shrink-0" />
                )}
                <Archive className="w-3.5 h-3.5 flex-shrink-0 text-muted-foreground" />
                <span className="flex-1 truncate">Archive</span>
                <span className="text-[10px] text-muted-foreground/50">{archivedSessions.length}</span>
              </div>
              {showArchived && archivedSessions.length > 0 && (
                <div className="ml-2">
                  {archivedSessions.map(renderSessionItem)}
                </div>
              )}
            </div>
            <div className="border-t my-2" />
            {rootGroups.map((g) => renderGroup(g))}
            {rootGroups.length > 0 && ungroupedSessions.length > 0 && (
              <div className="border-t my-2" />
            )}
            <div
              className={`min-h-[8px] rounded-md transition-colors ${
                dropTargetUngrouped && dragSessionId ? "bg-primary/10 ring-1 ring-primary/30 min-h-[32px] flex items-center justify-center" : ""
              }`}
              onDragOver={(e) => {
                if (!dragSessionId) return;
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                setDropTargetUngrouped(true);
                setDropTargetGroupId(null);
              }}
              onDragLeave={(e) => {
                if (!e.currentTarget.contains(e.relatedTarget as Node)) {
                  setDropTargetUngrouped(false);
                }
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (dragSessionId) {
                  updateSessionMutation.mutate({ id: dragSessionId, groupId: null });
                  toast({ title: "Removed from group" });
                }
                setDragSessionId(null);
                setDropTargetUngrouped(false);
              }}
              data-testid="drop-zone-ungrouped"
            >
              {dropTargetUngrouped && dragSessionId && (
                <span className="text-[10px] text-primary/60">Drop here to ungroup</span>
              )}
            </div>
            {ungroupedSessions.map(renderSessionItem)}
            {sessions.length === 0 && !sessionsQuery.isLoading && (
              <p className="text-xs text-muted-foreground text-center py-4">
                No conversations yet
              </p>
            )}
          </div>
        </ScrollArea>
        {gccMemory && activeSessionId && (
          <div className="border-t p-3 space-y-2" data-testid="container-gcc-memory">
            <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
              <GitBranch className="w-3 h-3" />
              GCC Memory
            </div>
            <div className="text-xs text-muted-foreground space-y-1">
              <div className="truncate" title={String(gccMemory["gcc.project_id"] || "")} data-testid="text-gcc-project">
                Project: {String(gccMemory["gcc.project_id"] || "—")}
              </div>
              <div data-testid="text-gcc-branch">
                Branch: {String(gccMemory["gcc.branch"] || "main")}
              </div>
              <div data-testid="text-gcc-tier">
                Tier: {String(gccMemory["gcc.tier"] || "tier1")}
              </div>
              <div data-testid="text-gcc-last-commit">
                Last Commit: <span className="font-mono">{String(gccMemory["gcc.last_commit_id"] || "—")}</span>
              </div>
              <div data-testid="text-gcc-commit-count">
                Commits: {Number(gccMemory["gcc.context_commit_count"] || 0)}
              </div>
              <div data-testid="text-gcc-action">
                Action: {String(gccMemory["gcc.last_action"] || "none")}
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col min-w-0 h-full">
        <div className="flex items-center justify-between gap-4 p-4 pb-3 border-b flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary">
              <Bot className="w-4 h-4 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-lg font-semibold" data-testid="heading-chat">Chat with Aiden</h1>
              <p className="text-xs text-muted-foreground">
                {activeSession
                  ? activeSession.title
                  : "Start a new conversation"}
              </p>
            </div>
          </div>
          <Badge variant="outline" data-testid="badge-chat-status">
            {chatMutation.isPending ? "Thinking..." : "Online"}
          </Badge>
        </div>

        <div className="flex-1 overflow-auto p-6" data-testid="container-messages">
          {!activeSessionId || messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center gap-4">
              <div className="flex items-center justify-center w-16 h-16 rounded-full bg-muted">
                <Bot className="w-8 h-8 text-muted-foreground" />
              </div>
              <div>
                <h2 className="text-lg font-medium" data-testid="text-empty-state">Welcome! I'm Aiden.</h2>
                <p className="text-sm text-muted-foreground mt-1 max-w-md">
                  Your Tier 1 orchestration manager. Ask me about work order statuses, sub-agent assignments, workflow progress, or any operational question.
                </p>
              </div>
              <div className="flex flex-wrap gap-2 mt-4 justify-center">
                {[
                  "What's the current system status?",
                  "Show me pending work orders",
                  "Which sub-agents are active?",
                  "Summarize recent activity",
                ].map((suggestion) => (
                  <Button
                    key={suggestion}
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setInput(suggestion);
                      textareaRef.current?.focus();
                    }}
                    data-testid={`button-suggestion-${suggestion.slice(0, 10).replace(/\s/g, "-").toLowerCase()}`}
                  >
                    {suggestion}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-4 max-w-3xl mx-auto">
              {messages.map((msg, i) => (
                <div
                  key={msg.id}
                  className={`flex gap-3 ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  data-testid={`message-${msg.role}-${i}`}
                >
                  {msg.role === "assistant" && (
                    <div className="flex-shrink-0 flex items-start pt-1">
                      <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary">
                        <Bot className="w-4 h-4 text-primary-foreground" />
                      </div>
                    </div>
                  )}
                  <Card
                    className={`px-4 py-3 max-w-[80%] ${
                      msg.role === "user"
                        ? "bg-primary text-primary-foreground"
                        : ""
                    }`}
                  >
                    <div
                      className={`text-sm whitespace-pre-wrap break-words ${
                        msg.role === "user" ? "" : "prose prose-sm dark:prose-invert max-w-none"
                      }`}
                      data-testid={`text-message-content-${i}`}
                    >
                      {msg.content}
                    </div>
                    <div
                      className={`text-xs mt-2 ${
                        msg.role === "user" ? "text-primary-foreground/70" : "text-muted-foreground"
                      }`}
                    >
                      {new Date(msg.createdAt).toLocaleTimeString()}
                    </div>
                  </Card>
                  {msg.role === "user" && (
                    <div className="flex-shrink-0 flex items-start pt-1">
                      <div className="flex items-center justify-center w-8 h-8 rounded-md bg-muted">
                        <User className="w-4 h-4 text-muted-foreground" />
                      </div>
                    </div>
                  )}
                </div>
              ))}
              {chatMutation.isPending && (
                <div className="flex gap-3 justify-start" data-testid="message-loading">
                  <div className="flex-shrink-0 flex items-start pt-1">
                    <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary">
                      <Bot className="w-4 h-4 text-primary-foreground" />
                    </div>
                  </div>
                  <Card className="px-4 py-3">
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Aiden is thinking...
                    </div>
                  </Card>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className="border-t p-4" data-testid="container-input">
          <div className="flex gap-2 max-w-3xl mx-auto items-end">
            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask Aiden anything about your work orders and operations..."
              className="resize-none min-h-[44px] max-h-[120px] text-sm"
              rows={1}
              disabled={chatMutation.isPending}
              data-testid="input-chat-message"
            />
            <Button
              onClick={handleSend}
              disabled={!input.trim() || chatMutation.isPending}
              size="icon"
              data-testid="button-send-message"
            >
              <Send className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>
      </SplitPane>

      <Dialog open={showGroupDialog} onOpenChange={setShowGroupDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingGroup ? "Edit Group" : "New Group"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <label className="text-sm font-medium">Name</label>
              <Input
                value={groupName}
                onChange={(e) => setGroupName(e.target.value)}
                placeholder="e.g., Work Orders, Research, Ideas"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && groupName.trim()) {
                    if (editingGroup) {
                      updateGroupMutation.mutate({ id: editingGroup.id, name: groupName });
                      setShowGroupDialog(false);
                    } else {
                      createGroupMutation.mutate({ name: groupName, parentId: groupParentId });
                    }
                  }
                }}
                data-testid="input-group-name"
              />
            </div>
            {groups.length > 0 && (editingGroup || !groupParentId) && (
              <div>
                <label className="text-sm font-medium">Nest under (optional)</label>
                <select
                  className="w-full mt-1 rounded-md border bg-background px-3 py-2 text-sm"
                  value={groupParentId || ""}
                  onChange={(e) => setGroupParentId(e.target.value || null)}
                  data-testid="select-parent-group"
                >
                  <option value="">None (top-level)</option>
                  {groups
                    .filter(g => !editingGroup || g.id !== editingGroup.id)
                    .map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowGroupDialog(false)} data-testid="button-cancel-group">
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (editingGroup) {
                  updateGroupMutation.mutate({ id: editingGroup.id, name: groupName, parentId: groupParentId });
                  setShowGroupDialog(false);
                } else {
                  createGroupMutation.mutate({ name: groupName, parentId: groupParentId });
                }
              }}
              disabled={!groupName.trim()}
              data-testid="button-save-group"
            >
              {editingGroup ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

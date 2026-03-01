import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { queryClient, apiRequest } from "@/lib/queryClient";
import { usePageTitle } from "@/hooks/use-page-title";
import type { SandboxSession } from "@shared/schema";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  FlaskConical,
  Plus,
  Play,
  Trash2,
  Eye,
  X,
  Clock,
  CheckCircle,
  AlertCircle,
  Loader2,
  Terminal,
  RotateCcw,
  Globe,
  Code,
} from "lucide-react";
import SplitPane from "@/components/split-pane";
import { ExpandablePanel } from "@/components/expandable-panel";

function getStatusColor(status: string) {
  switch (status) {
    case "active":
      return "secondary";
    case "running":
      return "default";
    case "completed":
      return "default";
    case "failed":
      return "destructive";
    default:
      return "secondary";
  }
}

function getStatusIcon(status: string) {
  switch (status) {
    case "active":
      return Clock;
    case "running":
      return Loader2;
    case "completed":
      return CheckCircle;
    case "failed":
      return AlertCircle;
    default:
      return Clock;
  }
}

function formatDate(dateStr: string | Date | null) {
  if (!dateStr) return "--";
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function SandboxPage() {
  usePageTitle("Sandbox");
  const { toast } = useToast();
  const [showNewDialog, setShowNewDialog] = useState(false);
  const [selectedSession, setSelectedSession] = useState<SandboxSession | null>(null);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [execCommand, setExecCommand] = useState("");
  const [execInput, setExecInput] = useState("");
  const [viewMode, setViewMode] = useState<"terminal" | "preview">("preview");
  const [iframeKey, setIframeKey] = useState(0);

  const { data: sessions = [], isLoading } = useQuery<SandboxSession[]>({
    queryKey: ["/api/sandbox-sessions"],
    staleTime: 5000,
    refetchOnMount: "always",
  });

  const createMutation = useMutation({
    mutationFn: (data: { name: string; description?: string; createdBy?: string }) =>
      apiRequest("POST", "/api/sandbox-sessions", data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
      setShowNewDialog(false);
      setNewName("");
      setNewDesc("");
      toast({ title: "Sandbox session created" });
    },
  });

  const executeMutation = useMutation({
    mutationFn: ({ id, command, input }: { id: string; command: string; input: string }) =>
      apiRequest("POST", `/api/sandbox-sessions/${id}/execute`, { command, input }),
    onSuccess: async (res) => {
      queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
      const updated = await res.json();
      setSelectedSession(updated);
      toast({ title: "Execution completed" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest("DELETE", `/api/sandbox-sessions/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
      if (selectedSession) setSelectedSession(null);
      toast({ title: "Session deleted" });
    },
  });

  const rerenderMutation = useMutation({
    mutationFn: (id: string) => apiRequest("POST", `/api/sandbox-sessions/${id}/rerender`),
    onSuccess: async (_, id) => {
      queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
      const res = await fetch(`/api/sandbox-sessions/${id}`);
      const updated = await res.json();
      setSelectedSession(updated);
      setIframeKey(k => k + 1);
      toast({ title: "Preview re-rendered with updated engine" });
    },
    onError: (err: any) => {
      toast({ title: "Re-render failed", description: err.message, variant: "destructive" });
    },
  });

  const resetMutation = useMutation({
    mutationFn: (id: string) =>
      apiRequest("PUT", `/api/sandbox-sessions/${id}`, {
        status: "active",
        logs: [],
        result: null,
        completedAt: null,
      }),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
      if (selectedSession) {
        const res = await fetch(`/api/sandbox-sessions/${selectedSession.id}`);
        const updated = await res.json();
        setSelectedSession(updated);
      }
      toast({ title: "Session reset" });
    },
  });

  const sessionListPanel = (
      <div className="flex flex-col min-w-0 h-full">
        <div className="p-4 border-b sticky top-0 z-10 bg-background">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h1 className="text-lg font-semibold" data-testid="heading-sandbox">Sandbox</h1>
              <p className="text-sm text-muted-foreground">
                Isolated testing environment for experiments
              </p>
            </div>
            <Button onClick={() => setShowNewDialog(true)} data-testid="button-new-session">
              <Plus className="w-4 h-4 mr-1" />
              New Session
            </Button>
          </div>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {isLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Card key={i} className="p-4 animate-pulse">
                  <div className="h-4 bg-muted rounded w-1/3 mb-2" />
                  <div className="h-3 bg-muted rounded w-2/3" />
                </Card>
              ))}
            </div>
          ) : sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <FlaskConical className="w-16 h-16 text-muted-foreground mb-4" />
              <h3 className="text-lg font-medium mb-2">No Sandbox Sessions</h3>
              <p className="text-sm text-muted-foreground mb-6 max-w-md">
                Create sandbox sessions to test work order processing, try out configurations, or run experiments in isolation.
              </p>
              <Button onClick={() => setShowNewDialog(true)} data-testid="button-new-session-empty">
                <Plus className="w-4 h-4 mr-2" />
                Create First Session
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {sessions.map((session) => {
                const StatusIcon = getStatusIcon(session.status);
                const isSelected = selectedSession?.id === session.id;
                return (
                  <Card
                    key={session.id}
                    className={`hover-elevate cursor-pointer ${isSelected ? "ring-2 ring-primary" : ""}`}
                    onClick={() => {
                      setSelectedSession(session);
                      const result = session.result as any;
                      if (result?.html && result?.renderable) {
                        setViewMode("preview");
                      } else {
                        setViewMode("terminal");
                      }
                    }}
                    data-testid={`session-${session.id}`}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-center justify-between gap-4 flex-wrap">
                        <div className="flex items-center gap-3 min-w-0">
                          <FlaskConical className="w-5 h-5 text-muted-foreground shrink-0" />
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="text-sm font-medium" data-testid={`text-session-name-${session.id}`}>
                                {session.name}
                              </span>
                              <Badge variant={getStatusColor(session.status)} className="text-[10px]">
                                <StatusIcon className={`w-3 h-3 mr-1 ${session.status === "running" ? "animate-spin" : ""}`} />
                                {session.status}
                              </Badge>
                            </div>
                            {session.description && (
                              <p className="text-xs text-muted-foreground mt-0.5 truncate">
                                {session.description}
                              </p>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">
                            {formatDate(session.createdAt)}
                          </span>
                          <Button
                            size="icon"
                            variant="ghost"
                            onClick={(e) => {
                              e.stopPropagation();
                              deleteMutation.mutate(session.id);
                            }}
                            data-testid={`button-delete-session-${session.id}`}
                          >
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
  );

  const sessionResult = selectedSession?.result as any;
  const isRenderable = !!(sessionResult?.html && sessionResult?.renderable);

  const activeViewMode = isRenderable ? viewMode : "terminal";

  const detailPanel = selectedSession ? (
        <div className="flex flex-col bg-background h-full" data-testid="panel-session-detail">
          <div className="p-3 border-b flex items-center justify-between gap-2">
            <div className="flex items-center gap-2 min-w-0">
              <FlaskConical className="w-4 h-4 text-muted-foreground shrink-0" />
              <span className="text-sm font-medium truncate">{selectedSession.name}</span>
              <Badge variant={getStatusColor(selectedSession.status)} className="text-[10px]">
                {selectedSession.status}
              </Badge>
              {isRenderable && (
                <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-600 border-green-500/30">
                  <Globe className="w-3 h-3 mr-0.5" />
                  Preview
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-1">
              {isRenderable && (
                <>
                  <Button
                    size="icon"
                    variant={activeViewMode === "preview" ? "default" : "ghost"}
                    onClick={() => setViewMode("preview")}
                    title="Live Preview"
                    data-testid="button-view-preview"
                  >
                    <Globe className="w-4 h-4" />
                  </Button>
                  <Button
                    size="icon"
                    variant={activeViewMode === "terminal" ? "default" : "ghost"}
                    onClick={() => setViewMode("terminal")}
                    title="Terminal / Logs"
                    data-testid="button-view-terminal"
                  >
                    <Terminal className="w-4 h-4" />
                  </Button>
                </>
              )}
              <Button
                size="icon"
                variant="ghost"
                onClick={() => setSelectedSession(null)}
                data-testid="button-close-session"
              >
                <X className="w-4 h-4" />
              </Button>
            </div>
          </div>

          {activeViewMode === "preview" && isRenderable ? (
            <div className="flex-1 flex flex-col min-h-0">
              <div className="px-3 py-2 border-b flex items-center justify-between bg-muted/30">
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Globe className="w-3 h-3" />
                  <span className="font-medium">{sessionResult.title || "HTML Preview"}</span>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setIframeKey(k => k + 1)}
                    title="Run / Reload preview"
                    data-testid="button-run-preview"
                    className="text-green-600 hover:text-green-700 hover:bg-green-500/10"
                  >
                    <Play className="w-3.5 h-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => rerenderMutation.mutate(selectedSession.id)}
                    disabled={rerenderMutation.isPending}
                    title="Re-render preview with updated engine"
                    data-testid="button-rerender-preview"
                  >
                    {rerenderMutation.isPending ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <RotateCcw className="w-3.5 h-3.5" />
                    )}
                  </Button>
                  <ExpandablePanel
                    title={`Preview: ${sessionResult.title || selectedSession.name}`}
                  >
                    <iframe
                      key={`expanded-${iframeKey}`}
                      src={`/api/sandbox-sessions/${selectedSession.id}/preview`}
                      className="w-full h-full border-0"
                      title={`Preview: ${selectedSession.name}`}
                      sandbox="allow-scripts allow-same-origin"
                      data-testid="iframe-preview-expanded"
                    />
                  </ExpandablePanel>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      window.open(`/api/sandbox-sessions/${selectedSession.id}/preview`, '_blank');
                    }}
                    title="Open in new tab"
                    data-testid="button-open-preview-tab"
                  >
                    <Eye className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
              <div className="flex-1 min-h-0 bg-white">
                <iframe
                  key={`preview-${iframeKey}`}
                  src={`/api/sandbox-sessions/${selectedSession.id}/preview`}
                  className="w-full h-full border-0"
                  title={`Preview: ${selectedSession.name}`}
                  sandbox="allow-scripts allow-same-origin"
                  data-testid="iframe-preview"
                />
              </div>
            </div>
          ) : (
            <>
              <div className="p-3 border-b">
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-muted-foreground">Created</span>
                    <div>{formatDate(selectedSession.createdAt)}</div>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Completed</span>
                    <div>{formatDate(selectedSession.completedAt)}</div>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Created By</span>
                    <div>{selectedSession.createdBy || "system"}</div>
                  </div>
                  <div>
                    <span className="text-muted-foreground">Executions</span>
                    <div>{Array.isArray(selectedSession.logs) ? (selectedSession.logs as any[]).length : 0}</div>
                  </div>
                </div>
              </div>

              <div className="p-3 border-b space-y-2">
                <h4 className="text-xs font-medium flex items-center gap-1">
                  <Terminal className="w-3 h-3" />
                  Execute Command
                </h4>
                <Input
                  placeholder="Command (e.g., test-workflow, validate-config)"
                  value={execCommand}
                  onChange={(e) => setExecCommand(e.target.value)}
                  data-testid="input-exec-command"
                />
                <Textarea
                  placeholder="Input data (optional JSON or text)..."
                  value={execInput}
                  onChange={(e) => setExecInput(e.target.value)}
                  className="min-h-[60px] font-mono text-xs"
                  data-testid="textarea-exec-input"
                />
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() =>
                      executeMutation.mutate({
                        id: selectedSession.id,
                        command: execCommand || "execute",
                        input: execInput,
                      })
                    }
                    disabled={executeMutation.isPending}
                    data-testid="button-execute"
                  >
                    {executeMutation.isPending ? (
                      <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4 mr-1" />
                    )}
                    Run
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => resetMutation.mutate(selectedSession.id)}
                    disabled={resetMutation.isPending}
                    data-testid="button-reset-session"
                  >
                    <RotateCcw className="w-4 h-4 mr-1" />
                    Reset
                  </Button>
                </div>
              </div>

              <div className="flex-1 overflow-auto p-3">
                <h4 className="text-xs font-medium mb-2">Execution Log</h4>
                {Array.isArray(selectedSession.logs) && (selectedSession.logs as any[]).length > 0 ? (
                  <div className="space-y-2">
                    {(selectedSession.logs as any[]).map((log: any, i: number) => (
                      <Card key={i} className="p-2">
                        <div className="text-[10px] text-muted-foreground mb-1">
                          {log.timestamp ? formatDate(log.timestamp) : `Run #${i + 1}`}
                        </div>
                        <div className="text-xs font-medium mb-1">
                          {log.command || "execute"}
                        </div>
                        {log.output && (
                          <pre className="text-[10px] font-mono text-muted-foreground whitespace-pre-wrap bg-muted/50 rounded p-1.5">
                            {typeof log.output === "string" ? log.output : JSON.stringify(log.output, null, 2)}
                          </pre>
                        )}
                      </Card>
                    ))}
                  </div>
                ) : (
                  <div className="text-xs text-muted-foreground text-center py-6">
                    No executions yet. Run a command above to test.
                  </div>
                )}

                {selectedSession.result ? (
                  <div className="mt-3">
                    <h4 className="text-xs font-medium mb-2">Latest Result</h4>
                    <Card className="p-2">
                      <pre className="text-[10px] font-mono whitespace-pre-wrap" data-testid="text-session-result">
                        {JSON.stringify(selectedSession.result, null, 2)}
                      </pre>
                    </Card>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
  ) : null;

  return (
    <div className="flex h-full" data-testid="page-sandbox">
      {selectedSession ? (
        <SplitPane
          panes={[
            { defaultSize: 55, minSize: 30, maxSize: 75 },
            { defaultSize: 45, minSize: 25, maxSize: 60 },
          ]}
          storageKey="sandbox"
        >
          {sessionListPanel}
          {detailPanel}
        </SplitPane>
      ) : (
        sessionListPanel
      )}

      <Dialog open={showNewDialog} onOpenChange={setShowNewDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Sandbox Session</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <Input
              placeholder="Session name"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              data-testid="input-session-name"
            />
            <Textarea
              placeholder="Description (what are you testing?)"
              value={newDesc}
              onChange={(e) => setNewDesc(e.target.value)}
              className="min-h-[80px]"
              data-testid="textarea-session-desc"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowNewDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (newName.trim()) {
                  createMutation.mutate({
                    name: newName.trim(),
                    description: newDesc.trim() || undefined,
                    createdBy: "admin",
                  });
                }
              }}
              disabled={!newName.trim() || createMutation.isPending}
              data-testid="button-create-session"
            >
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

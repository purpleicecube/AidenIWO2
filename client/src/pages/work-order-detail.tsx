import { useQuery, useMutation } from "@tanstack/react-query";
import { useParams, Link } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge, PriorityBadge } from "@/components/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  ArrowLeft,
  Play,
  RotateCcw,
  Clock,
  Layers,
  Activity,
  AlertTriangle,
  Copy,
  CheckCircle,
  Loader2,
  Brain,
  Bot,
  UserCheck,
  GitBranch,
  ShieldCheck,
  RefreshCw,
  XCircle,
  CircleAlert,
  Pencil,
  Save,
  X,
} from "lucide-react";
import type { WorkOrder, ExecutionLog, WorkflowExecution, WorkflowStepRun } from "@shared/schema";
import { useState } from "react";

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4">
        <Skeleton className="h-8 w-8" />
        <Skeleton className="h-8 w-64" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardContent className="p-6 space-y-4">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </CardContent>
          </Card>
        </div>
        <div>
          <Card>
            <CardContent className="p-6 space-y-3">
              {[1, 2, 3, 4].map((i) => (
                <div key={i}>
                  <Skeleton className="h-3 w-16 mb-1" />
                  <Skeleton className="h-5 w-24" />
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function TimelineItem({
  log,
  isLast,
}: {
  log: ExecutionLog;
  isLast: boolean;
}) {
  const meta = log.metadata as Record<string, any> | null;
  const llmSource = meta?.llmSource || meta?.executedBy;
  const isSubAgentOwn = log.tier === 2 && llmSource === "sub-agent";
  const TierIcon = log.tier === 1 ? Brain : Bot;
  const tierColor = log.tier === 1
    ? "bg-primary/10 text-primary dark:bg-primary/20"
    : isSubAgentOwn
      ? "bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
      : "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400";
  const tierLabel = log.tier === 1
    ? "Aiden (Tier 1)"
    : isSubAgentOwn
      ? `${meta?.subAgentName || "Sub-Agent"} (own LLM)`
      : meta?.subAgentName
        ? `${meta.subAgentName} (via Aiden)`
        : "Sub-Agent (Tier 2)";

  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <div className={`flex items-center justify-center w-8 h-8 rounded-full ${tierColor}`}>
          <TierIcon className="w-3.5 h-3.5" />
        </div>
        {!isLast && <div className="w-px flex-1 bg-border mt-2" />}
      </div>
      <div className={`flex-1 pb-6 ${isLast ? "" : ""}`}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm font-medium">{log.action}</span>
          <Badge
            variant="outline"
            className={`text-xs no-default-hover-elevate no-default-active-elevate ${isSubAgentOwn ? "border-blue-300 dark:border-blue-700 text-blue-600 dark:text-blue-400" : ""}`}
          >
            {tierLabel}
          </Badge>
          {isSubAgentOwn && meta?.llmModel && (
            <Badge variant="secondary" className="text-xs no-default-hover-elevate no-default-active-elevate">
              {meta.llmProvider}/{meta.llmModel}
            </Badge>
          )}
        </div>
        <p className="text-sm text-muted-foreground mt-1">{log.message}</p>
        <p className="text-xs text-muted-foreground mt-1.5">
          {new Date(log.createdAt).toLocaleString()}
        </p>
        {log.metadata && (
          <pre className="mt-2 p-3 rounded-md bg-muted/50 text-xs font-mono overflow-x-auto">
            {JSON.stringify(log.metadata, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}

function BlockedSummary({ order }: { order: WorkOrder }) {
  const bdm = order.bdmMarker as Record<string, any> | null;
  const tier2 = order.tier2Result as Record<string, any> | null;

  const reason = bdm?.reason || tier2?.reason || "Unknown reason";
  const tier = bdm?.tier ?? (tier2 ? 2 : null);
  const type = bdm?.type || "execution_block";

  const hasOutput = tier2 && !tier2.blocked && tier2.output;

  return (
    <div className="rounded-md border border-red-200 dark:border-red-800/40 overflow-hidden" data-testid="blocked-summary">
      <div className="flex items-start gap-3 p-4 bg-red-50 dark:bg-red-900/10">
        <CircleAlert className="w-5 h-5 text-red-600 dark:text-red-400 mt-0.5 flex-shrink-0" />
        <div className="space-y-1 min-w-0">
          <p className="text-sm font-medium text-red-700 dark:text-red-400">
            This work order is blocked
          </p>
          <p className="text-sm text-red-600 dark:text-red-300">
            {reason}
          </p>
        </div>
      </div>
      <div className="px-4 py-3 bg-red-50/50 dark:bg-red-900/5 space-y-2">
        <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
          {tier != null && (
            <span>Blocked at: <span className="font-medium text-foreground">Tier {tier}</span></span>
          )}
          <span>Type: <span className="font-medium text-foreground capitalize">{String(type).replace(/_/g, " ")}</span></span>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
          <span>Output produced: <span className="font-medium text-foreground">{hasOutput ? "Yes" : "No"}</span></span>
        </div>
      </div>
      <div className="px-4 py-3 border-t border-red-100 dark:border-red-800/20 bg-muted/30">
        <p className="text-xs text-muted-foreground">
          {hasOutput
            ? "Some output was produced before the block. You can re-issue to Aiden to attempt completion, or close the order."
            : "No output was produced. Use \"Re-issue to Aiden\" to try again, or \"Close Without Output\" if no longer needed."}
        </p>
      </div>
    </div>
  );
}

export default function WorkOrderDetail() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  const { data: order, isLoading: orderLoading } = useQuery<WorkOrder>({
    queryKey: ["/api/work-orders", params.id],
  });

  const { data: logs, isLoading: logsLoading } = useQuery<ExecutionLog[]>({
    queryKey: ["/api/work-orders", params.id, "logs"],
  });

  usePageTitle(order?.title || "Work Order");

  const processMutation = useMutation({
    mutationFn: () => apiRequest("POST", `/api/work-orders/${params.id}/process`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id, "logs"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/recent"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
      toast({ title: "Processing started", description: "Work order is being processed through the orchestration pipeline." });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to process work order.", variant: "destructive" });
    },
  });

  const retryMutation = useMutation({
    mutationFn: () => apiRequest("POST", `/api/work-orders/${params.id}/retry`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id, "logs"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/recent"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
      toast({ title: "Retry initiated", description: "Work order has been reset and resubmitted for processing." });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to retry work order.", variant: "destructive" });
    },
  });

  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [editType, setEditType] = useState("");
  const [editPriority, setEditPriority] = useState("");

  const startEditing = () => {
    if (!order) return;
    setEditTitle(order.title);
    setEditDescription(order.description);
    setEditType(order.type);
    setEditPriority(order.priority);
    setEditing(true);
  };

  const cancelEditing = () => {
    setEditing(false);
  };

  const saveMutation = useMutation({
    mutationFn: () =>
      apiRequest("PUT", `/api/work-orders/${params.id}`, {
        title: editTitle,
        description: editDescription,
        type: editType,
        priority: editPriority,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
      setEditing(false);
      toast({ title: "Saved", description: "Work order updated." });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to save changes.", variant: "destructive" });
    },
  });

  const [closeDialogOpen, setCloseDialogOpen] = useState(false);
  const [closeReason, setCloseReason] = useState("");
  const [reopenDialogOpen, setReopenDialogOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState("");

  const reopenMutation = useMutation({
    mutationFn: (reason: string) =>
      apiRequest("POST", `/api/work-orders/${params.id}/reopen`, { reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id, "logs"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/recent"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
      setReopenDialogOpen(false);
      setReopenReason("");
      toast({ title: "Work order reopened", description: "The work order has been reopened and is ready for editing or reprocessing." });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to reopen work order.", variant: "destructive" });
    },
  });

  const invalidateOrderQueries = () => {
    queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id] });
    queryClient.invalidateQueries({ queryKey: ["/api/work-orders", params.id, "logs"] });
    queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
    queryClient.invalidateQueries({ queryKey: ["/api/work-orders/recent"] });
    queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
  };

  const reissueMutation = useMutation({
    mutationFn: () =>
      apiRequest("POST", `/api/work-orders/${params.id}/unblock`, {
        resolution: "Re-issued to Aiden for re-processing.",
        reprocess: true,
      }),
    onSuccess: () => {
      invalidateOrderQueries();
      toast({
        title: "Re-issued to Aiden",
        description: "Work order has been cleared and re-submitted for processing.",
      });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to re-issue work order.", variant: "destructive" });
    },
  });

  const closeMutation = useMutation({
    mutationFn: () =>
      apiRequest("POST", `/api/work-orders/${params.id}/unblock`, {
        resolution: closeReason,
        reprocess: false,
      }),
    onSuccess: () => {
      invalidateOrderQueries();
      setCloseDialogOpen(false);
      setCloseReason("");
      toast({
        title: "Work order closed",
        description: "Marked as complete without re-processing.",
      });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to close work order.", variant: "destructive" });
    },
  });

  const copyCorrelationId = () => {
    if (order) {
      navigator.clipboard.writeText(order.correlationId);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (orderLoading) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <DetailSkeleton />
      </div>
    );
  }

  if (!order) {
    return (
      <div className="p-6 max-w-7xl mx-auto">
        <div className="flex flex-col items-center justify-center py-20">
          <AlertTriangle className="w-12 h-12 text-muted-foreground/40 mb-4" />
          <p className="text-lg font-medium">Work order not found</p>
          <Link href="/work-orders">
            <Button variant="ghost" className="mt-4" data-testid="button-back-to-list">
              <ArrowLeft className="w-4 h-4 mr-2" />
              Back to Work Orders
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <Link href="/work-orders">
            <Button variant="ghost" size="icon" data-testid="button-back">
              <ArrowLeft className="w-4 h-4" />
            </Button>
          </Link>
          <div className="min-w-0 flex-1">
            {editing ? (
              <Input
                value={editTitle}
                onChange={(e) => setEditTitle(e.target.value)}
                className="text-xl font-semibold"
                data-testid="input-edit-title"
              />
            ) : (
              <h1 className="text-xl font-semibold tracking-tight" data-testid="text-order-title">
                {order.title}
              </h1>
            )}
            <div className="flex items-center gap-2 mt-1">
              <button
                onClick={copyCorrelationId}
                className="flex items-center gap-1 text-xs text-muted-foreground font-mono cursor-pointer"
                data-testid="button-copy-correlation"
              >
                {copied ? <CheckCircle className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
                {order.correlationId.slice(0, 12)}...
              </button>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {editing ? (
            <>
              <Button
                onClick={() => saveMutation.mutate()}
                disabled={saveMutation.isPending || editTitle.trim().length === 0}
                data-testid="button-save-edit"
              >
                {saveMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Save className="w-4 h-4 mr-2" />
                )}
                {saveMutation.isPending ? "Saving..." : "Save Changes"}
              </Button>
              <Button variant="outline" onClick={cancelEditing} data-testid="button-cancel-edit">
                <X className="w-4 h-4 mr-2" />
                Cancel
              </Button>
            </>
          ) : (
            <>
              {order.status !== "completed" && order.status !== "processing" && (
                <Button variant="outline" onClick={startEditing} data-testid="button-edit">
                  <Pencil className="w-4 h-4 mr-2" />
                  Edit
                </Button>
              )}
              {order.status === "completed" && (
                <Button
                  variant="outline"
                  className="border-purple-300 text-purple-700 hover:bg-purple-50 dark:border-purple-700 dark:text-purple-400 dark:hover:bg-purple-900/20"
                  onClick={() => {
                    setReopenReason("");
                    setReopenDialogOpen(true);
                  }}
                  data-testid="button-reopen"
                >
                  <RotateCcw className="w-4 h-4 mr-2" />
                  Reopen
                </Button>
              )}
              {(order.status === "pending" || order.status === "reopened") && (
                <Button
                  onClick={() => processMutation.mutate()}
                  disabled={processMutation.isPending}
                  data-testid="button-process"
                >
                  {processMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Play className="w-4 h-4 mr-2" />
                  )}
                  {processMutation.isPending ? "Processing..." : "Process"}
                </Button>
              )}
              {order.status === "blocked" && order.bdmMarker && (
                <>
                  <Button
                    onClick={() => reissueMutation.mutate()}
                    disabled={reissueMutation.isPending}
                    data-testid="button-reissue"
                  >
                    {reissueMutation.isPending ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <RefreshCw className="w-4 h-4 mr-2" />
                    )}
                    {reissueMutation.isPending ? "Re-issuing..." : "Re-issue to Aiden"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setCloseReason("");
                      setCloseDialogOpen(true);
                    }}
                    data-testid="button-close-order"
                  >
                    <XCircle className="w-4 h-4 mr-2" />
                    Close Without Output
                  </Button>
                </>
              )}
              {order.status === "failed" && (
                <Button
                  onClick={() => retryMutation.mutate()}
                  disabled={retryMutation.isPending}
                  data-testid="button-retry"
                >
                  {retryMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <RotateCcw className="w-4 h-4 mr-2" />
                  )}
                  {retryMutation.isPending ? "Retrying..." : "Retry"}
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      <Dialog open={closeDialogOpen} onOpenChange={setCloseDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <XCircle className="w-5 h-5" />
              Close Without Output
            </DialogTitle>
            <DialogDescription>
              This will mark the work order as complete without producing any output. Please explain why you are closing it instead of re-issuing.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="close-reason">Why are you closing this?</Label>
            <Textarea
              id="close-reason"
              value={closeReason}
              onChange={(e) => setCloseReason(e.target.value)}
              placeholder="e.g., No longer needed, handled externally, duplicate of another order..."
              className="min-h-[100px]"
              data-testid="input-close-reason"
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setCloseDialogOpen(false)} data-testid="button-cancel-close">
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => closeMutation.mutate()}
              disabled={closeMutation.isPending || closeReason.trim().length === 0}
              data-testid="button-confirm-close"
            >
              {closeMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4 mr-2" />
              )}
              {closeMutation.isPending ? "Closing..." : "Close Order"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={reopenDialogOpen} onOpenChange={setReopenDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <RotateCcw className="w-5 h-5 text-purple-600" />
              Reopen Work Order
            </DialogTitle>
            <DialogDescription>
              This will reopen the completed work order for reprocessing. The previous deliverable will be preserved in the execution history. You can edit the work order before processing it again.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="reopen-reason">Why does this need to be reopened?</Label>
            <Textarea
              id="reopen-reason"
              value={reopenReason}
              onChange={(e) => setReopenReason(e.target.value)}
              placeholder="e.g., New requirements received, needs revision based on feedback, additional information available..."
              className="min-h-[100px]"
              data-testid="input-reopen-reason"
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setReopenDialogOpen(false)} data-testid="button-cancel-reopen">
              Cancel
            </Button>
            <Button
              className="bg-purple-600 hover:bg-purple-700 text-white"
              onClick={() => reopenMutation.mutate(reopenReason)}
              disabled={reopenMutation.isPending || reopenReason.trim().length === 0}
              data-testid="button-confirm-reopen"
            >
              {reopenMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <RotateCcw className="w-4 h-4 mr-2" />
              )}
              {reopenMutation.isPending ? "Reopening..." : "Reopen Work Order"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Description</p>
                {editing ? (
                  <Textarea
                    value={editDescription}
                    onChange={(e) => setEditDescription(e.target.value)}
                    className="min-h-[120px] text-sm"
                    data-testid="input-edit-description"
                  />
                ) : (
                  <p className="text-sm whitespace-pre-wrap" data-testid="text-order-description">{order.description}</p>
                )}
              </div>

              {order.status === "blocked" && order.bdmMarker && (
                <BlockedSummary order={order} />
              )}

              {order.status !== "blocked" && order.bdmMarker && (
                <div className="p-3 rounded-md bg-amber-50 border border-amber-200 dark:bg-amber-900/10 dark:border-amber-800/30">
                  <div className="flex items-center gap-2 mb-1">
                    <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400" />
                    <p className="text-sm font-medium text-amber-700 dark:text-amber-400">BDM Marker</p>
                  </div>
                  <pre className="text-xs font-mono text-amber-800 dark:text-amber-300 mt-1 overflow-x-auto">
                    {JSON.stringify(order.bdmMarker, null, 2)}
                  </pre>
                </div>
              )}

              {order.gccMemory && Object.keys(order.gccMemory as object).length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-2">GCC Memory</p>
                  <pre className="p-3 rounded-md bg-muted/50 text-xs font-mono overflow-x-auto">
                    {JSON.stringify(order.gccMemory, null, 2)}
                  </pre>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Execution Timeline</CardTitle>
            </CardHeader>
            <CardContent>
              {logsLoading ? (
                <div className="space-y-4">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="flex gap-3">
                      <Skeleton className="h-8 w-8 rounded-full flex-shrink-0" />
                      <div className="flex-1 space-y-2">
                        <Skeleton className="h-4 w-40" />
                        <Skeleton className="h-3 w-full" />
                        <Skeleton className="h-3 w-24" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : logs && logs.length > 0 ? (
                <div>
                  {logs.map((log, index) => (
                    <TimelineItem
                      key={log.id}
                      log={log}
                      isLast={index === logs.length - 1}
                    />
                  ))}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-8 text-center">
                  <Clock className="w-8 h-8 text-muted-foreground/30 mb-2" />
                  <p className="text-sm text-muted-foreground">No execution logs yet</p>
                  <p className="text-xs text-muted-foreground mt-1">
                    Process this work order to see the execution timeline
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Properties</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Status</p>
                <StatusBadge status={order.status} />
              </div>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-1">Priority</p>
                {editing ? (
                  <Select value={editPriority} onValueChange={setEditPriority}>
                    <SelectTrigger data-testid="select-edit-priority">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="low">Low</SelectItem>
                      <SelectItem value="medium">Medium</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="critical">Critical</SelectItem>
                    </SelectContent>
                  </Select>
                ) : (
                  <PriorityBadge priority={order.priority} />
                )}
              </div>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-1">Type</p>
                {editing ? (
                  <Select value={editType} onValueChange={setEditType}>
                    <SelectTrigger data-testid="select-edit-type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="standard">Standard</SelectItem>
                      <SelectItem value="urgent">Urgent</SelectItem>
                      <SelectItem value="maintenance">Maintenance</SelectItem>
                      <SelectItem value="investigation">Investigation</SelectItem>
                    </SelectContent>
                  </Select>
                ) : (
                  <p className="text-sm capitalize" data-testid="text-order-type">{order.type}</p>
                )}
              </div>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-1">Submitted By</p>
                <p className="text-sm" data-testid="text-order-submitter">{order.submittedBy || "system"}</p>
              </div>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-1">Created</p>
                <p className="text-sm">{new Date(order.createdAt).toLocaleString()}</p>
              </div>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-1">Updated</p>
                <p className="text-sm">{new Date(order.updatedAt).toLocaleString()}</p>
              </div>
              {order.assignedSubAgentId && (
                <>
                  <Separator />
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Assigned Sub-Agent</p>
                    <div className="flex items-center gap-1.5">
                      <Bot className="w-3.5 h-3.5 text-muted-foreground" />
                      <p className="text-sm" data-testid="text-assigned-agent">{order.assignedSubAgentId}</p>
                    </div>
                  </div>
                </>
              )}
              {order.executionMode && (
                <>
                  <Separator />
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Execution Mode</p>
                    <div className="flex items-center gap-1.5">
                      {order.executionMode === "aiden" ? (
                        <>
                          <Brain className="w-3.5 h-3.5 text-primary" />
                          <p className="text-sm text-primary font-medium">Aiden-controlled</p>
                        </>
                      ) : (
                        <>
                          <UserCheck className="w-3.5 h-3.5 text-violet-600 dark:text-violet-400" />
                          <p className="text-sm text-violet-600 dark:text-violet-400 font-medium">Independent</p>
                        </>
                      )}
                    </div>
                  </div>
                </>
              )}
            </CardContent>
          </Card>

          {order.workflowExecutionId && (
            <WorkflowExecutionPanel executionId={order.workflowExecutionId} />
          )}

          {(order.tier1Result || order.tier2Result) && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base font-medium">Results</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {order.tier1Result && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Aiden (Tier 1) Decision</p>
                    <pre className="p-2 rounded-md bg-muted/50 text-xs font-mono overflow-x-auto">
                      {JSON.stringify(order.tier1Result, null, 2)}
                    </pre>
                  </div>
                )}
                {order.tier2Result && (
                  <div>
                    <p className="text-xs text-muted-foreground mb-1">Sub-Agent (Tier 2) Result</p>
                    <pre className="p-2 rounded-md bg-muted/50 text-xs font-mono overflow-x-auto">
                      {JSON.stringify(order.tier2Result, null, 2)}
                    </pre>
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function WorkflowExecutionPanel({ executionId }: { executionId: string }) {
  const { data: execution } = useQuery<WorkflowExecution & { stepRuns: WorkflowStepRun[] }>({
    queryKey: ["/api/workflow-executions", executionId],
  });

  if (!execution) return null;

  const stepStatusColor: Record<string, string> = {
    completed: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
    running: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400",
    pending: "bg-muted text-muted-foreground",
    failed: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
    skipped: "bg-muted text-muted-foreground",
    awaiting_operator: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400",
  };

  const completedSteps = execution.stepRuns?.filter(s => s.status === "completed").length ?? 0;
  const totalSteps = execution.stepRuns?.length ?? 0;

  return (
    <Card data-testid="card-workflow-execution">
      <CardHeader className="flex flex-row items-center justify-between gap-4 pb-3">
        <div className="flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          <CardTitle className="text-base font-medium">Workflow Execution</CardTitle>
        </div>
        <Badge variant="outline" className="no-default-hover-elevate no-default-active-elevate">
          {completedSteps}/{totalSteps} steps
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <p className="text-xs text-muted-foreground">Goal</p>
            <p className="text-sm">{execution.goal || "N/A"}</p>
          </div>
          <Badge variant="outline" className="no-default-hover-elevate no-default-active-elevate">
            {execution.status}
          </Badge>
        </div>
        {execution.stepRuns && execution.stepRuns.length > 0 && (
          <div className="space-y-1.5 pt-2 border-t">
            <p className="text-xs text-muted-foreground mb-2">Steps</p>
            {execution.stepRuns.map((step) => (
              <div key={step.id} className="flex items-center justify-between gap-3 p-2 rounded-md bg-muted/30" data-testid={`step-run-${step.stepKey}`}>
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">{step.stepName}</p>
                  <p className="text-xs text-muted-foreground font-mono">{step.stepKey}</p>
                </div>
                <Badge variant="outline" className={`text-xs no-default-hover-elevate no-default-active-elevate ${stepStatusColor[step.status] || ""}`}>
                  {step.status}
                </Badge>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

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
  CalendarClock,
  ArrowRightCircle,
  Archive,
  ArchiveRestore,
} from "lucide-react";
import type { WorkOrder, ExecutionLog, WorkflowExecution, WorkflowStepRun, SubAgent } from "@shared/schema";
import { useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { ExpandablePanel } from "@/components/expandable-panel";
import { Calendar } from "@/components/ui/calendar";
import { format } from "date-fns";

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

function QualityReviewSummary({ order }: { order: WorkOrder }) {
  const gcc = (order.gccMemory || {}) as Record<string, any>;
  const meta = gcc["gcc.metadata"] || {};
  const qr = meta.qualityReview as { score?: number; recommendation?: string; issues?: string[] } | undefined;
  const bdm = order.bdmMarker as Record<string, any> | null;
  const isQualityBlock = bdm?.type === "quality_block";
  const tier2 = order.tier2Result as Record<string, any> | null;
  const hasOutput = tier2 && !tier2.blocked && tier2.output;

  if (!qr && !isQualityBlock) return null;

  const score = qr?.score ?? 0;
  const recommendation = qr?.recommendation || bdm?.type || "unknown";
  const issues = qr?.issues || bdm?.issues || [];
  const reason = bdm?.reason || "";

  const isRevision = order.status === "awaiting_operator";
  const borderColor = isRevision
    ? "border-amber-200 dark:border-amber-800/40"
    : "border-red-200 dark:border-red-800/40";
  const bgColor = isRevision
    ? "bg-amber-50 dark:bg-amber-900/10"
    : "bg-red-50 dark:bg-red-900/10";
  const textColor = isRevision
    ? "text-amber-700 dark:text-amber-400"
    : "text-red-700 dark:text-red-400";
  const subtextColor = isRevision
    ? "text-amber-600 dark:text-amber-300"
    : "text-red-600 dark:text-red-300";

  return (
    <div className={`rounded-md border ${borderColor} overflow-hidden`} data-testid="quality-review-summary">
      <div className={`flex items-start gap-3 p-4 ${bgColor}`}>
        <ShieldCheck className={`w-5 h-5 ${textColor} mt-0.5 flex-shrink-0`} />
        <div className="space-y-1 min-w-0">
          <p className={`text-sm font-medium ${textColor}`}>
            {isRevision ? "Aiden Quality Review — Revision Requested" : "Aiden Quality Review — Blocked"}
          </p>
          <p className={`text-sm ${subtextColor}`}>
            {reason || `Aiden reviewed the deliverable and recommends ${recommendation.replace(/_/g, " ")}.`}
          </p>
        </div>
      </div>
      <div className={`px-4 py-3 ${bgColor.replace("50", "50/50").replace("/10", "/5")} space-y-2`}>
        <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
          <span>Quality Score: <span className="font-medium text-foreground">{(score * 100).toFixed(0)}%</span></span>
          <span>Recommendation: <span className="font-medium text-foreground capitalize">{recommendation.replace(/_/g, " ")}</span></span>
          <span>Deliverable: <span className="font-medium text-foreground">{hasOutput ? "Available" : "None"}</span></span>
        </div>
        {issues.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Issues Identified:</p>
            <ul className="text-xs text-muted-foreground list-disc list-inside space-y-0.5">
              {issues.map((issue: string, i: number) => (
                <li key={i}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <div className={`px-4 py-3 border-t ${borderColor} bg-muted/30`}>
        <p className="text-xs text-muted-foreground">
          {isRevision
            ? "Review the deliverable below. You can Accept it as-is, Re-issue to Aiden for another attempt, Close the order, or Defer the decision."
            : "Aiden blocked this deliverable at quality review. You can Override and re-process, Close the order, or Defer."}
        </p>
      </div>
    </div>
  );
}

export default function WorkOrderDetail() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [copied, setCopied] = useState(false);
  const [archiveDialogOpen, setArchiveDialogOpen] = useState(false);
  const [archiveReason, setArchiveReason] = useState("");
  const [acceptDialogOpen, setAcceptDialogOpen] = useState(false);
  const [acceptNotes, setAcceptNotes] = useState("");

  const { data: order, isLoading: orderLoading } = useQuery<WorkOrder>({
    queryKey: ["/api/work-orders", params.id],
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "processing" ? 3000 : false;
    },
  });

  const { data: logs, isLoading: logsLoading } = useQuery<ExecutionLog[]>({
    queryKey: ["/api/work-orders", params.id, "logs"],
    refetchInterval: order?.status === "processing" ? 5000 : false,
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
  const [deferDialogOpen, setDeferDialogOpen] = useState(false);
  const [deferReason, setDeferReason] = useState("");
  const [deferUntil, setDeferUntil] = useState<Date | undefined>(undefined);

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
    queryClient.invalidateQueries({ queryKey: ["/api/work-orders?includeArchived=true"] });
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

  const acceptMutation = useMutation({
    mutationFn: () =>
      apiRequest("POST", `/api/work-orders/${params.id}/unblock`, {
        resolution: `Operator accepted deliverable despite Aiden quality review concerns.${acceptNotes.trim() ? ` Notes: ${acceptNotes.trim()}` : ""}`,
        reprocess: false,
      }),
    onSuccess: () => {
      invalidateOrderQueries();
      setAcceptDialogOpen(false);
      setAcceptNotes("");
      toast({
        title: "Deliverable accepted",
        description: "Work order marked as completed with operator approval.",
      });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to accept deliverable.", variant: "destructive" });
    },
  });

  const deferMutation = useMutation({
    mutationFn: () =>
      apiRequest("POST", `/api/work-orders/${params.id}/defer`, {
        reason: deferReason,
        deferUntil: deferUntil ? format(deferUntil, "yyyy-MM-dd") : "",
      }),
    onSuccess: () => {
      invalidateOrderQueries();
      setDeferDialogOpen(false);
      setDeferReason("");
      setDeferUntil(undefined);
      toast({
        title: "Decision deferred",
        description: "Work order deferred until the selected date.",
      });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to defer work order.", variant: "destructive" });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: () =>
      apiRequest("POST", `/api/work-orders/${params.id}/archive`, {
        reason: archiveReason,
      }),
    onSuccess: () => {
      invalidateOrderQueries();
      setArchiveDialogOpen(false);
      setArchiveReason("");
      toast({ title: "Archived", description: "Work order has been archived." });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to archive work order.", variant: "destructive" });
    },
  });

  const unarchiveMutation = useMutation({
    mutationFn: () => apiRequest("POST", `/api/work-orders/${params.id}/unarchive`),
    onSuccess: () => {
      invalidateOrderQueries();
      toast({ title: "Restored", description: "Work order has been restored from archive." });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to restore work order.", variant: "destructive" });
    },
  });

  const refileMutation = useMutation({
    mutationFn: () => apiRequest("POST", `/api/work-orders/${params.id}/refile`),
    onSuccess: () => {
      invalidateOrderQueries();
      queryClient.invalidateQueries({ queryKey: ["/api/sandbox-sessions"] });
      toast({ title: "Re-filed", description: "Work order output has been re-filed to Workspace and Sandbox." });
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to re-file work order.", variant: "destructive" });
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
                <>
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
                  <Button
                    variant="outline"
                    onClick={() => refileMutation.mutate()}
                    disabled={refileMutation.isPending}
                    data-testid="button-refile"
                  >
                    {refileMutation.isPending ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <RefreshCw className="w-4 h-4 mr-2" />
                    )}
                    {refileMutation.isPending ? "Re-filing..." : "Re-file to Sandbox"}
                  </Button>
                </>
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
              {(order.status === "blocked" || order.status === "deferred") && (
                <>
                  <Button
                    onClick={() => reissueMutation.mutate()}
                    disabled={reissueMutation.isPending}
                    data-testid="button-reissue"
                  >
                    {reissueMutation.isPending ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <ArrowRightCircle className="w-4 h-4 mr-2" />
                    )}
                    {reissueMutation.isPending ? "Overriding..." : "Override & Continue"}
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
                    Close Without Processing
                  </Button>
                  {order.status === "blocked" && (
                    <Button
                      variant="outline"
                      onClick={() => {
                        setDeferReason("");
                        setDeferUntil(undefined);
                        setDeferDialogOpen(true);
                      }}
                      data-testid="button-defer"
                    >
                      <CalendarClock className="w-4 h-4 mr-2" />
                      Defer Decision
                    </Button>
                  )}
                </>
              )}
              {order.status === "failed" && (
                <>
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
                  <Button
                    variant="outline"
                    onClick={() => {
                      setDeferReason("");
                      setDeferUntil(undefined);
                      setDeferDialogOpen(true);
                    }}
                    data-testid="button-defer-failed"
                  >
                    <CalendarClock className="w-4 h-4 mr-2" />
                    Defer Decision
                  </Button>
                </>
              )}
              {order.status === "awaiting_operator" && (
                <>
                  <Button
                    className="bg-green-600 hover:bg-green-700 text-white"
                    onClick={() => {
                      setAcceptNotes("");
                      setAcceptDialogOpen(true);
                    }}
                    data-testid="button-accept-deliverable"
                  >
                    <CheckCircle className="w-4 h-4 mr-2" />
                    Accept Deliverable
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => reissueMutation.mutate()}
                    disabled={reissueMutation.isPending}
                    data-testid="button-reissue-awaiting"
                  >
                    {reissueMutation.isPending ? (
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    ) : (
                      <ArrowRightCircle className="w-4 h-4 mr-2" />
                    )}
                    {reissueMutation.isPending ? "Re-issuing..." : "Re-issue to Aiden"}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setCloseReason("");
                      setCloseDialogOpen(true);
                    }}
                    data-testid="button-close-awaiting"
                  >
                    <XCircle className="w-4 h-4 mr-2" />
                    Reject & Close
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setDeferReason("");
                      setDeferUntil(undefined);
                      setDeferDialogOpen(true);
                    }}
                    data-testid="button-defer-awaiting"
                  >
                    <CalendarClock className="w-4 h-4 mr-2" />
                    Defer Decision
                  </Button>
                </>
              )}
              {isAdmin && !order.isArchived && (
                <Button
                  variant="outline"
                  onClick={() => {
                    setArchiveReason("");
                    setArchiveDialogOpen(true);
                  }}
                  data-testid="button-archive"
                >
                  <Archive className="w-4 h-4 mr-2" />
                  Archive
                </Button>
              )}
              {isAdmin && order.isArchived && (
                <Button
                  variant="outline"
                  onClick={() => unarchiveMutation.mutate()}
                  disabled={unarchiveMutation.isPending}
                  data-testid="button-unarchive"
                >
                  {unarchiveMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <ArchiveRestore className="w-4 h-4 mr-2" />
                  )}
                  {unarchiveMutation.isPending ? "Restoring..." : "Restore from Archive"}
                </Button>
              )}
            </>
          )}
        </div>
      </div>

      {order.isArchived && (
        <Card className="border-muted bg-muted/30" data-testid="archived-banner">
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <Archive className="w-4 h-4 text-muted-foreground" />
              <span className="text-sm font-medium text-muted-foreground">This work order is archived</span>
              {order.archivedBy && (
                <span className="text-xs text-muted-foreground ml-auto">
                  by {order.archivedBy}
                  {order.archivedAt && ` on ${new Date(order.archivedAt).toLocaleDateString()}`}
                </span>
              )}
            </div>
            {order.archivedReason && (
              <p className="text-xs text-muted-foreground mt-1.5 ml-6">
                Reason: {order.archivedReason}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <Dialog open={closeDialogOpen} onOpenChange={setCloseDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <XCircle className="w-5 h-5" />
              {order.status === "awaiting_operator" ? "Reject & Close" : "Close Without Output"}
            </DialogTitle>
            <DialogDescription>
              {order.status === "awaiting_operator"
                ? "This will reject the deliverable and close the work order. The existing output will be discarded. Please explain why you are rejecting it."
                : "This will mark the work order as complete without producing any output. Please explain why you are closing it instead of re-issuing."}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="close-reason">{order.status === "awaiting_operator" ? "Reason for rejection" : "Why are you closing this?"}</Label>
            <Textarea
              id="close-reason"
              value={closeReason}
              onChange={(e) => setCloseReason(e.target.value)}
              placeholder={order.status === "awaiting_operator"
                ? "e.g., Deliverable doesn't meet requirements, wrong approach taken, no longer needed..."
                : "e.g., No longer needed, handled externally, duplicate of another order..."}
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

      <Dialog open={acceptDialogOpen} onOpenChange={setAcceptDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CheckCircle className="w-5 h-5 text-green-600" />
              Accept Deliverable
            </DialogTitle>
            <DialogDescription>
              Aiden flagged this deliverable during quality review, but you can override and accept it as complete. The existing output will be kept and the work order will be marked as completed.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-2">
            <Label htmlFor="accept-notes">Operator Notes (optional)</Label>
            <Textarea
              id="accept-notes"
              value={acceptNotes}
              onChange={(e) => setAcceptNotes(e.target.value)}
              placeholder="e.g., Reviewed the deliverable — quality is acceptable for this use case, minor issues noted but not blocking..."
              className="min-h-[100px]"
              data-testid="input-accept-notes"
            />
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setAcceptDialogOpen(false)} data-testid="button-cancel-accept">
              Cancel
            </Button>
            <Button
              className="bg-green-600 hover:bg-green-700 text-white"
              onClick={() => acceptMutation.mutate()}
              disabled={acceptMutation.isPending}
              data-testid="button-confirm-accept"
            >
              {acceptMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <CheckCircle className="w-4 h-4 mr-2" />
              )}
              {acceptMutation.isPending ? "Accepting..." : "Accept & Complete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deferDialogOpen} onOpenChange={setDeferDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CalendarClock className="w-5 h-5 text-sky-600" />
              Defer Decision
            </DialogTitle>
            <DialogDescription>
              Defer the decision on this work order to a future date. The order will be placed on hold until then. You can override or close it at any time before the defer date.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Review Date</Label>
              {deferUntil && (
                <div className="flex items-center gap-2 p-2 rounded-md bg-muted text-sm" data-testid="text-selected-date">
                  <CalendarClock className="h-4 w-4 text-sky-600" />
                  <span className="font-medium">{format(deferUntil, "PPP")}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto h-6 w-6 p-0"
                    onClick={() => setDeferUntil(undefined)}
                    data-testid="button-clear-date"
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              )}
              <div className="border rounded-md flex justify-center" data-testid="input-defer-until">
                <Calendar
                  mode="single"
                  selected={deferUntil}
                  onSelect={setDeferUntil}
                  disabled={(date) => date <= new Date()}
                />
              </div>
              <p className="text-xs text-muted-foreground">When should this work order be revisited?</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="defer-reason">Reason for Deferral</Label>
              <Textarea
                id="defer-reason"
                value={deferReason}
                onChange={(e) => setDeferReason(e.target.value)}
                placeholder="e.g., Waiting for vendor response, pending budget approval, need more information..."
                className="min-h-[100px]"
                data-testid="input-defer-reason"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDeferDialogOpen(false)} data-testid="button-cancel-defer">
              Cancel
            </Button>
            <Button
              onClick={() => deferMutation.mutate()}
              disabled={deferMutation.isPending || deferReason.trim().length === 0 || !deferUntil}
              data-testid="button-confirm-defer"
            >
              {deferMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <CalendarClock className="w-4 h-4 mr-2" />
              )}
              {deferMutation.isPending ? "Deferring..." : "Defer Decision"}
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

      <Dialog open={archiveDialogOpen} onOpenChange={setArchiveDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Archive className="w-5 h-5" />
              Archive Work Order
            </DialogTitle>
            <DialogDescription>
              This will hide the work order from dashboards and active lists. It can be restored later.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Label htmlFor="archive-reason">Reason for archiving</Label>
            <Textarea
              id="archive-reason"
              placeholder="e.g. Completed and no longer relevant..."
              value={archiveReason}
              onChange={(e) => setArchiveReason(e.target.value)}
              data-testid="input-archive-reason"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setArchiveDialogOpen(false)} data-testid="button-cancel-archive">
              Cancel
            </Button>
            <Button
              onClick={() => archiveMutation.mutate()}
              disabled={archiveMutation.isPending || archiveReason.trim().length === 0}
              data-testid="button-confirm-archive"
            >
              {archiveMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Archive className="w-4 h-4 mr-2" />
              )}
              {archiveMutation.isPending ? "Archiving..." : "Archive"}
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

              {(order.status === "awaiting_operator" || order.status === "blocked") && (
                <QualityReviewSummary order={order} />
              )}

              {order.status === "blocked" && order.bdmMarker && !(order.bdmMarker as Record<string, any>).type?.includes("quality") && (
                <BlockedSummary order={order} />
              )}

              {order.status === "deferred" && (
                <div className="rounded-md border border-sky-200 dark:border-sky-800/40 overflow-hidden" data-testid="deferred-summary">
                  <div className="flex items-start gap-3 p-4 bg-sky-50 dark:bg-sky-900/10">
                    <CalendarClock className="w-5 h-5 text-sky-600 dark:text-sky-400 mt-0.5 flex-shrink-0" />
                    <div className="space-y-1 min-w-0">
                      <p className="text-sm font-medium text-sky-700 dark:text-sky-400">
                        Decision Deferred
                      </p>
                      <p className="text-sm text-sky-600 dark:text-sky-300">
                        {order.deferredReason || "No reason provided"}
                      </p>
                    </div>
                  </div>
                  <div className="px-4 py-3 bg-sky-50/50 dark:bg-sky-900/5 space-y-2">
                    <div className="flex items-center gap-4 text-xs text-muted-foreground flex-wrap">
                      {order.deferredUntil && (
                        <span>Review date: <span className="font-medium text-foreground">{new Date(order.deferredUntil).toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" })}</span></span>
                      )}
                    </div>
                    {order.deferredUntil && new Date(order.deferredUntil) <= new Date() && (
                      <div className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-400 font-medium">
                        <AlertTriangle className="w-3 h-3" />
                        Defer date has passed — this order is ready for review
                      </div>
                    )}
                  </div>
                  <div className="px-4 py-3 border-t border-sky-100 dark:border-sky-800/20 bg-muted/30">
                    <p className="text-xs text-muted-foreground">
                      Use "Override & Continue" to resume processing, or "Close Without Processing" if no longer needed.
                    </p>
                  </div>
                </div>
              )}

              {order.status !== "blocked" && order.status !== "deferred" && order.bdmMarker && (
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
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-medium">Execution Timeline</CardTitle>
                {logs && logs.length > 0 && (
                  <ExpandablePanel title={`Execution Timeline — ${order.title}`}>
                    <div className="p-6 space-y-0">
                      {logs.map((log, index) => (
                        <TimelineItem
                          key={log.id}
                          log={log}
                          isLast={index === logs.length - 1}
                        />
                      ))}
                    </div>
                  </ExpandablePanel>
                )}
              </div>
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
  const { toast } = useToast();
  const { data: execution, refetch } = useQuery<WorkflowExecution & { stepRuns: WorkflowStepRun[]; template?: any }>({
    queryKey: ["/api/workflow-executions", executionId],
    refetchInterval: (query) => {
      const d = query.state.data as any;
      return d?.status === "running" || d?.status === "processing" ? 3000 : false;
    },
  });

  const { data: subAgents } = useQuery<SubAgent[]>({ queryKey: ["/api/sub-agents"] });

  const retryMutation = useMutation({
    mutationFn: (stepRunId: string) => apiRequest("POST", `/api/workflow-executions/${executionId}/step-runs/${stepRunId}/retry`),
    onSuccess: () => { refetch(); toast({ title: "Step retrying" }); },
    onError: (e: any) => toast({ title: "Retry failed", description: e.message, variant: "destructive" }),
  });
  const skipMutation = useMutation({
    mutationFn: (stepRunId: string) => apiRequest("POST", `/api/workflow-executions/${executionId}/step-runs/${stepRunId}/skip`),
    onSuccess: () => { refetch(); toast({ title: "Step skipped" }); },
    onError: (e: any) => toast({ title: "Skip failed", description: e.message, variant: "destructive" }),
  });
  const resolveMutation = useMutation({
    mutationFn: (stepRunId: string) => apiRequest("POST", `/api/workflow-executions/${executionId}/step-runs/${stepRunId}/resolve`, { resolution: "Operator manual resolution" }),
    onSuccess: () => { refetch(); toast({ title: "Step resolved" }); },
    onError: (e: any) => toast({ title: "Resolve failed", description: e.message, variant: "destructive" }),
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
  const pmAgent = subAgents?.find(a => a.id === execution.pmSubAgentId);
  const execReview = execution.executiveReview as any;
  const workProduct = execution.finalWorkProduct as any;

  return (
    <Card data-testid="card-workflow-execution">
      <CardHeader className="flex flex-row items-center justify-between gap-4 pb-3">
        <div className="flex items-center gap-2">
          <GitBranch className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
          <CardTitle className="text-base font-medium">Workflow Execution</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="no-default-hover-elevate no-default-active-elevate" data-testid="badge-step-count">
            {completedSteps}/{totalSteps} steps
          </Badge>
          <Badge variant="outline" className={`no-default-hover-elevate no-default-active-elevate ${stepStatusColor[execution.status] || ""}`} data-testid="badge-execution-status">
            {execution.status === "running" && <Loader2 className="w-3 h-3 animate-spin mr-1" />}
            {execution.status}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-muted-foreground">Goal</p>
            <p className="text-sm">{execution.goal || "N/A"}</p>
          </div>
        </div>

        {pmAgent && (
          <div className="flex items-center gap-2 p-2 rounded-md bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800" data-testid="pm-assignment-info">
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 border-blue-500/50 text-blue-600 dark:text-blue-400 no-default-hover-elevate no-default-active-elevate">PM</Badge>
            <span className="text-xs font-medium text-blue-700 dark:text-blue-300">{pmAgent.name}</span>
            {execution.executionMode && (
              <Badge variant="outline" className="text-[10px] px-1.5 py-0 no-default-hover-elevate no-default-active-elevate ml-auto">
                {execution.executionMode}
              </Badge>
            )}
          </div>
        )}

        {execution.stepRuns && execution.stepRuns.length > 0 && (
          <div className="space-y-1.5 pt-2 border-t">
            <p className="text-xs text-muted-foreground mb-2">Steps</p>
            {execution.stepRuns.map((step) => {
              const pmReview = step.pmReview as any;
              const pfResult = step.pocketflowResult as any;
              return (
                <div key={step.id} className="rounded-md bg-muted/30 overflow-hidden" data-testid={`step-run-${step.stepKey}`}>
                  <div className="flex items-center justify-between gap-3 p-2">
                    <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium truncate">{step.stepName}</p>
                        {(step.revisionAttempt ?? 0) > 0 && (
                          <span className="text-[10px] text-amber-600 dark:text-amber-400">rev {step.revisionAttempt}</span>
                        )}
                      </div>
                      <p className="text-xs text-muted-foreground font-mono">{step.stepKey}</p>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {pfResult?.convergenceScore != null && (
                        <span className="text-[10px] text-muted-foreground">{(pfResult.convergenceScore * 100).toFixed(0)}%</span>
                      )}
                      <Badge variant="outline" className={`text-xs no-default-hover-elevate no-default-active-elevate ${stepStatusColor[step.status] || ""}`}>
                        {step.status === "running" && <Loader2 className="w-2.5 h-2.5 animate-spin mr-1" />}
                        {step.status}
                      </Badge>
                    </div>
                  </div>
                  {pmReview && (
                    <div className="px-2 pb-1.5 flex items-center gap-2 flex-wrap">
                      <span className="text-[10px] text-muted-foreground">PM Review:</span>
                      <Badge variant="outline" className={`text-[10px] px-1 py-0 no-default-hover-elevate no-default-active-elevate ${pmReview.recommendation === "advance" ? "text-emerald-600 dark:text-emerald-400" : pmReview.recommendation === "revise" ? "text-amber-600 dark:text-amber-400" : "text-red-600 dark:text-red-400"}`}>
                        {pmReview.recommendation} ({(pmReview.score * 100).toFixed(0)}%)
                      </Badge>
                      {pmReview.feedback && <span className="text-[10px] text-muted-foreground truncate max-w-[200px]">{pmReview.feedback}</span>}
                    </div>
                  )}
                  {(step.status === "failed" || step.status === "awaiting_operator") && (
                    <div className="px-2 pb-2 flex items-center gap-1.5">
                      {step.error && <p className="text-[10px] text-red-600 dark:text-red-400 truncate flex-1">{step.error}</p>}
                      <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => retryMutation.mutate(step.id)} disabled={retryMutation.isPending} data-testid={`button-retry-step-${step.stepKey}`}>
                        {retryMutation.isPending ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : "Retry"}
                      </Button>
                      <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => skipMutation.mutate(step.id)} disabled={skipMutation.isPending} data-testid={`button-skip-step-${step.stepKey}`}>
                        Skip
                      </Button>
                      {step.status === "awaiting_operator" && (
                        <Button size="sm" variant="outline" className="h-6 text-[10px] px-2" onClick={() => resolveMutation.mutate(step.id)} disabled={resolveMutation.isPending} data-testid={`button-resolve-step-${step.stepKey}`}>
                          Resolve
                        </Button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {workProduct && (
          <div className="pt-2 border-t space-y-2" data-testid="work-product-section">
            <p className="text-xs text-muted-foreground font-medium">Work Product</p>
            <div className="p-2 rounded-md bg-muted/30">
              <p className="text-sm font-medium">{workProduct.deliverableTitle || "Deliverable"}</p>
              <p className="text-xs text-muted-foreground mt-0.5">{workProduct.summary}</p>
              {workProduct.deliverableType && (
                <Badge variant="outline" className="text-[10px] px-1.5 py-0 mt-1 no-default-hover-elevate no-default-active-elevate">{workProduct.deliverableType}</Badge>
              )}
            </div>
          </div>
        )}

        {execReview && (
          <div className="pt-2 border-t space-y-2" data-testid="executive-review-section">
            <p className="text-xs text-muted-foreground font-medium">Executive Review</p>
            <div className="p-2 rounded-md bg-muted/30">
              <div className="flex items-center justify-between gap-2">
                <Badge variant="outline" className={`text-[10px] px-1.5 py-0 no-default-hover-elevate no-default-active-elevate ${execReview.approved ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}`}>
                  {execReview.recommendation} ({(execReview.score * 100).toFixed(0)}%)
                </Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-1">{execReview.feedback}</p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

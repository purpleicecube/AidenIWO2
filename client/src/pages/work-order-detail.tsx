import { useQuery, useMutation } from "@tanstack/react-query";
import { useParams, Link } from "wouter";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { StatusBadge, PriorityBadge } from "@/components/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
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
  const TierIcon = log.tier === 1 ? Brain : Bot;
  const tierColor = log.tier === 1
    ? "bg-primary/10 text-primary dark:bg-primary/20"
    : "bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400";
  const tierLabel = log.tier === 1 ? "Aiden" : "Sub-Agent";

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
          <Badge variant="outline" className="text-xs no-default-hover-elevate no-default-active-elevate">
            {tierLabel}
          </Badge>
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
        <div className="flex items-center gap-3">
          <Link href="/work-orders">
            <Button variant="ghost" size="icon" data-testid="button-back">
              <ArrowLeft className="w-4 h-4" />
            </Button>
          </Link>
          <div>
            <h1 className="text-xl font-semibold tracking-tight" data-testid="text-order-title">
              {order.title}
            </h1>
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
          {(order.status === "pending") && (
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
          {(order.status === "blocked" || order.status === "failed") && (
            <Button
              variant="outline"
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
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-medium">Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs text-muted-foreground mb-1">Description</p>
                <p className="text-sm" data-testid="text-order-description">{order.description}</p>
              </div>

              {order.bdmMarker && (
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
                <PriorityBadge priority={order.priority} />
              </div>
              <Separator />
              <div>
                <p className="text-xs text-muted-foreground mb-1">Type</p>
                <p className="text-sm capitalize" data-testid="text-order-type">{order.type}</p>
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

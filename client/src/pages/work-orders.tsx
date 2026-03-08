import { useQuery, useMutation } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/use-auth";
import { StatusBadge, PriorityBadge } from "@/components/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Link } from "wouter";
import { useState } from "react";
import { Search, Plus, ClipboardList, AlertTriangle, RefreshCw, XCircle, Eye, Loader2, UserCheck, CalendarClock, Archive, FileDown } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { usePageTitle } from "@/hooks/use-page-title";
import { useToast } from "@/hooks/use-toast";
import { apiRequest, queryClient } from "@/lib/queryClient";
import type { WorkOrder } from "@shared/schema";

function OrdersTableSkeleton() {
  return (
    <div className="space-y-2">
      {[1, 2, 3, 4, 5, 6].map((i) => (
        <div key={i} className="flex items-center gap-4 p-4 rounded-md border border-border/50">
          <Skeleton className="h-4 w-4 rounded" />
          <div className="flex-1 flex items-center gap-4">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-4 w-20" />
            <Skeleton className="h-6 w-16" />
            <Skeleton className="h-6 w-20" />
          </div>
          <Skeleton className="h-4 w-24" />
        </div>
      ))}
    </div>
  );
}

function NeedsAttentionBanner({ orders, canAct }: { orders: WorkOrder[]; canAct: boolean }) {
  const { toast } = useToast();
  const [actioningId, setActioningId] = useState<string | null>(null);

  const attentionOrders = orders.filter(o =>
    o.status === "blocked" || o.status === "awaiting_operator" || o.status === "failed" || o.status === "deferred"
  );

  const reissueMutation = useMutation({
    mutationFn: (id: string) =>
      apiRequest("POST", `/api/work-orders/${id}/unblock`, {
        resolution: "Re-issued to Aiden for re-processing.",
        reprocess: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders?includeArchived=true"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
      toast({ title: "Override & Continue", description: "Block overridden — work order re-submitted for processing." });
      setActioningId(null);
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to re-issue.", variant: "destructive" });
      setActioningId(null);
    },
  });

  const retryMutation = useMutation({
    mutationFn: (id: string) => apiRequest("POST", `/api/work-orders/${id}/retry`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders?includeArchived=true"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
      toast({ title: "Retrying", description: "Work order re-submitted for processing." });
      setActioningId(null);
    },
    onError: () => {
      toast({ title: "Error", description: "Failed to retry.", variant: "destructive" });
      setActioningId(null);
    },
  });

  if (attentionOrders.length === 0) return null;

  const blockedCount = attentionOrders.filter(o => o.status === "blocked").length;
  const awaitingCount = attentionOrders.filter(o => o.status === "awaiting_operator").length;
  const failedCount = attentionOrders.filter(o => o.status === "failed").length;
  const deferredCount = attentionOrders.filter(o => o.status === "deferred").length;

  return (
    <Card className="border-amber-300 dark:border-amber-700 bg-amber-50/50 dark:bg-amber-900/10" data-testid="banner-needs-attention">
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-3">
          <AlertTriangle className="w-4.5 h-4.5 text-amber-600 dark:text-amber-400" />
          <span className="text-sm font-semibold text-amber-800 dark:text-amber-300">
            Needs Attention
          </span>
          <Badge variant="outline" className="border-transparent bg-amber-200/80 text-amber-800 dark:bg-amber-800/40 dark:text-amber-300 no-default-hover-elevate no-default-active-elevate text-xs ml-1">
            {attentionOrders.length}
          </Badge>
          <div className="flex items-center gap-2 ml-auto text-xs text-muted-foreground">
            {blockedCount > 0 && <span>{blockedCount} blocked</span>}
            {awaitingCount > 0 && <span>{awaitingCount} awaiting</span>}
            {failedCount > 0 && <span>{failedCount} failed</span>}
            {deferredCount > 0 && <span>{deferredCount} deferred</span>}
          </div>
        </div>
        <div className="space-y-1.5">
          {attentionOrders.slice(0, 8).map(order => {
            const isActioning = actioningId === order.id;
            return (
              <div
                key={order.id}
                className="flex items-center gap-3 p-2.5 rounded-md bg-white dark:bg-card border border-border/60 hover:border-border transition-colors"
                data-testid={`attention-item-${order.id}`}
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{order.title}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <StatusBadge status={order.status} />
                    <PriorityBadge priority={order.priority} />
                    {(() => {
                      const marker = order.bdmMarker as Record<string, string> | null;
                      return marker?.reason ? (
                        <span className="text-[10px] text-muted-foreground truncate max-w-[200px]">
                          {marker.reason}
                        </span>
                      ) : null;
                    })()}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {canAct && order.status === "blocked" && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          size="sm"
                          variant="default"
                          className="h-7 text-xs px-2.5"
                          disabled={isActioning}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setActioningId(order.id);
                            reissueMutation.mutate(order.id);
                          }}
                          data-testid={`button-quick-reissue-${order.id}`}
                        >
                          {isActioning && reissueMutation.isPending ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                          ) : (
                            <RefreshCw className="w-3 h-3 mr-1" />
                          )}
                          Re-issue
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent><p className="text-xs">Re-issue to Aiden for re-processing</p></TooltipContent>
                    </Tooltip>
                  )}
                  {canAct && order.status === "failed" && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          size="sm"
                          variant="default"
                          className="h-7 text-xs px-2.5"
                          disabled={isActioning}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setActioningId(order.id);
                            retryMutation.mutate(order.id);
                          }}
                          data-testid={`button-quick-retry-${order.id}`}
                        >
                          {isActioning && retryMutation.isPending ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                          ) : (
                            <RefreshCw className="w-3 h-3 mr-1" />
                          )}
                          Retry
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent><p className="text-xs">Retry this failed work order</p></TooltipContent>
                    </Tooltip>
                  )}
                  {canAct && order.status === "awaiting_operator" && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          size="sm"
                          variant="default"
                          className="h-7 text-xs px-2.5"
                          disabled={isActioning}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setActioningId(order.id);
                            reissueMutation.mutate(order.id);
                          }}
                          data-testid={`button-quick-reissue-awaiting-${order.id}`}
                        >
                          {isActioning && reissueMutation.isPending ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                          ) : (
                            <RefreshCw className="w-3 h-3 mr-1" />
                          )}
                          Re-issue
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent><p className="text-xs">Re-issue to Aiden for re-processing</p></TooltipContent>
                    </Tooltip>
                  )}
                  {!canAct && order.status === "awaiting_operator" && (
                    <Badge variant="outline" className="border-transparent bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 no-default-hover-elevate no-default-active-elevate text-[10px] h-6">
                      <UserCheck className="w-3 h-3 mr-1" />
                      Awaiting
                    </Badge>
                  )}
                  {canAct && order.status === "deferred" && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          size="sm"
                          variant="default"
                          className="h-7 text-xs px-2.5"
                          disabled={isActioning}
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setActioningId(order.id);
                            reissueMutation.mutate(order.id);
                          }}
                          data-testid={`button-quick-override-${order.id}`}
                        >
                          {isActioning && reissueMutation.isPending ? (
                            <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                          ) : (
                            <RefreshCw className="w-3 h-3 mr-1" />
                          )}
                          Override
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent><p className="text-xs">Override deferral and continue processing</p></TooltipContent>
                    </Tooltip>
                  )}
                  {!canAct && order.status === "deferred" && order.deferredUntil && (
                    <Badge variant="outline" className="border-transparent bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400 no-default-hover-elevate no-default-active-elevate text-[10px] h-6">
                      <CalendarClock className="w-3 h-3 mr-1" />
                      Until {new Date(order.deferredUntil).toLocaleDateString()}
                    </Badge>
                  )}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Link href={`/work-orders/${order.id}`}>
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 text-xs px-2"
                          onClick={(e) => e.stopPropagation()}
                          data-testid={`button-quick-view-${order.id}`}
                        >
                          <Eye className="w-3 h-3" />
                        </Button>
                      </Link>
                    </TooltipTrigger>
                    <TooltipContent><p className="text-xs">View details</p></TooltipContent>
                  </Tooltip>
                </div>
              </div>
            );
          })}
          {attentionOrders.length > 8 && (
            <p className="text-xs text-muted-foreground text-center pt-1">
              +{attentionOrders.length - 8} more items need attention
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default function WorkOrders() {
  usePageTitle("Work Orders");
  const { user } = useAuth();
  const canSubmit = user?.role === "admin" || user?.role === "operator";
  const isAdmin = user?.role === "admin";
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [showArchived, setShowArchived] = useState(false);

  const includeArchived = showArchived || statusFilter === "archived";
  const { data: workOrders, isLoading } = useQuery<WorkOrder[]>({
    queryKey: [includeArchived ? "/api/work-orders?includeArchived=true" : "/api/work-orders"],
    staleTime: 5000,
    refetchOnMount: "always",
  });

  const filteredOrders = workOrders?.filter((order) => {
    const matchesSearch =
      searchQuery === "" ||
      order.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      order.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      order.correlationId.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesStatus = statusFilter === "all" ? true
      : statusFilter === "archived" ? order.isArchived
      : order.status === statusFilter;
    const matchesPriority = priorityFilter === "all" || order.priority === priorityFilter;
    const matchesArchive = statusFilter === "archived" ? true : !order.isArchived;

    return matchesSearch && matchesStatus && matchesPriority && matchesArchive;
  });

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-work-orders-title">
            Work Orders
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage and track all work orders in the pipeline
          </p>
        </div>
        {canSubmit && (
          <Link href="/submit">
            <Button data-testid="button-submit-new-order">
              <Plus className="w-4 h-4 mr-2" />
              New Work Order
            </Button>
          </Link>
        )}
      </div>

      {workOrders && <NeedsAttentionBanner orders={workOrders} canAct={canSubmit || false} />}

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search by title, description, or correlation ID..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9"
                data-testid="input-search"
              />
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[140px]" data-testid="select-status-filter">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Status</SelectItem>
                <SelectItem value="pending">Pending</SelectItem>
                <SelectItem value="processing">Processing</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="blocked">Blocked</SelectItem>
                <SelectItem value="failed">Failed</SelectItem>
                <SelectItem value="awaiting_operator">Awaiting Operator</SelectItem>
                <SelectItem value="deferred">Deferred</SelectItem>
                <SelectItem value="reopened">Reopened</SelectItem>
                <SelectItem value="archived">Archived</SelectItem>
              </SelectContent>
            </Select>
            <Select value={priorityFilter} onValueChange={setPriorityFilter}>
              <SelectTrigger className="w-[140px]" data-testid="select-priority-filter">
                <SelectValue placeholder="Priority" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Priority</SelectItem>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="critical">Critical</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <OrdersTableSkeleton />
          ) : filteredOrders && filteredOrders.length > 0 ? (
            <div className="space-y-1.5">
              <div className="grid grid-cols-[1fr_100px_90px_90px_120px] gap-3 px-4 py-2 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                <span>Title</span>
                <span>Type</span>
                <span>Priority</span>
                <span>Status</span>
                <span>Created</span>
              </div>
              {filteredOrders.map((order) => (
                <Link key={order.id} href={`/work-orders/${order.id}`}>
                  <div
                    className="grid grid-cols-[1fr_100px_90px_90px_120px] gap-3 items-center px-4 py-3 rounded-md hover-elevate cursor-pointer"
                    data-testid={`row-work-order-${order.id}`}
                  >
                    <div className="min-w-0">
                      <p className={`text-sm font-medium truncate ${order.isArchived ? "text-muted-foreground" : ""}`}>
                        {order.isArchived && <Archive className="w-3 h-3 inline mr-1.5 opacity-50" />}
                        {order.title}
                        {(() => {
                          const ppf = (order.tier2Result as any)?.output?.postProcessedFile;
                          return ppf ? (
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="inline-flex items-center ml-1.5">
                                  <FileDown className="w-3 h-3 text-emerald-500" />
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                <p className="text-xs">Has binary deliverable — open to download</p>
                              </TooltipContent>
                            </Tooltip>
                          ) : null;
                        })()}
                      </p>
                      <p className="text-xs text-muted-foreground truncate mt-0.5">
                        {order.correlationId.slice(0, 8)}...
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground capitalize">{order.type}</span>
                    <PriorityBadge priority={order.priority} />
                    {order.isArchived ? (
                      <Badge variant="outline" className="text-xs">
                        <Archive className="w-3 h-3 mr-1" />
                        Archived
                      </Badge>
                    ) : (
                      <StatusBadge status={order.status} />
                    )}
                    <span className="text-xs text-muted-foreground">
                      {new Date(order.createdAt).toLocaleDateString()}
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <ClipboardList className="w-12 h-12 text-muted-foreground/30 mb-4" />
              <p className="text-sm font-medium text-muted-foreground">No work orders found</p>
              <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                {searchQuery || statusFilter !== "all" || priorityFilter !== "all"
                  ? "Try adjusting your filters"
                  : "Submit your first work order to get started"}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

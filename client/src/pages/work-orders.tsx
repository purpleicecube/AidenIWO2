import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge, PriorityBadge } from "@/components/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Link } from "wouter";
import { useState } from "react";
import { Search, Plus, ClipboardList, ArrowUpDown } from "lucide-react";
import { usePageTitle } from "@/hooks/use-page-title";
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

export default function WorkOrders() {
  usePageTitle("Work Orders");
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");

  const { data: workOrders, isLoading } = useQuery<WorkOrder[]>({
    queryKey: ["/api/work-orders"],
  });

  const filteredOrders = workOrders?.filter((order) => {
    const matchesSearch =
      searchQuery === "" ||
      order.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      order.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      order.correlationId.toLowerCase().includes(searchQuery.toLowerCase());

    const matchesStatus = statusFilter === "all" || order.status === statusFilter;
    const matchesPriority = priorityFilter === "all" || order.priority === priorityFilter;

    return matchesSearch && matchesStatus && matchesPriority;
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
        <Link href="/submit">
          <Button data-testid="button-submit-new-order">
            <Plus className="w-4 h-4 mr-2" />
            New Work Order
          </Button>
        </Link>
      </div>

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
                <SelectItem value="reopened">Reopened</SelectItem>
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
                      <p className="text-sm font-medium truncate">{order.title}</p>
                      <p className="text-xs text-muted-foreground truncate mt-0.5">
                        {order.correlationId.slice(0, 8)}...
                      </p>
                    </div>
                    <span className="text-xs text-muted-foreground capitalize">{order.type}</span>
                    <PriorityBadge priority={order.priority} />
                    <StatusBadge status={order.status} />
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

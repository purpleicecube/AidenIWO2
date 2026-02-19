import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge, PriorityBadge } from "@/components/status-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Link } from "wouter";
import {
  ClipboardList,
  CheckCircle,
  AlertTriangle,
  Clock,
  ArrowRight,
  Plus,
  UserCheck,
  Brain,
  Bot,
  GitBranch,
  Wrench,
} from "lucide-react";
import { usePageTitle } from "@/hooks/use-page-title";
import type { WorkOrder, WorkflowExecution, Tool } from "@shared/schema";

interface DashboardStats {
  total: number;
  pending: number;
  processing: number;
  completed: number;
  blocked: number;
  failed: number;
  awaiting_operator: number;
}

function StatCard({
  title,
  value,
  icon: Icon,
  description,
  iconClass,
}: {
  title: string;
  value: number;
  icon: typeof ClipboardList;
  description: string;
  iconClass: string;
}) {
  return (
    <Card data-testid={`card-stat-${title.toLowerCase()}`}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="text-2xl font-semibold tracking-tight">{value}</p>
            <p className="text-xs text-muted-foreground">{description}</p>
          </div>
          <div className={`flex items-center justify-center w-10 h-10 rounded-md ${iconClass}`}>
            <Icon className="w-5 h-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function StatsSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {[1, 2, 3, 4].map((i) => (
        <Card key={i}>
          <CardContent className="p-5">
            <div className="flex items-start justify-between gap-3">
              <div className="flex flex-col gap-2">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-8 w-12" />
                <Skeleton className="h-3 w-24" />
              </div>
              <Skeleton className="h-10 w-10 rounded-md" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function RecentOrdersSkeleton() {
  return (
    <div className="space-y-3">
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className="flex items-center justify-between gap-4 p-3 rounded-md bg-muted/30">
          <div className="flex flex-col gap-1.5 flex-1">
            <Skeleton className="h-4 w-48" />
            <Skeleton className="h-3 w-32" />
          </div>
          <Skeleton className="h-6 w-20" />
        </div>
      ))}
    </div>
  );
}

export default function Dashboard() {
  usePageTitle("Dashboard");
  const { data: stats, isLoading: statsLoading } = useQuery<DashboardStats>({
    queryKey: ["/api/work-orders/stats"],
  });

  const { data: recentOrders, isLoading: ordersLoading } = useQuery<WorkOrder[]>({
    queryKey: ["/api/work-orders/recent"],
  });

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-dashboard-title">
            Dashboard
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitor Aiden (Tier 1) and sub-agent (Tier 2) orchestration
          </p>
        </div>
        <Link href="/submit">
          <Button data-testid="button-submit-new">
            <Plus className="w-4 h-4 mr-2" />
            New Work Order
          </Button>
        </Link>
      </div>

      {statsLoading ? (
        <StatsSkeleton />
      ) : stats ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
          <StatCard
            title="Total"
            value={stats.total}
            icon={ClipboardList}
            description="All work orders"
            iconClass="bg-primary/10 text-primary dark:bg-primary/20"
          />
          <StatCard
            title="Pending"
            value={stats.pending + stats.processing}
            icon={Clock}
            description="Awaiting Aiden review"
            iconClass="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
          />
          <StatCard
            title="Completed"
            value={stats.completed}
            icon={CheckCircle}
            description="Successfully processed"
            iconClass="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
          />
          <StatCard
            title="Awaiting Operator"
            value={stats.awaiting_operator}
            icon={UserCheck}
            description="Independent sub-agents"
            iconClass="bg-violet-100 text-violet-600 dark:bg-violet-900/30 dark:text-violet-400"
          />
          <StatCard
            title="Blocked"
            value={stats.blocked}
            icon={AlertTriangle}
            description="Requires attention"
            iconClass="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
          />
        </div>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between gap-4 pb-3">
            <CardTitle className="text-base font-medium">Recent Work Orders</CardTitle>
            <Link href="/work-orders">
              <Button variant="ghost" size="sm" data-testid="button-view-all">
                View All
                <ArrowRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </Link>
          </CardHeader>
          <CardContent>
            {ordersLoading ? (
              <RecentOrdersSkeleton />
            ) : recentOrders && recentOrders.length > 0 ? (
              <div className="space-y-2">
                {recentOrders.map((order) => (
                  <Link key={order.id} href={`/work-orders/${order.id}`}>
                    <div
                      className="flex items-center justify-between gap-4 p-3 rounded-md hover-elevate cursor-pointer"
                      data-testid={`card-recent-order-${order.id}`}
                    >
                      <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                        <p className="text-sm font-medium truncate">
                          {order.title}
                        </p>
                        <p className="text-xs text-muted-foreground truncate">
                          {order.type} &middot; {new Date(order.createdAt).toLocaleDateString()}
                        </p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <PriorityBadge priority={order.priority} />
                        <StatusBadge status={order.status} />
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <ClipboardList className="w-10 h-10 text-muted-foreground/40 mb-3" />
                <p className="text-sm text-muted-foreground">No work orders yet</p>
                <p className="text-xs text-muted-foreground mt-1">Submit your first work order to get started</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium">Orchestration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-3">
              <div className="flex items-center gap-3 p-3 rounded-md bg-muted/40">
                <div className="flex items-center justify-center w-8 h-8 rounded-md bg-primary/10 text-primary dark:bg-primary/20">
                  <Brain className="w-4 h-4" />
                </div>
                <div>
                  <p className="text-sm font-medium">Tier 1 — Aiden</p>
                  <p className="text-xs text-muted-foreground">Policy, Routing, Decisions</p>
                </div>
              </div>

              <div className="flex justify-center">
                <div className="w-px h-6 bg-border" />
              </div>

              <div className="flex items-center gap-3 p-3 rounded-md bg-muted/40">
                <div className="flex items-center justify-center w-8 h-8 rounded-md bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">
                  <Bot className="w-4 h-4" />
                </div>
                <div>
                  <p className="text-sm font-medium">Tier 2 — Sub-Agents</p>
                  <p className="text-xs text-muted-foreground">Aiden-controlled or Independent</p>
                </div>
              </div>
            </div>

            <div className="pt-2 border-t space-y-2">
              <Link href="/workflows">
                <div className="flex items-center gap-2 p-2 rounded-md hover-elevate cursor-pointer" data-testid="link-dashboard-workflows">
                  <GitBranch className="w-3.5 h-3.5 text-indigo-600 dark:text-indigo-400" />
                  <span className="text-sm">Workflows</span>
                  <ArrowRight className="w-3 h-3 ml-auto text-muted-foreground" />
                </div>
              </Link>
              <Link href="/tools">
                <div className="flex items-center gap-2 p-2 rounded-md hover-elevate cursor-pointer" data-testid="link-dashboard-tools">
                  <Wrench className="w-3.5 h-3.5 text-orange-600 dark:text-orange-400" />
                  <span className="text-sm">Tools</span>
                  <ArrowRight className="w-3 h-3 ml-auto text-muted-foreground" />
                </div>
              </Link>
              <Link href="/sub-agents">
                <div className="flex items-center gap-2 p-2 rounded-md hover-elevate cursor-pointer" data-testid="link-dashboard-sub-agents">
                  <Bot className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400" />
                  <span className="text-sm">Sub-Agents</span>
                  <ArrowRight className="w-3 h-3 ml-auto text-muted-foreground" />
                </div>
              </Link>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

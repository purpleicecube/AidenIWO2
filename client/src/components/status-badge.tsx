import { Badge } from "@/components/ui/badge";
import { CheckCircle, Clock, Loader2, AlertTriangle, XCircle, UserCheck, RotateCcw, CalendarClock, Skull } from "lucide-react";

const statusConfig: Record<string, { label: string; variant: "default" | "secondary" | "destructive" | "outline"; icon: typeof CheckCircle; className: string }> = {
  pending: {
    label: "Pending",
    variant: "secondary",
    icon: Clock,
    className: "bg-muted text-muted-foreground",
  },
  processing: {
    label: "Processing",
    variant: "default",
    icon: Loader2,
    className: "bg-primary/10 text-primary dark:bg-primary/20",
  },
  completed: {
    label: "Completed",
    variant: "default",
    icon: CheckCircle,
    className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400",
  },
  blocked: {
    label: "Blocked",
    variant: "destructive",
    icon: AlertTriangle,
    className: "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400",
  },
  failed: {
    label: "Failed",
    variant: "destructive",
    icon: XCircle,
    className: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
  },
  awaiting_operator: {
    label: "Operator",
    variant: "outline",
    icon: UserCheck,
    className: "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400",
  },
  reopened: {
    label: "Reopened",
    variant: "default",
    icon: RotateCcw,
    className: "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400",
  },
  deferred: {
    label: "Deferred",
    variant: "outline",
    icon: CalendarClock,
    className: "bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400",
  },
  killed: {
    label: "Killed",
    variant: "destructive",
    icon: Skull,
    className: "bg-red-200 text-red-900 dark:bg-red-900/50 dark:text-red-300",
  },
};

const priorityConfig: Record<string, { label: string; className: string }> = {
  low: { label: "Low", className: "bg-muted text-muted-foreground" },
  medium: { label: "Medium", className: "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400" },
  high: { label: "High", className: "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400" },
  critical: { label: "Critical", className: "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400" },
};

export function StatusBadge({ status }: { status: string }) {
  const config = statusConfig[status] || statusConfig.pending;
  const Icon = config.icon;

  return (
    <Badge variant="outline" className={`${config.className} gap-1 no-default-hover-elevate no-default-active-elevate border-transparent`} data-testid={`badge-status-${status}`}>
      <Icon className={`w-3 h-3 ${status === "processing" ? "animate-spin" : ""}`} />
      {config.label}
    </Badge>
  );
}

export function PriorityBadge({ priority }: { priority: string }) {
  const config = priorityConfig[priority] || priorityConfig.medium;

  return (
    <Badge variant="outline" className={`${config.className} no-default-hover-elevate no-default-active-elevate border-transparent`} data-testid={`badge-priority-${priority}`}>
      {config.label}
    </Badge>
  );
}

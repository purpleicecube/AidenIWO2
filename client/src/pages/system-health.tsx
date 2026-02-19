import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import {
  CheckCircle,
  XCircle,
  Activity,
  Database,
  Layers,
  RefreshCw,
  Server,
  Shield,
  Clock,
} from "lucide-react";
import { usePageTitle } from "@/hooks/use-page-title";
import { queryClient } from "@/lib/queryClient";

interface HealthStatus {
  status: string;
  timestamp: string;
  version: string;
  uptime: number;
  services: {
    database: string;
    tier1: string;
    tier2: string;
    gccMemory: string;
  };
  checks: {
    api: boolean;
    database: boolean;
    orchestration: boolean;
    schemaValidation: boolean;
  };
}

function HealthCardSkeleton() {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center gap-3">
          <Skeleton className="w-10 h-10 rounded-md" />
          <div className="space-y-1.5 flex-1">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-3 w-32" />
          </div>
          <Skeleton className="h-6 w-16" />
        </div>
      </CardContent>
    </Card>
  );
}

function ServiceCard({
  title,
  description,
  status,
  icon: Icon,
  iconClass,
}: {
  title: string;
  description: string;
  status: string;
  icon: typeof Activity;
  iconClass: string;
}) {
  const isHealthy = status === "healthy" || status === "ok" || status === "active";

  return (
    <Card data-testid={`card-service-${title.toLowerCase().replace(/\s/g, "-")}`}>
      <CardContent className="p-5">
        <div className="flex items-center gap-3">
          <div className={`flex items-center justify-center w-10 h-10 rounded-md ${iconClass}`}>
            <Icon className="w-5 h-5" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium">{title}</p>
            <p className="text-xs text-muted-foreground">{description}</p>
          </div>
          <Badge
            variant="outline"
            className={`no-default-hover-elevate no-default-active-elevate border-transparent ${
              isHealthy
                ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
            }`}
          >
            {isHealthy ? (
              <CheckCircle className="w-3 h-3 mr-1" />
            ) : (
              <XCircle className="w-3 h-3 mr-1" />
            )}
            {status}
          </Badge>
        </div>
      </CardContent>
    </Card>
  );
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}

export default function SystemHealth() {
  usePageTitle("System Health");
  const { data: health, isLoading, isError, refetch } = useQuery<HealthStatus>({
    queryKey: ["/api/health"],
    refetchInterval: 30000,
  });

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-health-title">
            System Health
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitor the status of all AIDEN_PTIB services and components
          </p>
        </div>
        <Button
          variant="outline"
          onClick={() => refetch()}
          data-testid="button-refresh-health"
        >
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <Card key={i}>
                <CardContent className="p-5">
                  <Skeleton className="h-4 w-16 mb-2" />
                  <Skeleton className="h-7 w-24" />
                </CardContent>
              </Card>
            ))}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <HealthCardSkeleton key={i} />
            ))}
          </div>
        </div>
      ) : isError ? (
        <Card>
          <CardContent className="p-8">
            <div className="flex flex-col items-center justify-center text-center">
              <XCircle className="w-12 h-12 text-red-500/60 mb-4" />
              <p className="text-lg font-medium">System Unreachable</p>
              <p className="text-sm text-muted-foreground mt-1 max-w-md">
                Unable to connect to the AIDEN_PTIB health endpoint. The system may be down or experiencing issues.
              </p>
              <Button
                variant="outline"
                onClick={() => refetch()}
                className="mt-4"
                data-testid="button-retry-health"
              >
                <RefreshCw className="w-4 h-4 mr-2" />
                Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : health ? (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card>
              <CardContent className="p-5">
                <p className="text-xs text-muted-foreground mb-1">Overall Status</p>
                <div className="flex items-center gap-2">
                  {health.status === "ok" ? (
                    <CheckCircle className="w-5 h-5 text-emerald-500" />
                  ) : (
                    <XCircle className="w-5 h-5 text-red-500" />
                  )}
                  <span className="text-lg font-semibold capitalize" data-testid="text-overall-status">
                    {health.status === "ok" ? "Operational" : health.status}
                  </span>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <p className="text-xs text-muted-foreground mb-1">Uptime</p>
                <div className="flex items-center gap-2">
                  <Clock className="w-5 h-5 text-muted-foreground" />
                  <span className="text-lg font-semibold" data-testid="text-uptime">
                    {formatUptime(health.uptime)}
                  </span>
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-5">
                <p className="text-xs text-muted-foreground mb-1">Version</p>
                <div className="flex items-center gap-2">
                  <Server className="w-5 h-5 text-muted-foreground" />
                  <span className="text-lg font-semibold font-mono" data-testid="text-version">
                    {health.version}
                  </span>
                </div>
              </CardContent>
            </Card>
          </div>

          <div>
            <h2 className="text-base font-medium mb-3">Services</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <ServiceCard
                title="Database"
                description="PostgreSQL persistence layer"
                status={health.services.database}
                icon={Database}
                iconClass="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
              />
              <ServiceCard
                title="Tier 1 - Policy"
                description="Policy gate and routing engine"
                status={health.services.tier1}
                icon={Layers}
                iconClass="bg-primary/10 text-primary dark:bg-primary/20"
              />
              <ServiceCard
                title="Tier 2 - Execution"
                description="Validation and execution engine"
                status={health.services.tier2}
                icon={Activity}
                iconClass="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
              />
              <ServiceCard
                title="GCC Memory"
                description="Shared context contract store"
                status={health.services.gccMemory}
                icon={Shield}
                iconClass="bg-purple-100 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400"
              />
            </div>
          </div>

          <div>
            <h2 className="text-base font-medium mb-3">System Checks</h2>
            <Card>
              <CardContent className="p-5">
                <div className="space-y-3">
                  {[
                    { label: "API Endpoint", key: "api" as const },
                    { label: "Database Connection", key: "database" as const },
                    { label: "Orchestration Pipeline", key: "orchestration" as const },
                    { label: "Schema Validation", key: "schemaValidation" as const },
                  ].map((check) => (
                    <div key={check.key} className="flex items-center justify-between">
                      <span className="text-sm">{check.label}</span>
                      <div className="flex items-center gap-1.5">
                        {health.checks[check.key] ? (
                          <>
                            <CheckCircle className="w-4 h-4 text-emerald-500" />
                            <span className="text-xs text-emerald-600 dark:text-emerald-400">Pass</span>
                          </>
                        ) : (
                          <>
                            <XCircle className="w-4 h-4 text-red-500" />
                            <span className="text-xs text-red-600 dark:text-red-400">Fail</span>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </div>

          <p className="text-xs text-muted-foreground">
            Last checked: {new Date(health.timestamp).toLocaleString()} &middot; Auto-refreshes every 30s
          </p>
        </div>
      ) : null}
    </div>
  );
}

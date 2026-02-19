import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Layers,
  Activity,
  ArrowDown,
  ArrowUp,
  Shield,
  Database,
  AlertTriangle,
  CheckCircle,
  XCircle,
  FileJson,
} from "lucide-react";

function FlowStep({
  step,
  title,
  description,
  icon: Icon,
  iconClass,
  showArrow = true,
}: {
  step: number;
  title: string;
  description: string;
  icon: typeof Layers;
  iconClass: string;
  showArrow?: boolean;
}) {
  return (
    <div className="flex flex-col items-center">
      <div className="flex items-center gap-3 w-full max-w-xs">
        <div className={`flex items-center justify-center w-10 h-10 rounded-md flex-shrink-0 ${iconClass}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-muted-foreground">Step {step}</span>
          </div>
          <p className="text-sm font-medium">{title}</p>
          <p className="text-xs text-muted-foreground">{description}</p>
        </div>
      </div>
      {showArrow && (
        <div className="py-2">
          <ArrowDown className="w-4 h-4 text-muted-foreground/50" />
        </div>
      )}
    </div>
  );
}

export default function Architecture() {
  usePageTitle("Tier Overview");
  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-architecture-title">
          Tier Overview
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          AIDEN_PTIB 2-tier orchestration architecture and request lifecycle
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary dark:bg-primary/20">
                <Layers className="w-5 h-5" />
              </div>
              <div>
                <CardTitle className="text-base font-medium">Tier 1 - Manager</CardTitle>
                <p className="text-xs text-muted-foreground">Policy, Approvals, Routing</p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              {[
                "Receives incoming work orders from API",
                "Applies policy gate checks (mode, rules)",
                "Routes to appropriate Tier 2 handler",
                "Handles BDM markers returned from Tier 2",
                "Resolves or pauses for human decision",
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                  <CheckCircle className="w-3.5 h-3.5 text-primary mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-muted-foreground">{item}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-9 h-9 rounded-md bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400">
                <Activity className="w-5 h-5" />
              </div>
              <div>
                <CardTitle className="text-base font-medium">Tier 2 - Worker</CardTitle>
                <p className="text-xs text-muted-foreground">Validation, Execution</p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              {[
                "Validates work order schema",
                "Executes the actual work order tasks",
                "Emits BDM marker if blocked",
                "Returns results back to Tier 1",
                "No direct Tier 2 to Tier 2 chaining",
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-muted-foreground">{item}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base font-medium">Request Lifecycle</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col items-center py-4">
            <FlowStep
              step={1}
              title="API Ingestion"
              description="Work order enters the system via API"
              icon={Database}
              iconClass="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
            />
            <FlowStep
              step={2}
              title="Tier 1 Policy Gate"
              description="Checks mode, applies rules"
              icon={Layers}
              iconClass="bg-primary/10 text-primary dark:bg-primary/20"
            />
            <FlowStep
              step={3}
              title="Tier 1 Dispatch"
              description="Routes to appropriate Tier 2 handler"
              icon={Shield}
              iconClass="bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400"
            />
            <FlowStep
              step={4}
              title="Tier 2 Validation & Execution"
              description="Schema validation, then execute"
              icon={Activity}
              iconClass="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
            />
            <FlowStep
              step={5}
              title="Result / BDM"
              description="Complete or emit blocked decision marker"
              icon={AlertTriangle}
              iconClass="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
            />
            <FlowStep
              step={6}
              title="Resolution"
              description="Tier 1 resolves or pauses for human decision"
              icon={CheckCircle}
              iconClass="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
              showArrow={false}
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <Shield className="w-5 h-5 text-purple-600 dark:text-purple-400" />
              <CardTitle className="text-base font-medium">GCC Memory Contract</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Approved Uses</p>
              <div className="space-y-1.5">
                {["Routing context", "Correlation IDs", "Execution breadcrumbs"].map((item) => (
                  <div key={item} className="flex items-center gap-2">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                    <span className="text-sm text-muted-foreground">{item}</span>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Prohibited Uses</p>
              <div className="space-y-1.5">
                {["Secrets", "Huge raw payload dumps", "Hidden side effects"].map((item) => (
                  <div key={item} className="flex items-center gap-2">
                    <XCircle className="w-3 h-3 text-red-500" />
                    <span className="text-sm text-muted-foreground">{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <AlertTriangle className="w-5 h-5 text-amber-600 dark:text-amber-400" />
              <CardTitle className="text-base font-medium">Hard Rules</CardTitle>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              {[
                { rule: "Keep 2-tier boundary", desc: "Tier 1 orchestrates, Tier 2 executes" },
                { rule: "No Tier 2 to Tier 2 chaining", desc: "All routing goes through Tier 1" },
                { rule: "PocketFlow as orchestration engine", desc: "Core flow engine cannot be replaced" },
                { rule: "GCC memory contract", desc: "Shared context with strict usage rules" },
                { rule: "Schema validation", desc: "Work order and BDM schemas must validate" },
              ].map((item, i) => (
                <div key={i} className="p-3 rounded-md bg-muted/40">
                  <p className="text-sm font-medium">{item.rule}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{item.desc}</p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

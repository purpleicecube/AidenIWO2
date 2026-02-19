import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  ArrowDown,
  Shield,
  Database,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Brain,
  Bot,
  UserCheck,
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
  icon: typeof Brain;
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
          Aiden (Tier 1) orchestrates sub-agents (Tier 2) in a 2-tier architecture
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary dark:bg-primary/20">
                <Brain className="w-5 h-5" />
              </div>
              <div>
                <CardTitle className="text-base font-medium">Tier 1 — Aiden (Manager)</CardTitle>
                <p className="text-xs text-muted-foreground">LLM-powered policy, approvals, routing</p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              {[
                "Receives incoming work orders from API",
                "Evaluates against policy rules (LLM or hardcoded)",
                "Routes to the appropriate sub-agent (Tier 2)",
                "Handles BDM markers returned from sub-agents",
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
                <Bot className="w-5 h-5" />
              </div>
              <div>
                <CardTitle className="text-base font-medium">Tier 2 — Sub-Agents (Workers)</CardTitle>
                <p className="text-xs text-muted-foreground">Validation, execution, specialized tasks</p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              {[
                "Validates work order schema",
                "Executes the actual work order tasks",
                "Emits BDM marker if execution is blocked",
                "Returns results back to Aiden (Tier 1)",
                "No direct sub-agent to sub-agent chaining",
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                  <CheckCircle className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-muted-foreground">{item}</p>
                </div>
              ))}
            </div>
            <div className="pt-2 border-t">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Control Modes</p>
              <div className="space-y-2">
                <div className="flex items-center gap-2 p-2 rounded-md bg-muted/40">
                  <Brain className="w-4 h-4 text-primary flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium">Aiden-controlled</p>
                    <p className="text-xs text-muted-foreground">Aiden executes through the sub-agent automatically</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 p-2 rounded-md bg-muted/40">
                  <UserCheck className="w-4 h-4 text-violet-600 dark:text-violet-400 flex-shrink-0" />
                  <div>
                    <p className="text-sm font-medium">Independent</p>
                    <p className="text-xs text-muted-foreground">Authorized human or AI operator executes independently</p>
                  </div>
                </div>
              </div>
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
              title="Aiden: Policy Gate"
              description="Aiden evaluates policy rules (LLM or hardcoded)"
              icon={Brain}
              iconClass="bg-primary/10 text-primary dark:bg-primary/20"
            />
            <FlowStep
              step={3}
              title="Aiden: Dispatch to Sub-Agent"
              description="Aiden selects and routes to the best sub-agent"
              icon={Shield}
              iconClass="bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400"
            />
            <FlowStep
              step={4}
              title="Sub-Agent: Execution"
              description="Aiden-controlled or awaiting independent operator"
              icon={Bot}
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
              title="Aiden: Resolution"
              description="Aiden confirms completion or pauses for human decision"
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
                {["Routing context", "Correlation IDs", "Execution breadcrumbs", "Sub-agent assignments"].map((item) => (
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
                { rule: "Aiden IS Tier 1", desc: "All policy and routing decisions go through Aiden" },
                { rule: "Sub-agents are Tier 2", desc: "Workers execute under Aiden's direction or independently" },
                { rule: "No sub-agent to sub-agent chaining", desc: "All routing goes through Aiden (Tier 1)" },
                { rule: "System Admin controls sub-agents", desc: "Humans determine control mode and operator assignments" },
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

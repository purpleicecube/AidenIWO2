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
  ClipboardList,
  GitMerge,
  RotateCcw,
  FileCheck,
  Cog,
  FileText,
  ExternalLink,
} from "lucide-react";

function FlowStep({
  step,
  title,
  description,
  icon: Icon,
  iconClass,
  showArrow = true,
  badge,
}: {
  step: number;
  title: string;
  description: string;
  icon: typeof Brain;
  iconClass: string;
  showArrow?: boolean;
  badge?: { label: string; className: string };
}) {
  return (
    <div className="flex flex-col items-center">
      <div className="flex items-center gap-3 w-full max-w-sm">
        <div className={`flex items-center justify-center w-10 h-10 rounded-md flex-shrink-0 ${iconClass}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-muted-foreground">Step {step}</span>
            {badge && (
              <Badge variant="outline" className={`text-[10px] px-1.5 py-0 h-4 ${badge.className}`}>
                {badge.label}
              </Badge>
            )}
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
          Aiden (Tier 1) orchestrates through an optional PM layer (Tier 1.5) and sub-agents (Tier 2)
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary dark:bg-primary/20">
                <Brain className="w-5 h-5" />
              </div>
              <div>
                <CardTitle className="text-base font-medium">Tier 1 — Aiden (Executive)</CardTitle>
                <p className="text-xs text-muted-foreground">Policy, approvals, routing, final review</p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-2">
              {[
                "Receives incoming work orders from API",
                "Evaluates against policy rules (LLM or hardcoded)",
                "Routes to PM (Tier 1.5) or sub-agent (Tier 2)",
                "Handles BDM markers and escalations",
                "Performs executive review of final deliverables",
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

        <Card className="border-amber-200 dark:border-amber-800/50">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="flex items-center justify-center w-9 h-9 rounded-md bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400">
                <ClipboardList className="w-5 h-5" />
              </div>
              <div>
                <CardTitle className="text-base font-medium">
                  Tier 1.5 — PM (Coordinator)
                </CardTitle>
                <p className="text-xs text-muted-foreground">Workflow orchestration, step coordination</p>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              {[
                "Breaks workflows into a series of linked work orders",
                "Dispatches each work order to the appropriate worker sub-agent",
                "Reviews work order outputs against workflow goals",
                "Requests revisions from workers if quality is low",
                "Assembles all work order outputs into a final deliverable",
                "Escalates to Aiden (Tier 1) on unresolvable failures",
              ].map((item, i) => (
                <div key={i} className="flex items-start gap-2">
                  <CheckCircle className="w-3.5 h-3.5 text-amber-500 mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-muted-foreground">{item}</p>
                </div>
              ))}
            </div>
            <div className="pt-2 border-t">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-2">Step Types</p>
              <div className="space-y-2">
                <div className="flex items-center gap-2 p-2 rounded-md bg-muted/40">
                  <Cog className="w-4 h-4 text-muted-foreground flex-shrink-0" />
                  <div>
                    <p className="text-xs font-medium">Internal</p>
                    <p className="text-[11px] text-muted-foreground">PM handles directly or dispatches to a worker — no formal work order</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 p-2 rounded-md bg-blue-50 dark:bg-blue-900/20">
                  <FileText className="w-4 h-4 text-blue-600 dark:text-blue-400 flex-shrink-0" />
                  <div>
                    <p className="text-xs font-medium">Work Order</p>
                    <p className="text-[11px] text-muted-foreground">Creates a linked child work order through the full Aiden pipeline</p>
                  </div>
                </div>
                <div className="flex items-center gap-2 p-2 rounded-md bg-purple-50 dark:bg-purple-900/20">
                  <ExternalLink className="w-4 h-4 text-purple-600 dark:text-purple-400 flex-shrink-0" />
                  <div>
                    <p className="text-xs font-medium">External</p>
                    <p className="text-[11px] text-muted-foreground">Placeholder for work outside AIDEN_IWO — pauses until marked complete</p>
                  </div>
                </div>
              </div>
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
                "Executes tasks via PocketFlow engine",
                "Emits BDM marker if execution is blocked",
                "Returns results to PM (1.5) or Aiden (Tier 1)",
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium">Simple Work Order Lifecycle</CardTitle>
            <p className="text-xs text-muted-foreground">Single-step work orders — bypasses Tier 1.5</p>
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
                badge={{ label: "Tier 1", className: "border-primary/30 text-primary" }}
              />
              <FlowStep
                step={3}
                title="Aiden: Dispatch to Sub-Agent"
                description="Aiden selects and routes to the best sub-agent"
                icon={Shield}
                iconClass="bg-indigo-100 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400"
                badge={{ label: "Tier 1", className: "border-primary/30 text-primary" }}
              />
              <FlowStep
                step={4}
                title="Sub-Agent: Execution"
                description="PocketFlow iterative execution with tools"
                icon={Bot}
                iconClass="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
                badge={{ label: "Tier 2", className: "border-emerald-500/30 text-emerald-600 dark:text-emerald-400" }}
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
                badge={{ label: "Tier 1", className: "border-primary/30 text-primary" }}
                showArrow={false}
              />
            </div>
          </CardContent>
        </Card>

        <Card className="border-amber-200/50 dark:border-amber-800/30">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-medium">Workflow Lifecycle</CardTitle>
            <p className="text-xs text-muted-foreground">A series of linked work orders orchestrated by the PM via Tier 1.5</p>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col items-center py-4">
              <FlowStep
                step={1}
                title="API Ingestion"
                description="Workflow work order enters the system via API"
                icon={Database}
                iconClass="bg-blue-100 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400"
              />
              <FlowStep
                step={2}
                title="Aiden: Policy Gate & Routing"
                description="Aiden evaluates policy and routes work order to PM sub-agent"
                icon={Brain}
                iconClass="bg-primary/10 text-primary dark:bg-primary/20"
                badge={{ label: "Tier 1", className: "border-primary/30 text-primary" }}
              />
              <FlowStep
                step={3}
                title="PM: Work Order Dispatch"
                description="PM breaks workflow into linked work orders and dispatches next to worker agent"
                icon={ClipboardList}
                iconClass="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
                badge={{ label: "Tier 1.5", className: "border-amber-500/30 text-amber-600 dark:text-amber-400" }}
              />
              <FlowStep
                step={4}
                title="Worker: Work Order Execution"
                description="Worker agent executes individual work order via PocketFlow with tools"
                icon={Bot}
                iconClass="bg-emerald-100 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400"
                badge={{ label: "Tier 2", className: "border-emerald-500/30 text-emerald-600 dark:text-emerald-400" }}
              />
              <FlowStep
                step={5}
                title="PM: Review & Revise"
                description="PM reviews work order output, requests revisions if needed"
                icon={RotateCcw}
                iconClass="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
                badge={{ label: "Tier 1.5", className: "border-amber-500/30 text-amber-600 dark:text-amber-400" }}
              />
              <FlowStep
                step={6}
                title="PM: Assemble Work Product"
                description="PM synthesizes all completed work order outputs into final deliverable"
                icon={GitMerge}
                iconClass="bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
                badge={{ label: "Tier 1.5", className: "border-amber-500/30 text-amber-600 dark:text-amber-400" }}
              />
              <FlowStep
                step={7}
                title="Aiden: Executive Review"
                description="Aiden reviews PM's assembled work product for final approval"
                icon={FileCheck}
                iconClass="bg-primary/10 text-primary dark:bg-primary/20"
                badge={{ label: "Tier 1", className: "border-primary/30 text-primary" }}
                showArrow={false}
              />
            </div>
          </CardContent>
        </Card>
      </div>

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
                {["Routing context", "Correlation IDs", "Execution breadcrumbs", "Sub-agent assignments", "PM coordination state"].map((item) => (
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
                { rule: "Aiden IS Tier 1", desc: "All policy, routing, and final review decisions go through Aiden" },
                { rule: "PM IS Tier 1.5", desc: "PM coordinates workflow steps but cannot override Aiden's policy decisions" },
                { rule: "Sub-agents are Tier 2", desc: "Workers execute under Aiden's or PM's direction, or independently" },
                { rule: "No sub-agent to sub-agent chaining", desc: "All routing goes through Aiden (Tier 1) or PM (Tier 1.5)" },
                { rule: "PM escalates to Aiden", desc: "Unresolvable failures escalate up, never down to other sub-agents" },
                { rule: "Executive review is mandatory", desc: "Aiden performs final quality review on all PM-assembled deliverables" },
                { rule: "GCC memory contract", desc: "Shared context with strict usage rules across all tiers" },
                { rule: "Schema validation", desc: "Work order and BDM schemas must validate at every tier boundary" },
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

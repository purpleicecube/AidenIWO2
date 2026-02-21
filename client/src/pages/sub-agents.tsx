import { useQuery, useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/hooks/use-toast";
import { usePageTitle } from "@/hooks/use-page-title";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { Bot, Plus, Pencil, Trash2, Loader2, Brain, UserCheck, Cpu, CheckCircle2, XCircle, AlertTriangle, Zap, Lock, Wrench, Clock, ArrowUpRight, ArrowDownLeft } from "lucide-react";
import { ModelSelector, providers } from "@/components/model-selector";
import type { SubAgent, ToolLease, Tool } from "@shared/schema";

const subAgentFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  type: z.string().min(1, "Type is required"),
  controlMode: z.string().min(1, "Control mode is required"),
  assignedTo: z.string().nullable().optional(),
  status: z.string().min(1, "Status is required"),
  description: z.string().nullable().optional(),
  llmEnabled: z.boolean().optional().default(true),
  llmProvider: z.string().nullable().optional(),
  llmModel: z.string().nullable().optional(),
  llmBaseUrl: z.string().nullable().optional(),
  llmSystemPrompt: z.string().nullable().optional(),
  llmApiKeyEnvVar: z.string().nullable().optional(),
}).refine(
  (data) => !data.llmEnabled || (data.llmProvider && data.llmProvider.length > 0),
  { message: "Provider is required when LLM is enabled", path: ["llmProvider"] }
).refine(
  (data) => !data.llmEnabled || (data.llmModel && data.llmModel.length > 0),
  { message: "Model is required when LLM is enabled", path: ["llmModel"] }
);

type SubAgentForm = z.infer<typeof subAgentFormSchema>;

interface LlmStatus {
  status: string;
  llmReady: boolean;
  aidenDirected: boolean;
  source?: string;
  provider?: string;
  model?: string;
  reason?: string;
}

function OperationalBadge({ agentId }: { agentId: string }) {
  const { data: llmStatus, isLoading } = useQuery<LlmStatus>({
    queryKey: ["/api/sub-agents", agentId, "llm-status"],
    queryFn: async () => {
      const res = await fetch(`/api/sub-agents/${agentId}/llm-status`);
      return res.json();
    },
  });

  if (isLoading || !llmStatus) return null;

  const isOperational = llmStatus.llmReady && llmStatus.aidenDirected;
  const isReady = llmStatus.llmReady && !llmStatus.aidenDirected;
  const isMissing = llmStatus.status === "missing_key";
  const isNoLlm = llmStatus.status === "no_llm";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div
          className={`flex items-center gap-1 text-xs font-medium ${
            isOperational
              ? "text-emerald-600 dark:text-emerald-400"
              : isReady
              ? "text-blue-600 dark:text-blue-400"
              : isMissing
              ? "text-amber-600 dark:text-amber-400"
              : "text-muted-foreground"
          }`}
          data-testid={`operational-status-${agentId}`}
        >
          {isOperational ? (
            <><CheckCircle2 className="w-3.5 h-3.5" /> Operational</>
          ) : isReady ? (
            <><CheckCircle2 className="w-3.5 h-3.5" /> LLM Ready</>
          ) : isMissing ? (
            <><AlertTriangle className="w-3.5 h-3.5" /> Key Missing</>
          ) : isNoLlm ? (
            <><XCircle className="w-3.5 h-3.5" /> No LLM</>
          ) : (
            <><XCircle className="w-3.5 h-3.5" /> Offline</>
          )}
        </div>
      </TooltipTrigger>
      <TooltipContent>
        <p className="text-xs max-w-[250px]">{llmStatus.reason || "Unknown status"}</p>
        {llmStatus.source && (
          <p className="text-xs text-muted-foreground mt-0.5">Source: {llmStatus.source}</p>
        )}
      </TooltipContent>
    </Tooltip>
  );
}

function ToolActivityBadge({ agentId }: { agentId: string }) {
  const { data: leases } = useQuery<ToolLease[]>({
    queryKey: [`/api/locker/leases?agentId=${agentId}&status=active`],
  });

  if (!leases || leases.length === 0) return null;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="flex items-center gap-1 text-xs font-medium text-orange-600 dark:text-orange-400" data-testid={`tool-activity-badge-${agentId}`}>
          <Wrench className="w-3.5 h-3.5" />
          {leases.length} tool{leases.length > 1 ? "s" : ""} active
        </div>
      </TooltipTrigger>
      <TooltipContent>
        <p className="text-xs">{leases.length} tool{leases.length > 1 ? "s" : ""} currently checked out</p>
      </TooltipContent>
    </Tooltip>
  );
}

function formatTimeAgo(date: string | Date) {
  const now = new Date();
  const d = new Date(date);
  const seconds = Math.floor((now.getTime() - d.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function ToolActivitySection({ agentId }: { agentId: string }) {
  const { data: allLeases, isLoading } = useQuery<ToolLease[]>({
    queryKey: [`/api/locker/leases?agentId=${agentId}`],
  });

  const { data: tools } = useQuery<Tool[]>({
    queryKey: ["/api/tools"],
  });

  const toolMap = new Map<string, Tool>();
  tools?.forEach(t => toolMap.set(t.id, t));

  const activeLeases = allLeases?.filter(l => l.status === "active") || [];
  const recentLeases = allLeases?.filter(l => l.status !== "active").slice(0, 5) || [];

  if (isLoading) {
    return (
      <div className="border rounded-md p-4">
        <div className="flex items-center gap-2 mb-3">
          <Wrench className="w-4 h-4" />
          <span className="text-sm font-medium">Tool Activity</span>
        </div>
        <div className="flex items-center justify-center py-3">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  return (
    <div className="border rounded-md p-4 space-y-3" data-testid="section-tool-activity">
      <div className="flex items-center gap-2">
        <Wrench className="w-4 h-4" />
        <span className="text-sm font-medium">Tool Activity</span>
        {activeLeases.length > 0 && (
          <Badge variant="outline" className="border-transparent bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 no-default-hover-elevate no-default-active-elevate text-xs">
            {activeLeases.length} active
          </Badge>
        )}
      </div>

      {activeLeases.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Currently Using</p>
          {activeLeases.map(lease => {
            const tool = toolMap.get(lease.toolId);
            return (
              <div key={lease.id} className="flex items-center gap-2 p-2 rounded-md bg-orange-50 dark:bg-orange-900/10 border border-orange-200/50 dark:border-orange-800/30" data-testid={`active-lease-${lease.id}`}>
                <ArrowUpRight className="w-3.5 h-3.5 text-orange-500 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{tool?.name || lease.toolId}</p>
                  <p className="text-[10px] text-muted-foreground">
                    Checked out {formatTimeAgo(lease.issuedAt)} · Expires {lease.expiresAt ? formatTimeAgo(lease.expiresAt) : "never"}
                  </p>
                </div>
                <Badge variant="outline" className="border-transparent bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 no-default-hover-elevate no-default-active-elevate text-[10px] h-5">
                  active
                </Badge>
              </div>
            );
          })}
        </div>
      )}

      {recentLeases.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Recent History</p>
          {recentLeases.map(lease => {
            const tool = toolMap.get(lease.toolId);
            const isReturned = lease.status === "returned";
            const isExpired = lease.status === "expired";
            return (
              <div key={lease.id} className="flex items-center gap-2 p-2 rounded-md bg-muted/50" data-testid={`recent-lease-${lease.id}`}>
                <ArrowDownLeft className={`w-3.5 h-3.5 flex-shrink-0 ${isReturned ? "text-emerald-500" : isExpired ? "text-amber-500" : "text-red-500"}`} />
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium truncate">{tool?.name || lease.toolId}</p>
                  <p className="text-[10px] text-muted-foreground">
                    {isReturned ? "Returned" : isExpired ? "Expired" : lease.status} {lease.returnedAt ? formatTimeAgo(lease.returnedAt) : formatTimeAgo(lease.issuedAt)}
                  </p>
                </div>
                <Badge
                  variant="outline"
                  className={`border-transparent no-default-hover-elevate no-default-active-elevate text-[10px] h-5 ${
                    isReturned ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                    : isExpired ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                    : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                  }`}
                >
                  {lease.status}
                </Badge>
              </div>
            );
          })}
        </div>
      )}

      {activeLeases.length === 0 && recentLeases.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-2">No tool activity recorded</p>
      )}
    </div>
  );
}

function AgentCard({ agent, onEdit, onDelete }: { agent: SubAgent; onEdit: (a: SubAgent) => void; onDelete: (id: string) => void }) {
  return (
    <Card data-testid={`card-sub-agent-${agent.id}`}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary dark:bg-primary/20 flex-shrink-0 mt-0.5">
              <Bot className="w-4 h-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-sm font-medium">{agent.name}</p>
                <Badge
                  variant="outline"
                  className={`border-transparent no-default-hover-elevate no-default-active-elevate ${
                    agent.status === "active"
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                      : agent.status === "maintenance"
                      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                      : "bg-muted text-muted-foreground"
                  }`}
                  data-testid={`badge-agent-status-${agent.id}`}
                >
                  {agent.status}
                </Badge>
                <OperationalBadge agentId={agent.id} />
                <ToolActivityBadge agentId={agent.id} />
              </div>
              {agent.description && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{agent.description}</p>
              )}
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="font-medium">Type:</span> {agent.type}
                </div>
                <div className="flex items-center gap-1.5 text-xs">
                  {agent.controlMode === "aiden" ? (
                    <>
                      <Brain className="w-3 h-3 text-primary" />
                      <span className="text-primary font-medium">Aiden-controlled</span>
                    </>
                  ) : (
                    <>
                      <UserCheck className="w-3 h-3 text-violet-600 dark:text-violet-400" />
                      <span className="text-violet-600 dark:text-violet-400 font-medium">Independent</span>
                      {agent.assignedTo && (
                        <span className="text-muted-foreground">({agent.assignedTo})</span>
                      )}
                    </>
                  )}
                </div>
                {agent.llmEnabled && agent.llmProvider && (
                  <div className="flex items-center gap-1.5 text-xs" data-testid={`llm-indicator-${agent.id}`}>
                    <Cpu className="w-3 h-3 text-cyan-600 dark:text-cyan-400" />
                    <span className="text-cyan-600 dark:text-cyan-400 font-medium">
                      {agent.llmProvider}/{agent.llmModel}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            <Button size="icon" variant="ghost" onClick={() => onEdit(agent)} data-testid={`button-edit-agent-${agent.id}`}>
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            <Button size="icon" variant="ghost" onClick={() => onDelete(agent.id)} data-testid={`button-delete-agent-${agent.id}`}>
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function SubAgentsPage() {
  usePageTitle("Sub-Agents");
  const { toast } = useToast();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingAgent, setEditingAgent] = useState<SubAgent | null>(null);
  const [testResult, setTestResult] = useState<{ operational: boolean; message?: string; reason?: string; source?: string; provider?: string; model?: string } | null>(null);
  const [testingLlm, setTestingLlm] = useState(false);

  const { data: agents, isLoading } = useQuery<SubAgent[]>({
    queryKey: ["/api/sub-agents"],
  });

  const form = useForm<SubAgentForm>({
    resolver: zodResolver(subAgentFormSchema),
    defaultValues: {
      name: "",
      type: "general",
      controlMode: "aiden",
      assignedTo: null,
      status: "active",
      description: null,
      llmEnabled: true,
      llmProvider: "groq",
      llmModel: "llama-3.3-70b-versatile",
      llmBaseUrl: null,
      llmSystemPrompt: null,
      llmApiKeyEnvVar: "GROQ_API_KEY",
    },
  });

  const watchControlMode = form.watch("controlMode");
  const watchLlmEnabled = form.watch("llmEnabled");
  const watchLlmProvider = form.watch("llmProvider");

  const createMutation = useMutation({
    mutationFn: (values: SubAgentForm) =>
      apiRequest("POST", "/api/sub-agents", values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/sub-agents"] });
      toast({ title: "Sub-agent created" });
      setDialogOpen(false);
      form.reset();
    },
    onError: (err: any) => {
      toast({ title: "Failed to create sub-agent", description: err.message, variant: "destructive" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: SubAgentForm) =>
      apiRequest("PUT", `/api/sub-agents/${editingAgent?.id}`, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/sub-agents"] });
      toast({ title: "Sub-agent updated" });
      setDialogOpen(false);
      setEditingAgent(null);
      form.reset();
    },
    onError: (err: any) => {
      toast({ title: "Failed to update sub-agent", description: err.message, variant: "destructive" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest("DELETE", `/api/sub-agents/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/sub-agents"] });
      toast({ title: "Sub-agent removed" });
    },
    onError: (err: any) => {
      toast({ title: "Failed to delete", description: err.message, variant: "destructive" });
    },
  });

  function openCreate() {
    setEditingAgent(null);
    setTestResult(null);
    form.reset({
      name: "",
      type: "general",
      controlMode: "aiden",
      assignedTo: null,
      status: "active",
      description: null,
      llmEnabled: true,
      llmProvider: "groq",
      llmModel: "llama-3.3-70b-versatile",
      llmBaseUrl: null,
      llmSystemPrompt: null,
      llmApiKeyEnvVar: "GROQ_API_KEY",
    });
    setDialogOpen(true);
  }

  function openEdit(agent: SubAgent) {
    setEditingAgent(agent);
    setTestResult(null);
    form.reset({
      name: agent.name,
      type: agent.type,
      controlMode: agent.controlMode,
      assignedTo: agent.assignedTo,
      status: agent.status,
      description: agent.description,
      llmEnabled: agent.llmEnabled ?? false,
      llmProvider: agent.llmProvider,
      llmModel: agent.llmModel,
      llmBaseUrl: agent.llmBaseUrl,
      llmSystemPrompt: agent.llmSystemPrompt,
      llmApiKeyEnvVar: agent.llmApiKeyEnvVar,
    });
    setDialogOpen(true);
  }

  function onSubmit(values: SubAgentForm) {
    if (editingAgent) {
      updateMutation.mutate(values);
    } else {
      createMutation.mutate(values);
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-sub-agents-title">
            Sub-Agents
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Tier 2 workers that execute work orders under Aiden's direction or independently.
          </p>
        </div>
        <Button onClick={openCreate} data-testid="button-create-agent">
          <Plus className="w-4 h-4 mr-2" />
          New Sub-Agent
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-md bg-muted/40 animate-pulse" />
          ))}
        </div>
      ) : agents && agents.length > 0 ? (
        <div className="space-y-3">
          {agents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onEdit={openEdit}
              onDelete={(id) => deleteMutation.mutate(id)}
            />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Bot className="w-12 h-12 text-muted-foreground/30 mb-4" />
            <p className="text-sm text-muted-foreground">No sub-agents configured</p>
            <p className="text-xs text-muted-foreground mt-1">
              Create sub-agents to handle Tier 2 work order execution
            </p>
            <Button className="mt-4" onClick={openCreate} data-testid="button-create-agent-empty">
              <Plus className="w-4 h-4 mr-2" />
              Create First Sub-Agent
            </Button>
          </CardContent>
        </Card>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingAgent ? "Edit Sub-Agent" : "Create Sub-Agent"}</DialogTitle>
          </DialogHeader>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="e.g. Deploy Worker Alpha" data-testid="input-agent-name" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={form.control}
                  name="type"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Type</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger data-testid="select-agent-type">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="general">General</SelectItem>
                          <SelectItem value="deployment">Deployment</SelectItem>
                          <SelectItem value="maintenance">Maintenance</SelectItem>
                          <SelectItem value="incident">Incident</SelectItem>
                          <SelectItem value="change_request">Change Request</SelectItem>
                          <SelectItem value="security">Security</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="status"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Status</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger data-testid="select-agent-status">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="active">Active</SelectItem>
                          <SelectItem value="inactive">Inactive</SelectItem>
                          <SelectItem value="maintenance">Maintenance</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="controlMode"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Control Mode</FormLabel>
                    <Select onValueChange={field.onChange} value={field.value}>
                      <FormControl>
                        <SelectTrigger data-testid="select-control-mode">
                          <SelectValue />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="aiden">Aiden-controlled (automatic)</SelectItem>
                        <SelectItem value="independent">Independent (human/AI operator)</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormDescription>
                      {field.value === "aiden"
                        ? "Aiden (Tier 1) will directly control and execute through this sub-agent."
                        : "An authorized operator will independently execute work orders assigned to this sub-agent."}
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {watchControlMode === "independent" && (
                <FormField
                  control={form.control}
                  name="assignedTo"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Assigned Operator</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          value={field.value || ""}
                          placeholder="e.g. ops-team, jsmith, ai-agent-3"
                          data-testid="input-assigned-to"
                        />
                      </FormControl>
                      <FormDescription>
                        The human or AI agent authorized to operate this sub-agent.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description (optional)</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value || ""}
                        placeholder="What does this sub-agent specialize in?"
                        className="resize-none"
                        data-testid="input-agent-description"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="border rounded-md p-4 space-y-4">
                <FormField
                  control={form.control}
                  name="llmEnabled"
                  render={({ field }) => (
                    <FormItem className="flex items-center justify-between gap-4">
                      <div className="space-y-0.5">
                        <FormLabel className="text-sm font-medium">Independent LLM</FormLabel>
                        <FormDescription className="text-xs">
                          Give this sub-agent its own LLM for Tier 2 execution instead of using Aiden's global model.
                        </FormDescription>
                      </div>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          data-testid="switch-llm-enabled"
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />

                {watchLlmEnabled && (
                  <>
                    <FormField
                      control={form.control}
                      name="llmProvider"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Provider</FormLabel>
                          <Select
                            onValueChange={(v) => {
                              field.onChange(v);
                              const prov = providers.find(p => p.value === v);
                              if (prov) {
                                form.setValue("llmModel", prov.defaultModel);
                                form.setValue("llmApiKeyEnvVar", prov.keyName);
                              }
                            }}
                            value={field.value || ""}
                          >
                            <FormControl>
                              <SelectTrigger data-testid="select-llm-provider">
                                <SelectValue placeholder="Select provider" />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              {providers.map((p) => (
                                <SelectItem key={p.value} value={p.value}>
                                  {p.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {watchLlmProvider && (
                      <FormField
                        control={form.control}
                        name="llmModel"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Model</FormLabel>
                            <FormControl>
                              <ModelSelector
                                provider={watchLlmProvider || ""}
                                value={field.value || ""}
                                onChange={field.onChange}
                                testIdPrefix="llm-"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    )}

                    {(() => {
                      const defaultKeyName = providers.find(p => p.value === watchLlmProvider)?.keyName || "";
                      const currentValue = form.watch("llmApiKeyEnvVar") || "";
                      const isDirectKey = currentValue && !/^[A-Z][A-Z0-9_]*$/.test(currentValue);
                      const maskedKey = isDirectKey ? currentValue.slice(0, 6) + "••••••" + currentValue.slice(-4) : "";
                      return (
                        <FormField
                          control={form.control}
                          name="llmApiKeyEnvVar"
                          render={({ field }) => (
                            <FormItem>
                              <FormLabel>API Key</FormLabel>
                              <div className="rounded-md bg-muted/50 p-3 space-y-2">
                                <div className="flex items-center gap-2">
                                  <div className="flex items-center gap-1.5 bg-background rounded-md border px-3 py-1.5 flex-1">
                                    <Lock className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                                    <span className="text-sm font-mono" data-testid="text-api-key-name">
                                      {isDirectKey ? maskedKey : (currentValue || defaultKeyName || "Not configured")}
                                    </span>
                                  </div>
                                  {isDirectKey && (
                                    <Button
                                      type="button"
                                      variant="outline"
                                      size="sm"
                                      onClick={() => form.setValue("llmApiKeyEnvVar", defaultKeyName)}
                                      data-testid="button-use-env-key"
                                    >
                                      Use env secret
                                    </Button>
                                  )}
                                </div>
                                <FormControl>
                                  <Input
                                    {...field}
                                    value={field.value || ""}
                                    placeholder={`Env var name (e.g. ${defaultKeyName}) or paste API key directly`}
                                    className="font-mono text-xs"
                                    data-testid="input-llm-api-key"
                                  />
                                </FormControl>
                                <p className="text-xs text-muted-foreground">
                                  {isDirectKey
                                    ? "Using a direct API key. This sub-agent will use its own key independently from Aiden."
                                    : <>Defaults to the <span className="font-mono font-medium">{defaultKeyName}</span> environment secret. You can also paste an API key directly.</>
                                  }
                                </p>
                              </div>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      );
                    })()}

                    <FormField
                      control={form.control}
                      name="llmBaseUrl"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Base URL (optional)</FormLabel>
                          <FormControl>
                            <Input
                              {...field}
                              value={field.value || ""}
                              placeholder="Custom API endpoint (leave blank for default)"
                              data-testid="input-llm-base-url"
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="llmSystemPrompt"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>System Prompt (optional)</FormLabel>
                          <FormControl>
                            <Textarea
                              {...field}
                              value={field.value || ""}
                              placeholder="Custom instructions for this sub-agent's LLM. Leave blank for auto-generated prompt based on the agent's name and type."
                              className="resize-none text-xs"
                              rows={3}
                              data-testid="input-llm-system-prompt"
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    {editingAgent && (
                      <div className="pt-2 space-y-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={testingLlm}
                          onClick={async () => {
                            if (!editingAgent) return;
                            setTestingLlm(true);
                            setTestResult(null);
                            try {
                              const res = await apiRequest("POST", `/api/sub-agents/${editingAgent.id}/test-llm`);
                              const result = await res.json();
                              setTestResult(result);
                              queryClient.invalidateQueries({ queryKey: ["/api/sub-agents", editingAgent.id, "llm-status"] });
                            } catch (err: any) {
                              setTestResult({ operational: false, reason: err.message });
                            } finally {
                              setTestingLlm(false);
                            }
                          }}
                          data-testid="button-test-llm-connection"
                        >
                          {testingLlm ? (
                            <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />
                          ) : (
                            <Zap className="w-3.5 h-3.5 mr-2" />
                          )}
                          Test Connection
                        </Button>
                        {testResult && (
                          <div
                            className={`flex items-start gap-2 p-2 rounded-md text-xs ${
                              testResult.operational
                                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-400"
                                : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-400"
                            }`}
                            data-testid="container-test-result"
                          >
                            {testResult.operational ? (
                              <CheckCircle2 className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                            ) : (
                              <XCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                            )}
                            <div>
                              <p className="font-medium">
                                {testResult.operational ? "Connection Successful" : "Connection Failed"}
                              </p>
                              <p className="mt-0.5">
                                {testResult.message || testResult.reason}
                              </p>
                              {testResult.source && (
                                <p className="text-muted-foreground mt-0.5">Source: {testResult.source}</p>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>

              {editingAgent && (
                <ToolActivitySection agentId={editingAgent.id} />
              )}

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={isPending} data-testid="button-save-agent">
                  {isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : null}
                  {editingAgent ? "Update" : "Create"}
                </Button>
              </div>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

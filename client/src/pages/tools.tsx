import { useQuery, useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
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
import { useToast } from "@/hooks/use-toast";
import { usePageTitle } from "@/hooks/use-page-title";
import { apiRequest, queryClient } from "@/lib/queryClient";
import {
  Terminal, Zap, Globe, Link2, Plus, Pencil, Trash2, Loader2, Wrench,
  Server, Code2, ShieldCheck, Key, FileCode, BookOpen, Settings2,
  ChevronRight, Eye, Lock, Unlock, X, AlertTriangle, Download, CheckCircle2, FileDown
} from "lucide-react";
import type { Tool } from "@shared/schema";

const toolTypes = [
  { value: "skill", label: "Claude Skill", icon: Zap, description: "Prompt-injected skill loaded into agent context (SKILL.md format)" },
  { value: "python_code", label: "Python Code", icon: Code2, description: "Sandboxed Python script executed in isolated environment" },
  { value: "slash_command", label: "Slash Command", icon: Terminal, description: "Agent-invokable slash command with structured input/output" },
  { value: "cli", label: "CLI Tool", icon: Terminal, description: "Command-line tool executed via shell" },
  { value: "api", label: "API Endpoint", icon: Globe, description: "External API endpoint with authentication" },
  { value: "webhook", label: "Webhook", icon: Link2, description: "Inbound/outbound webhook integration" },
  { value: "mcp_server", label: "MCP Server", icon: Server, description: "Model Context Protocol server providing tools/resources" },
] as const;

const toolFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  slug: z.string().min(2, "Slug must be at least 2 characters").regex(/^[a-z0-9-]+$/, "Lowercase letters, numbers, and hyphens only"),
  description: z.string().nullable().optional(),
  type: z.string().min(1, "Type is required"),
  category: z.string().min(1, "Category is required"),
  status: z.string().min(1, "Status is required"),
  version: z.string().min(1, "Version is required"),
  skillContent: z.string().nullable().optional(),
  skillInstructions: z.string().nullable().optional(),
  triggerConditions: z.any().optional(),
  executionMode: z.string().nullable().optional(),
  runtimeEnvironment: z.string().nullable().optional(),
  sourceCode: z.string().nullable().optional(),
  entryPoint: z.string().nullable().optional(),
  sandboxConfig: z.any().optional(),
  credentials: z.any().optional(),
  usageInstructions: z.string().nullable().optional(),
  mcpConfig: z.any().optional(),
  inputSchema: z.any().optional(),
  outputSchema: z.any().optional(),
  accessTier: z.string().optional(),
  maxConcurrent: z.number().optional(),
  defaultLeaseSeconds: z.number().optional(),
  maxLeaseSeconds: z.number().optional(),
  dailyUsageLimit: z.number().nullable().optional(),
  costCeilingPerDay: z.string().nullable().optional(),
  requiresApproval: z.boolean().optional(),
});

type ToolFormValues = z.infer<typeof toolFormSchema>;

function slugify(str: string): string {
  return str.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

const typeIcons: Record<string, typeof Terminal> = {
  slash_command: Terminal,
  skill: Zap,
  cli: Terminal,
  api: Globe,
  webhook: Link2,
  python_code: Code2,
  mcp_server: Server,
};

const typeLabels: Record<string, string> = {
  slash_command: "Slash Command",
  skill: "Claude Skill",
  cli: "CLI",
  api: "API",
  webhook: "Webhook",
  python_code: "Python Code",
  mcp_server: "MCP Server",
};

function ToolCard({ tool, onEdit, onDelete, onView }: { tool: Tool; onEdit: (t: Tool) => void; onDelete: (id: string) => void; onView: (t: Tool) => void }) {
  const TypeIcon = typeIcons[tool.type] || Wrench;
  const hasSkillContent = !!(tool as any).skillContent;
  const hasSourceCode = !!(tool as any).sourceCode;
  const hasCredentials = Array.isArray((tool as any).credentials) && (tool as any).credentials.length > 0;

  return (
    <Card data-testid={`card-tool-${tool.id}`} className="cursor-pointer transition-colors hover:bg-muted/30" onClick={() => onView(tool)}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary dark:bg-primary/20 flex-shrink-0 mt-0.5">
              <TypeIcon className="w-4 h-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-sm font-medium" data-testid={`text-tool-name-${tool.id}`}>{tool.name}</p>
                <Badge
                  variant="outline"
                  className={`border-transparent text-[10px] no-default-hover-elevate no-default-active-elevate ${
                    tool.status === "active"
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
                      : tool.status === "deprecated"
                      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                      : "bg-muted text-muted-foreground"
                  }`}
                  data-testid={`badge-tool-status-${tool.id}`}
                >
                  {tool.status}
                </Badge>
                {tool.restricted && (
                  <Badge variant="outline" className="border-transparent text-[10px] no-default-hover-elevate no-default-active-elevate bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400">
                    <Lock className="w-2.5 h-2.5 mr-1" />Restricted
                  </Badge>
                )}
              </div>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono" data-testid={`text-tool-slug-${tool.id}`}>{tool.slug}</p>
              {tool.description && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2" data-testid={`text-tool-description-${tool.id}`}>{tool.description}</p>
              )}
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <Badge variant="outline" className="border-transparent text-[10px] no-default-hover-elevate no-default-active-elevate bg-primary/10 text-primary dark:bg-primary/20" data-testid={`badge-tool-type-${tool.id}`}>
                  {typeLabels[tool.type] || tool.type}
                </Badge>
                <Badge variant="outline" className="border-transparent text-[10px] no-default-hover-elevate no-default-active-elevate bg-muted text-muted-foreground" data-testid={`badge-tool-category-${tool.id}`}>
                  {tool.category}
                </Badge>
                {hasSkillContent && <Badge variant="outline" className="border-transparent text-[10px] no-default-hover-elevate no-default-active-elevate bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400"><FileCode className="w-2.5 h-2.5 mr-1" />SKILL.md</Badge>}
                {hasSourceCode && <Badge variant="outline" className="border-transparent text-[10px] no-default-hover-elevate no-default-active-elevate bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400"><Code2 className="w-2.5 h-2.5 mr-1" />Code</Badge>}
                {hasCredentials && <Badge variant="outline" className="border-transparent text-[10px] no-default-hover-elevate no-default-active-elevate bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"><Key className="w-2.5 h-2.5 mr-1" />Creds</Badge>}
                <span className="text-[10px] text-muted-foreground">v{tool.version}</span>
                {tool.accessTier !== "any" && (
                  <span className="text-[10px] text-muted-foreground">Tier: {tool.accessTier}</span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0" onClick={(e) => e.stopPropagation()}>
            <Button size="icon" variant="ghost" onClick={() => onView(tool)} data-testid={`button-view-tool-${tool.id}`}>
              <Eye className="w-3.5 h-3.5" />
            </Button>
            <Button size="icon" variant="ghost" onClick={() => onEdit(tool)} data-testid={`button-edit-tool-${tool.id}`}>
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            <Button size="icon" variant="ghost" onClick={() => onDelete(tool.id)} data-testid={`button-delete-tool-${tool.id}`}>
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CredentialEditor({ value, onChange }: { value: any[]; onChange: (v: any[]) => void }) {
  const addCredential = () => {
    onChange([...value, { key: "", value: "", isSecret: true, description: "" }]);
  };

  const updateCredential = (index: number, field: string, val: string | boolean) => {
    const updated = [...value];
    updated[index] = { ...updated[index], [field]: val };
    onChange(updated);
  };

  const removeCredential = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-3">
      {value.map((cred: any, index: number) => (
        <div key={index} className="flex gap-2 items-start p-3 rounded-md border bg-muted/20">
          <div className="flex-1 space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs text-muted-foreground">Variable Name</Label>
                <Input
                  value={cred.key}
                  onChange={(e) => updateCredential(index, "key", e.target.value)}
                  placeholder="e.g. OPENAI_API_KEY"
                  className="font-mono text-xs h-8"
                  data-testid={`input-cred-key-${index}`}
                />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">Value / Reference</Label>
                <Input
                  value={cred.value}
                  onChange={(e) => updateCredential(index, "value", e.target.value)}
                  placeholder={cred.isSecret ? "env:OPENAI_API_KEY" : "https://api.example.com"}
                  className="font-mono text-xs h-8"
                  type={cred.isSecret ? "password" : "text"}
                  data-testid={`input-cred-value-${index}`}
                />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <Input
                value={cred.description || ""}
                onChange={(e) => updateCredential(index, "description", e.target.value)}
                placeholder="Description (e.g. OpenAI API key for GPT-4 access)"
                className="text-xs h-7 flex-1"
                data-testid={`input-cred-desc-${index}`}
              />
              <div className="flex items-center gap-1.5">
                <Switch
                  checked={cred.isSecret}
                  onCheckedChange={(checked) => updateCredential(index, "isSecret", checked)}
                  data-testid={`switch-cred-secret-${index}`}
                />
                <Label className="text-[10px] text-muted-foreground whitespace-nowrap">
                  {cred.isSecret ? "Secret" : "Plain"}
                </Label>
              </div>
            </div>
          </div>
          <Button size="icon" variant="ghost" className="h-7 w-7 flex-shrink-0 mt-4" onClick={() => removeCredential(index)} data-testid={`button-remove-cred-${index}`}>
            <X className="w-3 h-3" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={addCredential} data-testid="button-add-credential">
        <Plus className="w-3 h-3 mr-1" />Add Credential / Env Var
      </Button>
    </div>
  );
}

function TriggerConditionEditor({ value, onChange }: { value: any[]; onChange: (v: any[]) => void }) {
  const addTrigger = () => {
    onChange([...value, { pattern: "", description: "" }]);
  };

  const updateTrigger = (index: number, field: string, val: string) => {
    const updated = [...value];
    updated[index] = { ...updated[index], [field]: val };
    onChange(updated);
  };

  const removeTrigger = (index: number) => {
    onChange(value.filter((_, i) => i !== index));
  };

  return (
    <div className="space-y-2">
      {value.map((trigger: any, index: number) => (
        <div key={index} className="flex gap-2 items-center">
          <Input
            value={trigger.pattern}
            onChange={(e) => updateTrigger(index, "pattern", e.target.value)}
            placeholder="e.g. when user mentions PDFs"
            className="text-xs h-8 flex-1"
            data-testid={`input-trigger-pattern-${index}`}
          />
          <Input
            value={trigger.description || ""}
            onChange={(e) => updateTrigger(index, "description", e.target.value)}
            placeholder="Description"
            className="text-xs h-8 flex-1"
            data-testid={`input-trigger-desc-${index}`}
          />
          <Button size="icon" variant="ghost" className="h-7 w-7 flex-shrink-0" onClick={() => removeTrigger(index)}>
            <X className="w-3 h-3" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={addTrigger} data-testid="button-add-trigger">
        <Plus className="w-3 h-3 mr-1" />Add Trigger
      </Button>
    </div>
  );
}

function ToolDetailView({ tool, onClose, onEdit }: { tool: Tool; onClose: () => void; onEdit: () => void }) {
  const t = tool as any;
  const TypeIcon = typeIcons[tool.type] || Wrench;
  const creds = Array.isArray(t.credentials) ? t.credentials : [];
  const triggers = Array.isArray(t.triggerConditions) ? t.triggerConditions : [];

  return (
    <DialogContent className="sm:max-w-3xl max-h-[85vh] overflow-y-auto">
      <DialogHeader>
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-10 h-10 rounded-md bg-primary/10 text-primary">
            <TypeIcon className="w-5 h-5" />
          </div>
          <div>
            <DialogTitle className="text-lg">{tool.name}</DialogTitle>
            <p className="text-xs text-muted-foreground font-mono">{tool.slug} &middot; v{tool.version}</p>
          </div>
        </div>
      </DialogHeader>

      <div className="space-y-4 mt-2">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge variant="outline" className="border-transparent bg-primary/10 text-primary">{typeLabels[tool.type] || tool.type}</Badge>
          <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">{tool.category}</Badge>
          <Badge variant="outline" className={`border-transparent ${tool.status === "active" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400" : "bg-muted text-muted-foreground"}`}>{tool.status}</Badge>
          {tool.accessTier !== "any" && <Badge variant="outline" className="border-transparent bg-amber-100 text-amber-700">Tier: {tool.accessTier}</Badge>}
          {tool.restricted && <Badge variant="outline" className="border-transparent bg-red-100 text-red-700"><Lock className="w-2.5 h-2.5 mr-1" />Restricted</Badge>}
        </div>

        {tool.description && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1">Description</h4>
            <p className="text-sm">{tool.description}</p>
          </div>
        )}

        {t.skillContent && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1"><FileCode className="w-3 h-3" />Skill Content (SKILL.md)</h4>
            <pre className="text-xs bg-muted/50 p-3 rounded-md overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto font-mono">{t.skillContent}</pre>
          </div>
        )}

        {t.skillInstructions && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1">Skill Instructions</h4>
            <pre className="text-xs bg-muted/50 p-3 rounded-md overflow-x-auto whitespace-pre-wrap max-h-40 overflow-y-auto">{t.skillInstructions}</pre>
          </div>
        )}

        {triggers.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1">Trigger Conditions</h4>
            <div className="space-y-1">
              {triggers.map((tr: any, i: number) => (
                <div key={i} className="text-xs flex items-center gap-2">
                  <ChevronRight className="w-3 h-3 text-muted-foreground" />
                  <span className="font-mono">{tr.pattern || tr}</span>
                  {tr.description && <span className="text-muted-foreground">— {tr.description}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {t.sourceCode && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1"><Code2 className="w-3 h-3" />Source Code {t.runtimeEnvironment && `(${t.runtimeEnvironment})`}</h4>
            <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded-md overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto font-mono">{t.sourceCode}</pre>
            {t.entryPoint && <p className="text-[10px] text-muted-foreground mt-1">Entry point: <code className="font-mono">{t.entryPoint}</code></p>}
          </div>
        )}

        {t.executionMode && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1">Execution Mode</h4>
            <p className="text-sm">{t.executionMode === "prompt_injection" ? "Prompt Injection (loaded into agent context)" : t.executionMode === "sandbox_execution" ? "Sandbox Execution (isolated code run)" : t.executionMode}</p>
          </div>
        )}

        {creds.length > 0 && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1"><Key className="w-3 h-3" />Credentials & Environment ({creds.length})</h4>
            <div className="space-y-1.5">
              {creds.map((c: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs p-2 rounded-md bg-muted/30">
                  {c.isSecret ? <Lock className="w-3 h-3 text-amber-500" /> : <Unlock className="w-3 h-3 text-muted-foreground" />}
                  <code className="font-mono font-medium">{c.key}</code>
                  {c.isSecret ? <span className="text-muted-foreground">••••••••</span> : <span className="text-muted-foreground">{c.value}</span>}
                  {c.description && <span className="text-muted-foreground ml-auto">{c.description}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {t.usageInstructions && (
          <div>
            <h4 className="text-xs font-medium text-muted-foreground mb-1 flex items-center gap-1"><BookOpen className="w-3 h-3" />Agent Access / Usage Instructions</h4>
            <pre className="text-xs bg-muted/50 p-3 rounded-md overflow-x-auto whitespace-pre-wrap max-h-40 overflow-y-auto">{t.usageInstructions}</pre>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="p-2 rounded-md bg-muted/30">
            <p className="text-[10px] text-muted-foreground">Access Tier</p>
            <p className="text-xs font-medium">{tool.accessTier}</p>
          </div>
          <div className="p-2 rounded-md bg-muted/30">
            <p className="text-[10px] text-muted-foreground">Max Concurrent</p>
            <p className="text-xs font-medium">{tool.maxConcurrent === 0 ? "Unlimited" : tool.maxConcurrent}</p>
          </div>
          <div className="p-2 rounded-md bg-muted/30">
            <p className="text-[10px] text-muted-foreground">Lease (default/max)</p>
            <p className="text-xs font-medium">{tool.defaultLeaseSeconds}s / {tool.maxLeaseSeconds}s</p>
          </div>
          <div className="p-2 rounded-md bg-muted/30">
            <p className="text-[10px] text-muted-foreground">Daily Limit</p>
            <p className="text-xs font-medium">{tool.dailyUsageLimit ?? "Unlimited"}</p>
          </div>
        </div>

        {tool.requiresApproval && (
          <div className="flex items-center gap-2 p-2 rounded-md bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 text-xs">
            <AlertTriangle className="w-3.5 h-3.5" />
            Requires operator approval before checkout
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2 border-t">
          <Button variant="outline" size="sm" onClick={onClose}>Close</Button>
          <Button size="sm" onClick={onEdit} data-testid="button-edit-from-detail">
            <Pencil className="w-3 h-3 mr-1" />Edit Tool
          </Button>
        </div>
      </div>
    </DialogContent>
  );
}

function McpConfigTab({ form, activeTab }: { form: any; activeTab: string }) {
  const { toast } = useToast();
  const [mcpTransport, setMcpTransport] = useState<"stdio" | "sse">("stdio");
  const [mcpServerName, setMcpServerName] = useState("");
  const [mcpCommand, setMcpCommand] = useState("");
  const [mcpArgs, setMcpArgs] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpEnvPairs, setMcpEnvPairs] = useState<Array<{ key: string; value: string }>>([]);
  const [showRawJson, setShowRawJson] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; tools: any[] } | null>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [initialized, setInitialized] = useState(false);

  const currentConfig = form.watch("mcpConfig");

  useEffect(() => {
    if (initialized) return;
    if (currentConfig && typeof currentConfig === "object" && Object.keys(currentConfig).length > 0) {
      setMcpTransport(currentConfig.transport || "stdio");
      setMcpServerName(currentConfig.serverName || "");
      setMcpCommand(currentConfig.command || "");
      setMcpArgs(Array.isArray(currentConfig.args) ? currentConfig.args.join(", ") : currentConfig.args || "");
      setMcpUrl(currentConfig.url || "");
      const env = currentConfig.env || {};
      setMcpEnvPairs(Object.entries(env).map(([key, value]) => ({ key, value: String(value) })));
    }
    setInitialized(true);
  }, [currentConfig, initialized]);

  function syncToForm() {
    const config: any = {
      serverName: mcpServerName || "mcp-server",
      transport: mcpTransport,
    };
    if (mcpTransport === "stdio") {
      config.command = mcpCommand;
      config.args = mcpArgs.split(",").map(a => a.trim()).filter(Boolean);
    } else {
      config.url = mcpUrl;
    }
    if (mcpEnvPairs.length > 0) {
      config.env = {};
      for (const p of mcpEnvPairs) {
        if (p.key) config.env[p.key] = p.value;
      }
    }
    form.setValue("mcpConfig", config);
    form.setValue("accessTier", "tier2");
    return config;
  }

  useEffect(() => {
    if (initialized) syncToForm();
  }, [mcpTransport, mcpServerName, mcpCommand, mcpArgs, mcpUrl, mcpEnvPairs, initialized]);

  async function handleTestConnection() {
    setTestLoading(true);
    setTestResult(null);
    const config = syncToForm();
    try {
      const resp = await apiRequest("POST", "/api/locker/mcp/test", { mcpConfig: config });
      const data = await resp.json();
      setTestResult(data);
      if (data.success) {
        toast({ title: "Connection Successful", description: data.message });
      } else {
        toast({ title: "Connection Failed", description: data.message, variant: "destructive" });
      }
    } catch (err: any) {
      setTestResult({ success: false, message: err.message, tools: [] });
      toast({ title: "Test Failed", description: err.message, variant: "destructive" });
    } finally {
      setTestLoading(false);
    }
  }

  return (
    <TabsContent value="mcp" forceMount className={`space-y-4 mt-4 ${activeTab !== "mcp" ? "hidden" : ""}`}>
      <div className="p-3 rounded-md bg-indigo-50 dark:bg-indigo-900/20 text-indigo-700 dark:text-indigo-300 text-xs">
        <p className="font-medium mb-1">MCP Server Configuration</p>
        <p>Configure the Model Context Protocol server connection. Sub-agents connect to this server to access the tools and resources it exposes.</p>
      </div>

      <div className="p-3 rounded-md bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 text-xs flex items-start gap-2">
        <ShieldCheck className="w-3.5 h-3.5 mt-0.5 shrink-0" />
        <p>MCP tools are sub-agent only. Aiden routes through a sub-agent to access MCP servers. Access tier is automatically set to Tier 2.</p>
      </div>

      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Server Name</Label>
            <Input
              value={mcpServerName}
              onChange={(e) => setMcpServerName(e.target.value)}
              placeholder="my-mcp-server"
              className="text-xs mt-1"
              data-testid="input-mcp-server-name"
            />
          </div>
          <div>
            <Label className="text-xs">Transport</Label>
            <Select value={mcpTransport} onValueChange={(v) => setMcpTransport(v as "stdio" | "sse")}>
              <SelectTrigger className="text-xs mt-1" data-testid="select-mcp-transport">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="stdio">stdio (local process)</SelectItem>
                <SelectItem value="sse">SSE (remote HTTP)</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        {mcpTransport === "stdio" ? (
          <div className="space-y-3 p-3 rounded-md border bg-muted/20">
            <p className="text-xs font-medium text-muted-foreground flex items-center gap-1"><Terminal className="w-3 h-3" /> stdio Transport</p>
            <div>
              <Label className="text-xs">Command</Label>
              <Input
                value={mcpCommand}
                onChange={(e) => setMcpCommand(e.target.value)}
                placeholder="npx"
                className="text-xs mt-1 font-mono"
                data-testid="input-mcp-command"
              />
            </div>
            <div>
              <Label className="text-xs">Arguments (comma-separated)</Label>
              <Input
                value={mcpArgs}
                onChange={(e) => setMcpArgs(e.target.value)}
                placeholder="-y, @modelcontextprotocol/server-filesystem, /tmp"
                className="text-xs mt-1 font-mono"
                data-testid="input-mcp-args"
              />
            </div>
          </div>
        ) : (
          <div className="space-y-3 p-3 rounded-md border bg-muted/20">
            <p className="text-xs font-medium text-muted-foreground flex items-center gap-1"><Globe className="w-3 h-3" /> SSE Transport</p>
            <div>
              <Label className="text-xs">Server URL</Label>
              <Input
                value={mcpUrl}
                onChange={(e) => setMcpUrl(e.target.value)}
                placeholder="https://mcp.example.com/sse"
                className="text-xs mt-1 font-mono"
                data-testid="input-mcp-url"
              />
            </div>
          </div>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs">Environment Variables</Label>
            <Button type="button" variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setMcpEnvPairs([...mcpEnvPairs, { key: "", value: "" }])} data-testid="button-add-mcp-env">
              <Plus className="w-3 h-3 mr-1" /> Add
            </Button>
          </div>
          {mcpEnvPairs.map((pair, i) => (
            <div key={i} className="flex gap-2 items-center">
              <Input
                value={pair.key}
                onChange={(e) => {
                  const updated = [...mcpEnvPairs];
                  updated[i] = { ...updated[i], key: e.target.value };
                  setMcpEnvPairs(updated);
                }}
                placeholder="KEY"
                className="text-xs font-mono flex-1"
                data-testid={`input-mcp-env-key-${i}`}
              />
              <Input
                value={pair.value}
                onChange={(e) => {
                  const updated = [...mcpEnvPairs];
                  updated[i] = { ...updated[i], value: e.target.value };
                  setMcpEnvPairs(updated);
                }}
                placeholder="value or env:VAR_NAME"
                className="text-xs font-mono flex-1"
                data-testid={`input-mcp-env-value-${i}`}
              />
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => setMcpEnvPairs(mcpEnvPairs.filter((_, j) => j !== i))} data-testid={`button-remove-mcp-env-${i}`}>
                <X className="w-3 h-3" />
              </Button>
            </div>
          ))}
        </div>

        <div className="flex items-center gap-3 pt-2 border-t">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleTestConnection}
            disabled={testLoading || (mcpTransport === "stdio" && !mcpCommand) || (mcpTransport === "sse" && !mcpUrl)}
            className="text-xs"
            data-testid="button-test-mcp-connection"
          >
            {testLoading ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Zap className="w-3 h-3 mr-1" />}
            Test Connection
          </Button>
          <div className="flex items-center gap-2 ml-auto">
            <Label className="text-xs text-muted-foreground">Raw JSON</Label>
            <Switch checked={showRawJson} onCheckedChange={setShowRawJson} data-testid="switch-mcp-raw-json" />
          </div>
        </div>

        {testResult && (
          <div className={`p-3 rounded-md text-xs ${testResult.success ? "bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-300" : "bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-300"}`} data-testid="mcp-test-result">
            <p className="font-medium">{testResult.success ? "Connected" : "Connection Failed"}</p>
            <p className="mt-1">{testResult.message}</p>
            {testResult.tools?.length > 0 && (
              <div className="mt-2 space-y-1">
                <p className="font-medium">Discovered Tools:</p>
                {testResult.tools.map((t: any, i: number) => (
                  <div key={i} className="flex items-baseline gap-2">
                    <code className="font-mono text-[11px] bg-black/5 dark:bg-white/5 px-1 rounded">{t.name}</code>
                    <span className="text-[10px] text-muted-foreground">{t.description || "No description"}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {showRawJson && (
          <FormField control={form.control} name="mcpConfig" render={({ field }) => (
            <FormItem>
              <FormLabel className="text-xs">Raw JSON Config</FormLabel>
              <FormControl>
                <Textarea
                  value={typeof field.value === "object" ? JSON.stringify(field.value, null, 2) : field.value || ""}
                  onChange={(e) => {
                    try {
                      const parsed = JSON.parse(e.target.value);
                      field.onChange(parsed);
                      setMcpTransport(parsed.transport || "stdio");
                      setMcpServerName(parsed.serverName || "");
                      setMcpCommand(parsed.command || "");
                      setMcpArgs(Array.isArray(parsed.args) ? parsed.args.join(", ") : "");
                      setMcpUrl(parsed.url || "");
                      const env = parsed.env || {};
                      setMcpEnvPairs(Object.entries(env).map(([key, value]) => ({ key, value: String(value) })));
                    } catch {
                      field.onChange(e.target.value);
                    }
                  }}
                  className="resize-none font-mono text-xs bg-slate-50 dark:bg-slate-900"
                  rows={10}
                  data-testid="input-mcp-config-raw"
                />
              </FormControl>
              <FormMessage />
            </FormItem>
          )} />
        )}
      </div>
    </TabsContent>
  );
}

export default function ToolsPage() {
  usePageTitle("Tools Locker");
  const { toast } = useToast();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);
  const [viewingTool, setViewingTool] = useState<Tool | null>(null);
  const [activeTab, setActiveTab] = useState("identity");
  const [credentialsState, setCredentialsState] = useState<any[]>([]);
  const [triggersState, setTriggersState] = useState<any[]>([]);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importingSkill, setImportingSkill] = useState<string | null>(null);

  const { data: tools, isLoading } = useQuery<Tool[]>({
    queryKey: ["/api/tools"],
  });

  interface AvailableSkill {
    name: string;
    dirName: string;
    slug: string;
    description: string;
    content: string;
    alreadyImported: boolean;
    hasReferences: boolean;
    referenceFiles: string[];
  }

  const { data: availableSkills, isLoading: skillsLoading, refetch: refetchSkills } = useQuery<AvailableSkill[]>({
    queryKey: ["/api/skills/available"],
    enabled: importDialogOpen,
  });

  const importSkillMutation = useMutation({
    mutationFn: (dirName: string) =>
      apiRequest("POST", "/api/tools/import-skill", { dirName }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
      queryClient.invalidateQueries({ queryKey: ["/api/skills/available"] });
      toast({ title: "Skill imported to Tools Locker" });
      setImportingSkill(null);
    },
    onError: (err: any) => {
      toast({ title: "Failed to import skill", description: err.message, variant: "destructive" });
      setImportingSkill(null);
    },
  });

  const form = useForm<ToolFormValues>({
    resolver: zodResolver(toolFormSchema),
    defaultValues: {
      name: "",
      slug: "",
      description: null,
      type: "skill",
      category: "general",
      status: "active",
      version: "1.0.0",
      skillContent: null,
      skillInstructions: null,
      triggerConditions: [],
      executionMode: "prompt_injection",
      runtimeEnvironment: null,
      sourceCode: null,
      entryPoint: null,
      sandboxConfig: {},
      credentials: [],
      usageInstructions: null,
      mcpConfig: {},
      inputSchema: {},
      outputSchema: {},
      accessTier: "any",
      maxConcurrent: 0,
      defaultLeaseSeconds: 300,
      maxLeaseSeconds: 3600,
      dailyUsageLimit: null,
      costCeilingPerDay: null,
      requiresApproval: false,
    },
  });

  const watchName = form.watch("name");
  const watchType = form.watch("type");

  useEffect(() => {
    if (!editingTool) {
      form.setValue("slug", slugify(watchName));
    }
  }, [watchName, editingTool, form]);

  useEffect(() => {
    if (watchType === "skill" || watchType === "mcp_server") {
      form.setValue("executionMode", "prompt_injection");
    } else if (watchType === "python_code" || watchType === "cli") {
      form.setValue("executionMode", "sandbox_execution");
    }
    if (watchType === "mcp_server") {
      form.setValue("accessTier", "tier2");
    }
  }, [watchType, form]);

  const createMutation = useMutation({
    mutationFn: (values: ToolFormValues) =>
      apiRequest("POST", "/api/tools", { ...values, credentials: credentialsState, triggerConditions: triggersState }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
      toast({ title: "Tool deployed to locker" });
      setDialogOpen(false);
      form.reset();
      setCredentialsState([]);
      setTriggersState([]);
    },
    onError: (err: any) => {
      toast({ title: "Failed to deploy tool", description: err.message, variant: "destructive" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: ToolFormValues) =>
      apiRequest("PUT", `/api/tools/${editingTool?.id}`, { ...values, credentials: credentialsState, triggerConditions: triggersState }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
      toast({ title: "Tool updated" });
      setDialogOpen(false);
      setEditingTool(null);
      form.reset();
      setCredentialsState([]);
      setTriggersState([]);
    },
    onError: (err: any) => {
      toast({ title: "Failed to update tool", description: err.message, variant: "destructive" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest("DELETE", `/api/tools/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
      toast({ title: "Tool removed from locker" });
    },
    onError: (err: any) => {
      toast({ title: "Failed to delete", description: err.message, variant: "destructive" });
    },
  });

  function openCreate() {
    setEditingTool(null);
    form.reset({
      name: "", slug: "", description: null, type: "skill", category: "general",
      status: "active", version: "1.0.0", skillContent: null, skillInstructions: null,
      triggerConditions: [], executionMode: "prompt_injection", runtimeEnvironment: null,
      sourceCode: null, entryPoint: null, sandboxConfig: {}, credentials: [],
      usageInstructions: null, mcpConfig: {}, inputSchema: {}, outputSchema: {},
      accessTier: "any", maxConcurrent: 0, defaultLeaseSeconds: 300,
      maxLeaseSeconds: 3600, dailyUsageLimit: null, costCeilingPerDay: null, requiresApproval: false,
    });
    setCredentialsState([]);
    setTriggersState([]);
    setActiveTab("identity");
    setDialogOpen(true);
  }

  function openEdit(tool: Tool) {
    const t = tool as any;
    setEditingTool(tool);
    form.reset({
      name: tool.name, slug: tool.slug, description: tool.description,
      type: tool.type, category: tool.category, status: tool.status, version: tool.version,
      skillContent: t.skillContent || null,
      skillInstructions: t.skillInstructions || null,
      triggerConditions: t.triggerConditions || [],
      executionMode: t.executionMode || "prompt_injection",
      runtimeEnvironment: t.runtimeEnvironment || null,
      sourceCode: t.sourceCode || null,
      entryPoint: t.entryPoint || null,
      sandboxConfig: t.sandboxConfig || {},
      credentials: t.credentials || [],
      usageInstructions: t.usageInstructions || null,
      mcpConfig: t.mcpConfig || {},
      inputSchema: t.inputSchema || {},
      outputSchema: t.outputSchema || {},
      accessTier: tool.accessTier, maxConcurrent: tool.maxConcurrent,
      defaultLeaseSeconds: tool.defaultLeaseSeconds, maxLeaseSeconds: tool.maxLeaseSeconds,
      dailyUsageLimit: tool.dailyUsageLimit, costCeilingPerDay: tool.costCeilingPerDay,
      requiresApproval: tool.requiresApproval,
    });
    setCredentialsState(Array.isArray(t.credentials) ? t.credentials : []);
    setTriggersState(Array.isArray(t.triggerConditions) ? t.triggerConditions : []);
    setActiveTab("identity");
    setDialogOpen(true);
  }

  function onSubmit(values: ToolFormValues) {
    if (editingTool) {
      updateMutation.mutate(values);
    } else {
      createMutation.mutate(values);
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending;
  const showSkillTab = watchType === "skill" || watchType === "mcp_server";
  const showCodeTab = watchType === "python_code" || watchType === "cli" || watchType === "slash_command";
  const showMcpTab = watchType === "mcp_server";

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-tools-title">
            Tools Locker
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Deploy and govern agentic tools — Claude Skills, code blocks, slash commands, MCP servers, and API integrations
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => setImportDialogOpen(true)} data-testid="button-import-skills">
            <FileDown className="w-4 h-4 mr-2" />
            Import Skills
          </Button>
          <Button onClick={openCreate} data-testid="button-deploy-tool">
            <Plus className="w-4 h-4 mr-2" />
            Deploy Tool
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 rounded-md bg-muted/40 animate-pulse" />
          ))}
        </div>
      ) : tools && tools.length > 0 ? (
        <div className="space-y-3">
          {tools.map((tool) => (
            <ToolCard
              key={tool.id}
              tool={tool}
              onEdit={openEdit}
              onDelete={(id) => deleteMutation.mutate(id)}
              onView={(t) => setViewingTool(t)}
            />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Wrench className="w-12 h-12 text-muted-foreground/30 mb-4" />
            <p className="text-sm text-muted-foreground">No tools in locker</p>
            <p className="text-xs text-muted-foreground mt-1">
              Deploy agentic tools for sub-agents to check out and use during work order execution
            </p>
            <Button className="mt-4" onClick={openCreate} data-testid="button-deploy-tool-empty">
              <Plus className="w-4 h-4 mr-2" />
              Deploy First Tool
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Detail View Dialog */}
      <Dialog open={!!viewingTool} onOpenChange={(open) => !open && setViewingTool(null)}>
        {viewingTool && (
          <ToolDetailView
            tool={viewingTool}
            onClose={() => setViewingTool(null)}
            onEdit={() => {
              const t = viewingTool;
              setViewingTool(null);
              openEdit(t);
            }}
          />
        )}
      </Dialog>

      {/* Create/Edit Form Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-3xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingTool ? "Edit Tool" : "Deploy Tool to Locker"}</DialogTitle>
            <p className="text-xs text-muted-foreground">
              {editingTool ? "Update tool configuration" : "Onboard a new tool for agents to check out and use"}
            </p>
          </DialogHeader>

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
                <TabsList className="w-full flex flex-wrap h-auto gap-1 bg-muted/50 p-1">
                  <TabsTrigger value="identity" className="text-xs flex-1 min-w-[80px]" data-testid="tab-identity">
                    <Settings2 className="w-3 h-3 mr-1" />Identity
                  </TabsTrigger>
                  {showSkillTab && (
                    <TabsTrigger value="skill" className="text-xs flex-1 min-w-[80px]" data-testid="tab-skill">
                      <FileCode className="w-3 h-3 mr-1" />Skill
                    </TabsTrigger>
                  )}
                  {showCodeTab && (
                    <TabsTrigger value="code" className="text-xs flex-1 min-w-[80px]" data-testid="tab-code">
                      <Code2 className="w-3 h-3 mr-1" />Code
                    </TabsTrigger>
                  )}
                  {showMcpTab && (
                    <TabsTrigger value="mcp" className="text-xs flex-1 min-w-[80px]" data-testid="tab-mcp">
                      <Server className="w-3 h-3 mr-1" />MCP
                    </TabsTrigger>
                  )}
                  <TabsTrigger value="credentials" className="text-xs flex-1 min-w-[80px]" data-testid="tab-credentials">
                    <Key className="w-3 h-3 mr-1" />Creds
                  </TabsTrigger>
                  <TabsTrigger value="contracts" className="text-xs flex-1 min-w-[80px]" data-testid="tab-contracts">
                    <FileCode className="w-3 h-3 mr-1" />I/O
                  </TabsTrigger>
                  <TabsTrigger value="governance" className="text-xs flex-1 min-w-[80px]" data-testid="tab-governance">
                    <ShieldCheck className="w-3 h-3 mr-1" />Govern
                  </TabsTrigger>
                  <TabsTrigger value="access" className="text-xs flex-1 min-w-[80px]" data-testid="tab-access">
                    <BookOpen className="w-3 h-3 mr-1" />Access
                  </TabsTrigger>
                </TabsList>

                {/* === Identity Tab === */}
                <TabsContent value="identity" forceMount className={`space-y-4 mt-4 ${activeTab !== "identity" ? "hidden" : ""}`}>
                  <div className="space-y-3">
                    <FormField control={form.control} name="type" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Tool Type</FormLabel>
                        <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                          {toolTypes.map((tt) => {
                            const Icon = tt.icon;
                            const isSelected = field.value === tt.value;
                            return (
                              <button
                                key={tt.value}
                                type="button"
                                className={`flex items-start gap-2 p-3 rounded-md border text-left transition-colors ${
                                  isSelected
                                    ? "border-primary bg-primary/5 dark:bg-primary/10"
                                    : "border-border hover:border-primary/50 hover:bg-muted/30"
                                }`}
                                onClick={() => field.onChange(tt.value)}
                                data-testid={`button-type-${tt.value}`}
                              >
                                <Icon className={`w-4 h-4 mt-0.5 flex-shrink-0 ${isSelected ? "text-primary" : "text-muted-foreground"}`} />
                                <div>
                                  <p className={`text-xs font-medium ${isSelected ? "text-primary" : ""}`}>{tt.label}</p>
                                  <p className="text-[10px] text-muted-foreground mt-0.5 leading-tight">{tt.description}</p>
                                </div>
                              </button>
                            );
                          })}
                        </div>
                        <FormMessage />
                      </FormItem>
                    )} />

                    <div className="grid grid-cols-2 gap-3">
                      <FormField control={form.control} name="name" render={({ field }) => (
                        <FormItem>
                          <FormLabel>Name</FormLabel>
                          <FormControl><Input {...field} placeholder="e.g. PDF Processor" data-testid="input-tool-name" /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )} />
                      <FormField control={form.control} name="slug" render={({ field }) => (
                        <FormItem>
                          <FormLabel>Slug</FormLabel>
                          <FormControl><Input {...field} placeholder="e.g. pdf-processor" className="font-mono" data-testid="input-tool-slug" /></FormControl>
                          <FormDescription className="text-[10px]">Unique identifier. Lowercase, hyphens only.</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )} />
                    </div>

                    <FormField control={form.control} name="description" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Description</FormLabel>
                        <FormControl>
                          <Textarea
                            {...field}
                            value={field.value || ""}
                            placeholder="Brief description of what this tool does and when agents should use it. This is the Level 1 metadata that agents always see."
                            className="resize-none"
                            rows={3}
                            data-testid="input-tool-description"
                          />
                        </FormControl>
                        <FormDescription className="text-[10px]">Agents use this to decide when to load the tool. Keep it clear and specific.</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )} />

                    <div className="grid grid-cols-3 gap-3">
                      <FormField control={form.control} name="category" render={({ field }) => (
                        <FormItem>
                          <FormLabel>Category</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl><SelectTrigger data-testid="select-tool-category"><SelectValue /></SelectTrigger></FormControl>
                            <SelectContent>
                              <SelectItem value="general">General</SelectItem>
                              <SelectItem value="deployment">Deployment</SelectItem>
                              <SelectItem value="security">Security</SelectItem>
                              <SelectItem value="monitoring">Monitoring</SelectItem>
                              <SelectItem value="communication">Communication</SelectItem>
                              <SelectItem value="data">Data</SelectItem>
                              <SelectItem value="ai">AI / LLM</SelectItem>
                              <SelectItem value="integration">Integration</SelectItem>
                              <SelectItem value="automation">Automation</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )} />
                      <FormField control={form.control} name="status" render={({ field }) => (
                        <FormItem>
                          <FormLabel>Status</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value}>
                            <FormControl><SelectTrigger data-testid="select-tool-status"><SelectValue /></SelectTrigger></FormControl>
                            <SelectContent>
                              <SelectItem value="active">Active</SelectItem>
                              <SelectItem value="inactive">Inactive</SelectItem>
                              <SelectItem value="deprecated">Deprecated</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )} />
                      <FormField control={form.control} name="version" render={({ field }) => (
                        <FormItem>
                          <FormLabel>Version</FormLabel>
                          <FormControl><Input {...field} placeholder="1.0.0" data-testid="input-tool-version" /></FormControl>
                          <FormMessage />
                        </FormItem>
                      )} />
                    </div>
                  </div>
                </TabsContent>

                {/* === Skill Content Tab === */}
                {showSkillTab && (
                  <TabsContent value="skill" forceMount className={`space-y-4 mt-4 ${activeTab !== "skill" ? "hidden" : ""}`}>
                    <div className="p-3 rounded-md bg-violet-50 dark:bg-violet-900/20 text-violet-700 dark:text-violet-300 text-xs">
                      <p className="font-medium mb-1">Claude Skill Format (SKILL.md)</p>
                      <p>Write the skill content following the Claude SKILL.md convention. This is the Level 2 content loaded into the agent's context when the skill is triggered. Include step-by-step instructions, examples, and references.</p>
                    </div>

                    <FormField control={form.control} name="skillContent" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Skill Content (SKILL.md body)</FormLabel>
                        <FormControl>
                          <Textarea
                            {...field}
                            value={field.value || ""}
                            placeholder={`# My Skill\n\n## Quick Start\nDescribe the primary workflow here...\n\n## Instructions\n1. Step one...\n2. Step two...\n\n## Examples\n\`\`\`python\n# Example usage\nresult = process_data(input)\n\`\`\`\n\n## References\nSee [REFERENCE.md](REFERENCE.md) for detailed API docs.`}
                            className="resize-none font-mono text-xs"
                            rows={14}
                            data-testid="input-skill-content"
                          />
                        </FormControl>
                        <FormDescription className="text-[10px]">The main body of the skill. This is loaded into the agent context when triggered. Write clear, actionable instructions.</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )} />

                    <FormField control={form.control} name="skillInstructions" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Additional Instructions</FormLabel>
                        <FormControl>
                          <Textarea
                            {...field}
                            value={field.value || ""}
                            placeholder="Any supplementary instructions, constraints, or guardrails for the agent when using this skill..."
                            className="resize-none text-xs"
                            rows={4}
                            data-testid="input-skill-instructions"
                          />
                        </FormControl>
                        <FormDescription className="text-[10px]">Optional. Extra guidance, constraints, or safety guardrails.</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )} />

                    <div>
                      <Label className="text-sm font-medium">Trigger Conditions</Label>
                      <p className="text-[10px] text-muted-foreground mb-2">When should the agent automatically load this skill? Define patterns or conditions.</p>
                      <TriggerConditionEditor value={triggersState} onChange={setTriggersState} />
                    </div>
                  </TabsContent>
                )}

                {/* === Code Tab === */}
                {showCodeTab && (
                  <TabsContent value="code" forceMount className={`space-y-4 mt-4 ${activeTab !== "code" ? "hidden" : ""}`}>
                    <div className="p-3 rounded-md bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 text-xs">
                      <p className="font-medium mb-1">Code Execution</p>
                      <p>Source code is executed in a sandboxed environment. The agent runs this code and receives only the output — the code itself doesn't consume context tokens.</p>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <FormField control={form.control} name="executionMode" render={({ field }) => (
                        <FormItem>
                          <FormLabel>Execution Mode</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value || "sandbox_execution"}>
                            <FormControl><SelectTrigger data-testid="select-execution-mode"><SelectValue /></SelectTrigger></FormControl>
                            <SelectContent>
                              <SelectItem value="prompt_injection">Prompt Injection</SelectItem>
                              <SelectItem value="sandbox_execution">Sandbox Execution</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormDescription className="text-[10px]">Prompt injection loads into context. Sandbox runs isolated.</FormDescription>
                          <FormMessage />
                        </FormItem>
                      )} />
                      <FormField control={form.control} name="runtimeEnvironment" render={({ field }) => (
                        <FormItem>
                          <FormLabel>Runtime</FormLabel>
                          <Select onValueChange={field.onChange} value={field.value || ""}>
                            <FormControl><SelectTrigger data-testid="select-runtime"><SelectValue placeholder="Select runtime" /></SelectTrigger></FormControl>
                            <SelectContent>
                              <SelectItem value="python">Python</SelectItem>
                              <SelectItem value="nodejs">Node.js</SelectItem>
                              <SelectItem value="bash">Bash</SelectItem>
                              <SelectItem value="deno">Deno</SelectItem>
                            </SelectContent>
                          </Select>
                          <FormMessage />
                        </FormItem>
                      )} />
                    </div>

                    <FormField control={form.control} name="sourceCode" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Source Code</FormLabel>
                        <FormControl>
                          <Textarea
                            {...field}
                            value={field.value || ""}
                            placeholder={watchType === "python_code"
                              ? `import sys\nimport json\n\ndef main(input_data):\n    \"\"\"Process the input and return results.\"\"\"\n    result = {\n        \"status\": \"success\",\n        \"output\": f\"Processed: {input_data}\"\n    }\n    return result\n\nif __name__ == \"__main__\":\n    data = json.loads(sys.stdin.read())\n    print(json.dumps(main(data)))`
                              : `#!/bin/bash\n# Tool script\necho "Processing..."\n# Your code here`}
                            className="resize-none font-mono text-xs bg-slate-50 dark:bg-slate-900"
                            rows={14}
                            data-testid="input-source-code"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )} />

                    <FormField control={form.control} name="entryPoint" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Entry Point</FormLabel>
                        <FormControl>
                          <Input {...field} value={field.value || ""} placeholder="e.g. main.py or handler.js" className="font-mono text-xs" data-testid="input-entry-point" />
                        </FormControl>
                        <FormDescription className="text-[10px]">The file or function to execute when this tool is invoked.</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )} />
                  </TabsContent>
                )}

                {/* === MCP Server Tab === */}
                {showMcpTab && (
                  <McpConfigTab form={form} activeTab={activeTab} />
                )}

                {/* === Credentials Tab === */}
                <TabsContent value="credentials" forceMount className={`space-y-4 mt-4 ${activeTab !== "credentials" ? "hidden" : ""}`}>
                  <div className="p-3 rounded-md bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300 text-xs">
                    <p className="font-medium mb-1">Credentials & Environment Variables</p>
                    <p>Define the API keys, secrets, and environment variables this tool needs. For secrets, use <code className="font-mono bg-amber-100 dark:bg-amber-800 px-1 rounded">env:VARIABLE_NAME</code> to reference system environment variables rather than storing values directly.</p>
                  </div>
                  <CredentialEditor value={credentialsState} onChange={setCredentialsState} />
                </TabsContent>

                {/* === Contracts Tab === */}
                <TabsContent value="contracts" forceMount className={`space-y-4 mt-4 ${activeTab !== "contracts" ? "hidden" : ""}`}>
                  <div className="p-3 rounded-md bg-cyan-50 dark:bg-cyan-900/20 text-cyan-700 dark:text-cyan-300 text-xs">
                    <p className="font-medium mb-1">Input / Output Contracts</p>
                    <p>Define the JSON schema for what this tool expects as input and what it returns. This helps agents understand how to call the tool and parse results.</p>
                  </div>

                  <FormField control={form.control} name="inputSchema" render={({ field }) => (
                    <FormItem>
                      <FormLabel>Input Schema (JSON)</FormLabel>
                      <FormControl>
                        <Textarea
                          value={typeof field.value === "object" ? JSON.stringify(field.value, null, 2) : field.value || ""}
                          onChange={(e) => {
                            try { field.onChange(JSON.parse(e.target.value)); } catch { field.onChange(e.target.value); }
                          }}
                          placeholder={JSON.stringify({
                            type: "object",
                            properties: {
                              query: { type: "string", description: "The search query" },
                              limit: { type: "number", description: "Max results", default: 10 },
                            },
                            required: ["query"],
                          }, null, 2)}
                          className="resize-none font-mono text-xs"
                          rows={8}
                          data-testid="input-input-schema"
                        />
                      </FormControl>
                      <FormDescription className="text-[10px]">JSON Schema describing the expected input parameters.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )} />

                  <FormField control={form.control} name="outputSchema" render={({ field }) => (
                    <FormItem>
                      <FormLabel>Output Schema (JSON)</FormLabel>
                      <FormControl>
                        <Textarea
                          value={typeof field.value === "object" ? JSON.stringify(field.value, null, 2) : field.value || ""}
                          onChange={(e) => {
                            try { field.onChange(JSON.parse(e.target.value)); } catch { field.onChange(e.target.value); }
                          }}
                          placeholder={JSON.stringify({
                            type: "object",
                            properties: {
                              results: { type: "array", items: { type: "object" } },
                              total: { type: "number" },
                            },
                          }, null, 2)}
                          className="resize-none font-mono text-xs"
                          rows={8}
                          data-testid="input-output-schema"
                        />
                      </FormControl>
                      <FormDescription className="text-[10px]">JSON Schema describing what this tool returns.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )} />
                </TabsContent>

                {/* === Governance Tab === */}
                <TabsContent value="governance" forceMount className={`space-y-4 mt-4 ${activeTab !== "governance" ? "hidden" : ""}`}>
                  <div className="p-3 rounded-md bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 text-xs">
                    <p className="font-medium mb-1">Governance & Checkout Rules</p>
                    <p>Control which agents can check out this tool, concurrency limits, lease durations, and daily usage caps. These rules are enforced at checkout time.</p>
                  </div>

                  <FormField control={form.control} name="accessTier" render={({ field }) => (
                    <FormItem>
                      <FormLabel>Access Tier</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value || "any"}>
                        <FormControl><SelectTrigger data-testid="select-access-tier"><SelectValue /></SelectTrigger></FormControl>
                        <SelectContent>
                          <SelectItem value="any">Any (all agents)</SelectItem>
                          <SelectItem value="tier1">Tier 1 only (Aiden)</SelectItem>
                          <SelectItem value="tier2">Tier 2 only (Sub-Agents)</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormDescription className="text-[10px]">Which tier of agents can check out this tool.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )} />

                  <div className="grid grid-cols-2 gap-3">
                    <FormField control={form.control} name="maxConcurrent" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Max Concurrent Checkouts</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            value={field.value ?? 0}
                            onChange={(e) => field.onChange(parseInt(e.target.value) || 0)}
                            data-testid="input-max-concurrent"
                          />
                        </FormControl>
                        <FormDescription className="text-[10px]">0 = unlimited</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )} />
                    <FormField control={form.control} name="dailyUsageLimit" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Daily Usage Limit</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            value={field.value ?? ""}
                            onChange={(e) => field.onChange(e.target.value ? parseInt(e.target.value) : null)}
                            placeholder="Unlimited"
                            data-testid="input-daily-limit"
                          />
                        </FormControl>
                        <FormDescription className="text-[10px]">Leave empty for unlimited</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )} />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <FormField control={form.control} name="defaultLeaseSeconds" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Default Lease (seconds)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            value={field.value ?? 300}
                            onChange={(e) => field.onChange(parseInt(e.target.value) || 300)}
                            data-testid="input-default-lease"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )} />
                    <FormField control={form.control} name="maxLeaseSeconds" render={({ field }) => (
                      <FormItem>
                        <FormLabel>Max Lease (seconds)</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            value={field.value ?? 3600}
                            onChange={(e) => field.onChange(parseInt(e.target.value) || 3600)}
                            data-testid="input-max-lease"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )} />
                  </div>

                  <FormField control={form.control} name="costCeilingPerDay" render={({ field }) => (
                    <FormItem>
                      <FormLabel>Cost Ceiling Per Day</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          value={field.value || ""}
                          placeholder="e.g. $50.00"
                          data-testid="input-cost-ceiling"
                        />
                      </FormControl>
                      <FormDescription className="text-[10px]">Optional cost cap for tools that incur charges.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )} />

                  <FormField control={form.control} name="requiresApproval" render={({ field }) => (
                    <FormItem className="flex items-center gap-3 space-y-0 p-3 rounded-md border">
                      <FormControl>
                        <Switch checked={field.value || false} onCheckedChange={field.onChange} data-testid="switch-requires-approval" />
                      </FormControl>
                      <div>
                        <FormLabel className="text-sm">Requires Operator Approval</FormLabel>
                        <FormDescription className="text-[10px]">When enabled, an operator must approve each checkout request before the agent can use this tool.</FormDescription>
                      </div>
                    </FormItem>
                  )} />
                </TabsContent>

                {/* === Agent Access Tab === */}
                <TabsContent value="access" forceMount className={`space-y-4 mt-4 ${activeTab !== "access" ? "hidden" : ""}`}>
                  <div className="p-3 rounded-md bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 text-xs">
                    <p className="font-medium mb-1">Agent Access & Usage Guide</p>
                    <p>Tell the agent exactly how to invoke this tool, what to expect, and provide working examples. This is what the agent reads to understand how to use the tool once it's checked out.</p>
                  </div>

                  <FormField control={form.control} name="usageInstructions" render={({ field }) => (
                    <FormItem>
                      <FormLabel>Usage Instructions</FormLabel>
                      <FormControl>
                        <Textarea
                          {...field}
                          value={field.value || ""}
                          placeholder={`## How to Use This Tool\n\n### Invocation\nCall via: \`/my-tool --query "search term" --limit 10\`\n\n### Authentication\nThe API key is available at env:MY_API_KEY. Include it as Bearer token.\n\n### Example Request\n\`\`\`\ncurl -X POST https://api.example.com/v1/search \\\n  -H "Authorization: Bearer $MY_API_KEY" \\\n  -d '{"query": "example"}'\n\`\`\`\n\n### Expected Response\n\`\`\`json\n{"results": [...], "total": 42}\n\`\`\`\n\n### Error Handling\n- 429: Rate limited, wait and retry\n- 401: Check API key\n- 500: Report to operator`}
                          className="resize-none font-mono text-xs"
                          rows={16}
                          data-testid="input-usage-instructions"
                        />
                      </FormControl>
                      <FormDescription className="text-[10px]">Comprehensive usage guide with invocation syntax, authentication, examples, and error handling.</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )} />
                </TabsContent>
              </Tabs>

              <div className="flex justify-between items-center pt-2 border-t">
                <p className="text-[10px] text-muted-foreground">
                  {activeTab === "identity" ? "1/7" : activeTab === "skill" ? "2/7" : activeTab === "code" ? "2/7" : activeTab === "mcp" ? "3/7" : activeTab === "credentials" ? "4/7" : activeTab === "contracts" ? "5/7" : activeTab === "governance" ? "6/7" : "7/7"} — Fill out required tabs before deploying
                </p>
                <div className="flex gap-2">
                  <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>Cancel</Button>
                  <Button type="submit" disabled={isPending} data-testid="button-save-tool">
                    {isPending ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                    {editingTool ? "Update Tool" : "Deploy to Locker"}
                  </Button>
                </div>
              </div>
            </form>
          </Form>
        </DialogContent>
      </Dialog>

      <Dialog open={importDialogOpen} onOpenChange={setImportDialogOpen}>
        <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>Import Claude Skills</DialogTitle>
            <p className="text-sm text-muted-foreground mt-1">
              Scan approved skills from the project's skill directory and import them into the Tools Locker.
            </p>
          </DialogHeader>

          {skillsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin mr-2" />
              <span className="text-sm text-muted-foreground">Scanning skills directory...</span>
            </div>
          ) : availableSkills && availableSkills.length > 0 ? (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                {availableSkills.filter(s => !s.alreadyImported).length} of {availableSkills.length} skills available for import
              </p>
              {availableSkills.map((skill) => (
                <div
                  key={skill.dirName}
                  className={`border rounded-lg p-4 flex items-start justify-between gap-4 ${skill.alreadyImported ? "opacity-60 bg-muted/30" : ""}`}
                  data-testid={`skill-row-${skill.dirName}`}
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <Zap className="w-4 h-4 text-amber-500 flex-shrink-0" />
                      <span className="font-medium text-sm truncate">{skill.name}</span>
                      {skill.alreadyImported && (
                        <Badge variant="secondary" className="text-[10px] flex-shrink-0">
                          <CheckCircle2 className="w-3 h-3 mr-1" />
                          Imported
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{skill.description || "No description"}</p>
                    <div className="flex items-center gap-2 mt-1.5">
                      <Badge variant="outline" className="text-[10px]">{skill.dirName}</Badge>
                      {skill.hasReferences && (
                        <Badge variant="outline" className="text-[10px]">
                          {skill.referenceFiles.length} ref{skill.referenceFiles.length !== 1 ? "s" : ""}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant={skill.alreadyImported ? "ghost" : "default"}
                    disabled={skill.alreadyImported || importingSkill === skill.dirName}
                    onClick={() => {
                      setImportingSkill(skill.dirName);
                      importSkillMutation.mutate(skill.dirName);
                    }}
                    data-testid={`button-import-${skill.dirName}`}
                  >
                    {importingSkill === skill.dirName ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : skill.alreadyImported ? (
                      <CheckCircle2 className="w-4 h-4" />
                    ) : (
                      <>
                        <Download className="w-4 h-4 mr-1" />
                        Import
                      </>
                    )}
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8">
              <BookOpen className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
              <p className="text-sm text-muted-foreground">No skills found in the skills directory.</p>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

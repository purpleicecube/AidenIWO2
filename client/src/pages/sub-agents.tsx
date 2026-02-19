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
import { useToast } from "@/hooks/use-toast";
import { usePageTitle } from "@/hooks/use-page-title";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { Bot, Plus, Pencil, Trash2, Loader2, Brain, UserCheck } from "lucide-react";
import type { SubAgent } from "@shared/schema";

const subAgentFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  type: z.string().min(1, "Type is required"),
  controlMode: z.string().min(1, "Control mode is required"),
  assignedTo: z.string().nullable().optional(),
  status: z.string().min(1, "Status is required"),
  description: z.string().nullable().optional(),
});

type SubAgentForm = z.infer<typeof subAgentFormSchema>;

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
    },
  });

  const watchControlMode = form.watch("controlMode");

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
    form.reset({
      name: "",
      type: "general",
      controlMode: "aiden",
      assignedTo: null,
      status: "active",
      description: null,
    });
    setDialogOpen(true);
  }

  function openEdit(agent: SubAgent) {
    setEditingAgent(agent);
    form.reset({
      name: agent.name,
      type: agent.type,
      controlMode: agent.controlMode,
      assignedTo: agent.assignedTo,
      status: agent.status,
      description: agent.description,
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
        <DialogContent className="sm:max-w-md">
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

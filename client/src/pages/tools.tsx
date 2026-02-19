import { useQuery, useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState, useEffect } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
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
import { Terminal, Zap, Globe, Link2, Plus, Pencil, Trash2, Loader2, Wrench } from "lucide-react";
import type { Tool } from "@shared/schema";

const toolFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  slug: z.string().min(2, "Slug must be at least 2 characters"),
  description: z.string().nullable().optional(),
  type: z.string().min(1, "Type is required"),
  category: z.string().min(1, "Category is required"),
  status: z.string().min(1, "Status is required"),
  version: z.string().min(1, "Version is required"),
});

type ToolForm = z.infer<typeof toolFormSchema>;

const typeIcons: Record<string, typeof Terminal> = {
  slash_command: Terminal,
  skill: Zap,
  cli: Terminal,
  api: Globe,
  webhook: Link2,
};

const typeLabels: Record<string, string> = {
  slash_command: "Slash Command",
  skill: "Skill",
  cli: "CLI",
  api: "API",
  webhook: "Webhook",
};

function slugify(str: string): string {
  return str
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function ToolCard({ tool, onEdit, onDelete }: { tool: Tool; onEdit: (t: Tool) => void; onDelete: (id: string) => void }) {
  const TypeIcon = typeIcons[tool.type] || Wrench;

  return (
    <Card data-testid={`card-tool-${tool.id}`}>
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
                  className={`border-transparent no-default-hover-elevate no-default-active-elevate ${
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
              </div>
              <p className="text-xs text-muted-foreground mt-0.5 font-mono" data-testid={`text-tool-slug-${tool.id}`}>{tool.slug}</p>
              {tool.description && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2" data-testid={`text-tool-description-${tool.id}`}>{tool.description}</p>
              )}
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                <Badge
                  variant="outline"
                  className="border-transparent no-default-hover-elevate no-default-active-elevate bg-primary/10 text-primary dark:bg-primary/20"
                  data-testid={`badge-tool-type-${tool.id}`}
                >
                  {typeLabels[tool.type] || tool.type}
                </Badge>
                <Badge
                  variant="outline"
                  className="border-transparent no-default-hover-elevate no-default-active-elevate bg-muted text-muted-foreground"
                  data-testid={`badge-tool-category-${tool.id}`}
                >
                  {tool.category}
                </Badge>
                <span className="text-xs text-muted-foreground" data-testid={`text-tool-version-${tool.id}`}>v{tool.version}</span>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
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

export default function ToolsPage() {
  usePageTitle("Tools");
  const { toast } = useToast();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTool, setEditingTool] = useState<Tool | null>(null);

  const { data: tools, isLoading } = useQuery<Tool[]>({
    queryKey: ["/api/tools"],
  });

  const form = useForm<ToolForm>({
    resolver: zodResolver(toolFormSchema),
    defaultValues: {
      name: "",
      slug: "",
      description: null,
      type: "skill",
      category: "general",
      status: "active",
      version: "1.0.0",
    },
  });

  const watchName = form.watch("name");

  useEffect(() => {
    if (!editingTool) {
      form.setValue("slug", slugify(watchName));
    }
  }, [watchName, editingTool, form]);

  const createMutation = useMutation({
    mutationFn: (values: ToolForm) =>
      apiRequest("POST", "/api/tools", values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
      toast({ title: "Tool created" });
      setDialogOpen(false);
      form.reset();
    },
    onError: (err: any) => {
      toast({ title: "Failed to create tool", description: err.message, variant: "destructive" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: ToolForm) =>
      apiRequest("PUT", `/api/tools/${editingTool?.id}`, values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
      toast({ title: "Tool updated" });
      setDialogOpen(false);
      setEditingTool(null);
      form.reset();
    },
    onError: (err: any) => {
      toast({ title: "Failed to update tool", description: err.message, variant: "destructive" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => apiRequest("DELETE", `/api/tools/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/tools"] });
      toast({ title: "Tool removed" });
    },
    onError: (err: any) => {
      toast({ title: "Failed to delete", description: err.message, variant: "destructive" });
    },
  });

  function openCreate() {
    setEditingTool(null);
    form.reset({
      name: "",
      slug: "",
      description: null,
      type: "skill",
      category: "general",
      status: "active",
      version: "1.0.0",
    });
    setDialogOpen(true);
  }

  function openEdit(tool: Tool) {
    setEditingTool(tool);
    form.reset({
      name: tool.name,
      slug: tool.slug,
      description: tool.description,
      type: tool.type,
      category: tool.category,
      status: tool.status,
      version: tool.version,
    });
    setDialogOpen(true);
  }

  function onSubmit(values: ToolForm) {
    if (editingTool) {
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
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-tools-title">
            Tools
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Deploy and manage agentic tools — slash commands, skills, and CLI approaches
          </p>
        </div>
        <Button onClick={openCreate} data-testid="button-deploy-tool">
          <Plus className="w-4 h-4 mr-2" />
          Deploy Tool
        </Button>
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
            />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Wrench className="w-12 h-12 text-muted-foreground/30 mb-4" />
            <p className="text-sm text-muted-foreground">No tools registered</p>
            <p className="text-xs text-muted-foreground mt-1">
              Deploy agentic tools to extend sub-agent capabilities
            </p>
            <Button className="mt-4" onClick={openCreate} data-testid="button-deploy-tool-empty">
              <Plus className="w-4 h-4 mr-2" />
              Deploy First Tool
            </Button>
          </CardContent>
        </Card>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editingTool ? "Edit Tool" : "Deploy Tool"}</DialogTitle>
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
                      <Input {...field} placeholder="e.g. Deploy Checker" data-testid="input-tool-name" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="slug"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Slug</FormLabel>
                    <FormControl>
                      <Input {...field} placeholder="e.g. deploy-checker" className="font-mono" data-testid="input-tool-slug" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value || ""}
                        placeholder="What does this tool do?"
                        className="resize-none"
                        data-testid="input-tool-description"
                      />
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
                          <SelectTrigger data-testid="select-tool-type">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="slash_command">Slash Command</SelectItem>
                          <SelectItem value="skill">Skill</SelectItem>
                          <SelectItem value="cli">CLI</SelectItem>
                          <SelectItem value="api">API</SelectItem>
                          <SelectItem value="webhook">Webhook</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="category"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Category</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger data-testid="select-tool-category">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="general">General</SelectItem>
                          <SelectItem value="deployment">Deployment</SelectItem>
                          <SelectItem value="security">Security</SelectItem>
                          <SelectItem value="monitoring">Monitoring</SelectItem>
                          <SelectItem value="communication">Communication</SelectItem>
                          <SelectItem value="data">Data</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={form.control}
                  name="status"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Status</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger data-testid="select-tool-status">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="active">Active</SelectItem>
                          <SelectItem value="inactive">Inactive</SelectItem>
                          <SelectItem value="deprecated">Deprecated</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="version"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Version</FormLabel>
                      <FormControl>
                        <Input {...field} placeholder="1.0.0" data-testid="input-tool-version" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={isPending} data-testid="button-save-tool">
                  {isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : null}
                  {editingTool ? "Update" : "Deploy"}
                </Button>
              </div>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

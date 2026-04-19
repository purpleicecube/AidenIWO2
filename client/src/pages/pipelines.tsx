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
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { usePageTitle } from "@/hooks/use-page-title";
import { apiRequest, queryClient } from "@/lib/queryClient";
import {
  Layers,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  FileText,
  GitBranch,
  Globe,
  FileDown,
  BookOpen,
  Archive,
  Eye,
} from "lucide-react";
import type { Pipeline } from "@shared/schema";

const pipelineFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  slug: z.string().min(2, "Slug must be at least 2 characters").regex(/^[a-z0-9-]+$/, "Lowercase letters, numbers, and hyphens only"),
  description: z.string().nullable().optional(),
  overview: z.string().nullable().optional(),
  diagram: z.string().nullable().optional(),
  outputFormat: z.string().nullable().optional(),
  category: z.string().min(1, "Category is required"),
  status: z.string().min(1, "Status is required"),
  owner: z.string().nullable().optional(),
});

type PipelineForm = z.infer<typeof pipelineFormSchema>;

const categories = [
  { value: "research", label: "Research" },
  { value: "presentation", label: "Presentation" },
  { value: "document", label: "Document" },
  { value: "web", label: "Web / Landing Page" },
  { value: "sop", label: "SOP" },
  { value: "general", label: "General" },
];

const outputFormats = [
  { value: "pdf", label: "PDF" },
  { value: "pptx", label: "PPTX" },
  { value: "html", label: "HTML" },
  { value: "docx", label: "DOCX" },
  { value: "md", label: "Markdown" },
];

function categoryBadgeClass(category: string) {
  switch (category) {
    case "research":
      return "bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400";
    case "presentation":
      return "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400";
    case "document":
      return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
    case "web":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
    case "sop":
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function statusBadgeClass(status: string) {
  switch (status) {
    case "active":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
    case "draft":
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
    case "archived":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function formatIcon(format: string | null) {
  switch (format) {
    case "pdf":
      return <FileDown className="w-3.5 h-3.5" />;
    case "pptx":
      return <Layers className="w-3.5 h-3.5" />;
    case "html":
      return <Globe className="w-3.5 h-3.5" />;
    case "md":
    case "docx":
      return <FileText className="w-3.5 h-3.5" />;
    default:
      return <GitBranch className="w-3.5 h-3.5" />;
  }
}

export default function PipelinesPage() {
  usePageTitle("Pipelines");
  const { toast } = useToast();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingPipeline, setEditingPipeline] = useState<Pipeline | null>(null);
  const [viewingPipeline, setViewingPipeline] = useState<Pipeline | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Pipeline | null>(null);

  const { data: pipelinesData, isLoading } = useQuery<Pipeline[]>({
    queryKey: ["/api/pipelines"],
  });

  const form = useForm<PipelineForm>({
    resolver: zodResolver(pipelineFormSchema),
    defaultValues: {
      name: "",
      slug: "",
      description: "",
      overview: "",
      diagram: "",
      outputFormat: "",
      category: "general",
      status: "active",
      owner: "",
    },
  });

  const createMutation = useMutation({
    mutationFn: async (data: PipelineForm) => {
      const res = await apiRequest("POST", "/api/pipelines", data);
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/pipelines"] });
      setDialogOpen(false);
      form.reset();
      toast({ title: "Pipeline created" });
    },
    onError: (err: any) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, data }: { id: string; data: PipelineForm }) => {
      const res = await apiRequest("PUT", `/api/pipelines/${id}`, data);
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/pipelines"] });
      setDialogOpen(false);
      setEditingPipeline(null);
      form.reset();
      toast({ title: "Pipeline updated" });
    },
    onError: (err: any) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const res = await apiRequest("DELETE", `/api/pipelines/${id}`);
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/pipelines"] });
      setDeleteTarget(null);
      toast({ title: "Pipeline deleted" });
    },
    onError: (err: any) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  const archiveMutation = useMutation({
    mutationFn: async (id: string) => {
      const res = await apiRequest("PUT", `/api/pipelines/${id}`, { status: "archived" });
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/pipelines"] });
      toast({ title: "Pipeline archived" });
    },
    onError: (err: any) => {
      toast({ title: "Error", description: err.message, variant: "destructive" });
    },
  });

  function openCreate() {
    setEditingPipeline(null);
    form.reset({
      name: "",
      slug: "",
      description: "",
      overview: "",
      diagram: "",
      outputFormat: "",
      category: "general",
      status: "active",
      owner: "",
    });
    setDialogOpen(true);
  }

  function openEdit(pipeline: Pipeline) {
    setEditingPipeline(pipeline);
    form.reset({
      name: pipeline.name,
      slug: pipeline.slug,
      description: pipeline.description || "",
      overview: pipeline.overview || "",
      diagram: pipeline.diagram || "",
      outputFormat: pipeline.outputFormat || "",
      category: pipeline.category,
      status: pipeline.status,
      owner: pipeline.owner || "",
    });
    setDialogOpen(true);
  }

  function onSubmit(data: PipelineForm) {
    if (editingPipeline) {
      updateMutation.mutate({ id: editingPipeline.id, data });
    } else {
      createMutation.mutate(data);
    }
  }

  // Auto-generate slug from name
  function handleNameChange(value: string) {
    form.setValue("name", value);
    if (!editingPipeline) {
      const slug = value
        .toLowerCase()
        .replace(/[^a-z0-9\s-]/g, "")
        .replace(/\s+/g, "-")
        .slice(0, 60);
      form.setValue("slug", slug);
    }
  }

  const activePipelines = pipelinesData?.filter((p) => p.status !== "archived") || [];
  const archivedPipelines = pipelinesData?.filter((p) => p.status === "archived") || [];

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Pipelines</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Define and manage artifact pipelines — each pipeline describes how a specific output format
            (PDF, PPTX, HTML, etc.) is produced, including its processing stages and routing logic.
          </p>
        </div>
        <Button onClick={openCreate} data-testid="button-create-pipeline">
          <Plus className="w-4 h-4 mr-2" />
          New Pipeline
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin" />
        </div>
      ) : activePipelines.length === 0 && archivedPipelines.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <Layers className="w-10 h-10 mx-auto mb-3 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">No pipelines defined yet.</p>
            <Button variant="outline" size="sm" className="mt-4" onClick={openCreate}>
              <Plus className="w-3.5 h-3.5 mr-2" /> Create your first pipeline
            </Button>
          </CardContent>
        </Card>
      ) : (
        <Tabs defaultValue="active">
          <TabsList>
            <TabsTrigger value="active">Active ({activePipelines.length})</TabsTrigger>
            {archivedPipelines.length > 0 && (
              <TabsTrigger value="archived">Archived ({archivedPipelines.length})</TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="active" className="space-y-3 mt-4">
            {activePipelines.map((pipeline) => (
              <PipelineCard
                key={pipeline.id}
                pipeline={pipeline}
                onEdit={openEdit}
                onView={setViewingPipeline}
                onArchive={(p) => archiveMutation.mutate(p.id)}
                onDelete={setDeleteTarget}
              />
            ))}
          </TabsContent>

          {archivedPipelines.length > 0 && (
            <TabsContent value="archived" className="space-y-3 mt-4">
              {archivedPipelines.map((pipeline) => (
                <PipelineCard
                  key={pipeline.id}
                  pipeline={pipeline}
                  onEdit={openEdit}
                  onView={setViewingPipeline}
                  onDelete={setDeleteTarget}
                />
              ))}
            </TabsContent>
          )}
        </Tabs>
      )}

      {/* View Dialog */}
      <Dialog open={!!viewingPipeline} onOpenChange={() => setViewingPipeline(null)}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {viewingPipeline && formatIcon(viewingPipeline.outputFormat)}
              {viewingPipeline?.name}
            </DialogTitle>
          </DialogHeader>
          {viewingPipeline && (
            <div className="space-y-4">
              {viewingPipeline.description && (
                <p className="text-sm text-muted-foreground">{viewingPipeline.description}</p>
              )}
              {viewingPipeline.overview && (
                <div>
                  <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
                    <BookOpen className="w-3.5 h-3.5" /> Overview
                  </h3>
                  <pre className="text-xs bg-muted rounded-md p-4 whitespace-pre-wrap overflow-auto max-h-72">
                    {viewingPipeline.overview}
                  </pre>
                </div>
              )}
              {viewingPipeline.diagram && (
                <div>
                  <h3 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
                    <GitBranch className="w-3.5 h-3.5" /> Mermaid Diagram
                  </h3>
                  <pre className="text-xs bg-muted rounded-md p-4 whitespace-pre-wrap overflow-auto max-h-96 font-mono">
                    {viewingPipeline.diagram}
                  </pre>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Create/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editingPipeline ? "Edit Pipeline" : "New Pipeline"}</DialogTitle>
          </DialogHeader>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Name</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          onChange={(e) => handleNameChange(e.target.value)}
                          placeholder="PDF Document Pipeline"
                          data-testid="input-pipeline-name"
                        />
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
                        <Input {...field} placeholder="pdf-document-pipeline" data-testid="input-pipeline-slug" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

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
                        placeholder="Short description of what this pipeline produces and when it's used..."
                        rows={2}
                        data-testid="input-pipeline-description"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-3 gap-4">
                <FormField
                  control={form.control}
                  name="category"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Category</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger data-testid="select-pipeline-category">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {categories.map((c) => (
                            <SelectItem key={c.value} value={c.value}>{c.label}</SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="outputFormat"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Output Format</FormLabel>
                      <Select onValueChange={field.onChange} value={field.value || ""}>
                        <FormControl>
                          <SelectTrigger data-testid="select-pipeline-format">
                            <SelectValue placeholder="Any" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="any">Any</SelectItem>
                          {outputFormats.map((f) => (
                            <SelectItem key={f.value} value={f.value}>{f.label}</SelectItem>
                          ))}
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
                          <SelectTrigger data-testid="select-pipeline-status">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="active">Active</SelectItem>
                          <SelectItem value="draft">Draft</SelectItem>
                          <SelectItem value="archived">Archived</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="owner"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Owner</FormLabel>
                    <FormControl>
                      <Input {...field} value={field.value || ""} placeholder="e.g. darrel" data-testid="input-pipeline-owner" />
                    </FormControl>
                    <FormDescription>Optional. Who maintains this pipeline definition.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="overview"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Overview (Markdown)</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value || ""}
                        placeholder={"## PDF Pipeline\n\nDescribes how PDF artifacts are produced...\n\n### Stages\n1. Content generation (sub-agent)\n2. Gamma API conversion\n3. Local fallback (pandoc + Playwright)"}
                        rows={8}
                        className="font-mono text-xs"
                        data-testid="input-pipeline-overview"
                      />
                    </FormControl>
                    <FormDescription>Markdown description of the pipeline stages, routing, and behavior.</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="diagram"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Diagram (Mermaid)</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value || ""}
                        placeholder={"graph TD\n  A[WO Submitted] --> B[Tier 1 Gate]\n  B --> C{Format?}\n  C -->|PDF| D[Gamma API]\n  C -->|PPTX| E[Gamma API]\n  D --> F[Filing]"}
                        rows={10}
                        className="font-mono text-xs"
                        data-testid="input-pipeline-diagram"
                      />
                    </FormControl>
                    <FormDescription>Mermaid flowchart or sequence diagram (.mmd syntax).</FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="flex justify-end gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setDialogOpen(false)}>
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={createMutation.isPending || updateMutation.isPending}
                  data-testid="button-save-pipeline"
                >
                  {(createMutation.isPending || updateMutation.isPending) && (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  )}
                  {editingPipeline ? "Save Changes" : "Create Pipeline"}
                </Button>
              </div>
            </form>
          </Form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteTarget} onOpenChange={() => setDeleteTarget(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete pipeline "{deleteTarget?.name}"?</AlertDialogTitle>
            <AlertDialogDescription>
              This permanently removes the pipeline definition. Consider archiving instead if you may need it later.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

function PipelineCard({
  pipeline,
  onEdit,
  onView,
  onArchive,
  onDelete,
}: {
  pipeline: Pipeline;
  onEdit: (p: Pipeline) => void;
  onView: (p: Pipeline) => void;
  onArchive?: (p: Pipeline) => void;
  onDelete: (p: Pipeline) => void;
}) {
  return (
    <Card data-testid={`card-pipeline-${pipeline.id}`}>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary dark:bg-primary/20 flex-shrink-0 mt-0.5">
              {formatIcon(pipeline.outputFormat)}
            </div>
            <div className="min-w-0 flex-1">
              <CardTitle className="text-base">{pipeline.name}</CardTitle>
              {pipeline.description && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">{pipeline.description}</p>
              )}
              <div className="flex items-center gap-2 mt-2 flex-wrap">
                <Badge
                  variant="outline"
                  className={`border-transparent text-[10px] px-1.5 py-0 h-4 ${categoryBadgeClass(pipeline.category)}`}
                >
                  {pipeline.category}
                </Badge>
                <Badge
                  variant="outline"
                  className={`border-transparent text-[10px] px-1.5 py-0 h-4 ${statusBadgeClass(pipeline.status)}`}
                >
                  {pipeline.status}
                </Badge>
                {pipeline.outputFormat && (
                  <Badge variant="outline" className="border-transparent text-[10px] px-1.5 py-0 h-4 bg-muted text-muted-foreground">
                    {pipeline.outputFormat.toUpperCase()}
                  </Badge>
                )}
                {pipeline.owner && (
                  <span className="text-[10px] text-muted-foreground">by {pipeline.owner}</span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {(pipeline.overview || pipeline.diagram) && (
              <Button size="icon" variant="ghost" onClick={() => onView(pipeline)} title="View">
                <Eye className="w-3.5 h-3.5" />
              </Button>
            )}
            <Button size="icon" variant="ghost" onClick={() => onEdit(pipeline)} title="Edit">
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            {onArchive && pipeline.status !== "archived" && (
              <Button size="icon" variant="ghost" onClick={() => onArchive(pipeline)} title="Archive">
                <Archive className="w-3.5 h-3.5" />
              </Button>
            )}
            <Button size="icon" variant="ghost" onClick={() => onDelete(pipeline)} title="Delete">
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </CardHeader>
    </Card>
  );
}

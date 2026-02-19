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
import { Separator } from "@/components/ui/separator";
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
import {
  GitBranch,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  Play,
  ChevronDown,
  ChevronUp,
  ListOrdered,
  Clock,
  CheckCircle,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import type {
  WorkflowTemplate,
  WorkflowStep,
  WorkflowExecution,
} from "@shared/schema";

const templateFormSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  description: z.string().nullable().optional(),
  goal: z.string().nullable().optional(),
  category: z.string().min(1, "Category is required"),
  status: z.string().min(1, "Status is required"),
});

type TemplateForm = z.infer<typeof templateFormSchema>;

const stepFormSchema = z.object({
  stepKey: z.string().min(1, "Step key is required"),
  name: z.string().min(2, "Name must be at least 2 characters"),
  description: z.string().nullable().optional(),
  order: z.coerce.number().int().min(0),
  agentType: z.string().nullable().optional(),
});

type StepForm = z.infer<typeof stepFormSchema>;

interface TemplateWithSteps extends WorkflowTemplate {
  steps?: WorkflowStep[];
}

interface ExecutionWithTemplate extends WorkflowExecution {
  templateName?: string;
  stepRuns?: { total: number; completed: number };
}

function categoryBadgeClass(category: string) {
  switch (category) {
    case "deployment":
      return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
    case "security":
      return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
    case "maintenance":
      return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400";
    case "incident":
      return "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function statusBadgeClass(status: string) {
  switch (status) {
    case "active":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
    case "running":
      return "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400";
    case "completed":
      return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400";
    case "failed":
      return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function ExecutionStatusIcon({ status }: { status: string }) {
  switch (status) {
    case "running":
      return <Loader2 className="w-3 h-3 animate-spin" />;
    case "completed":
      return <CheckCircle className="w-3 h-3" />;
    case "failed":
      return <XCircle className="w-3 h-3" />;
    case "blocked":
      return <AlertTriangle className="w-3 h-3" />;
    default:
      return <Clock className="w-3 h-3" />;
  }
}

function StepCard({
  step,
  onDelete,
}: {
  step: WorkflowStep;
  onDelete: (id: string) => void;
}) {
  return (
    <div
      className="flex items-start justify-between gap-3 p-3 rounded-md bg-muted/40"
      data-testid={`card-step-${step.id}`}
    >
      <div className="flex items-start gap-3 min-w-0 flex-1">
        <div className="flex items-center justify-center w-7 h-7 rounded-md bg-primary/10 text-primary dark:bg-primary/20 flex-shrink-0 mt-0.5 text-xs font-semibold">
          {step.order}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-medium">{step.name}</p>
            <Badge
              variant="outline"
              className="border-transparent no-default-hover-elevate no-default-active-elevate bg-muted text-muted-foreground"
              data-testid={`badge-step-key-${step.id}`}
            >
              {step.stepKey}
            </Badge>
          </div>
          {step.description && (
            <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
              {step.description}
            </p>
          )}
          {step.agentType && (
            <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-1.5">
              <span className="font-medium">Agent:</span> {step.agentType}
            </div>
          )}
        </div>
      </div>
      <Button
        size="icon"
        variant="ghost"
        onClick={() => onDelete(step.id)}
        data-testid={`button-delete-step-${step.id}`}
      >
        <Trash2 className="w-3.5 h-3.5" />
      </Button>
    </div>
  );
}

function TemplateCard({
  template,
  onEdit,
  onDelete,
  onExpand,
  isExpanded,
}: {
  template: WorkflowTemplate;
  onEdit: (t: WorkflowTemplate) => void;
  onDelete: (id: string) => void;
  onExpand: (id: string) => void;
  isExpanded: boolean;
}) {
  return (
    <Card data-testid={`card-workflow-template-${template.id}`}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3 min-w-0 flex-1">
            <div className="flex items-center justify-center w-9 h-9 rounded-md bg-primary/10 text-primary dark:bg-primary/20 flex-shrink-0 mt-0.5">
              <GitBranch className="w-4 h-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 flex-wrap">
                <p className="text-sm font-medium">{template.name}</p>
                <Badge
                  variant="outline"
                  className={`border-transparent no-default-hover-elevate no-default-active-elevate ${statusBadgeClass(template.status)}`}
                  data-testid={`badge-template-status-${template.id}`}
                >
                  {template.status}
                </Badge>
                <Badge
                  variant="outline"
                  className={`border-transparent no-default-hover-elevate no-default-active-elevate ${categoryBadgeClass(template.category)}`}
                  data-testid={`badge-template-category-${template.id}`}
                >
                  {template.category}
                </Badge>
              </div>
              {template.description && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                  {template.description}
                </p>
              )}
              {template.goal && (
                <p className="text-xs text-muted-foreground mt-1 line-clamp-1">
                  <span className="font-medium">Goal:</span> {template.goal}
                </p>
              )}
              <div className="flex items-center gap-3 mt-2 flex-wrap">
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Clock className="w-3 h-3" />
                  {new Date(template.createdAt).toLocaleDateString()}
                </div>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1 flex-shrink-0">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => onExpand(template.id)}
              data-testid={`button-expand-template-${template.id}`}
            >
              {isExpanded ? (
                <ChevronUp className="w-3.5 h-3.5" />
              ) : (
                <ChevronDown className="w-3.5 h-3.5" />
              )}
            </Button>
            <Button
              size="icon"
              variant="ghost"
              onClick={() => onEdit(template)}
              data-testid={`button-edit-template-${template.id}`}
            >
              <Pencil className="w-3.5 h-3.5" />
            </Button>
            <Button
              size="icon"
              variant="ghost"
              onClick={() => onDelete(template.id)}
              data-testid={`button-delete-template-${template.id}`}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ExpandedSteps({ templateId }: { templateId: string }) {
  const { toast } = useToast();
  const [stepDialogOpen, setStepDialogOpen] = useState(false);

  const { data: templateDetail, isLoading } = useQuery<TemplateWithSteps>({
    queryKey: ["/api/workflow-templates", templateId],
  });

  const stepForm = useForm<StepForm>({
    resolver: zodResolver(stepFormSchema),
    defaultValues: {
      stepKey: "",
      name: "",
      description: null,
      order: 0,
      agentType: null,
    },
  });

  const createStepMutation = useMutation({
    mutationFn: (values: StepForm) =>
      apiRequest("POST", `/api/workflow-templates/${templateId}/steps`, {
        ...values,
        templateId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["/api/workflow-templates", templateId],
      });
      queryClient.invalidateQueries({
        queryKey: ["/api/workflow-templates"],
      });
      toast({ title: "Step added" });
      setStepDialogOpen(false);
      stepForm.reset();
    },
    onError: (err: any) => {
      toast({
        title: "Failed to add step",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const deleteStepMutation = useMutation({
    mutationFn: (id: string) => apiRequest("DELETE", `/api/workflow-steps/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["/api/workflow-templates", templateId],
      });
      queryClient.invalidateQueries({
        queryKey: ["/api/workflow-templates"],
      });
      toast({ title: "Step removed" });
    },
    onError: (err: any) => {
      toast({
        title: "Failed to delete step",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const steps = templateDetail?.steps || [];
  const sortedSteps = [...steps].sort((a, b) => a.order - b.order);

  if (isLoading) {
    return (
      <div className="space-y-2 p-4 pt-0">
        {[1, 2].map((i) => (
          <div
            key={i}
            className="h-16 rounded-md bg-muted/40 animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="px-4 pb-4 space-y-3">
      <Separator />
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <ListOrdered className="w-4 h-4 text-muted-foreground" />
          <p className="text-sm font-medium">
            Steps ({sortedSteps.length})
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            stepForm.reset({
              stepKey: "",
              name: "",
              description: null,
              order: sortedSteps.length,
              agentType: null,
            });
            setStepDialogOpen(true);
          }}
          data-testid={`button-add-step-${templateId}`}
        >
          <Plus className="w-3.5 h-3.5 mr-1.5" />
          Add Step
        </Button>
      </div>

      {sortedSteps.length > 0 ? (
        <div className="space-y-2">
          {sortedSteps.map((step) => (
            <StepCard
              key={step.id}
              step={step}
              onDelete={(id) => deleteStepMutation.mutate(id)}
            />
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground text-center py-4">
          No steps defined. Add steps to build this workflow.
        </p>
      )}

      <Dialog open={stepDialogOpen} onOpenChange={setStepDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add Step</DialogTitle>
          </DialogHeader>
          <Form {...stepForm}>
            <form
              onSubmit={stepForm.handleSubmit((v) =>
                createStepMutation.mutate(v)
              )}
              className="space-y-4"
            >
              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={stepForm.control}
                  name="stepKey"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Step Key</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          placeholder="e.g. validate_input"
                          data-testid="input-step-key"
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={stepForm.control}
                  name="order"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Order</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          type="number"
                          data-testid="input-step-order"
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={stepForm.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="e.g. Validate Input"
                        data-testid="input-step-name"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={stepForm.control}
                name="description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value || ""}
                        placeholder="What does this step do?"
                        className="resize-none"
                        data-testid="input-step-description"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={stepForm.control}
                name="agentType"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Agent Type</FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value || ""}
                    >
                      <FormControl>
                        <SelectTrigger data-testid="select-step-agent-type">
                          <SelectValue placeholder="Select agent type" />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        <SelectItem value="general">General</SelectItem>
                        <SelectItem value="deployment">Deployment</SelectItem>
                        <SelectItem value="maintenance">Maintenance</SelectItem>
                        <SelectItem value="incident">Incident</SelectItem>
                        <SelectItem value="change_request">
                          Change Request
                        </SelectItem>
                        <SelectItem value="security">Security</SelectItem>
                      </SelectContent>
                    </Select>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setStepDialogOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={createStepMutation.isPending}
                  data-testid="button-save-step"
                >
                  {createStepMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : null}
                  Add Step
                </Button>
              </div>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function WorkflowsPage() {
  usePageTitle("Workflows");
  const { toast } = useToast();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingTemplate, setEditingTemplate] =
    useState<WorkflowTemplate | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: templates, isLoading } = useQuery<WorkflowTemplate[]>({
    queryKey: ["/api/workflow-templates"],
  });

  const { data: executions, isLoading: executionsLoading } = useQuery<
    ExecutionWithTemplate[]
  >({
    queryKey: ["/api/workflow-executions"],
  });

  const form = useForm<TemplateForm>({
    resolver: zodResolver(templateFormSchema),
    defaultValues: {
      name: "",
      description: null,
      goal: null,
      category: "general",
      status: "active",
    },
  });

  const createMutation = useMutation({
    mutationFn: (values: TemplateForm) =>
      apiRequest("POST", "/api/workflow-templates", values),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["/api/workflow-templates"],
      });
      toast({ title: "Workflow template created" });
      setDialogOpen(false);
      form.reset();
    },
    onError: (err: any) => {
      toast({
        title: "Failed to create template",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const updateMutation = useMutation({
    mutationFn: (values: TemplateForm) =>
      apiRequest(
        "PUT",
        `/api/workflow-templates/${editingTemplate?.id}`,
        values
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["/api/workflow-templates"],
      });
      toast({ title: "Workflow template updated" });
      setDialogOpen(false);
      setEditingTemplate(null);
      form.reset();
    },
    onError: (err: any) => {
      toast({
        title: "Failed to update template",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) =>
      apiRequest("DELETE", `/api/workflow-templates/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["/api/workflow-templates"],
      });
      toast({ title: "Template deleted" });
    },
    onError: (err: any) => {
      toast({
        title: "Failed to delete",
        description: err.message,
        variant: "destructive",
      });
    },
  });

  function openCreate() {
    setEditingTemplate(null);
    form.reset({
      name: "",
      description: null,
      goal: null,
      category: "general",
      status: "active",
    });
    setDialogOpen(true);
  }

  function openEdit(template: WorkflowTemplate) {
    setEditingTemplate(template);
    form.reset({
      name: template.name,
      description: template.description,
      goal: template.goal,
      category: template.category,
      status: template.status,
    });
    setDialogOpen(true);
  }

  function onSubmit(values: TemplateForm) {
    if (editingTemplate) {
      updateMutation.mutate(values);
    } else {
      createMutation.mutate(values);
    }
  }

  function toggleExpand(id: string) {
    setExpandedId((prev) => (prev === id ? null : id));
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  function getTemplateName(templateId: string) {
    const t = templates?.find((t) => t.id === templateId);
    return t?.name || "Unknown";
  }

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1
            className="text-2xl font-semibold tracking-tight"
            data-testid="text-workflows-title"
          >
            Workflows
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Define reusable workflow templates with ordered steps for
            orchestrated execution.
          </p>
        </div>
        <Button onClick={openCreate} data-testid="button-create-workflow">
          <Plus className="w-4 h-4 mr-2" />
          New Workflow
        </Button>
      </div>

      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-24 rounded-md bg-muted/40 animate-pulse"
            />
          ))}
        </div>
      ) : templates && templates.length > 0 ? (
        <div className="space-y-3">
          {templates.map((template) => (
            <div key={template.id}>
              <TemplateCard
                template={template}
                onEdit={openEdit}
                onDelete={(id) => deleteMutation.mutate(id)}
                onExpand={toggleExpand}
                isExpanded={expandedId === template.id}
              />
              {expandedId === template.id && (
                <Card className="mt-1 border-t-0 rounded-t-none">
                  <ExpandedSteps templateId={template.id} />
                </Card>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <GitBranch className="w-12 h-12 text-muted-foreground/30 mb-4" />
            <p className="text-sm text-muted-foreground">
              No workflow templates defined
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              Create workflow templates to orchestrate multi-step processes
            </p>
            <Button
              className="mt-4"
              onClick={openCreate}
              data-testid="button-create-workflow-empty"
            >
              <Plus className="w-4 h-4 mr-2" />
              Create First Workflow
            </Button>
          </CardContent>
        </Card>
      )}

      <Separator />

      <div>
        <div className="flex items-center gap-2 mb-4">
          <Play className="w-4 h-4 text-muted-foreground" />
          <h2 className="text-lg font-semibold tracking-tight">
            Recent Executions
          </h2>
        </div>

        {executionsLoading ? (
          <div className="space-y-2">
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="h-14 rounded-md bg-muted/40 animate-pulse"
              />
            ))}
          </div>
        ) : executions && executions.length > 0 ? (
          <div className="space-y-2">
            {executions.map((exec) => (
              <div
                key={exec.id}
                className="flex items-center justify-between gap-4 p-3 rounded-md bg-muted/30"
                data-testid={`card-execution-${exec.id}`}
              >
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                  <p className="text-sm font-medium truncate">
                    {exec.templateName || getTemplateName(exec.templateId)}
                  </p>
                  {exec.goal && (
                    <p className="text-xs text-muted-foreground truncate">
                      {exec.goal}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
                  {exec.stepRuns && (
                    <span
                      className="text-xs text-muted-foreground"
                      data-testid={`text-step-progress-${exec.id}`}
                    >
                      {exec.stepRuns.completed}/{exec.stepRuns.total} steps
                    </span>
                  )}
                  <Badge
                    variant="outline"
                    className={`border-transparent no-default-hover-elevate no-default-active-elevate gap-1 ${statusBadgeClass(exec.status)}`}
                    data-testid={`badge-execution-status-${exec.id}`}
                  >
                    <ExecutionStatusIcon status={exec.status} />
                    {exec.status}
                  </Badge>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <Play className="w-8 h-8 text-muted-foreground/30 mb-3" />
            <p className="text-sm text-muted-foreground">
              No workflow executions yet
            </p>
          </div>
        )}
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {editingTemplate
                ? "Edit Workflow Template"
                : "Create Workflow Template"}
            </DialogTitle>
          </DialogHeader>
          <Form {...form}>
            <form
              onSubmit={form.handleSubmit(onSubmit)}
              className="space-y-4"
            >
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Name</FormLabel>
                    <FormControl>
                      <Input
                        {...field}
                        placeholder="e.g. Deploy Pipeline"
                        data-testid="input-workflow-name"
                      />
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
                        placeholder="Describe this workflow template"
                        className="resize-none"
                        data-testid="input-workflow-description"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="goal"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Goal</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        value={field.value || ""}
                        placeholder="What is the objective of this workflow?"
                        className="resize-none"
                        data-testid="input-workflow-goal"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-2 gap-3">
                <FormField
                  control={form.control}
                  name="category"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Category</FormLabel>
                      <Select
                        onValueChange={field.onChange}
                        value={field.value}
                      >
                        <FormControl>
                          <SelectTrigger data-testid="select-workflow-category">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="general">General</SelectItem>
                          <SelectItem value="deployment">
                            Deployment
                          </SelectItem>
                          <SelectItem value="security">Security</SelectItem>
                          <SelectItem value="maintenance">
                            Maintenance
                          </SelectItem>
                          <SelectItem value="incident">Incident</SelectItem>
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
                      <Select
                        onValueChange={field.onChange}
                        value={field.value}
                      >
                        <FormControl>
                          <SelectTrigger data-testid="select-workflow-status">
                            <SelectValue />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="active">Active</SelectItem>
                          <SelectItem value="inactive">Inactive</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setDialogOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  disabled={isPending}
                  data-testid="button-save-workflow"
                >
                  {isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : null}
                  {editingTemplate ? "Update" : "Create"}
                </Button>
              </div>
            </form>
          </Form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

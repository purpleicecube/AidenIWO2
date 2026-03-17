import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { z } from "zod";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
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
import { useAuth } from "@/hooks/use-auth";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { insertWorkOrderSchema } from "@shared/schema";
import { Send, ArrowLeft, Layers, Loader2 } from "lucide-react";
import { Link } from "wouter";

const submitOrderSchema = insertWorkOrderSchema.extend({
  title: z.string().min(3, "Title must be at least 3 characters").max(200),
  description: z.string().min(10, "Description must be at least 10 characters").max(8000),
  type: z.string().min(1, "Type is required"),
  priority: z.string().min(1, "Priority is required"),
  submittedBy: z.string().optional(),
  gammaTemplateKey: z.string().nullable().optional(),
});

type SubmitOrderForm = z.infer<typeof submitOrderSchema>;

export default function SubmitOrder() {
  usePageTitle("Submit Work Order");
  const [, navigate] = useLocation();
  const { toast } = useToast();
  const { user } = useAuth();

  if (user && user.role === "viewer") {
    navigate("/");
    return null;
  }

  const { data: gammaTemplates } = useQuery<any[]>({
    queryKey: ["/api/gamma-templates"],
  });

  const form = useForm<SubmitOrderForm>({
    resolver: zodResolver(submitOrderSchema),
    defaultValues: {
      title: "",
      description: "",
      type: "standard",
      priority: "medium",
      submittedBy: "",
    },
  });

  const submitMutation = useMutation({
    mutationFn: (data: SubmitOrderForm) =>
      apiRequest("POST", "/api/work-orders", data),
    onSuccess: async (response) => {
      const order = await response.json();
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/stats"] });
      queryClient.invalidateQueries({ queryKey: ["/api/work-orders/recent"] });
      toast({
        title: "Work order submitted",
        description: "Your work order has been created and is ready for processing.",
      });
      navigate(`/work-orders/${order.id}`);
    },
    onError: () => {
      toast({
        title: "Submission failed",
        description: "Could not submit the work order. Please try again.",
        variant: "destructive",
      });
    },
  });

  const onSubmit = (data: SubmitOrderForm) => {
    submitMutation.mutate({
      ...data,
      gammaTemplateKey: data.gammaTemplateKey || null,
    });
  };

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/work-orders">
          <Button variant="ghost" size="icon" data-testid="button-back">
            <ArrowLeft className="w-4 h-4" />
          </Button>
        </Link>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-submit-title">
            Submit Work Order
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Create a new work order for the orchestration pipeline
          </p>
        </div>
      </div>

      <Card>
        <CardContent className="p-6">
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5">
              <FormField
                control={form.control}
                name="title"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Title</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g., Deploy staging environment update"
                        {...field}
                        data-testid="input-title"
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
                        placeholder="Describe the work order in detail..."
                        className="resize-none min-h-[120px]"
                        {...field}
                        data-testid="input-description"
                      />
                    </FormControl>
                    <FormDescription>
                      Provide enough detail for the orchestration engine to route correctly
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <FormField
                  control={form.control}
                  name="type"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Type</FormLabel>
                      <Select onValueChange={field.onChange} defaultValue={field.value}>
                        <FormControl>
                          <SelectTrigger data-testid="select-type">
                            <SelectValue placeholder="Select type" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="standard">Standard</SelectItem>
                          <SelectItem value="deployment">Deployment</SelectItem>
                          <SelectItem value="maintenance">Maintenance</SelectItem>
                          <SelectItem value="incident">Incident</SelectItem>
                          <SelectItem value="change_request">Change Request</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="priority"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Priority</FormLabel>
                      <Select onValueChange={field.onChange} defaultValue={field.value}>
                        <FormControl>
                          <SelectTrigger data-testid="select-priority">
                            <SelectValue placeholder="Select priority" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="low">Low</SelectItem>
                          <SelectItem value="medium">Medium</SelectItem>
                          <SelectItem value="high">High</SelectItem>
                          <SelectItem value="critical">Critical</SelectItem>
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {gammaTemplates && gammaTemplates.length > 0 && (
                <FormField
                  control={form.control}
                  name="gammaTemplateKey"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Output Template (Brand)</FormLabel>
                      <Select onValueChange={(v) => field.onChange(v === "__default__" ? null : v)} value={field.value || "__default__"}>
                        <FormControl>
                          <SelectTrigger data-testid="select-gamma-template">
                            <SelectValue placeholder="Default (global setting)" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          <SelectItem value="__default__">Default (global setting)</SelectItem>
                          {gammaTemplates.map((t: any) => (
                            <SelectItem key={t.templateKey} value={t.templateKey}>
                              {t.name} ({t.outputFormat.toUpperCase()}, {t.mode})
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              <FormField
                control={form.control}
                name="submittedBy"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Submitted By</FormLabel>
                    <FormControl>
                      <Input
                        placeholder="Your name (optional)"
                        {...field}
                        data-testid="input-submitted-by"
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="flex items-center gap-3 pt-2">
                <Button
                  type="submit"
                  disabled={submitMutation.isPending}
                  data-testid="button-submit"
                >
                  {submitMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4 mr-2" />
                  )}
                  {submitMutation.isPending ? "Submitting..." : "Submit Work Order"}
                </Button>
              </div>

              <div className="flex items-start gap-3 p-3 rounded-md bg-muted/40 mt-2">
                <Layers className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                <p className="text-xs text-muted-foreground">
                  After submission, the work order enters Tier 1 for policy checks and routing, then proceeds to Tier 2 for validation and execution. If blocked, a BDM marker will be emitted.
                </p>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  );
}

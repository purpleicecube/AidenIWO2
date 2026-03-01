import { useQuery, useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Separator } from "@/components/ui/separator";
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
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useToast } from "@/hooks/use-toast";
import { usePageTitle } from "@/hooks/use-page-title";
import { apiRequest, queryClient } from "@/lib/queryClient";
import { Brain, Save, Zap, AlertTriangle, CheckCircle, Loader2, KeyRound } from "lucide-react";
import type { LlmSettings } from "@shared/schema";
import { useState, useEffect } from "react";
import { ModelSelector, providers } from "@/components/model-selector";

interface LlmSettingsResponse {
  settings: LlmSettings;
  apiKeyConfigured: boolean;
  requiredKeyName: string;
}

const settingsFormSchema = z.object({
  provider: z.string().min(1, "Provider is required"),
  model: z.string().min(1, "Model is required"),
  baseUrl: z.string().nullable().optional(),
  systemPrompt: z.string().min(10, "System prompt must be at least 10 characters"),
  enabled: z.boolean(),
});

type SettingsForm = z.infer<typeof settingsFormSchema>;

function SettingsSkeleton() {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div key={i} className="h-24 rounded-md bg-muted/40 animate-pulse" />
      ))}
    </div>
  );
}

export default function Settings() {
  usePageTitle("Aiden Settings");

  const { data, isLoading } = useQuery<LlmSettingsResponse>({
    queryKey: ["/api/llm-settings"],
  });

  const form = useForm<SettingsForm>({
    resolver: zodResolver(settingsFormSchema),
    defaultValues: {
      provider: "openai",
      model: "gpt-4o",
      baseUrl: null,
      systemPrompt: "",
      enabled: false,
    },
    values: data ? {
      provider: data.settings.provider,
      model: data.settings.model,
      baseUrl: data.settings.baseUrl,
      systemPrompt: data.settings.systemPrompt,
      enabled: data.settings.enabled,
    } : undefined,
  });

  const saveMutation = useMutation({
    mutationFn: (values: SettingsForm) =>
      apiRequest("PUT", "/api/llm-settings", values),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["/api/llm-settings"] });
      toast({ title: "Settings saved", description: "Aiden configuration updated successfully." });
    },
    onError: (err: any) => {
      toast({ title: "Save failed", description: err.message, variant: "destructive" });
    },
  });

  const [testSuccess, setTestSuccess] = useState<boolean | null>(null);

  const testMutation = useMutation({
    mutationFn: () => apiRequest("POST", "/api/llm-settings/test"),
    onSuccess: async (res) => {
      const body = await res.json();
      setTestSuccess(true);
      toast({ title: "Connection successful", description: body.message });
      setTimeout(() => setTestSuccess(null), 8000);
    },
    onError: (err: any) => {
      setTestSuccess(false);
      toast({ title: "Connection failed", description: err.message, variant: "destructive" });
      setTimeout(() => setTestSuccess(null), 8000);
    },
  });

  const { toast } = useToast();

  const watchProvider = form.watch("provider");
  const currentProviderInfo = providers.find((p) => p.value === watchProvider);

  function onSubmit(values: SettingsForm) {
    saveMutation.mutate(values);
  }

  if (isLoading) {
    return (
      <div className="p-6 max-w-3xl mx-auto">
        <h1 className="text-2xl font-semibold tracking-tight mb-6" data-testid="text-settings-title">Aiden Configuration</h1>
        <SettingsSkeleton />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="text-settings-title">
          Aiden Configuration
        </h1>
        <p className="text-sm text-muted-foreground mt-1">
          Configure the LLM that powers Aiden's orchestration decisions.
        </p>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 pb-4">
          <CardTitle className="flex items-center gap-2 text-base">
            <Brain className="w-4 h-4" />
            LLM Provider
          </CardTitle>
          <div className="flex items-center gap-2">
            {data?.apiKeyConfigured ? (
              <Badge variant="secondary" data-testid="badge-key-status">
                <CheckCircle className="w-3 h-3 mr-1" />
                API Key Set
              </Badge>
            ) : (
              <Badge variant="destructive" data-testid="badge-key-status">
                <AlertTriangle className="w-3 h-3 mr-1" />
                Key Missing
              </Badge>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-5">
              <div className="flex items-center justify-between rounded-md border p-3">
                <div className="space-y-0.5">
                  <div className="text-sm font-medium">Enable Aiden LLM</div>
                  <div className="text-xs text-muted-foreground">
                    When enabled, Aiden uses the LLM for Tier 1/Tier 2 decisions. When disabled, hardcoded rules are used.
                  </div>
                </div>
                <FormField
                  control={form.control}
                  name="enabled"
                  render={({ field }) => (
                    <FormItem>
                      <FormControl>
                        <Switch
                          checked={field.value}
                          onCheckedChange={field.onChange}
                          data-testid="switch-enabled"
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />
              </div>

              <FormField
                control={form.control}
                name="provider"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Provider</FormLabel>
                    <Select
                      onValueChange={(val) => {
                        field.onChange(val);
                        const prov = providers.find((p) => p.value === val);
                        if (prov) form.setValue("model", prov.defaultModel);
                      }}
                      value={field.value}
                    >
                      <FormControl>
                        <SelectTrigger data-testid="select-provider">
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

              <FormField
                control={form.control}
                name="model"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Model</FormLabel>
                    <FormControl>
                      <ModelSelector
                        provider={watchProvider}
                        value={field.value}
                        onChange={field.onChange}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {(watchProvider === "openrouter" || watchProvider === "groq") && (
                <FormField
                  control={form.control}
                  name="baseUrl"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Base URL (optional)</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          value={field.value || ""}
                          placeholder={
                            watchProvider === "openrouter"
                              ? "https://openrouter.ai/api/v1"
                              : "https://api.groq.com/openai/v1"
                          }
                          data-testid="input-base-url"
                        />
                      </FormControl>
                      <FormDescription>
                        Leave empty to use the default endpoint for {currentProviderInfo?.label}.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              <div className="flex items-start gap-3 p-3 rounded-md bg-muted/40">
                <KeyRound className="w-4 h-4 text-muted-foreground mt-0.5 flex-shrink-0" />
                <div className="text-xs text-muted-foreground">
                  Set your API key as a secret named <code className="font-mono text-foreground">{currentProviderInfo?.keyName || data?.requiredKeyName}</code> in your project's Secrets tab.
                </div>
              </div>

              <Separator />

              <FormField
                control={form.control}
                name="systemPrompt"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>System Prompt</FormLabel>
                    <FormControl>
                      <Textarea
                        {...field}
                        className="min-h-[200px] resize-y text-sm font-mono"
                        placeholder="Define Aiden's behavior and rules..."
                        data-testid="input-system-prompt"
                      />
                    </FormControl>
                    <FormDescription>
                      This prompt defines how Aiden evaluates work orders at both tiers.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div className="flex items-center gap-3 pt-2 flex-wrap">
                <Button
                  type="submit"
                  disabled={saveMutation.isPending}
                  data-testid="button-save-settings"
                >
                  {saveMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Save className="w-4 h-4 mr-2" />
                  )}
                  {saveMutation.isPending ? "Saving..." : "Save Settings"}
                </Button>
                <Button
                  type="button"
                  variant={testSuccess === true ? "default" : testSuccess === false ? "destructive" : "outline"}
                  className={testSuccess === true ? "bg-green-600 hover:bg-green-700 text-white border-green-600" : ""}
                  onClick={() => testMutation.mutate()}
                  disabled={testMutation.isPending || !data?.apiKeyConfigured}
                  data-testid="button-test-connection"
                >
                  {testMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : testSuccess === true ? (
                    <CheckCircle className="w-4 h-4 mr-2" />
                  ) : testSuccess === false ? (
                    <AlertTriangle className="w-4 h-4 mr-2" />
                  ) : (
                    <Zap className="w-4 h-4 mr-2" />
                  )}
                  {testMutation.isPending ? "Testing..." : testSuccess === true ? "Connected" : testSuccess === false ? "Failed" : "Test Connection"}
                </Button>
              </div>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  );
}

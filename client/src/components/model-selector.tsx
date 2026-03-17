import { useState, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Loader2, RefreshCw } from "lucide-react";

interface ProviderModel {
  id: string;
  name: string;
  contextWindow?: number;
  owned_by?: string;
}

interface ModelsResponse {
  provider: string;
  keyConfigured: boolean;
  models: ProviderModel[];
}

export const providers = [
  { value: "openai", label: "OpenAI", defaultModel: "gpt-4o", keyName: "OPENAI_API_KEY" },
  { value: "anthropic", label: "Anthropic", defaultModel: "claude-sonnet-4-5", keyName: "ANTHROPIC_API_KEY" },
  { value: "openrouter", label: "OpenRouter", defaultModel: "openai/gpt-4o", keyName: "OPENROUTER_API_KEY" },
  { value: "groq", label: "Groq", defaultModel: "llama-3.3-70b-versatile", keyName: "GROQ_API_KEY" },
];

export function ModelSelector({
  provider,
  value,
  onChange,
  testIdPrefix = "",
}: {
  provider: string;
  value: string;
  onChange: (val: string) => void;
  testIdPrefix?: string;
}) {
  const [manualInput, setManualInput] = useState(false);
  const [searchFilter, setSearchFilter] = useState("");

  const { data: modelsData, isLoading, refetch, isFetching } = useQuery<ModelsResponse>({
    queryKey: ["/api/llm-settings/models", provider],
    enabled: !!provider,
    staleTime: 5 * 60 * 1000,
  });

  const models = modelsData?.models || [];
  const keyConfigured = modelsData?.keyConfigured ?? false;

  const filteredModels = useMemo(() => {
    const sorted = [...models].sort((a, b) => a.id.localeCompare(b.id));
    if (!searchFilter) return sorted;
    const lower = searchFilter.toLowerCase();
    return sorted.filter(m =>
      m.id.toLowerCase().includes(lower) ||
      m.name.toLowerCase().includes(lower) ||
      (m.owned_by && m.owned_by.toLowerCase().includes(lower))
    );
  }, [models, searchFilter]);

  useEffect(() => {
    setManualInput(false);
    setSearchFilter("");
  }, [provider]);

  if (!keyConfigured && !isLoading) {
    return (
      <div className="space-y-2">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Enter model ID manually"
          data-testid={`${testIdPrefix}input-model`}
        />
        <p className="text-xs text-muted-foreground">
          API key not set — type a model ID manually or add the key to load available models.
        </p>
      </div>
    );
  }

  if (manualInput) {
    return (
      <div className="space-y-2">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Enter model ID"
          data-testid={`${testIdPrefix}input-model`}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setManualInput(false)}
          data-testid={`${testIdPrefix}button-browse-models`}
        >
          Browse available models
        </Button>
      </div>
    );
  }

  if (isLoading || isFetching) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground p-2">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Loading models from {providers.find(p => p.value === provider)?.label}...
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger data-testid={`${testIdPrefix}button-select-model`}>
          <SelectValue placeholder="Select a model..." />
        </SelectTrigger>
        <SelectContent>
          {models.length > 10 && (
            <div className="px-2 pb-2">
              <Input
                placeholder="Filter models..."
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                className="h-8 text-xs"
                data-testid={`${testIdPrefix}input-model-search`}
              />
            </div>
          )}
          {filteredModels.length === 0 ? (
            <div className="py-4 text-center text-sm text-muted-foreground">No models found.</div>
          ) : (
            filteredModels.map((model) => (
              <SelectItem
                key={model.id}
                value={model.id}
                data-testid={`${testIdPrefix}model-option-${model.id}`}
              >
                <div className="flex items-center gap-2">
                  <span className="truncate">{model.name !== model.id ? model.name : model.id}</span>
                  {model.contextWindow && (
                    <span className="text-xs text-muted-foreground shrink-0">
                      {Math.round(model.contextWindow / 1000)}k ctx
                    </span>
                  )}
                </div>
              </SelectItem>
            ))
          )}
        </SelectContent>
      </Select>
      <div className="flex items-center gap-2 flex-wrap">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => refetch()}
          disabled={isFetching}
          data-testid={`${testIdPrefix}button-refresh-models`}
        >
          <RefreshCw className={`w-3 h-3 mr-1 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setManualInput(true)}
          data-testid={`${testIdPrefix}button-manual-model`}
        >
          Enter manually
        </Button>
        {models.length > 0 && (
          <span className="text-xs text-muted-foreground">
            {models.length} model{models.length !== 1 ? "s" : ""} available
          </span>
        )}
      </div>
    </div>
  );
}

import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import { Loader2, ChevronsUpDown, Check, RefreshCw } from "lucide-react";

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
  const [open, setOpen] = useState(false);
  const [manualInput, setManualInput] = useState(false);

  const { data: modelsData, isLoading, refetch, isFetching } = useQuery<ModelsResponse>({
    queryKey: ["/api/llm-settings/models", provider],
    enabled: !!provider,
    staleTime: 5 * 60 * 1000,
  });

  const models = modelsData?.models || [];
  const keyConfigured = modelsData?.keyConfigured ?? false;

  useEffect(() => {
    setManualInput(false);
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
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-full justify-between font-normal"
            data-testid={`${testIdPrefix}button-select-model`}
          >
            <span className="truncate">
              {value ? (models.find(m => m.id === value)?.name || value) : "Select a model..."}
            </span>
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command>
            <CommandInput placeholder="Search models..." data-testid={`${testIdPrefix}input-model-search`} />
            <CommandList>
              <CommandEmpty>No model found.</CommandEmpty>
              <CommandGroup>
                {models.map((model) => (
                  <CommandItem
                    key={model.id}
                    value={model.id}
                    onSelect={(val) => {
                      onChange(val);
                      setOpen(false);
                    }}
                    data-testid={`${testIdPrefix}model-option-${model.id}`}
                  >
                    <Check className={`mr-2 h-4 w-4 ${value === model.id ? "opacity-100" : "opacity-0"}`} />
                    <div className="flex flex-col min-w-0 flex-1">
                      <span className="text-sm truncate">{model.name !== model.id ? model.name : model.id}</span>
                      {model.name !== model.id && (
                        <span className="text-xs text-muted-foreground font-mono truncate">{model.id}</span>
                      )}
                    </div>
                    {model.contextWindow && (
                      <span className="text-xs text-muted-foreground ml-2 shrink-0">
                        {Math.round(model.contextWindow / 1000)}k ctx
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
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

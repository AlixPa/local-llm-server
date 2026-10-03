import type { CreateChatCompletionRequest } from "@/api/chat";
import type { PlaygroundMessage } from "@/components/playground-messages";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";

type Kind = "number" | "integer" | "text" | "json" | "jsonOrText" | "boolean" | "enum";

type OptionField = {
  key: string;
  kind: Kind;
  placeholder?: string;
  choices?: readonly string[];
};

const FIELDS: readonly OptionField[] = [
  { key: "temperature", kind: "number", placeholder: "1" },
  { key: "top_p", kind: "number", placeholder: "1" },
  { key: "max_tokens", kind: "integer" },
  { key: "max_completion_tokens", kind: "integer" },
  { key: "frequency_penalty", kind: "number", placeholder: "0" },
  { key: "presence_penalty", kind: "number", placeholder: "0" },
  { key: "stop", kind: "jsonOrText", placeholder: 'text or ["a", "b"]' },
  { key: "n", kind: "integer", placeholder: "1" },
  { key: "seed", kind: "integer" },
  { key: "stream", kind: "boolean" },
  { key: "stream_options", kind: "json", placeholder: '{"include_usage": true}' },
  {
    key: "response_format",
    kind: "json",
    placeholder: '{"type": "json_object"}',
  },
  { key: "tools", kind: "json", placeholder: "[...]" },
  { key: "tool_choice", kind: "jsonOrText", placeholder: "auto" },
  { key: "parallel_tool_calls", kind: "boolean" },
  { key: "functions", kind: "json", placeholder: "[...]" },
  { key: "function_call", kind: "jsonOrText", placeholder: "auto" },
  { key: "logprobs", kind: "boolean" },
  { key: "top_logprobs", kind: "integer" },
  { key: "logit_bias", kind: "json", placeholder: '{"token_id": -100}' },
  {
    key: "reasoning_effort",
    kind: "enum",
    choices: ["none", "minimal", "low", "medium", "high", "xhigh", "max"],
  },
  { key: "modalities", kind: "json", placeholder: '["text"]' },
  { key: "verbosity", kind: "enum", choices: ["low", "medium", "high"] },
  { key: "prediction", kind: "json" },
  { key: "audio", kind: "json" },
  { key: "web_search_options", kind: "json" },
  { key: "moderation", kind: "json" },
  { key: "metadata", kind: "json", placeholder: '{"key": "value"}' },
  { key: "store", kind: "boolean" },
  { key: "user", kind: "text" },
  { key: "safety_identifier", kind: "text" },
  { key: "prompt_cache_key", kind: "text" },
  { key: "prompt_cache_retention", kind: "enum", choices: ["in_memory", "24h"] },
  { key: "prompt_cache_options", kind: "json" },
  {
    key: "service_tier",
    kind: "enum",
    choices: ["auto", "default", "flex", "scale", "priority", "fast"],
  },
];

export type OptionValues = Partial<Record<string, string>>;

export type BuildResult = { body: CreateChatCompletionRequest } | { error: string };

function parseJson(raw: string): { ok: true; value: unknown } | { ok: false } {
  try {
    const value: unknown = JSON.parse(raw);
    return { ok: true, value };
  } catch {
    return { ok: false };
  }
}

function parseField(field: OptionField, raw: string): { value: unknown } | null {
  switch (field.kind) {
    case "number":
    case "integer": {
      const value = Number(raw);
      if (raw.trim() === "" || Number.isNaN(value)) return null;
      if (field.kind === "integer" && !Number.isInteger(value)) return null;
      return { value };
    }
    case "boolean":
      return { value: raw === "true" };
    case "json": {
      const parsed = parseJson(raw);
      return parsed.ok ? { value: parsed.value } : null;
    }
    case "jsonOrText": {
      const trimmed = raw.trim();
      if (!trimmed.startsWith("{") && !trimmed.startsWith("[")) return { value: raw };
      const parsed = parseJson(trimmed);
      return parsed.ok ? { value: parsed.value } : null;
    }
    case "text":
    case "enum":
      return { value: raw };
  }
}

// Only touched (non-empty) options are included, so the server's own defaults apply
export function buildRequestBody(
  model: string,
  messages: readonly PlaygroundMessage[],
  values: OptionValues,
): BuildResult {
  const extras: Record<string, unknown> = {};
  for (const field of FIELDS) {
    const raw = values[field.key];
    if (raw === undefined || raw === "") continue;
    const parsed = parseField(field, raw);
    if (parsed === null) return { error: `Invalid value for ${field.key}` };
    extras[field.key] = parsed.value;
  }
  return {
    body: {
      ...extras,
      messages: messages.map(({ role, content }) => ({ role, content })),
      model,
    },
  };
}

type Props = {
  models: readonly string[];
  model: string | undefined;
  onModelChange: (model: string) => void;
  values: OptionValues;
  onValuesChange: (values: OptionValues) => void;
};

export function PlaygroundOptions({
  models,
  model,
  onModelChange,
  values,
  onValuesChange,
}: Props) {
  const set = (key: string, value: string) =>
    onValuesChange({ ...values, [key]: value });

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="option-model">model</Label>
        <Select
          value={model ?? null}
          onValueChange={(value) => {
            if (value !== null) onModelChange(value);
          }}
        >
          <SelectTrigger id="option-model" className="w-full">
            <SelectValue placeholder="No models available" />
          </SelectTrigger>
          <SelectContent>
            {models.map((id) => (
              <SelectItem key={id} value={id}>
                {id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {FIELDS.map((field) => {
        const id = `option-${field.key}`;
        const value = values[field.key];
        return (
          <div key={field.key} className="flex flex-col gap-1.5">
            <Label htmlFor={id}>{field.key}</Label>
            {field.kind === "boolean" ? (
              <Switch
                id={id}
                checked={value === "true"}
                onCheckedChange={(checked) => set(field.key, String(checked))}
              />
            ) : field.kind === "enum" ? (
              <Select
                value={value ?? null}
                onValueChange={(next) => {
                  if (next !== null) set(field.key, next);
                }}
              >
                <SelectTrigger id={id} className="w-full">
                  <SelectValue placeholder="not set" />
                </SelectTrigger>
                <SelectContent>
                  {field.choices?.map((choice) => (
                    <SelectItem key={choice} value={choice}>
                      {choice}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : field.kind === "json" ? (
              <Textarea
                id={id}
                value={value ?? ""}
                placeholder={field.placeholder ?? "not set"}
                onChange={(event) => set(field.key, event.target.value)}
              />
            ) : (
              <Input
                id={id}
                value={value ?? ""}
                placeholder={field.placeholder ?? "not set"}
                onChange={(event) => set(field.key, event.target.value)}
              />
            )}
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        className="self-start"
        onClick={() => onValuesChange({})}
      >
        Reset options
      </Button>
    </div>
  );
}

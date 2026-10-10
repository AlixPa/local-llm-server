import type { CreateResponse } from "@/api/responses";
import type {
  PlaygroundMessage,
  ResponsesRole,
} from "@/components/playground-messages";
import {
  collectOptions,
  OptionControls,
  type OptionField,
  type OptionValues,
} from "@/components/playground-options";

const FIELDS: readonly OptionField[] = [
  { key: "temperature", kind: "number", placeholder: "1" },
  { key: "top_p", kind: "number", placeholder: "1" },
  { key: "max_output_tokens", kind: "integer" },
  { key: "max_tool_calls", kind: "integer" },
  { key: "stream", kind: "boolean" },
  {
    key: "stream_options",
    kind: "json",
    placeholder: '{"include_obfuscation": false}',
  },
  { key: "text", kind: "json", placeholder: '{"format": {"type": "json_object"}}' },
  { key: "tools", kind: "json", placeholder: "[...]" },
  { key: "tool_choice", kind: "jsonOrText", placeholder: "auto" },
  { key: "parallel_tool_calls", kind: "boolean" },
  { key: "reasoning", kind: "json", placeholder: '{"effort": "low"}' },
  { key: "top_logprobs", kind: "integer" },
  { key: "include", kind: "json", placeholder: '["message.output_text.logprobs"]' },
  { key: "truncation", kind: "enum", choices: ["auto", "disabled"] },
  { key: "previous_response_id", kind: "text" },
  { key: "conversation", kind: "jsonOrText" },
  { key: "context_management", kind: "json" },
  { key: "prompt", kind: "json" },
  { key: "background", kind: "boolean" },
  { key: "moderation", kind: "json" },
  { key: "metadata", kind: "json", placeholder: '{"key": "value"}' },
  { key: "store", kind: "boolean" },
  { key: "user", kind: "text" },
  { key: "safety_identifier", kind: "text" },
  { key: "prompt_cache_key", kind: "text" },
  { key: "prompt_cache_retention", kind: "enum", choices: ["in_memory", "24h"] },
  { key: "prompt_cache_options", kind: "json" },
  { key: "service_tier", kind: "text", placeholder: "auto" },
];

export type BuildResponsesResult = { body: CreateResponse } | { error: string };

export function buildResponsesBody(
  model: string,
  messages: readonly PlaygroundMessage<ResponsesRole>[],
  instructions: string,
  values: OptionValues,
): BuildResponsesResult {
  const collected = collectOptions(FIELDS, values);
  if ("error" in collected) return collected;
  return {
    body: {
      ...collected.extras,
      model,
      input: messages.map(({ role, content }) => ({ role, content })),
      ...(instructions === "" ? {} : { instructions }),
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

export function ResponsesPlaygroundOptions(props: Props) {
  return <OptionControls fields={FIELDS} {...props} />;
}

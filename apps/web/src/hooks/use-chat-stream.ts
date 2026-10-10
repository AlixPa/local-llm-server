import type { CreateChatCompletionRequest } from "@/api/chat";
import { useSseStream } from "@/hooks/use-sse-stream";

function deltaContent(chunk: unknown): string {
  if (typeof chunk !== "object" || chunk === null || !("choices" in chunk)) return "";
  const { choices } = chunk;
  if (!Array.isArray(choices)) return "";
  let text = "";
  for (const choice of choices) {
    if (
      typeof choice === "object" &&
      choice !== null &&
      "delta" in choice &&
      typeof choice.delta === "object" &&
      choice.delta !== null &&
      "content" in choice.delta &&
      typeof choice.delta.content === "string"
    ) {
      text += choice.delta.content;
    }
  }
  return text;
}

export function useChatStream() {
  return useSseStream<CreateChatCompletionRequest>(
    "/v1/chat/completions",
    deltaContent,
  );
}

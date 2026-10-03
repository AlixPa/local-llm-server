import { useCallback, useEffect, useRef, useState } from "react";
import type { CreateChatCompletionRequest } from "@/api/chat";
import { ApiError } from "@/api/client";
import { parseSse } from "@/lib/parse-sse";

export type StreamOutcome =
  | { status: "completed" | "cancelled"; text: string }
  | { status: "failed"; text: string; message: string };

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

async function errorMessageOf(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  if (
    typeof body === "object" &&
    body !== null &&
    "error" in body &&
    typeof body.error === "object" &&
    body.error !== null &&
    "message" in body.error &&
    typeof body.error.message === "string"
  ) {
    return body.error.message;
  }
  return response.statusText;
}

export function useChatStream() {
  const [text, setText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (body: CreateChatCompletionRequest): Promise<StreamOutcome> => {
      const controller = new AbortController();
      controllerRef.current = controller;
      setText("");
      setError(null);
      setIsStreaming(true);
      let accumulated = "";
      try {
        const response = await fetch("/v1/chat/completions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, stream: true }),
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new ApiError(response.status, await errorMessageOf(response));
        }
        if (!response.body) throw new Error("Empty response body");
        for await (const chunk of parseSse(response.body, controller.signal)) {
          accumulated += deltaContent(chunk);
          setText(accumulated);
        }
        return controller.signal.aborted
          ? { status: "cancelled", text: accumulated }
          : { status: "completed", text: accumulated };
      } catch (caught) {
        if (controller.signal.aborted) {
          return { status: "cancelled", text: accumulated };
        }
        const message = caught instanceof Error ? caught.message : "Request failed";
        setError(message);
        return { status: "failed", text: accumulated, message };
      } finally {
        setIsStreaming(false);
        controllerRef.current = null;
      }
    },
    [],
  );

  const cancel = useCallback(() => controllerRef.current?.abort(), []);

  useEffect(() => cancel, [cancel]);

  return { text, isStreaming, error, send, cancel };
}

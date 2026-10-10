import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { parseSse } from "@/lib/parse-sse";

export type StreamOutcome =
  | { status: "completed" | "cancelled"; text: string }
  | { status: "failed"; text: string; message: string };

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

// The single raw fetch: openapi-fetch cannot stream
export function useSseStream<TBody extends object>(
  url: string,
  deltaOf: (payload: unknown) => string,
) {
  const [text, setText] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const send = useCallback(
    async (body: TBody): Promise<StreamOutcome> => {
      const controller = new AbortController();
      controllerRef.current = controller;
      setText("");
      setError(null);
      setIsStreaming(true);
      let accumulated = "";
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ...body, stream: true }),
          signal: controller.signal,
        });
        if (!response.ok) {
          throw new ApiError(response.status, await errorMessageOf(response));
        }
        if (!response.body) throw new Error("Empty response body");
        for await (const payload of parseSse(response.body, controller.signal)) {
          accumulated += deltaOf(payload);
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
    [url, deltaOf],
  );

  const cancel = useCallback(() => controllerRef.current?.abort(), []);

  useEffect(() => cancel, [cancel]);

  return { text, isStreaming, error, send, cancel };
}

import { ApiError } from "@/api/client";

function messageOf(value: unknown): string | null {
  if (typeof value === "object" && value !== null && "message" in value) {
    if (typeof value.message === "string") return value.message;
  }
  return null;
}

// Covers chat `{error: {...}}`, Responses `type: "error"` and `response.failed`
function errorMessage(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  if ("error" in payload) return messageOf(payload.error) ?? "Stream failed";
  if (!("type" in payload)) return null;
  if (payload.type === "error") return messageOf(payload) ?? "Stream failed";
  if (payload.type === "response.failed") {
    const response = "response" in payload ? payload.response : null;
    const error =
      typeof response === "object" && response !== null && "error" in response
        ? response.error
        : null;
    return messageOf(error) ?? "Stream failed";
  }
  return null;
}

// Yields each JSON `data:` payload until [DONE] or the end of the stream
// (`event:` lines are ignored). The payload is
// `unknown` because streamed chunks are not described by the generated schema.
export async function* parseSse(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): AsyncGenerator<unknown> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      let chunk: ReadableStreamReadResult<Uint8Array>;
      try {
        chunk = await reader.read();
      } catch (error) {
        if (signal?.aborted) return;
        throw error;
      }
      if (chunk.done) {
        buffer += decoder.decode();
      } else {
        buffer += decoder.decode(chunk.value, { stream: true });
      }
      const lines = buffer.split("\n");
      // The last element is an incomplete line unless the stream has ended
      buffer = chunk.done ? "" : (lines.pop() ?? "");
      for (const rawLine of lines) {
        const line = rawLine.trimEnd();
        if (!line.startsWith("data:")) continue;
        const data = line.slice("data:".length).trim();
        if (data === "[DONE]") return;
        const payload: unknown = JSON.parse(data);
        const message = errorMessage(payload);
        if (message !== null) throw new ApiError(200, message);
        yield payload;
      }
      if (chunk.done) return;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
  }
}

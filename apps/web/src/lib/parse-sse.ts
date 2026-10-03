import { ApiError } from "@/api/client";

function errorMessage(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null || !("error" in payload)) {
    return null;
  }
  const { error } = payload;
  if (
    typeof error === "object" &&
    error !== null &&
    "message" in error &&
    typeof error.message === "string"
  ) {
    return error.message;
  }
  return "Stream failed";
}

// Yields each JSON `data:` payload until the [DONE] sentinel. The payload is
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

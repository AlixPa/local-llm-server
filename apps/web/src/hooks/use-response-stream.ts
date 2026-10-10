import type { CreateResponse } from "@/api/responses";
import { useSseStream } from "@/hooks/use-sse-stream";

function deltaText(event: unknown): string {
  if (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "response.output_text.delta" &&
    "delta" in event &&
    typeof event.delta === "string"
  ) {
    return event.delta;
  }
  return "";
}

export function useResponseStream() {
  return useSseStream<CreateResponse>("/v1/responses", deltaText);
}

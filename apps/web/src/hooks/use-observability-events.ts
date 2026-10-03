import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { OBSERVABILITY_KEY } from "@/api/observability";

export type ConnectionState =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected";

// The event stream is not in the generated OpenAPI schema, so its payload is typed here
type RequestEventPayload = { id: number };

function isRequestEventPayload(value: unknown): value is RequestEventPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number"
  );
}

export function useObservabilityEvents(): { connection: ConnectionState } {
  const queryClient = useQueryClient();
  const [connection, setConnection] = useState<ConnectionState>("connecting");

  useEffect(() => {
    const refetch = () => {
      void queryClient.invalidateQueries({ queryKey: OBSERVABILITY_KEY });
    };
    const onEvent = (event: MessageEvent<string>) => {
      try {
        if (isRequestEventPayload(JSON.parse(event.data))) refetch();
      } catch {
        // A malformed notification carries nothing to act on
      }
    };

    // EventSource is the one transport openapi-fetch cannot provide
    const source = new EventSource("/v1/observability/events");
    source.onopen = () => {
      setConnection("connected");
      // Events are not replayed, so every (re)connect catches up by refetching
      refetch();
    };
    source.onerror = () =>
      // CLOSED means the browser gave up; otherwise it is retrying
      setConnection(
        source.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting",
      );
    source.addEventListener("request.created", onEvent);
    source.addEventListener("request.updated", onEvent);
    return () => source.close();
  }, [queryClient]);

  return { connection };
}

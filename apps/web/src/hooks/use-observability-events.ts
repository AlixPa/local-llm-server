import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
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

type ObservabilityEvents = {
  connection: ConnectionState;
  paused: boolean;
  pendingCount: number;
  pause: () => void;
  clearPending: () => void;
  resume: () => void;
};

export function useObservabilityEvents(): ObservabilityEvents {
  const queryClient = useQueryClient();
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [paused, setPaused] = useState(false);
  const [pendingIds, setPendingIds] = useState<ReadonlySet<number>>(new Set());
  // Read by the stream handlers so toggling pause never reconnects the stream
  const pausedRef = useRef(false);

  const pause = useCallback(() => {
    pausedRef.current = true;
    setPaused(true);
  }, []);

  const clearPending = useCallback(() => setPendingIds(new Set()), []);

  const resume = useCallback(() => {
    pausedRef.current = false;
    setPaused(false);
    setPendingIds(new Set());
    void queryClient.invalidateQueries({ queryKey: OBSERVABILITY_KEY });
  }, [queryClient]);

  useEffect(() => {
    const refetch = () => {
      void queryClient.invalidateQueries({ queryKey: OBSERVABILITY_KEY });
    };
    const onEvent = (event: MessageEvent<string>) => {
      try {
        const payload: unknown = JSON.parse(event.data);
        if (!isRequestEventPayload(payload)) return;
        if (pausedRef.current) {
          if (event.type === "request.created") {
            setPendingIds((ids) => new Set(ids).add(payload.id));
          }
          // An open request's detail keeps refreshing; only the list is held back
          void queryClient.invalidateQueries({
            queryKey: [...OBSERVABILITY_KEY, "request"],
          });
        } else {
          refetch();
        }
      } catch {
        // A malformed notification carries nothing to act on
      }
    };

    // EventSource is the one transport openapi-fetch cannot provide
    const source = new EventSource("/v1/observability/events");
    source.onopen = () => {
      setConnection("connected");
      // Events are not replayed, so every (re)connect catches up by refetching
      if (!pausedRef.current) refetch();
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

  return {
    connection,
    paused,
    pendingCount: pendingIds.size,
    pause,
    clearPending,
    resume,
  };
}

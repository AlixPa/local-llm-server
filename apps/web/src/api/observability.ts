import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";
import { type FilterValues, toUnixSeconds } from "@/components/request-filters";

export type TracedRequestItem = components["schemas"]["TracedRequestItem"];
export type TracedRequestDetail = components["schemas"]["TracedRequestDetail"];
export type WorkflowStepItem = components["schemas"]["WorkflowStepItem"];
export type StepKind = components["schemas"]["StepKind"];
export type Participant = components["schemas"]["Participant"];
export type TraceOutcome = components["schemas"]["TraceOutcome"];

export const TRACE_OUTCOMES = [
  "in_progress",
  "success",
  "error",
  "canceled",
  "interrupted",
] as const satisfies readonly TraceOutcome[];

export type RequestFilters = {
  endpoint?: string;
  outcome?: TraceOutcome[];
  since?: number;
  until?: number;
};

export function toRequestFilters(values: FilterValues): RequestFilters {
  const outcome = TRACE_OUTCOMES.find((candidate) => candidate === values.status);
  return {
    endpoint: values.endpoint || undefined,
    outcome: outcome ? [outcome] : undefined,
    since: toUnixSeconds(values.since),
    until: toUnixSeconds(values.until),
  };
}

export const OBSERVABILITY_KEY = ["observability"] as const;

type Cursor = number | undefined;

export function useTracedRequests(filters: RequestFilters = {}) {
  return useInfiniteQuery({
    queryKey: [...OBSERVABILITY_KEY, "requests", filters],
    initialPageParam: undefined,
    placeholderData: keepPreviousData,
    queryFn: async ({ pageParam }: { pageParam: Cursor }) => {
      const { data } = await api.GET("/v1/observability/requests", {
        params: { query: { ...filters, after: pageParam } },
      });
      if (!data) throw new Error("Empty response");
      return data;
    },
    getNextPageParam: (page) =>
      page.has_more ? (page.last_id ?? undefined) : undefined,
  });
}

export function useTracedRequest(id: number | null) {
  return useQuery({
    queryKey: [...OBSERVABILITY_KEY, "request", id],
    enabled: id !== null,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      if (id === null) throw new Error("No request selected");
      const { data } = await api.GET("/v1/observability/requests/{request_id}", {
        params: { path: { request_id: id } },
      });
      if (!data) throw new Error("Empty response");
      return data;
    },
  });
}

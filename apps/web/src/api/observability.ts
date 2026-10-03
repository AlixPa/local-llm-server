import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type TracedRequestItem = components["schemas"]["TracedRequestItem"];
export type TracedRequestDetail = components["schemas"]["TracedRequestDetail"];
export type WorkflowStepItem = components["schemas"]["WorkflowStepItem"];
export type StepKind = components["schemas"]["StepKind"];
export type Participant = components["schemas"]["Participant"];
export type TraceOutcome = components["schemas"]["TraceOutcome"];

export type RequestFilters = {
  endpoint?: string;
  outcome?: TraceOutcome[];
  since?: number;
  until?: number;
};

export const OBSERVABILITY_KEY = ["observability"] as const;

type Cursor = number | undefined;

export function useTracedRequests(filters: RequestFilters = {}) {
  return useInfiniteQuery({
    queryKey: [...OBSERVABILITY_KEY, "requests", filters],
    initialPageParam: undefined,
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

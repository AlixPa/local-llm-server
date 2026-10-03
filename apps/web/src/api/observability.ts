import { useInfiniteQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type TracedRequestItem = components["schemas"]["TracedRequestItem"];
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

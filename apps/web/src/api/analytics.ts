import { keepPreviousData, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";
import {
  endpointOf,
  type FilterValues,
  toUnixSeconds,
} from "@/components/request-filters";

export type AnalyticsRequestItem = components["schemas"]["AnalyticsRequestItem"];
export type AnalyticsRequestSummary = components["schemas"]["AnalyticsRequestSummary"];
type RequestStatus = components["schemas"]["RequestStatus"];

export const REQUEST_STATUSES = [
  "succeeded",
  "failed",
  "cancelled",
] as const satisfies readonly RequestStatus[];

export type AnalyticsFilters = {
  endpoint?: NonNullable<ReturnType<typeof endpointOf>>;
  status?: RequestStatus;
  since?: number;
  until?: number;
};

export function toAnalyticsFilters(values: FilterValues): AnalyticsFilters {
  return {
    endpoint: endpointOf(values.endpoint),
    status: REQUEST_STATUSES.find((status) => status === values.status),
    since: toUnixSeconds(values.since),
    until: toUnixSeconds(values.until),
  };
}

export function useRequestAnalytics(filters: AnalyticsFilters) {
  return useInfiniteQuery({
    queryKey: ["analytics", "requests", filters],
    initialPageParam: undefined as string | undefined,
    placeholderData: keepPreviousData,
    queryFn: async ({ pageParam }) => {
      const { data } = await api.GET("/v1/analytics/requests", {
        params: { query: { ...filters, after: pageParam } },
      });
      if (!data) throw new Error("Empty response");
      return data;
    },
    getNextPageParam: (page) =>
      page.has_more ? (page.last_id ?? undefined) : undefined,
  });
}

export function useRequestSummary(filters: AnalyticsFilters) {
  return useQuery({
    queryKey: ["analytics", "requests", "summary", filters],
    placeholderData: keepPreviousData,
    queryFn: async () => {
      const { data } = await api.GET("/v1/analytics/requests/summary", {
        params: { query: filters },
      });
      if (!data) throw new Error("Empty response");
      return data;
    },
  });
}

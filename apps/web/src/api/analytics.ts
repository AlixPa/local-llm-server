import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type ChatCompletionAnalyticsItem =
  components["schemas"]["ChatCompletionAnalyticsItem"];
export type ChatCompletionAnalyticsSummary =
  components["schemas"]["ChatCompletionAnalyticsSummary"];

export function useChatCompletionAnalytics() {
  return useInfiniteQuery({
    queryKey: ["analytics", "chat-completions"],
    initialPageParam: undefined as string | undefined,
    queryFn: async ({ pageParam }) => {
      const { data } = await api.GET("/v1/analytics/chat-completions", {
        params: { query: { after: pageParam } },
      });
      if (!data) throw new Error("Empty response");
      return data;
    },
    getNextPageParam: (page) =>
      page.has_more ? (page.last_id ?? undefined) : undefined,
  });
}

export function useChatCompletionSummary() {
  return useQuery({
    queryKey: ["analytics", "chat-completions", "summary"],
    queryFn: async () => {
      const { data } = await api.GET("/v1/analytics/chat-completions/summary");
      if (!data) throw new Error("Empty response");
      return data;
    },
  });
}

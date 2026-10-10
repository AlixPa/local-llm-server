import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type CreateResponse = components["schemas"]["CreateResponse"];

export function useCreateResponse() {
  return useMutation({
    mutationFn: async ({
      body,
      signal,
    }: {
      body: CreateResponse;
      signal: AbortSignal;
    }) => {
      const { data } = await api.POST("/v1/responses", { body, signal });
      if (!data) throw new Error("Empty response");
      return data;
    },
  });
}

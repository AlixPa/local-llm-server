import { useMutation } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type CreateChatCompletionRequest =
  components["schemas"]["CreateChatCompletionRequest"];

export function useCreateChatCompletion() {
  return useMutation({
    mutationFn: async (body: CreateChatCompletionRequest) => {
      const { data } = await api.POST("/v1/chat/completions", { body });
      if (!data) throw new Error("Empty response");
      return data;
    },
  });
}

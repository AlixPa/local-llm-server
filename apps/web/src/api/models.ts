import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: async () => {
      const { data } = await api.GET("/v1/models");
      if (!data) throw new Error("Empty response");
      return data.data;
    },
  });
}

import { useTracedRequests } from "@/api/observability";
import { ObservabilityFeed } from "@/components/observability-feed";
import { useObservabilityEvents } from "@/hooks/use-observability-events";

export function ObservabilityPage() {
  const { connection } = useObservabilityEvents();
  const list = useTracedRequests();
  const items = list.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <main className="flex flex-col gap-6 p-6">
      <h1 className="font-semibold text-xl">Observability</h1>
      {list.isError && (
        <p role="alert" className="text-destructive">
          {list.error.message}
        </p>
      )}
      {list.isPending && <p role="status">Loading…</p>}
      {list.data && (
        <ObservabilityFeed
          items={items}
          hasMore={list.hasNextPage}
          isLoadingMore={list.isFetchingNextPage}
          onLoadMore={() => list.fetchNextPage()}
          connection={connection}
        />
      )}
    </main>
  );
}

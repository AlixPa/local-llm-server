import { useState } from "react";
import { useTracedRequest, useTracedRequests } from "@/api/observability";
import { ObservabilityFeed } from "@/components/observability-feed";
import { ObservabilitySequence } from "@/components/observability-sequence";
import { useObservabilityEvents } from "@/hooks/use-observability-events";

export function ObservabilityPage() {
  const { connection } = useObservabilityEvents();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const list = useTracedRequests();
  const detail = useTracedRequest(selectedId);
  const items = list.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <main className="flex flex-col gap-6 p-6">
      <h1 className="font-semibold text-xl">Observability</h1>
      {selectedId !== null && detail.isError && (
        <p role="alert" className="text-destructive">
          {detail.error.message}
        </p>
      )}
      {selectedId !== null && detail.data && (
        <div
          aria-busy={detail.isPlaceholderData}
          className={detail.isPlaceholderData ? "opacity-60" : undefined}
        >
          <ObservabilitySequence
            key={detail.data.id}
            request={detail.data}
            onClose={() => setSelectedId(null)}
          />
        </div>
      )}
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
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      )}
    </main>
  );
}

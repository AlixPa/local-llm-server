import { useMemo, useState } from "react";
import { useTracedRequest, useTracedRequests } from "@/api/observability";
import { ObservabilityFeed } from "@/components/observability-feed";
import {
  EMPTY_FILTERS,
  type FilterValues,
  ObservabilityFilters,
  toRequestFilters,
} from "@/components/observability-filters";
import { ObservabilitySequence } from "@/components/observability-sequence";
import { Button } from "@/components/ui/button";
import { useObservabilityEvents } from "@/hooks/use-observability-events";

export function ObservabilityPage() {
  const { connection, paused, pendingCount, pause, clearPending, resume } =
    useObservabilityEvents();
  const [filterValues, setFilterValues] = useState<FilterValues>(EMPTY_FILTERS);
  const filters = useMemo(() => toRequestFilters(filterValues), [filterValues]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const list = useTracedRequests(filters);
  const detail = useTracedRequest(selectedId);
  const items = list.data?.pages.flatMap((page) => page.data) ?? [];
  const [knownEndpoints, setKnownEndpoints] = useState<string[]>([]);
  const unseen = items.filter((item) => !knownEndpoints.includes(item.endpoint));
  if (unseen.length > 0) {
    setKnownEndpoints([
      ...new Set([...knownEndpoints, ...unseen.map((item) => item.endpoint)]),
    ]);
  }
  const filtersActive = Object.values(filters).some((v) => v !== undefined);

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
      <div className="flex flex-wrap items-end justify-between gap-4">
        <ObservabilityFilters
          values={filterValues}
          onChange={(values) => {
            setFilterValues(values);
            clearPending();
          }}
          knownEndpoints={knownEndpoints}
        />
        <div className="flex items-center gap-3">
          {paused && pendingCount > 0 && (
            <p role="status" className="text-sm">
              {pendingCount} new {pendingCount === 1 ? "request" : "requests"} waiting
            </p>
          )}
          <Button variant="outline" onClick={paused ? resume : pause}>
            {paused ? "Resume" : "Pause"}
          </Button>
        </div>
      </div>
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
          filtersActive={filtersActive}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
      )}
    </main>
  );
}

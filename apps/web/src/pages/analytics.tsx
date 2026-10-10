import { useMemo, useState } from "react";
import {
  REQUEST_STATUSES,
  toAnalyticsFilters,
  useRequestAnalytics,
  useRequestSummary,
} from "@/api/analytics";
import { AnalyticsSummary } from "@/components/analytics-summary";
import { AnalyticsTable } from "@/components/analytics-table";
import {
  EMPTY_FILTERS,
  type FilterValues,
  RequestFilters,
} from "@/components/request-filters";

function Message({ children, error }: { children: string; error?: boolean }) {
  return (
    <p role={error ? "alert" : "status"} className={error ? "text-destructive" : ""}>
      {children}
    </p>
  );
}

export function AnalyticsPage() {
  const [filterValues, setFilterValues] = useState<FilterValues>(EMPTY_FILTERS);
  const filters = useMemo(() => toAnalyticsFilters(filterValues), [filterValues]);
  const summary = useRequestSummary(filters);
  const list = useRequestAnalytics(filters);
  const items = list.data?.pages.flatMap((page) => page.data) ?? [];
  const filtersActive = Object.values(filters).some((v) => v !== undefined);

  return (
    <main className="flex flex-col gap-6 p-6">
      <h1 className="font-semibold text-xl">Analytics</h1>
      <RequestFilters
        values={filterValues}
        onChange={setFilterValues}
        statusOptions={REQUEST_STATUSES}
      />
      {summary.isError && <Message error>{summary.error.message}</Message>}
      {summary.data && <AnalyticsSummary summary={summary.data} />}
      {list.isError && <Message error>{list.error.message}</Message>}
      {list.isPending && <Message>Loading…</Message>}
      {list.data && (
        <AnalyticsTable
          items={items}
          filtersActive={filtersActive}
          onClearFilters={() => setFilterValues(EMPTY_FILTERS)}
          hasMore={list.hasNextPage}
          isLoadingMore={list.isFetchingNextPage}
          onLoadMore={() => list.fetchNextPage()}
        />
      )}
    </main>
  );
}

import { useChatCompletionAnalytics, useChatCompletionSummary } from "@/api/analytics";
import { AnalyticsSummary } from "@/components/analytics-summary";
import { AnalyticsTable } from "@/components/analytics-table";

function Message({ children, error }: { children: string; error?: boolean }) {
  return (
    <p role={error ? "alert" : "status"} className={error ? "text-destructive" : ""}>
      {children}
    </p>
  );
}

export function AnalyticsPage() {
  const summary = useChatCompletionSummary();
  const list = useChatCompletionAnalytics();
  const items = list.data?.pages.flatMap((page) => page.data) ?? [];

  return (
    <main className="flex flex-col gap-6 p-6">
      <h1 className="font-semibold text-xl">Analytics</h1>
      {summary.isError && <Message error>{summary.error.message}</Message>}
      {summary.data && <AnalyticsSummary summary={summary.data} />}
      {list.isError && <Message error>{list.error.message}</Message>}
      {list.isPending && <Message>Loading…</Message>}
      {list.data && (
        <AnalyticsTable
          items={items}
          hasMore={list.hasNextPage}
          isLoadingMore={list.isFetchingNextPage}
          onLoadMore={() => list.fetchNextPage()}
        />
      )}
    </main>
  );
}

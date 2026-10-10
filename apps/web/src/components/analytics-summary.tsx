import type { AnalyticsRequestSummary } from "@/api/analytics";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatMs } from "@/lib/format";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{label}</CardTitle>
      </CardHeader>
      <CardContent className="font-semibold text-2xl">{value}</CardContent>
    </Card>
  );
}

export function AnalyticsSummary({ summary }: { summary: AnalyticsRequestSummary }) {
  const errorRate =
    summary.request_count === 0
      ? "—"
      : `${((summary.error_count / summary.request_count) * 100).toFixed(1)}%`;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat label="Requests" value={summary.request_count.toLocaleString()} />
      <Stat label="Error rate" value={errorRate} />
      <Stat label="Input tokens" value={summary.prompt_tokens.toLocaleString()} />
      <Stat label="Output tokens" value={summary.completion_tokens.toLocaleString()} />
      <Stat label="Avg duration" value={formatMs(summary.avg_duration_ms)} />
      <Stat
        label="Avg time to first token"
        value={formatMs(summary.avg_time_to_first_token_ms)}
      />
      <Stat
        label="Avg generation duration"
        value={formatMs(summary.avg_generation_duration_ms)}
      />
    </div>
  );
}

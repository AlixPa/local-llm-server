import type { TracedRequestItem } from "@/api/observability";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { ConnectionState } from "@/hooks/use-observability-events";
import { formatMs } from "@/lib/format";

type Props = {
  items: TracedRequestItem[];
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
  connection: ConnectionState;
  filtersActive: boolean;
  selectedId: number | null;
  onSelect: (id: number) => void;
};

const OUTCOME_VARIANT = {
  in_progress: "outline",
  success: "secondary",
  error: "destructive",
  canceled: "outline",
  interrupted: "ghost",
} as const;

const CONNECTION_LABEL = {
  connecting: "Connecting…",
  connected: "Live",
  reconnecting: "Connection lost, retrying…",
  disconnected: "Disconnected",
} as const;

export function ObservabilityFeed({
  items,
  hasMore,
  isLoadingMore,
  onLoadMore,
  connection,
  filtersActive,
  selectedId,
  onSelect,
}: Props) {
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="text-muted-foreground text-sm">
        {CONNECTION_LABEL[connection]}
      </p>
      {items.length === 0 && filtersActive ? (
        <p className="text-muted-foreground">No requests match the current filters.</p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground">
          No requests recorded yet. Requests to tracked endpoints, such as chat
          completions and responses, appear here as they happen. Send one from the
          Playground to get started.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Endpoint</TableHead>
              <TableHead>Method</TableHead>
              <TableHead>Summary</TableHead>
              <TableHead>Outcome</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Duration</TableHead>
              <TableHead>Error</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow
                key={item.id}
                data-state={item.id === selectedId ? "selected" : undefined}
                className={item.outcome === "error" ? "bg-destructive/5" : undefined}
              >
                <TableCell>
                  <Button
                    variant="link"
                    size="sm"
                    aria-pressed={item.id === selectedId}
                    onClick={() => onSelect(item.id)}
                  >
                    {new Date(item.started_at_ms).toLocaleString()}
                  </Button>
                </TableCell>
                <TableCell>{item.endpoint}</TableCell>
                <TableCell>{item.method}</TableCell>
                <TableCell>{item.summary ?? "—"}</TableCell>
                <TableCell>
                  <Badge
                    variant={OUTCOME_VARIANT[item.outcome]}
                    className={
                      item.outcome === "interrupted" ? "border-dashed" : undefined
                    }
                  >
                    {item.outcome.replace("_", " ")}
                  </Badge>
                </TableCell>
                <TableCell>{item.http_status ?? "—"}</TableCell>
                <TableCell>{formatMs(item.duration_ms)}</TableCell>
                <TableCell className="text-destructive">{item.error_message}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {hasMore && (
        <Button
          variant="outline"
          className="self-center"
          disabled={isLoadingMore}
          onClick={onLoadMore}
        >
          Load more
        </Button>
      )}
    </div>
  );
}

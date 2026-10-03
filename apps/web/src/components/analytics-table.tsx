import type { ChatCompletionAnalyticsItem } from "@/api/analytics";
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
import { formatMs } from "@/lib/format";

type Props = {
  items: ChatCompletionAnalyticsItem[];
  hasMore: boolean;
  isLoadingMore: boolean;
  onLoadMore: () => void;
};

const STATUS_VARIANT = {
  succeeded: "secondary",
  failed: "destructive",
  cancelled: "outline",
} as const;

function tokens(value: number | null): string {
  return value === null ? "—" : value.toLocaleString();
}

export function AnalyticsTable({ items, hasMore, isLoadingMore, onLoadMore }: Props) {
  if (items.length === 0) {
    return <p className="text-muted-foreground">No requests recorded yet</p>;
  }

  return (
    <div className="flex flex-col gap-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Time</TableHead>
            <TableHead>Model</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Input tokens</TableHead>
            <TableHead>Output tokens</TableHead>
            <TableHead>Total tokens</TableHead>
            <TableHead>Duration</TableHead>
            <TableHead>Time to first token</TableHead>
            <TableHead>Model load</TableHead>
            <TableHead>Generation</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((item) => (
            <TableRow key={item.id}>
              <TableCell>{new Date(item.created * 1000).toLocaleString()}</TableCell>
              <TableCell>{item.model}</TableCell>
              <TableCell>
                <Badge variant={STATUS_VARIANT[item.status]}>{item.status}</Badge>
              </TableCell>
              <TableCell>{tokens(item.prompt_tokens)}</TableCell>
              <TableCell>{tokens(item.completion_tokens)}</TableCell>
              <TableCell>{tokens(item.total_tokens)}</TableCell>
              <TableCell>{formatMs(item.duration_ms)}</TableCell>
              <TableCell>{formatMs(item.time_to_first_token_ms)}</TableCell>
              <TableCell>{formatMs(item.load_duration_ms)}</TableCell>
              <TableCell>{formatMs(item.generation_duration_ms)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
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

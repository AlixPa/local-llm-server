import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

export type HistoryEntry = {
  id: string;
  request: unknown;
  preview: string;
  status: "completed" | "cancelled" | "failed";
  answer: string;
  error: string | null;
};

type Props = {
  entries: readonly HistoryEntry[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
};

export function PlaygroundHistory({ entries, selectedId, onSelect }: Props) {
  const selected = entries.find((entry) => entry.id === selectedId);

  if (entries.length === 0) {
    return <p className="text-muted-foreground text-sm">No requests yet.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col gap-1">
        {entries.map((entry, index) => (
          <li key={entry.id}>
            <Button
              type="button"
              variant={entry.id === selectedId ? "secondary" : "ghost"}
              className="w-full justify-start gap-2"
              aria-pressed={entry.id === selectedId}
              onClick={() => onSelect(entry.id === selectedId ? null : entry.id)}
            >
              <span>#{index + 1}</span>
              <Badge variant={entry.status === "failed" ? "destructive" : "outline"}>
                {entry.status}
              </Badge>
              <span className="truncate">{entry.preview}</span>
            </Button>
          </li>
        ))}
      </ul>
      {selected && (
        <div className="flex flex-col gap-2 rounded-lg border p-3 text-sm">
          <h3 className="font-medium">Request</h3>
          <pre className="overflow-x-auto text-xs">
            {JSON.stringify(selected.request, null, 2)}
          </pre>
          <h3 className="font-medium">{selected.error ? "Error" : "Answer"}</h3>
          <pre className="whitespace-pre-wrap text-xs">
            {selected.error ?? selected.answer}
          </pre>
        </div>
      )}
    </div>
  );
}

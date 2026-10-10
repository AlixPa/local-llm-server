import { useId, useState } from "react";
import type { StepKind, TracedRequestDetail } from "@/api/observability";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatMs } from "@/lib/format";
import { layoutSteps, type StepLayout } from "@/lib/sequence-layout";
import { cn } from "@/lib/utils";

const TRUNCATE_AT = 2000;

const LANES = ["Client", "API", "Ollama"] as const;

const KIND_LABEL: Record<StepKind, string> = {
  request_received: "Request received",
  sent_to_ollama: "Sent to Ollama",
  received_from_ollama: "Received from Ollama",
  response_returned: "Response returned",
  error: "Error",
};

function formatContent(content: unknown): string {
  return JSON.stringify(content, null, 2);
}

function truncate(text: string): string {
  const last = text.charCodeAt(TRUNCATE_AT - 1);
  const end = last >= 0xd800 && last <= 0xdbff ? TRUNCATE_AT - 1 : TRUNCATE_AT;
  return `${text.slice(0, end)}…`;
}

function StepContent({ content }: { content: unknown }) {
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState(false);
  const contentId = useId();
  const text = formatContent(content);
  const truncated = !full && text.length > TRUNCATE_AT;

  return (
    <div className="col-span-3 flex flex-col gap-2">
      <Button
        variant="ghost"
        size="sm"
        className="self-start"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? "Hide content" : "Show content"}
      </Button>
      {open && (
        <>
          <pre
            id={contentId}
            className="max-h-96 overflow-auto rounded-md bg-muted p-3 text-xs"
          >
            {truncated ? truncate(text) : text}
          </pre>
          {text.length > TRUNCATE_AT && (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              aria-expanded={full}
              aria-controls={contentId}
              onClick={() => setFull(!full)}
            >
              {full ? "Show less" : "Show full content"}
            </Button>
          )}
        </>
      )}
    </div>
  );
}

function StepRow({ layout }: { layout: StepLayout }) {
  const { step, fromLane, toLane, direction } = layout;
  const first = Math.min(fromLane, toLane);
  const span = Math.abs(fromLane - toLane) + 1;
  const arrow = direction === "right" ? "→" : "←";

  return (
    <li
      data-status={step.status}
      className={cn(
        "grid grid-cols-3 gap-y-1 rounded-md border border-transparent px-2 py-2",
        layout.failed && "border-destructive bg-destructive/5",
        layout.inProgress && "animate-pulse motion-reduce:animate-none",
        (layout.canceled || layout.interrupted) && "border-dashed",
      )}
    >
      <div
        className="flex flex-col items-center gap-1"
        style={{
          gridColumn: `${first + 1} / span ${span}`,
          marginInline: `${100 / (2 * span)}%`,
        }}
      >
        <span className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">{KIND_LABEL[step.kind]}</span>
          <span className="text-muted-foreground text-xs">
            +{formatMs(step.offset_ms)}
            {step.duration_ms !== null && ` · took ${formatMs(step.duration_ms)}`}
          </span>
          {step.status !== "completed" && (
            <Badge
              variant={
                layout.failed ? "destructive" : layout.interrupted ? "ghost" : "outline"
              }
              className={layout.interrupted ? "border border-dashed" : undefined}
            >
              {step.status.replace("_", " ")}
            </Badge>
          )}
        </span>
        <span
          aria-hidden="true"
          className={cn(
            "flex w-full items-center text-muted-foreground",
            direction === "left" && "flex-row-reverse",
          )}
        >
          <span className="h-px flex-1 bg-current" />
          {arrow}
        </span>
        <span className="sr-only">{`${step.source} to ${step.destination}`}</span>
      </div>
      {step.error_message && (
        <p role="alert" className="col-span-3 text-destructive text-sm">
          {step.error_message}
        </p>
      )}
      {step.content !== null && step.content !== undefined && (
        <StepContent content={step.content} />
      )}
    </li>
  );
}

type Props = { request: TracedRequestDetail; onClose: () => void };

export function ObservabilitySequence({ request, onClose }: Props) {
  const layouts = layoutSteps(request.steps);

  return (
    <section
      aria-label="Request workflow"
      className="flex flex-col gap-3 rounded-lg border p-4"
    >
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-medium">
          {request.endpoint}
          {request.summary && (
            <span className="text-muted-foreground"> · {request.summary}</span>
          )}
        </h2>
        <Button variant="outline" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
      <div className="grid grid-cols-3 text-center font-medium text-sm">
        {LANES.map((lane) => (
          <span key={lane} className="border-b pb-1">
            {lane}
          </span>
        ))}
      </div>
      <ol className="flex flex-col gap-1">
        {layouts.map((layout) => (
          <StepRow key={layout.step.position} layout={layout} />
        ))}
      </ol>
    </section>
  );
}

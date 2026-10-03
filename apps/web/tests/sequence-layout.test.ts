import { expect, test } from "vitest";
import type { Participant, StepKind, WorkflowStepItem } from "@/api/observability";
import { layoutSteps } from "@/lib/sequence-layout";

function step(
  position: number,
  kind: StepKind,
  source: Participant,
  destination: Participant,
  overrides: Partial<WorkflowStepItem> = {},
): WorkflowStepItem {
  return {
    position,
    kind,
    source,
    destination,
    status: "completed",
    offset_ms: position,
    duration_ms: null,
    content: null,
    error_message: null,
    ...overrides,
  };
}

const request = step(0, "request_received", "client", "api");
const sent = step(1, "sent_to_ollama", "api", "ollama");
const received = step(2, "received_from_ollama", "ollama", "api");
const returned = step(3, "response_returned", "api", "client");

test("maps a success sequence to lanes and directions", () => {
  const layout = layoutSteps([request, sent, received, returned]);

  expect(
    layout.map(({ fromLane, toLane, direction }) => [fromLane, toLane, direction]),
  ).toEqual([
    [0, 1, "right"],
    [1, 2, "right"],
    [2, 1, "left"],
    [1, 0, "left"],
  ]);
  expect(layout.every((row) => !row.failed && !row.inProgress)).toBe(true);
});

test("a rejected request never touches the Ollama lane", () => {
  const layout = layoutSteps([request, step(1, "error", "api", "client")]);

  expect(layout.flatMap((row) => [row.fromLane, row.toLane])).not.toContain(2);
});

test("flags a failed Ollama step", () => {
  const [row] = layoutSteps([
    step(2, "received_from_ollama", "ollama", "api", {
      status: "failed",
      error_message: "boom",
    }),
  ]);

  expect(row).toMatchObject({ failed: true, inProgress: false });
});

test("flags in-progress, canceled and interrupted steps", () => {
  const rows = layoutSteps([
    step(0, "received_from_ollama", "ollama", "api", { status: "in_progress" }),
    step(1, "received_from_ollama", "ollama", "api", { status: "canceled" }),
    step(2, "received_from_ollama", "ollama", "api", { status: "interrupted" }),
  ]);

  expect(rows[0]).toMatchObject({ inProgress: true, failed: false });
  expect(rows[1]).toMatchObject({ canceled: true });
  expect(rows[2]).toMatchObject({ interrupted: true });
});

test("keeps step order for n > 1 calls", () => {
  const steps = [
    request,
    sent,
    received,
    step(3, "sent_to_ollama", "api", "ollama"),
    step(4, "received_from_ollama", "ollama", "api"),
    step(5, "response_returned", "api", "client"),
  ];

  expect(layoutSteps(steps).map((row) => row.step.position)).toEqual([
    0, 1, 2, 3, 4, 5,
  ]);
});

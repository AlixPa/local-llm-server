import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { beforeEach, expect, test, vi } from "vitest";
import { App } from "@/App";
import { FakeEventSource } from "./fake-event-source";
import { renderWithProviders } from "./render";
import { server } from "./server";

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
});

const ITEM = {
  id: 1,
  endpoint: "/v1/chat/completions",
  method: "POST",
  started_at: 1790000000,
  started_at_ms: 1790000000123,
  duration_ms: 3150,
  http_status: 200,
  outcome: "success",
  summary: "qwen3.5:9b · stream",
  response_id: "chatcmpl-1",
  error_message: null,
};

function step(position: number, overrides: Record<string, unknown>) {
  return {
    position,
    kind: "request_received",
    source: "client",
    destination: "api",
    status: "completed",
    offset_ms: position,
    duration_ms: null,
    content: null,
    error_message: null,
    ...overrides,
  };
}

const SENT = {
  kind: "sent_to_ollama",
  source: "api",
  destination: "ollama",
};
const RECEIVED = {
  kind: "received_from_ollama",
  source: "ollama",
  destination: "api",
};

function serve(steps: () => unknown[]) {
  server.use(
    http.get("*/v1/observability/requests", () =>
      HttpResponse.json({
        object: "list",
        data: [ITEM],
        first_id: 1,
        last_id: 1,
        has_more: false,
      }),
    ),
    http.get("*/v1/observability/requests/1", () =>
      HttpResponse.json({ ...ITEM, steps: steps() }),
    ),
  );
}

async function openDetail() {
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");
  const rows = await screen.findAllByRole("row");
  const row = rows[1];
  if (!row) throw new Error("Missing feed row");
  await user.click(within(row).getByRole("button"));
  return { user, workflow: await screen.findByLabelText("Request workflow") };
}

test("selecting a row renders the steps in order and expands content", async () => {
  serve(() => [
    step(0, { content: { model: "qwen3.5:9b" } }),
    step(1, SENT),
    step(2, { ...RECEIVED, duration_ms: 3100 }),
    step(3, { kind: "response_returned", source: "api", destination: "client" }),
  ]);

  const { user, workflow } = await openDetail();

  const labels = within(workflow)
    .getAllByRole("listitem")
    .map((item) => item.textContent);
  expect(labels[0]).toContain("Request received");
  expect(labels[1]).toContain("Sent to Ollama");
  expect(labels[2]).toContain("Received from Ollama");
  expect(labels[2]).toContain("3,100 ms");
  expect(labels[3]).toContain("Response returned");
  expect(screen.queryByText(/"model"/)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Show content" }));

  expect(screen.getByText(/"model": "qwen3.5:9b"/)).toBeInTheDocument();
});

test("long content is truncated until the full-content toggle", async () => {
  const long = "x".repeat(3000);
  serve(() => [step(0, { content: { text: long } })]);

  const { user } = await openDetail();
  await user.click(screen.getByRole("button", { name: "Show content" }));

  expect(screen.getByText(/x+…$/).textContent).not.toContain(long);
  await user.click(screen.getByRole("button", { name: "Show full content" }));
  expect(screen.getByText(new RegExp(long))).toBeInTheDocument();
  expect(screen.getByText(new RegExp(long)).textContent).not.toContain("…");
});

test("a failed step is highlighted with its error message", async () => {
  serve(() => [
    step(0, {}),
    step(1, SENT),
    step(2, { ...RECEIVED, status: "failed", error_message: "model crashed" }),
  ]);

  const { workflow } = await openDetail();

  const items = within(workflow).getAllByRole("listitem");
  expect(items[2]).toHaveAttribute("data-status", "failed");
  expect(items[1]).toHaveAttribute("data-status", "completed");
  expect(within(workflow).getByRole("alert")).toHaveTextContent("model crashed");
});

test("an in-progress step fills in after the next refetch", async () => {
  let done = false;
  serve(() => [
    step(0, {}),
    step(1, SENT),
    done
      ? step(2, { ...RECEIVED, duration_ms: 900, content: { answer: "Hello" } })
      : step(2, { ...RECEIVED, status: "in_progress" }),
  ]);

  const { user, workflow } = await openDetail();
  const received = within(workflow).getAllByRole("listitem")[2];
  expect(received).toHaveAttribute("data-status", "in_progress");

  done = true;
  act(() => {
    FakeEventSource.instances[0]?.emit("request.updated", '{"id":1}');
  });

  await within(workflow).findByText("took 900 ms", { exact: false });
  await user.click(screen.getByRole("button", { name: "Show content" }));
  expect(screen.getByText(/"answer": "Hello"/)).toBeInTheDocument();
  expect(within(workflow).getAllByRole("listitem")[2]).toHaveAttribute(
    "data-status",
    "completed",
  );
});

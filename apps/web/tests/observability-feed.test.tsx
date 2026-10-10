import { screen, within } from "@testing-library/react";
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

function item(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    endpoint: "/v1/chat/completions",
    method: "POST",
    started_at: 1790000000,
    started_at_ms: 1790000000123,
    duration_ms: 3150,
    http_status: 200,
    outcome: "success",
    summary: "qwen3.5:9b · stream",
    response_id: `chatcmpl-${id}`,
    error_message: null,
    ...overrides,
  };
}

function rowAt(rows: HTMLElement[], index: number) {
  const row = rows[index];
  if (!row) throw new Error(`Missing row ${index}`);
  return within(row);
}

function list(data: { id: number }[], hasMore = false) {
  const ids = data.map((row) => row.id);
  return {
    object: "list",
    data,
    first_id: ids[0] ?? null,
    last_id: ids.at(-1) ?? null,
    has_more: hasMore,
  };
}

test("renders in-progress, success and error rows", async () => {
  server.use(
    http.get("*/v1/observability/requests", () =>
      HttpResponse.json(
        list([
          item(3, { outcome: "in_progress", duration_ms: null, http_status: null }),
          item(2, {
            outcome: "error",
            http_status: 400,
            error_message: "messages is required",
          }),
          item(1),
        ]),
      ),
    ),
  );
  renderWithProviders(<App />, "/observability");

  const rows = await screen.findAllByRole("row");
  const inProgress = rowAt(rows, 1);
  expect(inProgress.getByText("in progress")).toBeInTheDocument();
  expect(inProgress.getAllByText("—")).toHaveLength(2);
  const failed = rowAt(rows, 2);
  expect(failed.getByText("error")).toBeInTheDocument();
  expect(failed.getByText("400")).toBeInTheDocument();
  expect(failed.getByText("messages is required")).toBeInTheDocument();
  const ok = rowAt(rows, 3);
  expect(ok.getByText("success")).toBeInTheDocument();
  expect(ok.getByText("3,150 ms")).toBeInTheDocument();
  expect(ok.getByText("qwen3.5:9b · stream")).toBeInTheDocument();
});

test("shows an empty state that explains how to generate traffic", async () => {
  server.use(
    http.get("*/v1/observability/requests", () => HttpResponse.json(list([]))),
  );
  renderWithProviders(<App />, "/observability");

  const empty = await screen.findByText(/No requests recorded yet/);
  expect(empty).toHaveTextContent("Playground");
  expect(empty).toHaveTextContent("chat completions and responses");
});

test("renders a responses entry with its endpoint", async () => {
  server.use(
    http.get("*/v1/observability/requests", () =>
      HttpResponse.json(
        list([
          item(1, {
            endpoint: "/v1/responses",
            response_id: "resp_1",
            summary: "qwen3.5:9b · non-stream",
          }),
        ]),
      ),
    ),
  );
  renderWithProviders(<App />, "/observability");

  const rows = await screen.findAllByRole("row");
  const row = rowAt(rows, 1);
  expect(row.getByText("/v1/responses")).toBeInTheDocument();
  expect(row.getByText("qwen3.5:9b · non-stream")).toBeInTheDocument();
});

test("load more passes last_id as the after cursor", async () => {
  const afterValues: (string | null)[] = [];
  server.use(
    http.get("*/v1/observability/requests", ({ request }) => {
      const after = new URL(request.url).searchParams.get("after");
      afterValues.push(after);
      return HttpResponse.json(
        after === null
          ? list([item(2), item(1)], true)
          : list([item(0, { summary: "second-page" })]),
      );
    }),
  );
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");

  await user.click(await screen.findByRole("button", { name: "Load more" }));

  expect(await screen.findByText("second-page")).toBeInTheDocument();
  expect(afterValues).toEqual([null, "1"]);
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
});

test("renders an interrupted request distinctly from canceled", async () => {
  server.use(
    http.get("*/v1/observability/requests", () =>
      HttpResponse.json(
        list([
          item(2, { outcome: "interrupted", duration_ms: null, http_status: null }),
          item(1, { outcome: "canceled" }),
        ]),
      ),
    ),
  );
  renderWithProviders(<App />, "/observability");

  const rows = await screen.findAllByRole("row");
  const interrupted = rowAt(rows, 1).getByText("interrupted");
  expect(interrupted).toHaveClass("border-dashed");
  expect(rowAt(rows, 2).getByText("canceled")).not.toHaveClass("border-dashed");
});

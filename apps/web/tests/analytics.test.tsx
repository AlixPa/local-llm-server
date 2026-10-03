import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { App } from "@/App";
import { renderWithProviders } from "./render";
import { server } from "./server";

const SENTINEL = "SENTINEL-PROMPT-TEXT";

function item(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    created: 1790000000,
    model: "qwen3.5:9b",
    status: "succeeded",
    stream: true,
    n: 1,
    prompt_tokens: 42,
    completion_tokens: 128,
    total_tokens: 170,
    duration_ms: 3150,
    time_to_first_token_ms: 410,
    generation_duration_ms: 2600,
    load_duration_ms: 12,
    finish_reason: "stop",
    error_type: null,
    error_code: null,
    // Not part of the contract; must never be rendered
    request: SENTINEL,
    response: SENTINEL,
    ...overrides,
  };
}

const SUMMARY = {
  request_count: 4,
  error_count: 1,
  prompt_tokens: 420,
  completion_tokens: 1280,
  avg_duration_ms: 3000.4,
  avg_time_to_first_token_ms: null,
  avg_generation_duration_ms: 2500,
};

function mockAnalytics(afterValues: (string | null)[] = []) {
  server.use(
    http.get("*/v1/analytics/chat-completions/summary", () =>
      HttpResponse.json(SUMMARY),
    ),
    http.get("*/v1/analytics/chat-completions", ({ request }) => {
      const after = new URL(request.url).searchParams.get("after");
      afterValues.push(after);
      if (after === null) {
        return HttpResponse.json({
          object: "list",
          data: [
            item("chatcmpl-2", { status: "failed", time_to_first_token_ms: null }),
            item("chatcmpl-1", { load_duration_ms: null }),
          ],
          first_id: "chatcmpl-2",
          last_id: "chatcmpl-1",
          has_more: true,
        });
      }
      return HttpResponse.json({
        object: "list",
        data: [item("chatcmpl-0", { model: "second-page-model" })],
        first_id: "chatcmpl-0",
        last_id: "chatcmpl-0",
        has_more: false,
      });
    }),
  );
}

test("renders rows and summary, loads the next page by cursor", async () => {
  const afterValues: (string | null)[] = [];
  mockAnalytics(afterValues);
  const user = userEvent.setup();
  renderWithProviders(<App />, "/analytics");

  expect(await screen.findAllByText("qwen3.5:9b")).toHaveLength(2);
  const rows = screen.getAllByRole("row");
  const failed = within(rows[1] as HTMLElement);
  expect(failed.getByText("failed")).toBeInTheDocument();
  expect(failed.getByText("3,150 ms")).toBeInTheDocument();
  expect(failed.getAllByText("—")).toHaveLength(1);

  expect(screen.getByText("25.0%")).toBeInTheDocument();
  expect(screen.getByText("1,280")).toBeInTheDocument();
  expect(screen.getByText("3,000 ms")).toBeInTheDocument();
  expect(screen.getByText("2,500 ms")).toBeInTheDocument();
  expect(screen.getAllByText("—").length).toBeGreaterThan(1);

  await user.click(screen.getByRole("button", { name: "Load more" }));

  expect(await screen.findByText("second-page-model")).toBeInTheDocument();
  expect(afterValues).toEqual([null, "chatcmpl-1"]);
  expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent(SENTINEL);
});

test("shows the empty state and a dash for the error rate", async () => {
  server.use(
    http.get("*/v1/analytics/chat-completions/summary", () =>
      HttpResponse.json({
        ...SUMMARY,
        request_count: 0,
        error_count: 0,
        avg_duration_ms: null,
        avg_generation_duration_ms: null,
      }),
    ),
    http.get("*/v1/analytics/chat-completions", () =>
      HttpResponse.json({
        object: "list",
        data: [],
        first_id: null,
        last_id: null,
        has_more: false,
      }),
    ),
  );
  renderWithProviders(<App />, "/analytics");

  expect(await screen.findByText("No requests recorded yet")).toBeInTheDocument();
  expect(screen.getByText("Error rate").parentElement?.parentElement).toHaveTextContent(
    "—",
  );
});

test("shows the server error message as-is", async () => {
  server.use(
    http.get("*/v1/analytics/chat-completions/summary", () =>
      HttpResponse.json(SUMMARY),
    ),
    http.get("*/v1/analytics/chat-completions", () =>
      HttpResponse.json(
        {
          error: {
            message: "Database is down",
            type: "server_error",
            param: null,
            code: null,
          },
        },
        { status: 500 },
      ),
    ),
  );
  renderWithProviders(<App />, "/analytics");

  expect(await screen.findByText("Database is down")).toBeInTheDocument();
});

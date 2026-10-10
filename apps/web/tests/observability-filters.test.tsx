import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "@/App";
import { FakeEventSource } from "./fake-event-source";
import { renderWithProviders } from "./render";
import { server } from "./server";

let queries: URLSearchParams[] = [];

beforeEach(() => {
  FakeEventSource.instances = [];
  queries = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  server.use(
    http.get("*/v1/observability/requests", ({ request }) => {
      queries.push(new URL(request.url).searchParams);
      return HttpResponse.json({
        object: "list",
        data: [],
        first_id: null,
        last_id: null,
        has_more: false,
      });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function lastQuery(): URLSearchParams {
  const query = queries.at(-1);
  if (!query) throw new Error("No list request was made");
  return query;
}

function source(): FakeEventSource {
  const [instance] = FakeEventSource.instances;
  if (!instance) throw new Error("No EventSource was created");
  return instance;
}

test("changing filters issues requests with the matching query params", async () => {
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(queries).toHaveLength(1));
  expect(lastQuery().has("endpoint")).toBe(false);

  await user.selectOptions(screen.getByLabelText("Endpoint"), "/v1/chat/completions");
  await waitFor(() => expect(lastQuery().get("endpoint")).toBe("/v1/chat/completions"));

  await user.click(screen.getByLabelText("Errors only"));
  await waitFor(() => expect(lastQuery().getAll("outcome")).toEqual(["error"]));

  await user.type(screen.getByLabelText("Since"), "2026-01-01T00:00");
  const expected = Math.floor(new Date("2026-01-01T00:00").getTime() / 1000);
  await waitFor(() => expect(lastQuery().get("since")).toBe(String(expected)));
});

test("pausing holds the list back and resume refetches once", async () => {
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(queries).toHaveLength(1));

  await user.click(screen.getByRole("button", { name: "Pause" }));
  act(() => source().emit("request.created", '{"id": 1}'));
  act(() => source().emit("request.updated", '{"id": 1}'));
  act(() => source().emit("request.created", '{"id": 2}'));

  expect(await screen.findByText("2 new requests waiting")).toBeInTheDocument();
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(queries).toHaveLength(1);

  act(() => source().emit("request.updated", '{"id": 2}'));
  expect(screen.getByText("2 new requests waiting")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Resume" }));
  await waitFor(() => expect(queries).toHaveLength(2));
  expect(screen.queryByText(/waiting/)).not.toBeInTheDocument();
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(queries).toHaveLength(2);
});

test("one created and updated request counts as a single new request", async () => {
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(queries).toHaveLength(1));

  await user.click(screen.getByRole("button", { name: "Pause" }));
  act(() => source().emit("request.created", '{"id": 1}'));
  act(() => source().emit("request.updated", '{"id": 1}'));

  expect(await screen.findByText("1 new request waiting")).toBeInTheDocument();
});

test("changing filters while paused resets the pending count", async () => {
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(queries).toHaveLength(1));

  await user.click(screen.getByRole("button", { name: "Pause" }));
  act(() => source().emit("request.created", '{"id": 1}'));
  expect(await screen.findByText("1 new request waiting")).toBeInTheDocument();

  await user.click(screen.getByLabelText("Errors only"));
  await waitFor(() => expect(screen.queryByText(/waiting/)).not.toBeInTheDocument());
});

test("clearing a filter drops its query param", async () => {
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(queries).toHaveLength(1));

  await user.click(screen.getByLabelText("Errors only"));
  await waitFor(() => expect(lastQuery().getAll("outcome")).toEqual(["error"]));
  await user.click(screen.getByLabelText("Errors only"));
  await waitFor(() => expect(lastQuery().has("outcome")).toBe(false));
});

test("an empty result says no requests match when filters are active", async () => {
  const user = userEvent.setup();
  renderWithProviders(<App />, "/observability");
  expect(await screen.findByText(/No requests recorded yet/)).toBeInTheDocument();

  await user.click(screen.getByLabelText("Errors only"));
  expect(await screen.findByText(/No requests match/)).toBeInTheDocument();
  expect(screen.queryByText(/No requests recorded yet/)).not.toBeInTheDocument();
});

import { act, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "@/App";
import { FakeEventSource } from "./fake-event-source";
import { renderWithProviders } from "./render";
import { server } from "./server";

let listRequests = 0;

beforeEach(() => {
  FakeEventSource.instances = [];
  listRequests = 0;
  vi.stubGlobal("EventSource", FakeEventSource);
  server.use(
    http.get("*/v1/observability/requests", () => {
      listRequests += 1;
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

function source(): FakeEventSource {
  const [instance] = FakeEventSource.instances;
  if (!instance) throw new Error("No EventSource was created");
  return instance;
}

test("an event triggers a refetch of the list", async () => {
  renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(listRequests).toBe(1));

  act(() => source().emit("request.created", '{"id": 1}'));
  await waitFor(() => expect(listRequests).toBe(2));

  act(() => source().emit("request.updated", '{"id": 1}'));
  await waitFor(() => expect(listRequests).toBe(3));
});

test("a malformed event is ignored", async () => {
  renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(listRequests).toBe(1));

  act(() => source().emit("request.updated", "not json"));
  act(() => source().emit("request.updated", '{"id": "x"}'));

  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(listRequests).toBe(1);
});

test("connection state follows the stream and open refetches", async () => {
  renderWithProviders(<App />, "/observability");
  expect(await screen.findByText("Connecting…")).toBeInTheDocument();
  expect(source().url).toBe("/v1/observability/events");

  act(() => source().open());
  expect(await screen.findByText("Live")).toBeInTheDocument();
  await waitFor(() => expect(listRequests).toBe(2));

  act(() => source().fail());
  expect(await screen.findByText("Connection lost, retrying…")).toBeInTheDocument();

  act(() => source().open());
  expect(await screen.findByText("Live")).toBeInTheDocument();
  await waitFor(() => expect(listRequests).toBe(3));

  act(() => source().fail(true));
  expect(await screen.findByText("Disconnected")).toBeInTheDocument();
});

test("the stream is closed on unmount", async () => {
  const { unmount } = renderWithProviders(<App />, "/observability");
  await waitFor(() => expect(listRequests).toBe(1));
  const instance = source();

  unmount();

  expect(instance.closed).toBe(true);
});

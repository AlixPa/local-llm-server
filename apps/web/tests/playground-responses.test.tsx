import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { App } from "@/App";
import { renderWithProviders } from "./render";
import { server } from "./server";

const MODELS = {
  object: "list",
  data: [{ id: "qwen3:8b", object: "model", created: 1, owned_by: "ollama" }],
};

function response(text: string) {
  return {
    id: "resp_1",
    object: "response",
    created_at: 1,
    status: "completed",
    model: "qwen3:8b",
    output: [
      {
        type: "message",
        id: "msg_1",
        status: "completed",
        role: "assistant",
        content: [{ type: "output_text", text, annotations: [] }],
      },
    ],
  };
}

function delta(text: string): string {
  return `event: response.output_text.delta\ndata: ${JSON.stringify({
    type: "response.output_text.delta",
    delta: text,
  })}\n\n`;
}

async function renderPlayground() {
  server.use(http.get("*/v1/models", () => HttpResponse.json(MODELS)));
  const user = userEvent.setup();
  renderWithProviders(<App />, "/playground/responses");
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "model" })).toHaveTextContent(
      "qwen3:8b",
    ),
  );
  await user.type(screen.getByRole("textbox", { name: "Message 1" }), "Hello");
  return user;
}

test("a non-streamed request shows the full answer and builds the body", async () => {
  const user = await renderPlayground();
  let body: Record<string, unknown> = {};
  server.use(
    http.post("*/v1/responses", async ({ request }) => {
      const json: unknown = await request.json();
      if (typeof json === "object" && json !== null) {
        body = Object.fromEntries(Object.entries(json));
      }
      return HttpResponse.json(response("Hi there"));
    }),
  );

  await user.type(screen.getByRole("textbox", { name: "Instructions" }), "Be brief");
  await user.type(screen.getByLabelText("temperature"), "0.2");
  await user.click(screen.getByRole("button", { name: "Send" }));

  expect(await screen.findByText("Hi there")).toBeInTheDocument();
  expect(body).toMatchObject({
    model: "qwen3:8b",
    input: [{ role: "user", content: "Hello" }],
    instructions: "Be brief",
    temperature: 0.2,
  });
  expect(body).not.toHaveProperty("top_p");
  expect(await screen.findByRole("button", { name: /#1/ })).toHaveTextContent(
    "completed",
  );
});

test("a streamed response renders progressively and cancel stops it", async () => {
  const user = await renderPlayground();
  const encoder = new TextEncoder();
  server.use(
    http.post("*/v1/responses", ({ request }) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(delta("Hel")));
          request.signal.addEventListener("abort", () => {
            try {
              controller.close();
            } catch {
              // already closed
            }
          });
        },
      });
      return new HttpResponse(body, {
        headers: { "Content-Type": "text/event-stream" },
      });
    }),
  );

  await user.click(screen.getByRole("switch", { name: "stream" }));
  await user.click(screen.getByRole("button", { name: "Send" }));

  expect(await screen.findByText("Hel")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled(),
  );
  expect(await screen.findByRole("button", { name: /#1/ })).toHaveTextContent(
    "cancelled",
  );
});

test("a stream that ends without [DONE] completes", async () => {
  const user = await renderPlayground();
  server.use(
    http.post(
      "*/v1/responses",
      () =>
        new HttpResponse(delta("Done") + delta("!"), {
          headers: { "Content-Type": "text/event-stream" },
        }),
    ),
  );

  await user.click(screen.getByRole("switch", { name: "stream" }));
  await user.click(screen.getByRole("button", { name: "Send" }));

  expect(await screen.findByText("Done!")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /#1/ })).toHaveTextContent(
    "completed",
  );
});

test("a server error is shown as-is in its history entry", async () => {
  const user = await renderPlayground();
  server.use(
    http.post("*/v1/responses", () =>
      HttpResponse.json(
        {
          error: {
            message: "The model `x` does not exist or you do not have access to it.",
            type: "invalid_request_error",
            param: null,
            code: "model_not_found",
          },
        },
        { status: 404 },
      ),
    ),
  );

  await user.click(screen.getByRole("button", { name: "Send" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "The model `x` does not exist or you do not have access to it.",
  );
  expect(await screen.findByRole("button", { name: /#1/ })).toHaveTextContent("failed");
});

test("history holds only Responses entries", async () => {
  const user = await renderPlayground();
  server.use(http.post("*/v1/responses", () => HttpResponse.json(response("one"))));
  await user.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByText("one");
  expect(screen.getAllByRole("button", { name: /^#\d/ })).toHaveLength(1);
});

test("multiple messages with roles are sent as an input list", async () => {
  const user = await renderPlayground();
  let body: Record<string, unknown> = {};
  server.use(
    http.post("*/v1/responses", async ({ request }) => {
      const json: unknown = await request.json();
      if (typeof json === "object" && json !== null) {
        body = Object.fromEntries(Object.entries(json));
      }
      return HttpResponse.json(response("ok"));
    }),
  );

  await user.click(screen.getByRole("button", { name: "Add message" }));
  await user.click(screen.getByRole("combobox", { name: "Role of message 2" }));
  await user.click(await screen.findByRole("option", { name: "developer" }));
  await user.type(screen.getByRole("textbox", { name: "Message 2" }), "Be terse");
  await user.click(screen.getByRole("button", { name: "Send" }));

  await screen.findByText("ok");
  expect(body.input).toEqual([
    { role: "user", content: "Hello" },
    { role: "developer", content: "Be terse" },
  ]);
});

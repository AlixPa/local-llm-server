import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { App } from "@/App";
import { renderWithProviders } from "./render";
import { server } from "./server";

const MODELS = {
  object: "list",
  data: [
    { id: "qwen3:8b", object: "model", created: 1, owned_by: "ollama" },
    { id: "qwen3:4b", object: "model", created: 1, owned_by: "ollama" },
  ],
};

function completion(content: string) {
  return {
    id: "chatcmpl-1",
    object: "chat.completion",
    created: 1,
    model: "qwen3:8b",
    choices: [
      {
        index: 0,
        message: { role: "assistant", content },
        logprobs: null,
        finish_reason: "stop",
      },
    ],
  };
}

function chunk(content: string): string {
  return `data: ${JSON.stringify({ choices: [{ index: 0, delta: { content } }] })}\n\n`;
}

function mockModels() {
  server.use(http.get("*/v1/models", () => HttpResponse.json(MODELS)));
}

async function renderPlayground() {
  mockModels();
  const user = userEvent.setup();
  renderWithProviders(<App />, "/playground/chat");
  await screen.findByRole("combobox", { name: "model" });
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "model" })).toHaveTextContent(
      "qwen3:8b",
    ),
  );
  await user.type(screen.getByRole("textbox", { name: "Message 1" }), "Hello");
  return user;
}

test("a non-streamed message shows the answer and a history entry", async () => {
  const user = await renderPlayground();
  server.use(
    http.post("*/v1/chat/completions", () => HttpResponse.json(completion("Hi there"))),
  );

  await user.click(screen.getByRole("button", { name: "Send" }));

  expect(await screen.findByText("Hi there")).toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: /#1/ }));
  expect(screen.getByText(/"model": "qwen3:8b"/)).toBeInTheDocument();
});

test("the model selector lists served models and the default is sent", async () => {
  const user = await renderPlayground();
  let body: unknown;
  server.use(
    http.post("*/v1/chat/completions", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(completion("ok"));
    }),
  );

  await user.click(screen.getByRole("combobox", { name: "model" }));
  expect(await screen.findByRole("option", { name: "qwen3:4b" })).toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: "qwen3:8b" }));
  await user.click(screen.getByRole("button", { name: "Send" }));

  await screen.findByText("ok");
  expect(body).toMatchObject({ model: "qwen3:8b" });
});

test("untouched options are not sent, a changed temperature is", async () => {
  const user = await renderPlayground();
  let body: Record<string, unknown> = {};
  server.use(
    http.post("*/v1/chat/completions", async ({ request }) => {
      const json: unknown = await request.json();
      if (typeof json === "object" && json !== null) {
        body = Object.fromEntries(Object.entries(json));
      }
      return HttpResponse.json(completion("ok"));
    }),
  );

  await user.type(screen.getByLabelText("temperature"), "0.2");
  await user.click(screen.getByRole("button", { name: "Send" }));

  await screen.findByText("ok");
  expect(body.temperature).toBe(0.2);
  expect(body).not.toHaveProperty("top_p");
  expect(body).not.toHaveProperty("n");
});

test("a streamed response renders progressively and cancel stops it", async () => {
  const user = await renderPlayground();
  const encoder = new TextEncoder();
  server.use(
    http.post("*/v1/chat/completions", ({ request }) => {
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode(chunk("Hel")));
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

test("a server error is shown verbatim and logged in history", async () => {
  const user = await renderPlayground();
  server.use(
    http.post("*/v1/chat/completions", () =>
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

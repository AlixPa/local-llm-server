import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { App } from "@/App";
import { renderWithProviders } from "./render";
import { server } from "./server";

function mockModels() {
  server.use(
    http.get("*/v1/models", () => HttpResponse.json({ object: "list", data: [] })),
  );
}

test("renders the app shell with a Playground group", () => {
  mockModels();
  renderWithProviders(<App />);
  expect(screen.getByText("local-llm-server")).toBeInTheDocument();
  expect(screen.getByText("Playground")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Chat" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Responses" })).toBeInTheDocument();
});

test("/ redirects to the chat playground and highlights Chat", () => {
  mockModels();
  renderWithProviders(<App />, "/");
  expect(screen.getByText("Conversation")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute("data-active");
  expect(screen.getByRole("link", { name: "Responses" })).not.toHaveAttribute(
    "data-active",
  );
});

test("the Responses entry is highlighted on its page", () => {
  mockModels();
  renderWithProviders(<App />, "/playground/responses");
  expect(screen.getByRole("link", { name: "Responses" })).toHaveAttribute(
    "data-active",
  );
});

test("/playground alone matches nothing", () => {
  mockModels();
  renderWithProviders(<App />, "/playground");
  expect(screen.queryByText("Conversation")).not.toBeInTheDocument();
  expect(screen.queryByText("Answer")).not.toBeInTheDocument();
});

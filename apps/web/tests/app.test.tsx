import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { App } from "@/App";
import { renderWithProviders } from "./render";

test("renders the app shell with a sidebar", () => {
  renderWithProviders(<App />);
  expect(screen.getByText("local-llm-server")).toBeInTheDocument();
});

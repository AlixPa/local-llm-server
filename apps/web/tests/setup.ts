import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";
import { server } from "./server";

// jsdom does not implement matchMedia, which the sidebar's mobile hook uses
window.matchMedia = ((query: string) => ({
  matches: false,
  media: query,
  addEventListener: () => {},
  removeEventListener: () => {},
})) as unknown as typeof window.matchMedia;

// Node's fetch/Request reject the relative /v1 URLs the app uses; resolve them
// against the jsdom origin
function absolute(input: RequestInfo | URL): RequestInfo | URL {
  return typeof input === "string" && input.startsWith("/")
    ? new URL(input, window.location.href)
    : input;
}

const NativeRequest = globalThis.Request;
globalThis.Request = class extends NativeRequest {
  constructor(input: RequestInfo | URL, init?: RequestInit) {
    super(absolute(input), init);
  }
};

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  const mswFetch = globalThis.fetch;
  globalThis.fetch = (input, init) => mswFetch(absolute(input), init);
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => server.close());

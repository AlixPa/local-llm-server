import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "@/api/schema";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const throwOnError: Middleware = {
  async onResponse({ response }) {
    if (response.ok) return undefined;
    const body: unknown = await response
      .clone()
      .json()
      .catch(() => null);
    const message =
      typeof body === "object" &&
      body !== null &&
      "error" in body &&
      typeof body.error === "object" &&
      body.error !== null &&
      "message" in body.error &&
      typeof body.error.message === "string"
        ? body.error.message
        : response.statusText;
    throw new ApiError(response.status, message);
  },
};

// Resolve fetch per call: openapi-fetch otherwise captures it at import time,
// before MSW patches the global in tests
export const api = createClient<paths>({
  fetch: (request) => globalThis.fetch(request),
});
api.use(throwOnError);

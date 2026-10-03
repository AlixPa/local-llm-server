import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { ApiError, api } from "@/api/client";
import { server } from "./server";

const ORIGIN = "http://localhost";

test("throws ApiError carrying the OpenAI error envelope message", async () => {
  server.use(
    http.get(`${ORIGIN}/v1/health`, () =>
      HttpResponse.json(
        { error: { message: "boom", type: "server_error", param: null, code: null } },
        { status: 500 },
      ),
    ),
  );

  const error = await api
    .GET("/v1/health", { baseUrl: ORIGIN })
    .catch((e: unknown) => e);

  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 500, message: "boom" });
});

import { describe, expect, test } from "vitest";
import { parseSse } from "@/lib/parse-sse";

const encoder = new TextEncoder();

function streamOf(parts: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const part of parts) controller.enqueue(encoder.encode(part));
      controller.close();
    },
  });
}

async function collect(
  stream: ReadableStream<Uint8Array>,
  signal?: AbortSignal,
): Promise<unknown[]> {
  const payloads: unknown[] = [];
  for await (const payload of parseSse(stream, signal)) payloads.push(payload);
  return payloads;
}

describe("parseSse", () => {
  test("handles events split mid-line across reads", async () => {
    const payloads = await collect(
      streamOf(['data: {"a"', ":1}\n", '\ndata: {"a":2}\n\n', "data: [DONE]\n\n"]),
    );
    expect(payloads).toEqual([{ a: 1 }, { a: 2 }]);
  });

  test("yields multiple events delivered in one read", async () => {
    const payloads = await collect(
      streamOf(['data: {"a":1}\n\ndata: {"a":2}\n\ndata: [DONE]\n\n']),
    );
    expect(payloads).toEqual([{ a: 1 }, { a: 2 }]);
  });

  test("stops at [DONE] and ignores what follows", async () => {
    const payloads = await collect(
      streamOf(['data: {"a":1}\n\n', "data: [DONE]\n\n", 'data: {"a":2}\n\n']),
    );
    expect(payloads).toEqual([{ a: 1 }]);
  });

  test("throws the message of an error event", async () => {
    const stream = streamOf([
      'data: {"a":1}\n\n',
      'data: {"error":{"message":"boom","type":"server_error"}}\n\n',
    ]);
    const payloads: unknown[] = [];
    const run = async () => {
      for await (const payload of parseSse(stream)) payloads.push(payload);
    };
    await expect(run()).rejects.toThrow("boom");
    expect(payloads).toEqual([{ a: 1 }]);
  });

  test("ends iteration when the signal aborts", async () => {
    const controller = new AbortController();
    const stream = new ReadableStream<Uint8Array>({
      start(streamController) {
        streamController.enqueue(encoder.encode('data: {"a":1}\n\n'));
        controller.signal.addEventListener("abort", () =>
          streamController.error(new DOMException("aborted", "AbortError")),
        );
      },
    });
    const payloads: unknown[] = [];
    for await (const payload of parseSse(stream, controller.signal)) {
      payloads.push(payload);
      controller.abort();
    }
    expect(payloads).toEqual([{ a: 1 }]);
  });
});

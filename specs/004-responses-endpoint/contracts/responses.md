# Contract: `POST /v1/responses` (OpenAI-defined)

Authoritative source: the vendored `openai-spec/openapi.yaml` (`createResponse`, schemas
`CreateResponse`, `Response`, `ResponseStreamEvent`). This file records only the local decisions;
where it is silent, the vendored spec governs.

## Scope

Only the create operation. `GET`/`DELETE /v1/responses/{id}`, `POST …/cancel`,
`GET …/input_items`, `POST /v1/responses/input_tokens`, `POST /v1/responses/compact` are not
implemented and return the standard unknown-route / method-not-allowed error envelope.

## Request

`application/json`, schema `CreateResponse`; unknown fields ignored. Field handling is the
policy table in [research.md R3](../research.md) (rejected options → 400
`invalid_request_error` / `unsupported_parameter` with `param` = the option, message
`Unsupported parameter: '<option>'.`).

Minimal example:

```json
{ "model": "qwen3.5:9b", "input": "Say hi", "instructions": "Be brief." }
```

## Non-streaming response (200)

Schema `Response`: `id` (`resp_…`), `object: "response"`, `created_at`, `completed_at`, `status`
(`completed` | `incomplete`), `model`, `output` (message item, then function-call items),
`usage`, `error: null`, `incomplete_details` (`{"reason": "max_output_tokens"}` when cut off,
else `null`), plus the echoed request settings (research R5).

## Streaming response (200, `text/event-stream`)

Frames: `event: <type>` + `data: <json>` + blank line; payload `type` equals the `event` name;
every event has `sequence_number` (0-based, increasing). **No `[DONE]` line.** Order for a text
reply:

```
response.created            (response.status = in_progress, output = [])
response.in_progress
response.output_item.added  (message item, status in_progress, content = [])
response.content_part.added
response.output_text.delta  × N     (logprobs: [] unless requested)
response.output_text.done
response.content_part.done
response.output_item.done
response.completed          (full Response incl. usage)   # or response.incomplete
```

A tool call adds, after the message item (or instead of it when there is no text):
`response.output_item.added` (function_call) → `response.function_call_arguments.delta` (the whole
JSON string) → `response.function_call_arguments.done` → `response.output_item.done`.

Each event validates against `ResponseStreamEvent` in the contract tests.

## Errors

Envelope `{"error": {"message", "type", "param", "code"}}` with the statuses used for chat:

| Condition | Status | `type` | `code` |
|---|---|---|---|
| Schema validation failure | 400 | `invalid_request_error` | (per `api/errors.py`) |
| Unsupported option / input item / tool / image URL | 400 | `invalid_request_error` | `unsupported_parameter` |
| Context overflow with `truncation: disabled` | 400 | `invalid_request_error` | `context_length_exceeded` |
| Unknown model | 404 | `invalid_request_error` | `model_not_found` |
| Ollama unreachable | 503 | `server_error` | `null` |
| Ollama error | 500 | `server_error` | `null` |

Failure after the stream has started: a final `response.failed` event
(`response.status = "failed"`, `response.error = {code, message}`), then the stream ends.
Client disconnect: generation stops; nothing more is sent; the request is recorded as cancelled.

## Recording and tracing

- Recorded in `response_records` / `response_contents` for every request that reaches the endpoint
  logic (see data-model.md).
- Tracked endpoint: workflow steps request received → sent to Ollama → received from Ollama
  (assembled for streams) → response returned, plus errors; `traced_requests.response_id` =
  the record's `external_id`; summary `"<model> · stream|non-stream"`.

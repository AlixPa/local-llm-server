# Research: Responses Endpoint End to End

Sources: the vendored `openai-spec/openapi.yaml`, the existing chat implementation
(`specs/002-chat-completions/research.md`), and the installed `openai` SDK (checked for stream
error handling). Ollama behavior (`/api/chat`, timings, `done_reason`, context overflow count) is
reused from chat research R2, R3, R6, R7 and not re-verified; the integration test re-checks it.

## R1. Ollama access

- **Decision**: reuse the existing `OllamaClient.chat` / `chat_stream` (native `/api/chat`)
  unchanged. No change to `packages/llm`.
- **Rationale**: Responses needs the same capabilities as chat (timings, tools, format, think,
  logprobs, `num_ctx`); the translation lives in the API layer.
- **Alternatives**: Ollama's own `/v1/responses` compatibility route (no timings, which breaks
  analytics; the same objection as chat R2).

## R2. Shared inference helpers (extraction from chat)

- **Decision**: move the endpoint-agnostic parts of `chat/service.py` into `api/inference.py`:
  `Policy` enum, `THINK_LEVELS`, `ReasoningEffort` mapping input, `ClientDisconnectedError`,
  error builders (`unsupported`, `model_not_found`, `context_exceeded`, `to_api_error`,
  `internal_error`, `OLLAMA_ERRORS`), `overflowed`, `ms`, `Totals` (without the chat-shaped
  `usage()`), `race`, `close_open_steps`, the tool-choice emulation core (normalized to a
  mode + optional function name so both schemas feed it), and the shielded-record wrapper. Chat
  keeps its schema-specific code and its tests unchanged.
- **Rationale**: ~250 lines are identical for the second consumer; copying them would let the two
  endpoints drift on cancellation/shielding subtleties. YAGNI is satisfied because the second
  consumer exists now; nothing speculative is extracted (no base class, no generic "run" framework).
- **Alternatives**: copy-paste into `responses/service.py` (drift risk on subtle cancel/shield
  code); a generic endpoint-runner abstraction (premature, two endpoints differ in event shapes).

## R3. Request field policy (all 32 `CreateResponse` properties)

Every property must appear in `FIELD_POLICY` in `responses/service.py`; a test asserts the table
equals the vendored schema's property set. "Empty" values (`null`, `false`, `[]`, `{}`) of a
rejected option are accepted, as for chat's `logit_bias`.

| Field | Policy | Mapping |
|---|---|---|
| `model` | honor | must match a `models` row, else 404 `model_not_found` |
| `input` | honor | string → one user message; list → items (R5) |
| `instructions` | honor | leading `system` message (merged with the tool-choice instruction, as in chat) |
| `stream` | honor | typed SSE events (R6) |
| `temperature`, `top_p` | honor | same-named `options` |
| `max_output_tokens` | honor | `num_predict`; `done_reason == "length"` → `status: incomplete`, `incomplete_details.reason: max_output_tokens` |
| `text` | honor | `format` `text` → none; `json_object` → `format: "json"`; `json_schema` → its schema as `format`; `verbosity` ignored |
| `tools` | honor | `function` tools → Ollama tools (Responses tools are flat: `name` at top level); any other tool type → 400 `unsupported_parameter` naming `tools` |
| `tool_choice` | emulate | `none`/`auto`/`required`/`{type: function, name}` as chat R5; `allowed_tools` and hosted-tool choices → 400 |
| `reasoning` | honor | `effort` → `THINK_LEVELS` (default `think: false`); thinking text never returned; `summary`/`generate_summary` ignored |
| `top_logprobs`, `include` | honor | `include` containing `message.output_text.logprobs` turns on Ollama logprobs (`top_logprobs` honored); other `include` values ignored |
| `truncation` | honor | `disabled` (default): context overflow → 400 `context_length_exceeded` (chat R3 rule); `auto`: overflow is not raised (Ollama truncates) |
| `parallel_tool_calls`, `max_tool_calls` | ignore | model decides |
| `metadata` | ignore | accepted, echoed in the response object |
| `store` | ignore | accepted; nothing is retrievable so there is nothing to store |
| `stream_options`, `user`, `safety_identifier`, `service_tier`, `prompt_cache_key`, `prompt_cache_retention`, `prompt_cache_options`, `access_programs` | ignore | accepted and dropped |
| `previous_response_id` | reject | 400 `unsupported_parameter` (a client must never silently lose context) |
| `conversation` | reject | 400 |
| `background` | reject when true | 400 (no async execution/polling exists) |
| `prompt` | reject | 400 (stored prompt templates) |
| `context_management` | reject | 400 (server-side compaction is absent) |
| `moderation` | reject | 400, as chat |

- **Rationale**: same rule as chat R5: reject only where ignoring would change the output or
  promise a capability that is absent.

## R4. Pydantic models (typed subset + catch-all)

- **Decision** (confirmed by the user): hand-written models with OpenAI's schema names verbatim,
  `extra="ignore"`. Request side: all 32 `CreateResponse` properties typed. Typed unions for what
  we consume: `InputParam` (string | list of `InputItem`), `EasyInputMessage`, `InputMessage`,
  `OutputMessage` (as input), `FunctionToolCall`, `FunctionCallOutputItemParam`, `ReasoningItem`
  (accepted and dropped), content parts `InputTextContent` / `InputImageContent` /
  `OutputTextContent`, `FunctionTool`, tool-choice variants, `TextResponseFormatConfiguration`,
  `Reasoning`. Every other input item / tool type is parsed by a loose catch-all (type string
  plus extras) and rejected in `_prepare` with 400 `unsupported_parameter`. Response side: only
  what we emit: `Response`, `OutputMessage`, `FunctionToolCall`, `ResponseUsage`,
  `ResponseOutputText`, `ResponseLogProb`, `IncompleteDetails`/`ResponseError`, and the stream
  events listed in R6.
- **Rationale**: hosted-tool items and ~50 stream events can never be produced or accepted
  locally; typing them would be thousands of dead lines (YAGNI). Contract tests validate
  everything we emit against the vendored spec, which is the actual fidelity guarantee.
- **Alternatives**: full hand-written parity; `datamodel-code-generator` (new dependency,
  generated code conflicts with strict typing and verbatim naming conventions).

## R5. Input and output translation

- **Input items** → Ollama messages: `EasyInputMessage`/`InputMessage`/`OutputMessage`
  (`developer` → `system`; text parts joined; `input_image` with a `data:` URL → `images`;
  http(s) `image_url` or `file_id`, `input_file`, `input_audio` → 400);
  `FunctionToolCall` → assistant message with `tool_calls`; `FunctionCallOutputItemParam` → `tool`
  message (`tool_name` resolved from the matching earlier call by `call_id`); `ReasoningItem` →
  dropped; `item_reference` and any catch-all type → 400.
- **Output**: `Response` with `output` = `[message item]` (always present when there is text or no
  tool call: `id: msg_<hex>`, `status: completed`, one `output_text` part with `annotations: []`
  and `logprobs` only when requested) followed by one `function_call` item per tool call
  (`id: fc_<hex>`, `call_id: call_<hex>`, `arguments` as a JSON string). Echo the request's
  `instructions`, `metadata`, `temperature`, `top_p`, `tools`, `tool_choice`,
  `parallel_tool_calls`, `max_output_tokens`, `text`, `truncation`, `reasoning`, `top_logprobs`
  (spec-required fields default as OpenAI does). `usage`: `input_tokens`, `output_tokens`,
  `total_tokens`, `cached_tokens: 0`, `reasoning_tokens: 0`. `id: resp_<24 hex>`.
- **Rationale**: matches what an SDK needs to run a function-calling loop; reasoning items are not
  emitted (consistent with chat R4).

## R6. Streaming wire format and events

- **Decision**: SSE frames are `event: <type>\ndata: <json>\n\n` where `<type>` equals the
  payload's `type`; **no `data: [DONE]`** (OpenAI's Responses stream ends at the connection close
  after the terminal event). Emitted events, with a monotonically increasing `sequence_number`:
  `response.created`, `response.in_progress`, then per output item `response.output_item.added`,
  (message: `response.content_part.added`, `response.output_text.delta`\*,
  `response.output_text.done`, `response.content_part.done`; function call:
  `response.function_call_arguments.delta` (once, the full JSON, since Ollama returns tool calls
  whole) and `.done`), `response.output_item.done`, and finally `response.completed` or
  `response.incomplete` (both carry the full `Response` incl. `usage`).
- **Failure mid-stream**: emit `response.failed` (the `Response` with `status: failed` and
  `error: {code, message}`) and end the stream. **Verified in the installed SDK**: it raises
  `APIError` only when a payload has a top-level truthy `error` key, so a flat `error` event or
  `response.failed` is surfaced as a normal event; that is also what OpenAI's server does.
  Errors before the first event (validation, unknown model, unreachable Ollama) are plain HTTP
  error responses, as for chat.
- **Streams are recorded once** at the end (spec/CLAUDE.md logging rules): one assembled
  `received_from_ollama` step; cancelled and failed streams never get a `response_returned` step.
- **CLAUDE.md**: the "Streaming" convention was amended in this planning step to say each
  endpoint follows OpenAI's own stream format (chat: `data:` + `[DONE]`; Responses: `event:` +
  `data:`, no `[DONE]`). The router's wrapper emits `event:` lines and `[DONE]` per endpoint contract.

## R7. Persistence

- **Decision** (user decision, not merged): `response_records` (metadata) and `response_contents`
  (request + response bodies, 1:1, `ON DELETE CASCADE`), mirroring the chat pair minus `n`. One
  insert per request at completion, including failed and cancelled. No in-progress rows (the
  trace covers in-flight state).
- **Alternatives**: one generic table for both endpoints (rejected by the user).

## R8. Combined analytics

- **Decision**: `GET /v1/analytics/requests` and `GET /v1/analytics/requests/summary` replace the
  chat-only endpoints. One read-only repository module builds a `UNION ALL` of the two metadata
  tables (with a literal `endpoint` column holding `/v1/chat/completions` or `/v1/responses`,
  the same values the tracing tables use), then applies the filters (`endpoint`, `status`,
  `since`, `until`), ordering `(created_at DESC, external_id DESC)` and the cursor. The cursor is
  the item's `id` (`external_id`), unique across both tables because prefixes differ (`chatcmpl-`
  vs `resp_`). The summary uses the same filtered union, so table and summary always agree.
- **Rationale**: the table must be one list across endpoints (user decision); separate tables stay
  separate on disk, the union lives only in a read path. Each table keeps its
  `(created_at DESC, external_id DESC)` index (the chat one is re-created to match, since the union orders and pages by `external_id`), which SQLite uses for the per-branch ordering and cursor seek; 10k rows are
  trivially within SC-010.
- **Alternatives**: two requests merged client-side (breaks cursor pagination); a database view
  (needs a migration and obscures the query; revisit only if performance demands).

## R9. Shared status enum

- **Decision**: replace `ChatCompletionStatus` by a shared `RequestStatus`
  (`succeeded`/`failed`/`cancelled`) used by both record tables and the analytics filter. The
  column is a non-native, constraint-free enum, so the rename itself needs no column change (the
  migration is reviewed to confirm autogenerate emits nothing for it beyond the index swap in R8).
- **Rationale**: the union read path and the status filter need one type; the tables stay
  separate. No backward compatibility is required, so the rename is a plain refactor.

## R10. Tracing

- **Decision**: add `("POST", "/v1/responses")` to `TRACKED`; the service uses the same `Trace`
  calls as chat (summary `"<model> · stream|non-stream"`, `set_response_id`, `step_sent` /
  `step_received`, `close_open_steps`). `traced_requests.response_id` keeps its value-link
  semantics; its model comment is updated to mention both record tables. The Observability tab's
  sequence view is endpoint-agnostic, so it needs only the endpoint filter default list and the
  empty-state text updated.

## R11. Frontend

- **Navigation**: nested routes `/playground/chat` and `/playground/responses`; `/` navigates to
  `/playground/chat`; the flat `/playground` route is deleted (no redirect). The sidebar renders
  "Playground" as a group header with `SidebarMenuSub` entries Chat and Responses (always
  expanded; no collapsible, YAGNI); Analytics and Observability stay top-level links.
- **Filters** (user decision): `observability-filters.tsx` becomes the shared `request-filters.tsx`
  (endpoint select, status select, since, until). Observability's "Errors only" checkbox is
  replaced by the status select (its options are the five trace outcomes; superset of the old
  behavior); Analytics supplies `succeeded/failed/cancelled`. Both pages keep filter state in
  `useState` and pass it to TanStack Query keys; Analytics' list uses `useInfiniteQuery`, its
  summary a `useQuery` on the same filters.
- **Streaming hook**: `use-chat-stream.ts` and the new `use-response-stream.ts` share one generic
  fetch + `AbortController` + `parseSse` core parametrized by URL and a text-delta extractor
  (`choices[].delta.content` vs `response.output_text.delta`), keeping the single allowed raw
  `fetch`. `parseSse` additionally throws on `type: "response.failed"` / `type: "error"`
  payloads (carrying the server message) and already tolerates a stream that ends without `[DONE]`.
- **Playground page**: input (text) + instructions fields, model selector, option controls for the
  honored/accepted `CreateResponse` fields (rejected ones are still enterable as JSON so the
  server's error shows as-is, as in the chat playground), stream switch + cancel, session history
  of request/answer pairs.
- **Types**: `pnpm gen:api` regenerates `schema.d.ts`; the Responses request type is the generated
  `CreateResponse`; no hand-written API types.

## R12. Testing summary

- Contract: `validate_contract` for non-streaming success and error cases; `validate_schema(event,
  "ResponseStreamEvent")` for every streamed event (checked early that the normalized `anyOf`
  union validates our events; fall back to the concrete event schema by `type` if it is ambiguous).
- Policy test over the vendored `CreateResponse` properties (SC-002).
- Behavior: input translation (string, messages, images, function call round trip), tool choice,
  structured output, `max_output_tokens` → incomplete, truncation, unknown model, unreachable
  Ollama, cancel mid-stream, recorded rows (success/failed/cancelled), no recording on validation
  failure, trace steps.
- Analytics: combined ordering/pagination across both tables, each filter and their combinations,
  summary equals table set, no content leak, empty state.
- Frontend: sidebar group + routes, Responses playground (stream on/off, error shown as-is,
  history), SSE parser failure events, Analytics filters/combined table, shared filters in
  Observability.
- One `@pytest.mark.integration` test with the real SDK and Ollama (non-streaming, streaming,
  function-call loop).

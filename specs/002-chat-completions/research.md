# Research: Chat Completions End to End

Sources: Ollama library pages and API docs (fetched 2026-10-03). Items marked **verify** were
checked against a running Ollama (T010, T032, T062; results recorded inline as "Verified"). The
one exception is mid-stream failure behavior (R7), which stays unverified.

## R1. Model

- **Decision**: `qwen3.5:9b` (6.6 GB, 256K context), seeded as the only row of the `models` table by the migration (R12). No model env var: the served set lives in the database.
- **Rationale**: qwen3.6 and qwen3.8 only ship 27B+ tags, so qwen3.5 is the newest generation with
  a size under 10B. Supports tools and thinking (**verified** 2026-10-03: `/api/show` reports capabilities
  `completion`, `vision`, `tools`, `thinking`; context length 262144; 9.7B, Q4_K_M).
- **Alternatives**: `qwen3.5:4b` / `2b` / `0.8b` (useful as fast test models: add a row to `models`); `qwen3.8-flash-next` (experimental preview, size unchecked, rejected as unstable).

## R2. Ollama API surface

- **Decision**: call Ollama's native `/api/chat` through one shared `httpx.AsyncClient`, translating
  OpenAI requests/responses ourselves.
- **Rationale**: only the native API returns timings (`total_duration`, `load_duration`,
  `prompt_eval_*`, `eval_*`, in nanoseconds) and exposes `top_k`, `think`, `logprobs`, `keep_alive`,
  `num_ctx`. The OpenAI-compatible endpoint lacks timings, `tool_choice`, `logit_bias`, `n`, and
  logprobs. We must translate for `n` and `tool_choice` regardless.
- **Alternatives**: Ollama's `/v1/chat/completions` (less translation, but no timings → breaks the
  Analytics requirement); the `ollama` Python package (extra dependency; `httpx` is enough and
  matches the "one shared client" convention).

## R3. Context window

- **Decision**: always send `options.num_ctx` explicitly (default `32768`, configurable via
  `LOCAL_LLM_OLLAMA_NUM_CTX`). Treat `prompt_eval_count >= num_ctx` as context overflow and return
  OpenAI's `context_length_exceeded` (400). **verify** (task T010, a gate before the service tasks)
  that Ollama truncates rather than errors, and that `prompt_eval_count` reaches `num_ctx` in that
  case. Streaming: `prompt_eval_count` only arrives in the final chunk, so if overflow is only
  detectable then, it is delivered as an SSE error event; if Ollama errors up front, it is returned
  as a real 400 before streaming starts (R13). T010's outcome fixes this row. Because `prompt_eval_count == num_ctx` may also be a legitimate prompt that exactly fills the window, T010 must record the observed behavior (truncation vs error, and the exact count on overflow) here, together with the resulting rule and its false-positive behavior; a test covers a prompt just below `num_ctx`.
- **Rationale**: Ollama's default of 2048 silently truncates prompts; an explicit value makes the
  limit known and the overflow detectable.
- **Verified (T010, qwen3.5:9b, 2026-10-03)**: Ollama never errors on overflow (200, also when streaming) and
  truncates the prompt; the reported `prompt_eval_count` is then **`num_ctx // 2 + 2`** (1026 for 2048, 2050
  for 4096), never `>= num_ctx`, so the `>= num_ctx` rule above does not work. Rule to implement
  instead: overflow when `prompt_eval_count == num_ctx // 2 + 2`. False positive: a legitimate prompt of
  exactly that many tokens (rare; counts below and above it are reported faithfully, e.g. 1902 for
  `num_ctx` 2048). Detectable only in the final chunk (streaming: SSE error event, not an up-front 400).
  Repeating the same prompt does not lower `prompt_eval_count` (no KV-cache effect on the count).

## R4. Thinking output

- **Decision**: send `think: false` unless `reasoning_effort` is provided (then map to a think
  level; `none`/`minimal` → `false`). Never include the model's `thinking` text in responses.
- **Rationale**: OpenAI's response schema has no field for it (contract fidelity); default-off keeps
  latency low and content clean. Thinking tokens, when enabled, still count in `eval_count`.

## R5. OpenAI field policy (honor / emulate / ignore / reject)

| Field | Policy | Mapping |
|---|---|---|
| `messages` | honor | `developer` → `system`; text parts joined; `image_url` with a `data:` URL → Ollama `images`; http(s) image URLs → 400; `input_audio`/`file` parts → 400 |
| `model` | honor | must match a row of the `models` table (id = Ollama tag), else 404 `model_not_found`; the response reports that model |
| `stream`, `stream_options` | honor | NDJSON → SSE chunks; `include_usage` adds the final usage chunk |
| `temperature`, `top_p`, `seed` | honor | same-named `options` |
| `max_tokens`, `max_completion_tokens` | honor | → `num_predict`; `max_completion_tokens` wins if both set |
| `stop` | honor | string or array → `options.stop` |
| `frequency_penalty`, `presence_penalty` | honor (verified T010: Ollama accepts both options, 200) | pass in `options`; whether they change the output is not asserted |
| `response_format` | honor | `json_object` → `format: "json"`; `json_schema` → schema as `format`; `text` → none |
| `tools`, `functions`, `function_call` | honor | `tools` passthrough; legacy `functions`/`function_call` converted to `tools`/`tool_choice` |
| `tool_choice` | emulate | `none` → drop tools; `auto` → default; `required` / named function → restrict `tools` to the named one (or all) and append a system instruction; best-effort |
| `parallel_tool_calls` | ignore | model decides |
| `logprobs`, `top_logprobs` | honor | native `logprobs`/`top_logprobs`, reshaped to `choices[].logprobs` |
| `n` | emulate | `n` concurrent Ollama calls; usage summed; with `stream`, choices streamed one after another |
| `reasoning_effort` | honor | see R4 |
| `logit_bias` | reject | 400 `invalid_request_error` (no mapping; ignoring would silently change output); an empty map is accepted |
| `modalities` | honor/reject | `["text"]` accepted; `audio` → 400 |
| `audio`, `web_search_options`, `moderation` | reject | 400 naming the option |
| `verbosity`, `prediction`, `metadata`, `store`, `user`, `safety_identifier`, `service_tier`, `prompt_cache_key`, `prompt_cache_retention`, `prompt_cache_options` | ignore | accepted and dropped |

- **Rationale**: matches spec FR-003/004/005. Reject only where silently ignoring would change the
  output or promise a capability that is absent.

## R6. Timings and time to first token

- **Decision**: store milliseconds (ns ÷ 1e6, rounded). `load_duration_ms` is kept and shown: cold-load time is unrecoverable if not captured and is the main input for performance analysis of the Ollama server. `duration_ms` = wall-clock measured by the
  API; `generation_duration_ms` = Ollama `eval_duration`; `load_duration_ms` = Ollama
  `load_duration`; `time_to_first_token_ms` measured by the API at the first streamed chunk
  (null for non-streaming). For `n > 1`, durations are the wall-clock for the whole request and
  generation/load are summed.
- **Rationale**: Ollama has no time-to-first-token field.

## R7. Error mapping

| Condition | Status | `type` | `code` |
|---|---|---|---|
| Unsupported / invalid option | 400 | `invalid_request_error` | `unsupported_parameter` (param = option) |
| Context overflow (R3) | 400 | `invalid_request_error` | `context_length_exceeded` |
| Model not in `models` table, or in the table but not pulled (Ollama 404) | 404 | `invalid_request_error` | `model_not_found`, param `null`, message ``The model `X` does not exist or you do not have access to it.`` |
| Ollama unreachable / 5xx | 503 / 500 | `server_error` | `null` |
| Schema validation failure | 400 | `invalid_request_error` | per CLAUDE.md fix of `api/errors.py` |

- A model still loading is not an error: Ollama holds the request until the load finishes, so the client must have no read timeout (connect timeout only); an unreachable host fails fast on connect.
- Verified (T010): unknown model → HTTP 404 with body `{"error": "model 'X' not found"}`; `done_reason` is
  `"length"` when `num_predict` is hit. Mid-stream failure behavior remains unverified. A failure after
  streaming has begun is delivered as an SSE `data: {"error": ...}` event followed by `[DONE]`.

## R8. Persistence model

- **Decision**: two tables, `chat_completion_records` (metadata) and `chat_completion_contents`
  (request + response bodies, 1:1, `ON DELETE CASCADE`). One insert per request at completion
  (including failed and cancelled); no in-progress rows.
- **Rationale**: FR-015 — analytics queries physically never touch content. Writing once at the end
  avoids status-transition logic (YAGNI); in-flight requests simply don't appear yet.
- **Alternatives**: single table with a projection (content leaks one forgotten column away);
  write-at-start + update (needs crash recovery for orphan rows).

## R9. Analytics endpoints

- **Decision**: `GET /v1/analytics/chat-completions` (cursor `after`, `limit` ≤ 100, OpenAI list
  envelope, newest first) and `GET /v1/analytics/chat-completions/summary`.
- **Rationale**: OpenAI defines `GET /v1/chat/completions[/{id}]` (stored completions); a
  non-OpenAI endpoint must not shadow them (constitution I), so analytics lives under its own
  prefix. Validation errors on these use standard 422 per CLAUDE.md.

## R10. Frontend

- **Decision**: routes `/playground` (default redirect from `/`) and `/analytics`; sidebar links in
  `AppSidebar`. Playground: `useState` conversation/options/history, TanStack `useMutation` for
  non-streaming, a pure `parseSse` in `src/lib/` for streaming with `AbortController` (the one
  allowed raw `fetch`). Analytics: `useInfiniteQuery` (cursor `after`) + summary `useQuery`. Add
  shadcn components as needed (`textarea`, `select`, `switch`, `slider`, `label`, `table`,
  `card`, `badge`), regenerate `schema.d.ts`.
- **Rationale**: follows the Frontend section of `.claude/CLAUDE.md`; no store, no polling (not a
  batch).

## R11. Testing

- Ollama mocked via an `httpx.MockTransport` injected into the shared client (FastAPI dependency
  override); `validate_contract` for non-stream success and error cases; `validate_schema` against
  `CreateChatCompletionStreamResponse` for stream chunks; db repository tests on in-memory SQLite;
  one `@pytest.mark.integration` test against real Ollama; Vitest + MSW for the SSE parser, the
  playground flow, and analytics rendering (asserting no content fields are ever requested).

## R12. Models

- **Decision**: a `models` table (`id` int PK, `external_id` unique = Ollama tag, `created_at`,
  `owned_by`), seeded with `qwen3.5:9b` / `qwen` in the migration. `GET /v1/models` returns
  OpenAI's `ListModelsResponse` exactly (`{"object": "list", "data": [Model]}`, no pagination
  fields: OpenAI defines none). Chat completions validates `model` against the table.
- **Rationale**: OpenAI defines this endpoint, so it follows their contract verbatim
  (`validate_contract`). A table avoids hardcoding and costs one small repository function.
- **Out of scope**: `GET /v1/models/{model}`, deletion, any admin write path (rows are added by
  migration or by hand).

## R13. Streaming error timing

- **Decision**: for `stream=true`, option-policy rejection, model validation, and the first Ollama
  chunk are all obtained *before* returning `StreamingResponse`, so pre-stream failures (unsupported
  option, `model_not_found`, Ollama unreachable/404/5xx, up-front context overflow) return a real
  4xx/5xx envelope. Only failures after the first chunk are sent as an SSE `data: {"error": ...}`
  event followed by `[DONE]`.
- **Rationale**: a `StreamingResponse` commits status 200 on first byte; SDKs rely on the status to
  raise the right exception.

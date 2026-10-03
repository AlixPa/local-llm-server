---

description: "Task list for Chat Completions End to End"
---

# Tasks: Chat Completions End to End

**Input**: Design documents from `/specs/002-chat-completions/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R13), data-model.md, contracts/chat-completions.md, contracts/analytics.md, quickstart.md

**Tests**: Included. `.claude/CLAUDE.md` requires a `validate_contract` test for every OpenAI-defined endpoint, behavior tests for non-OpenAI endpoints, and Vitest tests for SSE parsing and key interactions. Ollama is mocked with `httpx.MockTransport` except for the single `integration`-marked test.

**Organization**: Grouped by user story. Conventions that apply to every task (from `.claude/CLAUDE.md`): `mypy --strict`, Ruff (88 cols), modern syntax (`X | None`, builtin generics, `StrEnum`), minimal comments, absolute imports, `async def` handlers, no DB statements outside `packages/db`; frontend: Biome, `tsc` strict, named exports, kebab-case files, `@/` imports, no `any`. Add dependencies only via `uv add --project <pkg>` / `pnpm add`, never by hand-editing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 (endpoint), US2 (Playground), US3 (Analytics)

---

## Phase 1: Setup

**Purpose**: Scaffolding for the new `llm` workspace package and shared config.

- [X] T001 Create the `llm` workspace package: `packages/llm/pyproject.toml` (name `llm`, Python >=3.14, build system matching `packages/db/pyproject.toml`), `packages/llm/src/llm/__init__.py`, empty `packages/llm/src/llm/py.typed`; add `"packages/llm"` to `[tool.uv.workspace].members` and `llm = { workspace = true }` to `[tool.uv.sources]` in root `pyproject.toml`; add `"llm"` to the root dev group and as a dependency of `apps/api` via `uv add --project apps/api llm`
- [X] T002 Add runtime dependencies: `uv add --project packages/llm httpx pydantic-settings`; add `packages/llm/tests` to `testpaths` in root `pyproject.toml`
- [X] T003 Add the OpenAI SDK as a dev dependency for the SDK drop-in test (SC-001): `uv add --project apps/api --dev openai`
- [X] T004 [P] Add `LOCAL_LLM_OLLAMA_HOST` (`http://localhost:11434`) and `LOCAL_LLM_OLLAMA_NUM_CTX` (`32768`) to `.env.example` (no model variable: served models live in the `models` table)
- [X] T005 [P] Update `README.md` setup steps: Ollama must be running, `ollama pull qwen3.5:9b`, and the new `LOCAL_LLM_OLLAMA_*` vars (setup steps changed, so README update is warranted)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: `llm` client, persistence layer, error handling, and app wiring that every story needs.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### `llm` package

- [X] T006 [P] Implement `packages/llm/src/llm/config.py`: `pydantic-settings` `OllamaSettings` with env prefix `LOCAL_LLM_OLLAMA_` and fields `host`, `num_ctx` (defaults per T004); the model comes per request from the `models` table, reading `.env`
- [X] T007 [P] Implement `packages/llm/src/llm/schemas.py`: Pydantic models for Ollama's native `/api/chat` wire format: request (`model`, `messages` with optional `images`/`tool_calls`/`tool_name`, `tools`, `format`, `options`, `stream`, `think`, `logprobs`, `top_logprobs`), non-stream response and stream chunk (`message`, `done`, `done_reason`, `total_duration`, `load_duration`, `prompt_eval_count`, `prompt_eval_duration`, `eval_count`, `eval_duration`, `logprobs`), and Ollama error body; durations are nanoseconds (research R6); `extra="ignore"`
- [X] T008 Implement `packages/llm/src/llm/client.py`: `OllamaClient(client: httpx.AsyncClient, settings)` with `async chat(request) -> OllamaChatResponse` and `async chat_stream(request) -> AsyncIterator[OllamaChatChunk]` (built with `httpx.Timeout(None, connect=5.0)`: no read timeout, since model loads and long generations take minutes; NDJSON lines parsed into typed chunks; closing the iterator closes the upstream httpx stream so Ollama stops generating, FR-011). Define typed exceptions `OllamaUnreachableError`, `OllamaModelNotFoundError` (HTTP 404), `OllamaServerError` (5xx / error body). Depends on T006, T007
- [X] T009 [P] (needs T008) Test `packages/llm/tests/test_ollama_client.py` with `httpx.MockTransport`: non-stream parse incl. timings, NDJSON stream parse, 404 → `OllamaModelNotFoundError`, connect error → `OllamaUnreachableError`, early iterator close closes the upstream response, no read timeout (a mock transport delaying longer than httpx's 5 s default still succeeds)
- [X] T010 Add `packages/llm/tests/test_ollama_live.py` marked `@pytest.mark.integration`: one real non-stream and one stream call against Ollama, also asserting the **verify** items from research.md (penalty options accepted, `done_reason: "length"` on tiny `num_predict`, context-overflow behavior R3, error body shape for an unknown model, and `prompt_eval_count` when the same long prompt is sent twice, since KV-cache reuse may lower it and defeat the R3 overflow rule). Run it against a live Ollama and record findings by updating the R3/R5/R7/R13 **verify** rows in `specs/002-chat-completions/research.md`. **GATE: must complete before T026**, because the context-overflow rule (R3/R13) and penalty-option policy depend on its outcome. Depends on T008

### `db` package

- [X] T011 [P] Create `packages/db/src/db/models/chat_completions.py` exactly per data-model.md: `ChatCompletionStatus(StrEnum)` (`succeeded`, `failed`, `cancelled`); `ChatCompletionRecord` → `chat_completion_records` (columns: `id` int PK, `external_id` str unique, `created_at` `UtcDateTime` (no single-column index; the composite below covers it), `model` str, `status`, `stream` bool, `n` int, `prompt_tokens` int null, `completion_tokens` int null, `duration_ms` int, `time_to_first_token_ms` int null, `generation_duration_ms` int null, `load_duration_ms` int null, `finish_reason` str null, `error_type` str null, `error_code` str null; composite index `(created_at DESC, id DESC)`; no stored `total_tokens`); `ChatCompletionContent` → `chat_completion_contents` (`id` int PK, `record_id` int FK → `chat_completion_records.id` unique with `ON DELETE CASCADE`, `request` JSON, `response` JSON null, `error_message` str null). Export both from `packages/db/src/db/models/__init__.py` (together with `Model` from T012)
- [X] T012 [P] Create `packages/db/src/db/models/models.py` per data-model.md: `Model` → `models` (`id` int PK, `external_id` str unique, `created_at` `UtcDateTime`, `owned_by` str); export from `models/__init__.py`
- [X] T013 Generate the migration with `uv run --project packages/db alembic revision --autogenerate -m "chat completions"` in `packages/db/alembic/versions/`, then review and correct it by hand (only the DESC composite index on `created_at`/`id`, no redundant single-column index, FK `ondelete="CASCADE"`, status stored as a plain string column, no CHECK constraint); add an `op.bulk_insert` seeding the `models` row (`qwen3.5:9b`, owner `qwen`, `created_at` = migration time); apply with `alembic upgrade head` and verify downgrade/upgrade round-trips. Depends on T011, T012
- [X] T014 Implement `create_chat_completion(session, ...)` in `packages/db/src/db/repositories/chat_completions.py` (create `repositories/__init__.py` if absent): typed keyword args for every record column plus `request: dict[str, Any]`, `response: dict[str, Any] | None`, `error_message: str | None`; inserts record + content in one transaction and returns the record. Depends on T011
- [X] T015 [P] Implement `list_models(session)` and `get_model(session, external_id) -> Model | None` in `packages/db/src/db/repositories/models.py`. Depends on T012
- [X] T016 [P] Test `packages/db/tests/test_chat_completions_repository.py` (create `packages/db/tests/conftest.py` if absent, fresh in-memory `sqlite+aiosqlite:///:memory:` per test): create persists both rows, content row cascades on record delete, naive datetimes rejected / UTC restored. Depends on T014
- [X] T017 [P] Test `packages/db/tests/test_models_repository.py`: list, get hit/miss; plus a migration test asserting the seeded `qwen3.5:9b` row exists after `upgrade head`. Depends on T015, T013

### API foundations

- [X] T018 Fix `apps/api/src/api/errors.py`: add `ApiError(status, type, code, param, message)` exception handled into the OpenAI envelope `{"error": {"message", "type", "param", "code"}}`; make `RequestValidationError` return **400** `invalid_request_error` on OpenAI paths (`/v1/chat/completions`) and **422** elsewhere; update `apps/api/tests/test_errors.py` accordingly
- [X] T019 Wire the app lifespan in `apps/api/src/api/app.py`: create one shared `httpx.AsyncClient` and `OllamaClient` at startup (stored on `app.state`), `aclose()` on shutdown; add FastAPI dependencies `get_ollama_client` and re-export `db.get_session` so tests can override both. Depends on T008
- [X] T020 Extend `apps/api/tests/conftest.py`: fixture overriding `get_ollama_client` with an `OllamaClient` over `httpx.MockTransport` (handler configurable per test), and the in-memory SQLite session override with tables created per test and a `Model` row (`qwen3.5:9b`) inserted directly through the ORM in the fixture (tables are created from metadata, so the migration seed is absent; no `create_model` function is added, YAGNI). Depends on T014, T015, T019

**Checkpoint**: `llm` client, DB create path, error handling, and test fixtures ready.

---

## Phase 3: User Story 1 - Chat completion through the OpenAI-compatible endpoint (Priority: P1) 🎯 MVP

**Goal**: A stock OpenAI SDK pointed at `/v1` gets a correct response (single or streamed) from local Qwen; every request that reaches endpoint logic is recorded.

**Independent Test**: `uv run pytest` (mocked) passes; with Ollama running, the OpenAI Python SDK completes a non-streaming and a streaming `chat.completions.create` and a record exists in `chat_completion_records` for each.

### Schemas

- [X] T021 [P] [US1] Create `apps/api/src/api/chat/schemas.py` with Pydantic models using OpenAI's names verbatim and field-for-field parity from `/openai-spec/openapi.yaml`, `extra="ignore"`, `StrEnum` for enums: `CreateChatCompletionRequest` (all ~35 options incl. messages of every role and content-part types, `tools`, `functions`, `function_call`, `tool_choice`, `response_format`, `stream_options`, `logit_bias`, `modalities`, `audio`, `web_search_options`, …), `CreateChatCompletionResponse`, `CreateChatCompletionStreamResponse` (the chunk), nested message/choice/usage/logprobs/tool-call models. Also define a typed `ChatCompletionStreamError` model for the mid-stream `{"error": …}` event (local, separate from the OpenAI-shaped models). Do not add local-only fields to the OpenAI models

### Tests (write first, expect failure)

- [X] T022 [P] [US1] `apps/api/tests/test_chat_completions.py`: `validate_contract` for (a) minimal success, (b) success with options (tools → tool_calls response, `response_format`, `n=2`, `logprobs`), (c) each R7 error row (unsupported option 400 `unsupported_parameter` with `param`, context overflow 400 `context_length_exceeded`, unknown model name such as `gpt-4o` → 404 `model_not_found` with OpenAI's exact message and `param: null`, model missing in Ollama (Ollama 404) → same error, Ollama unreachable 503 `server_error`, schema validation failure 400); behavior asserts: `id` is `chatcmpl-…` and equals the stored `external_id`, usage summed for `n=2`, the served model id is accepted, unknown extra body fields tolerated, a record exists afterwards for success and for post-validation failures (incl. option-policy rejections and unknown model, stored with the requested name) but **not** for schema-validation failures
- [X] T023 [P] [US1] `apps/api/tests/test_chat_completions_options.py`: table-driven test of the research.md R5 policy — every row: honored options appear correctly in the mocked Ollama request (`options`, `format`, `tools`, `num_predict` with `max_completion_tokens` winning, `developer`→`system`, `data:` image → `images`), ignored options accepted and not forwarded, rejected options (`logit_bias` non-empty, `audio`, `web_search_options`, `moderation`, http(s) image URL, `input_audio`/`file` parts, `modalities` containing `audio`) → 400 naming the option; `tool_choice` emulation (`none` drops tools; named function restricts tools); a test iterating every property of the vendored `CreateChatCompletionRequest` asserting each appears in the policy table (SC-002); empty and mixed-part message content passes through; non-conforming JSON output is returned as generated; legacy `functions`/`function_call` converted; `reasoning_effort` → `think` mapping (R4)
- [X] T024 [P] [US1] `apps/api/tests/test_chat_completions_stream.py`: SSE body is `data: {json}\n\n` lines ending `data: [DONE]\n\n`; every chunk passes `validate_schema(chunk, "CreateChatCompletionStreamResponse")`; final usage chunk only when `stream_options.include_usage`; `n=2` with stream yields choices sequentially; mid-stream Ollama error → `data: {"error": …}` then `[DONE]` and a `failed` record; client disconnect → upstream closed and `cancelled` record persisted with partial response; non-streaming disconnect (incl. `n=3`) cancels every upstream call within 1 s and records `cancelled` (FR-011); pre-stream failures (unsupported option, unknown model, Ollama unreachable, Ollama 404) return a real 4xx/5xx OpenAI envelope, not a 200 stream (R13)
- [X] T025 [P] [US1] `apps/api/tests/test_models.py`: `validate_contract` for `GET /v1/models` (shape, seeded `qwen3.5:9b` entry with `object: "model"`, integer `created`, `owned_by`)

### Implementation

- [X] T026 [US1] Implement `apps/api/src/api/chat/service.py` — option policy and translation: apply the R5 table first (reject early with `ApiError` 400 `invalid_request_error`/`unsupported_parameter` and `param`), then validate `model` via `db.get_model` (absent → `ApiError` 404 `invalid_request_error`/`model_not_found`, message ``The model `X` does not exist or you do not have access to it.``, `param` null; still recorded as `failed`), build the Ollama request (always `options.num_ctx` from settings, `think: false` unless `reasoning_effort`, R4), map OpenAI messages/content parts/tools/tool_choice/response_format/logprobs, ignore the R5 "ignore" fields. Depends on T021
- [X] T027 [US1] Extend `apps/api/src/api/chat/service.py` — non-streaming execution: call `OllamaClient.chat`, emulate `n` with `n` concurrent calls inside one `asyncio.TaskGroup` (usage summed, generation/load durations summed, wall-clock `duration_ms`), assemble `CreateChatCompletionResponse` (`chatcmpl-<short random>` id, `created`, served model, `finish_reason` incl. `length`/`tool_calls`, logprobs reshaped), detect context overflow per the rule fixed by T010 (R3; e.g. `prompt_eval_count >= num_ctx` → 400 `context_length_exceeded`), with a test that a prompt just below `num_ctx` succeeds; run the handler body raced against `request.is_disconnected()` so a client disconnect cancels the TaskGroup and closes every upstream request (FR-011), recording `cancelled`; map `OllamaModelNotFoundError`→404 `model_not_found`, `OllamaUnreachableError`→503 and `OllamaServerError`→500 `server_error` (code `null`). Depends on T026
- [X] T028 [US1] Extend `apps/api/src/api/chat/service.py` — recording: after every request that reaches endpoint logic (success, failure, cancel) call `db.repositories.chat_completions.create_chat_completion` with status, tokens, `duration_ms`, `generation_duration_ms`, `load_duration_ms`, `finish_reason`, `error_type`/`error_code`/`error_message`, and request/response JSON; schema-validation failures are not recorded, but every rejection raised after validation (option-policy 400s, unknown model, Ollama errors) is recorded as `failed` before the error is returned. Depends on T027
- [X] T029 [US1] Extend `apps/api/src/api/chat/service.py` — streaming: an `async def` generator yielding typed `CreateChatCompletionStreamResponse` chunks (role chunk, content/tool-call deltas, finish chunk, optional usage chunk when `include_usage`); `n>1` streamed choice-after-choice; measure `time_to_first_token_ms` at the first chunk; record in a `finally` deciding `succeeded`/`failed`/`cancelled` from how it exited, with the DB write shielded (`asyncio.shield`) so cancellation still persists; mid-stream errors yielded as a typed `ChatCompletionStreamError` event. Pre-stream failures must surface as real HTTP errors (R13): the policy checks, model validation, and the first Ollama chunk are obtained *before* the router returns `StreamingResponse`, so the generator is primed with that first chunk; context overflow is applied per T010's outcome (up-front 400 if detectable then, otherwise an SSE error event). Depends on T028
- [X] T030 [US1] Create `apps/api/src/api/chat/router.py`: `POST /chat/completions`, `async def`, return annotation `CreateChatCompletionResponse | StreamingResponse` (no `response_model=`), branch on `stream`; the first-chunk priming from T029 happens before the response is returned; a thin wrapper serializes chunk models to `data: {...}\n\n` and appends `data: [DONE]\n\n`, `media_type="text/event-stream"`; include the router under `/v1` in `apps/api/src/api/app.py`. Depends on T029
- [X] T031 [US1] Create `apps/api/src/api/models/schemas.py` (OpenAI names verbatim: `ListModelsResponse`, `Model`; `created` as unix int converted in the schema) and `apps/api/src/api/models/router.py`: `GET /models`, `async def`, calls `db.list_models` only; include under `/v1` in `apps/api/src/api/app.py`. Depends on T015
- [X] T032 [US1] (depends on T030) Add `apps/api/tests/test_ollama_integration.py` marked `@pytest.mark.integration`: real Ollama through the app only: tools, `n=2`, context overflow, plus one non-stream and one stream sanity call (the **verify** items and any R5/research.md adjustments belong to T010)
- [X] T033 [US1] Add `apps/api/tests/test_openai_sdk_integration.py` marked `@pytest.mark.integration`: the real `openai` SDK (`base_url` to the ASGI app or a running server) completes a non-streaming and a streaming `chat.completions.create`, `models.list()` returns the served model, and an unknown model raises the SDK's `NotFoundError` (SC-001). Depends on T003, T030, T031
- [X] T034 [US1] Run `uv run pytest`, `uv run pre-commit run --all-files`; fix failures. Then run the quickstart SDK drop-in step (quickstart.md step 2) against a live Ollama and the T033 test

**Checkpoint**: US1 fully functional and independently testable (the MVP).

---

## Phase 4: User Story 2 - Playground tab (Priority: P2)

**Goal**: A sidebar-navigable Playground to compose a conversation, set every option, send (streaming or not), cancel, and review session history.

**Independent Test**: `pnpm dev` + API: open `/playground`, send a streamed message, cancel one, send another non-streamed with changed temperature; history lists all exchanges and reopens full request + answer; errors show verbatim.

- [X] T035 [US2] Regenerate `apps/web/src/api/schema.d.ts` with `pnpm gen:api` (API running, `VITE_LOCAL_LLM_API_URL` from shell) so it contains `CreateChatCompletionRequest`/`Response`/stream chunk types and `ListModelsResponse`; commit the result
- [X] T036 [P] [US2] Add shadcn components into `apps/web/src/components/ui/` via the shadcn CLI: `textarea`, `select`, `switch`, `slider`, `label`, `badge`, `card` (excluded from Biome; do not hand-edit)
- [X] T037 [P] [US2] Implement `apps/web/src/lib/parse-sse.ts`: pure `parseSse(stream: ReadableStream<Uint8Array>)` async generator yielding parsed `data: {…}` JSON payloads (handling lines split across reads), stopping at `[DONE]`, throwing/yielding an error for a `data: {"error": …}` event; typed with schema types, no `any`
- [X] T038 [P] [US2] Test `apps/web/tests/parse-sse.test.ts` (explicit `vitest` imports): chunks split mid-line, multiple events per read, `[DONE]` termination, error event, abort via `AbortController` ends iteration
- [X] T039 [US2] Implement `apps/web/src/hooks/use-chat-stream.ts` exporting `useChatStream`: the one allowed raw `fetch` to relative `/v1/chat/completions` with `stream: true`, owns the `AbortController`, exposes `{ text, isStreaming, error, send, cancel }`; non-2xx responses surface the error envelope's `error.message` unchanged. Depends on T035, T037
- [X] T040 [US2] Add the non-streaming path in `apps/web/src/api/` (e.g. `chat.ts`): a TanStack `useMutation` hook posting through the typed `openapi-fetch` client in `apps/web/src/api/client.ts`; errors arrive as `ApiError`. Depends on T035
- [X] T041 [US2] Add `apps/web/src/api/models.ts` exporting `useModels`: `useQuery` over `GET /v1/models` through the typed client, no polling. Depends on T035
- [X] T042 [P] [US2] Build `apps/web/src/components/playground-messages.tsx`: multi-message editor (add/remove, role select system/user/assistant, textarea per message). Depends on T036
- [X] T043 [P] [US2] Build `apps/web/src/components/playground-options.tsx`: a model `Select` populated from `useModels` (T041; no free-text model name, FR-029) plus one control per other `CreateChatCompletionRequest` option, including the ones the server rejects (`audio`, `web_search_options`, `moderation`, so the user can see the error) and `functions`/`function_call`/`prediction` (sampling, penalties, stop, token limits, `n`, `response_format`, tools/tool_choice JSON, logprobs/top_logprobs, seed, `stream`, `stream_options`, `reasoning_effort`, `logit_bias`, `modalities`, and the accepted-and-ignored fields) where optional fields show the endpoint's own default as a placeholder (not a prefilled value) and `model` defaults to the first served model; tracks which fields the user touched so untouched options are **not** sent (FR-017); exports a pure helper that builds the request body from touched options. Depends on T036, T041
- [X] T044 [P] [US2] Build `apps/web/src/components/playground-history.tsx`: session-only list of `{request, answer | error}` entries (React state), selecting one shows the full request (messages + options) and its answer or error. Depends on T036
- [X] T045 [US2] Build `apps/web/src/pages/playground.tsx` composing messages, options, send/cancel buttons, live/streamed answer display, error display, and history via `useState`/`useReducer`; picks the streaming or mutation path from the `stream` option; failed attempts are added to history. Depends on T039–T044
- [X] T046 [US2] Update `apps/web/src/App.tsx` routes (`/` redirects to `/playground`, `/playground`) and `apps/web/src/components/app-sidebar.tsx` with a Playground nav link (`NavLink`, active state, accessible labels). Depends on T045
- [X] T047 [US2] Test `apps/web/tests/playground.test.tsx` using `renderWithProviders` and MSW (`server.use(...)`): sending a non-streamed message shows the answer and a history entry; a streamed response renders progressively and cancel stops it; the model selector lists the models returned by `/v1/models` and the chosen id is sent; an untouched option is absent from the request body while a changed temperature is present; a server error message is shown verbatim and logged in history
- [X] T048 [US2] Run `pnpm check`, `pnpm typecheck`, `pnpm test` in `apps/web`; fix failures

**Checkpoint**: US1 + US2 work independently.

---

## Phase 5: User Story 3 - Analytics tab (Priority: P3)

**Goal**: Content-free request metadata list (cursor-paginated) and summary figures over all recorded requests.

**Independent Test**: Make mixed requests (success, failure, streamed, cancelled), open `/analytics`: every request appears newest first with correct metadata and no message text anywhere; summary matches; empty state when none.

### Backend

- [X] T049 [P] [US3] Add `list_chat_completion_metadata(session, *, limit, after)` and `get_chat_completion_summary(session)` to `packages/db/src/db/repositories/chat_completions.py`: list selects only `chat_completion_records` columns (never joins content), orders `created_at DESC, id DESC`, cursor `after` = `external_id` of the last item (unknown id raises a typed db-package exception), returns items plus `has_more`; summary returns `request_count`, `error_count` (`failed` only), `prompt_tokens` and `completion_tokens` sums (0 when empty), and `avg_duration_ms`, `avg_time_to_first_token_ms`, `avg_generation_duration_ms` (`None` when nothing to average). Add a single-statement `SUM`/`AVG` implementation, no Python-side aggregation
- [X] T050 [P] [US3] Extend `packages/db/tests/test_chat_completions_repository.py`: ordering, cursor paging across pages with `has_more`, unknown cursor error, empty db, summary figures incl. null averages and failed-only error count; assert the list function returns no content fields; seed 10,000 rows and assert the page query completes in under 500 ms (SC-008). Depends on T049
- [X] T051 [P] [US3] Create `apps/api/src/api/analytics/schemas.py`: list-item model (`id`, `created` int unix, `model`, `status` `StrEnum`, `stream`, `n`, `prompt_tokens`, `completion_tokens`, `total_tokens` derived in the schema, `duration_ms`, `time_to_first_token_ms`, `generation_duration_ms`, `load_duration_ms`, `finish_reason`, `error_type`, `error_code`; nullable fields always present), list envelope (`object: "list"`, `data`, `first_id`, `last_id`, `has_more`), and summary model per contracts/analytics.md
- [X] T052 [US3] Create `apps/api/src/api/analytics/router.py`: `GET /analytics/chat-completions` (`limit` 1–100 default 20, optional `after`; unknown `after` → 404 `not_found` via `ApiError`; empty db → `data: []`, `first_id`/`last_id` null) and `GET /analytics/chat-completions/summary`; both `async def`, only calling db functions; include under `/v1` in `apps/api/src/api/app.py`. Depends on T049, T051
- [X] T053 [US3] Test `apps/api/tests/test_analytics.py` (ordinary behavior tests, not `validate_contract`; `validate_schema` for the error envelope): list shape matches contracts/analytics.md, pagination via `after`, `limit` bounds → 422 envelope, unknown `after` → 404, empty state, summary values, and that no response contains request/response text (create a record with a sentinel prompt and assert the sentinel is absent from both responses). Depends on T052

### Frontend

- [X] T054 [US3] Regenerate `apps/web/src/api/schema.d.ts` (`pnpm gen:api`) to include the analytics endpoints. Depends on T052
- [X] T055 [P] [US3] Add shadcn `table` to `apps/web/src/components/ui/` (CLI)
- [X] T056 [US3] Add analytics query hooks in `apps/web/src/api/analytics.ts`: `useInfiniteQuery` over `/v1/analytics/chat-completions` with cursor `after` = `last_id` (`getNextPageParam` from `has_more`), and `useQuery` for the summary; no polling. Depends on T054
- [X] T057 [P] [US3] Build `apps/web/src/components/analytics-summary.tsx` (cards: request count, error rate = `error_count`/`request_count` (failed only; cancelled is not an error), total input/output tokens, average durations; `null` averages shown as "—"; error rate shown as "—" when `request_count` is 0). Depends on T055
- [X] T058 [P] [US3] Build `apps/web/src/components/analytics-table.tsx`: columns timestamp, model, status badge, input/output/total tokens, total duration, time to first token (— when null), model load duration (— when null), generation duration; "Load more" button driven by `has_more`; empty state ("No requests recorded yet"). Renders no content fields. Depends on T055
- [X] T059 [US3] Build `apps/web/src/pages/analytics.tsx` composing summary and table with loading and error states (error message shown as-is); add the `/analytics` route in `apps/web/src/App.tsx` and an Analytics link in `apps/web/src/components/app-sidebar.tsx`. Depends on T056–T058
- [X] T060 [US3] Test `apps/web/tests/analytics.test.tsx` (MSW): rows render with correct figures, "Load more" fetches the next page with `after=<last_id>`, empty state, summary values, and no handler is hit other than the two analytics URLs; fixtures carry a sentinel prompt/response string and the test asserts it never appears in the rendered DOM (FR-024). Depends on T059
- [X] T061 [US3] Run `pnpm check`, `pnpm typecheck`, `pnpm test` in `apps/web`; fix failures

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T062 Run the full `specs/002-chat-completions/quickstart.md` manual flow end to end (SDK drop-in, Playground cancel, error cases, Analytics, restart persistence) and fix discrepancies; this also checks SC-007 (first Playground message answered in under 1 minute after setup)
- [X] T063 [P] Verify SC-005: for a mix of success/failure/cancelled requests, analytics token counts equal those returned to the client; verify SC-004 (first streamed content ≤ 2 s once loaded)
- [X] T064 [P] Reconcile `specs/002-chat-completions/research.md` **verify** items with the findings from T010/T032 (adjust R5 rows if a check failed)
- [X] T065 Final gate: `uv run pytest`, `uv run mypy`, `uv run pre-commit run --all-files`, and in `apps/web` `pnpm check && pnpm typecheck && pnpm test` all pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (1)** → **Foundational (2)** → user stories → **Polish (6)**
- **US1 (P1)**: needs Phase 2 only, with T010 (live Ollama verification) done before the service tasks T026–T029. MVP.
- **US2 (P2)**: needs Phase 2 and a running US1 endpoint (T035 regenerates types from the live API).
- **US3 (P3)**: backend (T049–T053) needs only Phase 2 and can run in parallel with US1/US2; its frontend needs T052 and the sidebar/routes from US2 (T046).

### Within Foundational

T006, T007 → T008 → T019; T011 + T012 → T013; T011 → T014 → T016; T012 → T015 → T017; T014 + T019 → T020; T018 independent.

### Within Each Story

Tests written first (expected to fail), then schemas → service → router; shared `service.py` tasks (T026–T029) are sequential because they edit the same file.

### Parallel Opportunities

- Setup: T004, T005
- Foundational: T006 ‖ T007; T009 ‖ T010; T011 ‖ T018 (different packages); T016 after T014
- US1: T021–T024 in parallel (different files)
- US2: T036–T038 together; T042–T044 together
- US3: T049, T051, T055 together; T057 ‖ T058; backend US3 ‖ US1/US2 work

### Parallel Example: User Story 1

```bash
Task: "Create schemas in apps/api/src/api/chat/schemas.py"            # T021
Task: "Contract tests in apps/api/tests/test_chat_completions.py"     # T022
Task: "Option policy tests in apps/api/tests/test_chat_completions_options.py"  # T023
Task: "Stream tests in apps/api/tests/test_chat_completions_stream.py"          # T024
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → Phase 2 Foundational
2. Phase 3 US1 → **stop and validate** with the OpenAI SDK against live Ollama (SC-001, SC-003)

### Incremental Delivery

1. Setup + Foundational
2. US1 → validate (MVP)
3. US2 → Playground validated manually and with Vitest
4. US3 → Analytics validated; Polish and final gate

### Notes

- Commit only when asked; one atomic Conventional Commit per logical change; feature branch `002-chat-completions`, squash-merged by PR.
- Do not add `service.py`-style layers beyond those listed, no speculative repository functions, no global store on the frontend (YAGNI).
- Never hand-write API types on the frontend; they come from `pnpm gen:api`.

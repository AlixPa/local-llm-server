---

description: "Task list for Responses Endpoint End to End"
---

# Tasks: Responses Endpoint End to End

**Input**: Design documents from `/specs/004-responses-endpoint/`

**Prerequisites**: plan.md, spec.md, research.md (R1–R12), data-model.md, contracts/responses.md, contracts/analytics.md, quickstart.md

**Tests**: Included. CLAUDE.md requires contract tests for every new/changed OpenAI endpoint and the spec mandates a policy-coverage test (FR-002/SC-002), repository tests, and frontend tests for logic/risk.

**Organization**: Grouped by user story. US1 = endpoint (P1), US2 = Responses playground (P2), US3 = combined Analytics (P2), US4 = Observability support (P2).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on incomplete tasks)
- **[Story]**: US1–US4; Setup/Foundational/Polish have none
- Paths are relative to the repo root. Python deps: none new. Never hand-edit `pyproject.toml`/`package.json` dependencies.

## Conventions every task inherits (CLAUDE.md)

Python: `mypy --strict`, Ruff, 88 cols, `X | None`, builtin generics, minimal comments, handlers `async def`, **no SQLAlchemy statements outside `packages/db`**. Pydantic classes use OpenAI schema names verbatim, `extra="ignore"`. TS: strict, no `any`/`as`, named exports, kebab-case files, `@/` imports, Biome; API types only from generated `schema.d.ts`. Do not commit unless asked.

---

## Phase 1: Setup

**Purpose**: Confirm the baseline is green before refactoring.

- [X] T001 Run `uv run pytest` and `pnpm --dir apps/web check && pnpm --dir apps/web typecheck && pnpm --dir apps/web test` and record that the baseline passes (SC-009 reference point). No file changes.

---

## Phase 2: Foundational (blocking prerequisites)

**Purpose**: Shared status enum, shared inference helpers, and the new tables. MUST finish before any story.

**⚠️ CRITICAL**: Chat behavior must stay identical: existing chat tests pass unmodified (SC-009).

- [X] T002 Create `packages/db/src/db/models/status.py` with `class RequestStatus(StrEnum)` members `succeeded`, `failed`, `cancelled` (values identical strings). Replace `ChatCompletionStatus` with `RequestStatus` in `packages/db/src/db/models/chat_completions.py`, `packages/db/src/db/models/__init__.py`, `packages/db/src/db/repositories/chat_completions.py`, `apps/api/src/api/chat/service.py`, `apps/api/src/api/analytics/schemas.py`, and every test/import that references it (grep `ChatCompletionStatus`). Keep the column a non-native, constraint-free enum of length 16 so no chat-table schema change results (research R9).
- [X] T003 Create `packages/db/src/db/models/responses.py` with `ResponseRecord` (`response_records`) and `ResponseContent` (`response_contents`) exactly per data-model.md: `ResponseRecord` columns `id` int PK, `external_id` str unique, `created_at` `UtcDateTime`, `model` str, `status` `RequestStatus`, `stream` bool, `prompt_tokens` int | None, `completion_tokens` int | None, `duration_ms` int, `time_to_first_token_ms` int | None, `generation_duration_ms` int | None, `load_duration_ms` int | None, `finish_reason` str | None, `error_type` str | None, `error_code` str | None; index `ix_response_records_created_at_external_id` on `(created_at DESC, external_id DESC)`; no `n` column. `ResponseContent` columns `id` int PK, `record_id` int FK → `response_records.id` unique with `ON DELETE CASCADE` (1:1), `request` JSON, `response` JSON | None, `error_message` str | None. Mirror `chat_completions.py` style. Export from `packages/db/src/db/models/__init__.py`. Update the `TracedRequest.response_id` comment in `packages/db/src/db/models/tracing.py` to say it links by value to either record table's `external_id` (no schema change).
- [X] T004 Generate the migration with `uv run alembic -c packages/db/alembic.ini revision --autogenerate -m responses` (file lands in `packages/db/alembic/versions/`). Review and correct it: it must create `response_records` + `response_contents` (with the index and cascade FK) and swap the chat index `ix_chat_completion_records_created_at_id` for `ix_chat_completion_records_created_at_external_id` (update the index in `packages/db/src/db/models/chat_completions.py` in this task), and emit nothing else for chat tables or the status rename; fix server defaults/enum details by hand; verify `downgrade` drops both tables and restores the old chat index. Apply with `upgrade head`.
- [X] T005 [P] Create `packages/db/src/db/repositories/responses.py` with `async def create_response(session, ...)` inserting one `ResponseRecord` plus its `ResponseContent` in one call, typed arguments mirroring the signature style of `create_chat_completion` in `packages/db/src/db/repositories/chat_completions.py`.
- [X] T006 [P] Add `packages/db/tests/test_responses_repository.py` (in-memory SQLite): insert succeeded/failed/cancelled records, content 1:1 and cascade delete, nullable fields stay null, unique `external_id`. Extend `packages/db/tests/test_migrations.py` if it asserts the table set.
- [X] T007 Extract the endpoint-agnostic code from `apps/api/src/api/chat/service.py` into new `apps/api/src/api/inference.py` per research R2: field-policy enum (`Policy`), `THINK_LEVELS`, reasoning-effort mapping input, `ClientDisconnectedError`, error builders (`unsupported`, `model_not_found`, `context_exceeded`, `to_api_error`, `internal_error`, `OLLAMA_ERRORS`), `overflowed`, `ms`, `Totals` (without the chat-shaped `usage()`; keep that in chat), `race` (race against client disconnect), `close_open_steps`, the tool-choice emulation core (normalized to a mode + optional function name), and the shielded-record wrapper. `chat/service.py` imports them and keeps its schema-specific code. No base class or generic runner. Behavior must not change.
- [X] T008 Run the existing chat suites (`apps/api/tests/test_chat_completions*.py`, `test_observability_tracing.py`) **unmodified** plus `mypy --strict`; fix the extraction until green. (Checkpoint for Phase 2.)

**Checkpoint**: foundation ready; stories can start.

---

## Phase 3: User Story 1 - Create a response through the OpenAI-compatible endpoint (Priority: P1) 🎯 MVP

**Goal**: `POST /v1/responses` (create only, stream and non-stream) end to end on Ollama `/api/chat`, recorded in `response_records`/`response_contents`.

**Independent Test**: With the OpenAI SDK pointed at `http://localhost:8000/v1`, `client.responses.create(...)` (non-stream, then `stream=True`) succeeds and a `response_records` row exists afterwards.

### Tests for User Story 1

- [X] T009 [P] [US1] `apps/api/tests/test_responses.py`: non-stream behavior + contract. Use `validate_contract` for success (string input; message list with `developer`/`user` roles, inline `data:` image, `instructions` as leading `system` message), and for each error class in contracts/responses.md (schema validation 400, `unsupported_parameter` 400 incl. `previous_response_id`, unknown model 404 `model_not_found`, Ollama unreachable 503 `server_error`, Ollama error 500, context overflow 400 `context_length_exceeded` with `truncation: disabled`). Also: function-call round trip (`FunctionToolCall` + `FunctionCallOutputItemParam` input → tool message with `tool_name` resolved by `call_id`; output has message item then `function_call` items with `fc_`/`call_` ids and string `arguments`), `max_output_tokens` → `status: incomplete` + `incomplete_details.reason: max_output_tokens`, `usage` fields, `id` matches `resp_<24 hex>`. Non-stream client disconnect → row with status `cancelled` (usage only where known). Recording assertions: succeeded/failed rows exist; validation failure writes no row (FR-008); unknown route `GET /v1/responses/resp_x` returns the standard error envelope.
- [X] T010 [P] [US1] `apps/api/tests/test_responses_stream.py`: streaming. Every event passes `validate_schema(event, "ResponseStreamEvent")` (fall back to the concrete event schema by `type` if the normalized union is ambiguous; extend `conftest.py` normalization rather than working around it). Assert frame shape `event: <type>\ndata: <json>\n\n` with `event` == payload `type`, **no `[DONE]`**, monotonically increasing 0-based `sequence_number`, event order from contracts/responses.md, function-call events (single `delta` with full JSON then `done`), terminal `response.completed`/`response.incomplete` carries `usage`, mid-stream upstream failure → final `response.failed` with `error {code, message}` then end, client disconnect → row with status `cancelled` and no `response_returned` step is recorded (Streaming convention in CLAUDE.md), disconnect before first event → cancelled with null token counts.
- [X] T011 [P] [US1] `apps/api/tests/test_responses_options.py`: (a) policy-coverage test asserting `FIELD_POLICY` keys equal the vendored `CreateResponse` property set (32 properties, SC-002); (b) per-option behavior: `temperature`/`top_p`/`max_output_tokens` → Ollama options; `text.format` `json_object`/`json_schema` → `format`; `tools` function honored, hosted tool type → 400 `unsupported_parameter` with `param: "tools"`; `tool_choice` `none`/`auto`/`required`/`{type: function, name}` emulation and `allowed_tools` → 400; `reasoning.effort` → `think` level (default `think: false`); `include` with `message.output_text.logprobs` + `top_logprobs` → logprobs; `truncation: auto` suppresses overflow error; ignored options accepted (`store`, `metadata` echoed, `parallel_tool_calls`, `user`, …); rejected options 400 (`previous_response_id`, `conversation`, `background: true`, `prompt`, `context_management`, `moderation`) while their empty values (`null`, `false`, `[]`, `{}`) are accepted.
- [X] T012 [P] [US1] Extend `apps/api/tests/test_openai_sdk_integration.py` with `@pytest.mark.integration` tests using the real OpenAI SDK against real Ollama: non-streaming, streaming (iterate to completion), and a function-call loop.

### Implementation for User Story 1

- [X] T013 [P] [US1] `apps/api/src/api/responses/__init__.py` (match other packages) and `apps/api/src/api/responses/schemas.py`: hand-written models with OpenAI names verbatim, `extra="ignore"`, per research R4. Request: `CreateResponse` (all 32 properties typed, optionality as in the vendored spec), `InputParam` (string | list of `InputItem`), `EasyInputMessage`, `InputMessage`, `OutputMessage` (as input), `FunctionToolCall`, `FunctionCallOutputItemParam`, `ReasoningItem`, `InputTextContent`, `InputImageContent`, `OutputTextContent`, `FunctionTool` (flat, `name` top-level), tool-choice variants, `TextResponseFormatConfiguration` variants, `Reasoning`, plus a loose catch-all model (type string + extras) for any other input item/tool type. Response: `Response`, `OutputMessage`, `FunctionToolCall`, `ResponseUsage` (`input_tokens`, `output_tokens`, `total_tokens`, `cached_tokens: 0`, `reasoning_tokens: 0`), `ResponseOutputText`, `ResponseLogProb`, `IncompleteDetails`, `ResponseError`, and the stream events `ResponseCreatedEvent`, `ResponseInProgressEvent`, `ResponseOutputItemAddedEvent`, `ResponseContentPartAddedEvent`, `ResponseTextDeltaEvent`, `ResponseTextDoneEvent`, `ResponseContentPartDoneEvent`, `ResponseFunctionCallArgumentsDeltaEvent`, `ResponseFunctionCallArgumentsDoneEvent`, `ResponseOutputItemDoneEvent`, `ResponseCompletedEvent`, `ResponseIncompleteEvent`, `ResponseFailedEvent` (each with `type` and `sequence_number`). Use `StrEnum` for status values (`completed`, `incomplete`, `in_progress`, `failed`).
- [X] T014 [US1] `apps/api/src/api/responses/service.py` (depends on T007, T013): `FIELD_POLICY` covering all 32 `CreateResponse` properties with the exact policies in research R3 (honor/emulate/ignore/reject; rejected options' empty values accepted); `_prepare` translating input per research R5 (`developer` → `system`; text parts joined; `input_image` `data:` URL → `images`; http(s) `image_url`, `file_id`, `input_file`, `input_audio`, `item_reference`, catch-all types → 400 `unsupported_parameter`; `ReasoningItem` dropped; `FunctionToolCall` → assistant message with `tool_calls`; `FunctionCallOutputItemParam` → `tool` message with `tool_name` from the earlier call by `call_id`); `instructions` as leading system message merged with the tool-choice instruction; model lookup via the existing models repository → 404 `model_not_found`; non-stream run building `Response` (message item `msg_<hex>` with one `output_text` part, `annotations: []`, `logprobs` only when requested, then one `function_call` per tool call; echo request settings per R5; `id: resp_<24 hex>`; `completed_at`; `done_reason == "length"` → `incomplete`); stream generator yielding typed event models in the R6 order with `sequence_number`, `response.failed` on mid-stream failure; record via `db.repositories.responses.create_response` through the shared shielded-record wrapper (status/finish_reason/tokens/timings per data-model.md state transitions; stream recorded once with assembled content; failed/cancelled streams never produce a returned-response step); `Trace` calls identical to chat (summary `"<model> · stream|non-stream"`, `set_response_id`, `step_sent`, `step_received`, `close_open_steps`). Tracking never fails the request.
- [X] T015 [US1] `apps/api/src/api/responses/router.py`: `POST /responses` as `async def`, return annotation `Response | StreamingResponse` (no `response_model=`), branch on `stream`; a thin `StreamingResponse` wrapper serializes each typed event as `event: <type>\ndata: <json>\n\n` with **no `[DONE]`**; media type `text/event-stream`. Register in `apps/api/src/api/app.py` (`include_router`, mounted under `/v1`). Add `/v1/responses` to `OPENAI_PATHS` in `apps/api/src/api/errors.py` so request-validation failures on this path return 400 `invalid_request_error` (422 stays for non-OpenAI paths); T009 asserts the 400.
- [X] T016 [US1] Make T009–T011 pass; run `uv run pytest`, `uv run mypy` on touched modules, `uv run ruff check` / `ruff format`. Then, with Ollama running, run `uv run pytest -m integration -k responses`.

**Checkpoint**: US1 independently functional and testable (MVP).

---

## Phase 4: User Story 3 - Responses in the combined Analytics tab (Priority: P2)

**Goal**: One filterable table over both endpoints and a matching summary, via `/v1/analytics/requests[/summary]`, replacing the chat-only analytics endpoints. (Placed before US2 because the analytics frontend and playground are independent and this unlocks SC-005/006; US2 can run in parallel with it.)

**Independent Test**: Send successful/failed/streamed requests to both endpoints; the Analytics tab shows them in one table (no content) and endpoint/status/date filters narrow table and summary identically.

### Tests for User Story 3

- [X] T017 [P] [US3] `packages/db/tests/test_analytics_repository.py`: seed both tables; assert ordering `(created_at DESC, external_id DESC)` across both, cursor pagination across the union (`UnknownCursorError` for an unknown id), each filter (`endpoint`, `status`, `since` inclusive, `until` inclusive) and combinations, summary computed over the identical filtered set (`error_count` = `failed` rows, averages `None` when empty), and that no content column is ever selected.
- [X] T018 [P] [US3] Rewrite `apps/api/tests/test_analytics.py` for `/v1/analytics/requests` and `/summary`: combined list with `endpoint` field, `object: "list"` envelope (`first_id`, `last_id`, `has_more`), `limit` 1–100 default 20, `after` unknown id → 404 `not_found`, filter params, `total_tokens` derived, `n` absent, no request/response text anywhere in payloads (FR-009/SC-006), old `/v1/analytics/chat-completions*` return the standard not-found error. Add a performance sanity check at ≥10,000 seeded rows across both tables staying well under 2 s (SC-010).

### Implementation for User Story 3

- [X] T019 [US3] `packages/db/src/db/repositories/analytics.py`: frozen dataclasses `RequestMetadata`, `RequestFilters(endpoint, status, since, until)`, `RequestSummary`, `UnknownCursorError`; `list_request_metadata` and `get_request_summary` over a `UNION ALL` of `chat_completion_records` and `response_records` with a literal `endpoint` column (`/v1/chat/completions` | `/v1/responses`), ordering `(created_at DESC, external_id DESC)`, cursor = `external_id`, read-only, content tables never touched. Fields exactly per data-model.md. Remove the list/summary functions (and their tests) from `packages/db/src/db/repositories/chat_completions.py`, leaving create only; move/adjust `packages/db/tests/test_chat_completions_repository.py` accordingly.
- [X] T020 [US3] Rewrite `apps/api/src/api/analytics/schemas.py` (non-OpenAI, so names are local: `AnalyticsRequestItem` with `id`, `endpoint`, `created` as int unix seconds, `model`, `status`, `stream`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `duration_ms`, `time_to_first_token_ms`, `generation_duration_ms`, `load_duration_ms`, `finish_reason`, `error_type`, `error_code`; `AnalyticsRequestList`; `AnalyticsRequestSummary`) and `apps/api/src/api/analytics/router.py` (`GET /analytics/requests` with `limit` 1–100 default 20, `after`, and `GET /analytics/requests/summary`; shared filter query params `endpoint`, `status`, `since`, `until` per contracts/analytics.md; unknown `after` → 404 `not_found`). Remove the chat-only routes. Unix-int conversion happens in the schema, not the model.
- [X] T021 [US3] (depends on T015 so the `/v1/responses` types are included) Run `pnpm --dir apps/web gen:api` (API running, `VITE_LOCAL_LLM_API_URL` in the shell) to regenerate `apps/web/src/api/schema.d.ts`; commit-ready. (Also picks up `/v1/responses` types for US2.)
- [X] T022 [P] [US3] Frontend shared filters: `git mv apps/web/src/components/observability-filters.tsx apps/web/src/components/request-filters.tsx` and `apps/web/tests/observability-filters.test.tsx` → `apps/web/tests/request-filters.test.tsx`. Make it a controlled component with endpoint select (`/v1/chat/completions`, `/v1/responses`, all), status select taking its options as a prop (Observability supplies the five trace outcomes, Analytics supplies `succeeded`/`failed`/`cancelled`), `since`, `until`, and a clear action. Observability's "Errors only" checkbox is replaced by the status select (research R11). The shared filter exposes one `status` value; Observability sends it as the existing `outcome` query parameter and Analytics sends it as `status`. Each page's API module owns that mapping. Update `apps/web/src/pages/observability.tsx`, `apps/web/src/api/observability.ts` (query params) and affected tests accordingly; keep filter state in `useState` and in TanStack Query keys.
- [X] T023 [US3] Rework `apps/web/src/api/analytics.ts` (hooks on the new `/v1/analytics/requests` and `/summary` with filter params; list via `useInfiniteQuery` using `after`/`last_id`/`has_more`; summary via `useQuery` on the same filters), `apps/web/src/components/analytics-table.tsx` (Endpoint column, combined rows, no content, token/timing columns, error type, empty state with "clear filters"), `apps/web/src/components/analytics-summary.tsx`, and `apps/web/src/pages/analytics.tsx` (renders `request-filters` above table and summary).
- [X] T024 [US3] Rewrite `apps/web/tests/analytics.test.tsx` (MSW): combined rows from both endpoints, endpoint/status/date filters change the requests sent and both table and summary follow, load-more via cursor, empty state with clear-filters, error shown as-is.

**Checkpoint**: the US3 backend (T017–T020) works independently of US1 (needs only Phase 2, or a seeded DB); the US3 frontend (T021 onward) also needs the US1 router (T015) for the regenerated types.

---

## Phase 5: User Story 2 - Responses playground in the web app (Priority: P2)

**Goal**: Sidebar "Playground" group with Chat and Responses; dedicated Responses playground page with all option controls, streaming/cancel, and session history.

**Independent Test**: Open `/playground/responses`, send with streaming on and off, see both answers in the history; trigger a bad model and see the server error as-is.

### Tests for User Story 2

- [X] T025 [P] [US2] Extend `apps/web/tests/parse-sse.test.ts` for `event:`-framed streams without `[DONE]` (ends cleanly at stream close), and `response.failed` / `type: "error"` payloads throwing with the server message.
- [X] T026 [P] [US2] `apps/web/tests/playground-responses.test.tsx` (MSW, `renderWithProviders`): stream on shows text progressively and Cancel aborts; stream off shows full answer; error response shown as-is in that history entry; history only contains Responses entries (not chat); request body built from input + instructions + options. Update `apps/web/tests/app.test.tsx` for the sidebar group (Playground → Chat, Responses; active entry highlighted), `/` → `/playground/chat`, and `/playground` alone not matching. Rename/adjust `apps/web/tests/playground.test.tsx` (chat) only for the new address.

### Implementation for User Story 2

- [X] T027 [US2] Routing and sidebar: in `apps/web/src/App.tsx` declare `/playground/chat` and `/playground/responses` (nested), `/` navigates to `/playground/chat`, delete the flat `/playground` route (no redirect). `git mv apps/web/src/pages/playground.tsx apps/web/src/pages/playground-chat.tsx` (rename the exported component, behavior unchanged). In `apps/web/src/components/app-sidebar.tsx` render "Playground" as a group header with `SidebarMenuSub` entries Chat and Responses (always expanded, no collapsible; highlight the active one; usable when the sidebar is collapsed/narrow), Analytics and Observability stay top-level.
- [X] T028 [P] [US2] Extract the shared stream core: refactor `apps/web/src/hooks/use-chat-stream.ts` so one generic fetch + `AbortController` + `parseSse` core (the only allowed raw `fetch`) is parametrized by URL and a text-delta extractor; chat keeps `choices[].delta.content`. Add `apps/web/src/hooks/use-response-stream.ts` exporting `useResponseStream` using the extractor for `response.output_text.delta`. Update `apps/web/src/lib/parse-sse.ts` to tolerate missing `[DONE]` and to throw on `response.failed`/`error` payloads carrying the server message. Chat tests must still pass unchanged.
- [X] T029 [P] [US2] `apps/web/src/api/responses.ts`: non-streaming call through the typed `openapi-fetch` client for `POST /v1/responses`; request type is the generated `CreateResponse` from `schema.d.ts` (no hand-written API types).
- [X] T030 [P] [US2] `apps/web/src/components/responses-playground-input.tsx` (input text + instructions fields, labeled) and `apps/web/src/components/responses-playground-options.tsx` (controls for honored/accepted `CreateResponse` options: `temperature`, `top_p`, `max_output_tokens`, `text` format, `tools`/`tool_choice`, `reasoning.effort`, `top_logprobs`/`include`, `truncation`, `parallel_tool_calls`, `metadata`, `store`, etc.; options the server rejects remain enterable via a raw JSON field so the server error displays as-is, as in the chat playground). Follow `playground-options.tsx` patterns.
- [X] T031 [US2] `apps/web/src/pages/playground-responses.tsx`: model selector (existing `api/models.ts`), input + instructions + options components, stream on/off switch with cancel, session history of request/answer pairs (reuse `playground-history.tsx` if it fits without Chat-specific coupling; otherwise a small Responses-specific rendering), server errors shown as-is. History is Responses-only and in-browser for the session.
- [X] T032 [US2] Make T025–T026 pass; run `pnpm --dir apps/web check`, `typecheck`, `test`.

**Checkpoint**: US2 independently demonstrable against US1.

---

## Phase 6: User Story 4 - Responses in the Observability tab (Priority: P2)

**Goal**: Responses requests appear live in the feed, are filterable by endpoint, and expose their workflow detail linked to the metadata record.

**Independent Test**: Send a streaming Responses request; it appears in-progress, then final, and its detail shows request received → sent to Ollama → received from Ollama (assembled) → response returned.

### Tests for User Story 4

- [X] T033 [P] [US4] Extend `apps/api/tests/test_observability_tracing.py`: `/v1/responses` traced (summary `"<model> · stream|non-stream"`), `traced_requests.response_id` equals the record's `external_id` (`resp_…`), step sequence for non-stream and stream (one assembled `received_from_ollama` step, never per-chunk events), failed stream → `error` step with no `response_returned`, cancelled stream → outcome cancelled with partial content kept, validation failure still appears in the feed, endpoint filter returns only Responses entries, interrupted-on-restart semantics unchanged (`test_observability_restart.py` still green). Extend `apps/api/tests/test_observability_endpoints.py` if it lists endpoint values.
- [X] T034 [P] [US4] Frontend: extend `apps/web/tests/observability-feed.test.tsx` / `observability-detail.test.tsx` / `observability-events.test.tsx` so a `/v1/responses` entry renders in the feed (endpoint shown), the endpoint filter lists Responses, the status select sends `outcome=` on the observability request (and `status=` on analytics), live updates arrive, and detail renders the same sequence view; update the empty-state text expectation.

### Implementation for User Story 4

- [X] T035 [US4] Add `("POST", "/v1/responses")` to the tracked set in `apps/api/src/api/observability/tracing.py` (`TRACKED`); if `apps/api/src/api/observability/router.py` / `schemas.py` enumerate endpoint values anywhere, add `/v1/responses` (the `endpoint` filter is currently a free string, so likely nothing else changes).
- [X] T036 [US4] Frontend: update `apps/web/src/components/observability-feed.tsx` if it enumerates endpoints (the shared `request-filters` already lists `/v1/responses` from T022), and the empty-state text in `apps/web/src/pages/observability.tsx` to mention both endpoints; confirm `apps/web/src/components/observability-sequence.tsx` needs no change (endpoint-agnostic). Regenerate `schema.d.ts` if the API schema for filters changed (`pnpm gen:api`).
- [X] T037 [US4] Make T033–T034 pass.

**Checkpoint**: all four stories functional.

---

## Phase 7: Polish & Cross-Cutting

- [ ] T038 Run the quickstart (`specs/004-responses-endpoint/quickstart.md`) sections 1–3 by hand against a real Ollama: curl non-stream/stream, OpenAI SDK, failure checks, sidebar/playground/Analytics/Observability flows; verify SC-004 (first stream content ≤ 2 s in the playground) and SC-007 (new request visible ≤ 1 s); both are manual-only checks, pass = measured value within the limit on the target machine, repeated 3 times. Also check the Playground sub-navigation is usable with the sidebar collapsed and at a narrow window width.
- [X] T039 Update `apps/api/README.md` / root `README.md` **only if** setup/run steps changed (none expected; skip otherwise). Confirm `CLAUDE.md` "Streaming" convention text already matches the per-endpoint stream formats (it was amended during planning).
- [X] T040 Final gates ("done means"): `uv run pytest`, `uv run pre-commit run --all-files`, `pnpm --dir apps/web check && pnpm --dir apps/web typecheck && pnpm --dir apps/web test`; confirm chat suites passed with unchanged expectations (SC-009, apart from analytics/filter tests). Do not commit unless asked.

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2** (T002 → T003 → T004; T005/T006 after T003–T004; T007 → T008 independent of the DB work and can run in parallel with T003–T006 by a different worker).
- **US1 (Phase 3)** needs all of Phase 2. Tests T009–T012 and schemas T013 are parallel; T014 needs T007 + T013 + T005; T015 needs T014; T016 last.
- **US3 (Phase 4)** needs Phase 2 only for the backend (T017–T020); T021 needs T020 and T015 (the generated schema must include `/v1/responses`; T029 and T031 rely on it); T022 can start immediately after Phase 2; T023–T024 need T021 + T022.
- **US2 (Phase 5)** needs US1 for end-to-end use and T021 for generated types; T027/T028/T029/T030 are mostly parallel; T031 needs T027–T030.
- **US4 (Phase 6)** needs US1 (T014 trace calls) and T022 (shared filters); T035 is a one-line change that unlocks T033.
- **Polish** after all desired stories.

User stories after Phase 2 are independent of each other except where noted above (frontend stories share the regenerated `schema.d.ts` from T021 and the `request-filters` component from T022).

## Parallel Examples

- **Phase 2**: T005 + T006 (db repo + tests) in parallel with T007 (inference extraction).
- **US1**: T009, T010, T011, T012, T013 together (all different files).
- **US3**: T017 + T018 together; T022 can run alongside T019–T020.
- **US2**: T025, T026, T028, T029, T030 together.
- **US4**: T033 + T034 together.

## Implementation Strategy

1. **MVP**: Phase 1 → Phase 2 → US1 (Phase 3). Stop and validate with the OpenAI SDK; the endpoint, recording and policy table are complete.
2. Add US3 (combined Analytics) and US4 (observability) for the data-facing features, then US2 (playground) for the UI; US2/US3/US4 can proceed in parallel after US1 and T021/T022.
3. Polish and run the full gates before any commit; per CLAUDE.md, commit only when asked, on branch `004-responses-endpoint`.

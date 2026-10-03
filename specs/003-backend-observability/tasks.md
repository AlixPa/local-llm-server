---

description: "Task list for Backend Observability Tab"
---

# Tasks: Backend Observability Tab

**Input**: Design documents from `/specs/003-backend-observability/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/observability.md, quickstart.md

**Tests**: Included. CLAUDE.md requires tests for logic/risk; the plan lists backend and frontend test files. Non-OpenAI endpoints get ordinary behavior tests (no `validate_contract`); use `validate_schema(body, "Error")`-style checks only for the error envelope.

**Organization**: Grouped by user story. Conventions that apply to every task: Python `mypy --strict`, Ruff, 88 cols, minimal comments, `X | None`, `StrEnum`; no DB statements outside `packages/db`; all handlers `async def`; frontend Biome + `tsc -b`, named exports, kebab-case files, `@/` imports, no `any`. No new dependencies.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1–US4

## Path Conventions

- DB: `packages/db/src/db/`, `packages/db/alembic/versions/`, `packages/db/tests/`
- API: `apps/api/src/api/observability/`, `apps/api/tests/`
- Web: `apps/web/src/`, `apps/web/tests/`

---

## Phase 1: Setup

**Purpose**: Scaffolding that has no behavior of its own

- [X] T001 [P] Create empty package `apps/api/src/api/observability/__init__.py` (match the style of `apps/api/src/api/analytics/__init__.py`)
- [X] T002 [P] Check whether shadcn components needed by the UI (tabs/collapsible/badge/select/switch) already exist in `apps/web/src/components/ui/`; add only missing ones via the shadcn CLI (`pnpm dlx shadcn@latest add <name>` in `apps/web`). Skip if none are needed (YAGNI).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: DB schema, repository, and the tracing core (Trace handle, writer, hub, middleware) that every story depends on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Create `packages/db/src/db/models/tracing.py` with `StrEnum`s `TraceOutcome` (`in_progress`, `success`, `error`, `canceled`, `interrupted`), `StepKind` (`request_received`, `sent_to_ollama`, `received_from_ollama`, `response_returned`, `error`), `StepStatus` (`in_progress`, `completed`, `failed`, `canceled`, `interrupted`), `Participant` (`client`, `api`, `ollama`), and models `TracedRequest` (`traced_requests`: `id` int PK, `endpoint` str, `method` str, `started_at` `UtcDateTime`, `duration_ms` int | None, `http_status` int | None, `outcome` `TraceOutcome`, `summary` str | None, `response_id` str | None (value link to `chat_completion_records.external_id`, no FK), `error_message` str | None; no extra index (feed order/cursor = `id DESC`)) and `WorkflowStep` (`workflow_steps`: `id` int PK, `request_id` int FK → `traced_requests.id` ON DELETE CASCADE indexed, `position` int 0-based, `kind` `StepKind`, `source`/`destination` `Participant`, `status` `StepStatus`, `started_at` `UtcDateTime`, `duration_ms` int | None, `content` JSON | None with `none_as_null=True`, `error_message` str | None; `UniqueConstraint(request_id, position)`). Enums stored as non-native strings with no check constraint, same pattern as `ChatCompletionStatus` in `packages/db/src/db/models/chat_completions.py`.
- [X] T004 Export the new models/enums in `packages/db/src/db/models/__init__.py` (depends on T003)
- [X] T005 Generate the migration with `alembic revision --autogenerate -m observability` from `packages/db`, then review and fix by hand (FK cascade, unique constraints, JSON column, no server-default misses); confirm `alembic upgrade head` and `downgrade -1` work. File lands in `packages/db/alembic/versions/` (depends on T004)
- [X] T006 Create `packages/db/src/db/repositories/tracing.py` with `create_request`, `add_steps` (insert one or more, returns the created steps' ids), `finish_step`, `finish_request`, `list_requests(filters, limit, after)` → `(rows, has_more)` (filters: `endpoint`, repeatable `outcome`, `since` inclusive / `until` exclusive on `started_at`; newest first by `id`; raises `UnknownCursorError` like `db/repositories/chat_completions.py`), `get_request_with_steps(id)` (steps ordered by `position`), `mark_in_progress_interrupted()` (requests and steps with `in_progress` → `interrupted`). Functions take the session + typed args; add nothing else (depends on T004)
- [X] T007 [P] Repository tests in `packages/db/tests/test_tracing_repository.py`: create/finish request, step insert + `finish_step`, list ordering + cursor + each filter + unknown cursor, detail with ordered steps, `mark_in_progress_interrupted` touches only in-progress rows, unique `(request_id, position)` (depends on T006)
- [X] T008 [P] Extend `packages/db/tests/test_migrations.py` if needed so the new migration is covered by the existing upgrade/autogenerate-drift check (depends on T005)
- [X] T009 Create `apps/api/src/api/observability/tracing.py` containing: (a) the notification hub (set of per-subscriber `asyncio.Queue`s; `subscribe()` async generator, `publish(event)`, `close()` ending all subscribers); (b) the background writer (single `asyncio.Queue` of write commands applied in FIFO order with short sessions from `db.engine.get_async_session_factory()` via `db.repositories.tracing`; every command wrapped in `try/except` that logs and continues (FR-014); publishes `request.created` / `request.updated` with the request `id` only after commit; `start()`, and `stop()` that stops accepting work and drains the queue); (c) the `Trace` handle (assigns `position` locally; the writer owns the trace→row-id mapping so steps queued before the create commit attach to the right row; `step_sent(payload)` enqueues the `sent_to_ollama` step AND its paired `received_from_ollama` step with `status = in_progress`, `content = null`; `step_received(content, status, error_message)` finishes that pair half with duration/content; `set_summary`, `set_outcome`, `set_response(body)`, `set_response_id(id)`, `add_error`) plus a `ContextVar` with `get_trace()` returning a no-op handle when none is active; (d) the `TRACKED` allow-list (`POST /v1/chat/completions` only). Per research R2/R3/R5. Writer/hub are module-level singletons (or held on `app.state`) started/stopped by the lifespan in T011.
- [X] T010 Add the pure-ASGI middleware to `apps/api/src/api/observability/tracing.py` (not `BaseHTTPMiddleware`): for `(method, path)` in `TRACKED`, create the `Trace`, set the `ContextVar`, wrap `receive` to capture the request body (record `request_received` client→api with the parsed JSON, falling back to `{"raw": …}` if not JSON) and wrap `send` to capture status and, for non-streaming responses, the body; on completion in `finally` finalize once: default outcome from status (2xx success, ≥400 error) unless overridden via `trace.set_outcome`, record `response_returned` api→client only for a successful outcome (body from captured bytes, or from `trace.set_response` for streams); for ≥400 responses, or when the service called `trace.add_error` (failed stream after HTTP 200), record an `error` step api→client (content = error envelope / translated message) and set the request `error_message`; a canceled request gets neither; handle `asyncio.CancelledError` as `canceled` and re-raise (best effort: `canceled` comes only from `CancelledError` or `trace.set_outcome`, never from a status code; `http_status` stays whatever was already sent, `null` if nothing was). Response bytes on the wire MUST be unchanged (Principle I). Untracked paths pass straight through (depends on T009)
- [X] T011 Wire into `apps/api/src/api/app.py`: in `lifespan`, before `yield`: call `mark_in_progress_interrupted()` (own session), then start the writer; after `yield`/on shutdown: `hub.close()` first, then writer drain/stop, before the engine goes away; add the middleware to `app` (depends on T006, T009, T010)
- [X] T012 Add Trace calls to `apps/api/src/api/chat/service.py` without behavior change: `trace.set_summary(f"{model} · stream|non-stream")` once the request is parsed; non-stream — `step_sent(prepared.ollama)` before each `_generate_all` Ollama call, `step_received(...)` after it (content = assembled response; `failed` + message on Ollama errors); stream — `step_sent` before each `ollama.chat_stream(...)`, and a single `step_received` per call in the `finally` of `_stream_body` with the assembled content from `run.streamed_response()` and status completed/failed/canceled (partial content kept; never per chunk); `n > 1` ⇒ one pair per Ollama call in call order; failed/canceled streams still return HTTP 200, so they report through the trace: completed → `trace.set_response(run.streamed_response(), …)`; failed → `trace.add_error(message)` + `set_outcome(error)`; canceled → `set_outcome(canceled)` only (no `response_returned`, no `error` step). In every scenario (stream or not, any outcome) call `trace.set_response_id(run.external_id)` as soon as the run exists, so `response_id` always links the usage record (FR-011). Rejections before Ollama (validation, unsupported option, unknown model) produce no Ollama steps (depends on T009)
- [X] T013 [P] Foundational backend tests in `apps/api/tests/test_observability_tracing.py` (reuse `ollama_fakes.OllamaMock` and the `conftest.py` client/session fixtures; add a fixture there that starts the writer and awaits queue drain so assertions can read committed rows): non-stream success yields the four steps in order; response bytes identical with tracing on; untracked endpoints (`/v1/models`, `/v1/health`, `/v1/analytics/*`) create no rows (FR-013, SC-004); two concurrent requests each get their own correct step set (ContextVar/writer isolation). Also add a `live_server` fixture in `conftest.py`: run the real app with `uvicorn.Server` on an ephemeral port (port 0) in a background asyncio task and talk to it with `httpx.AsyncClient` over TCP. `ASGITransport` buffers whole responses and cannot simulate a client disconnect, so every test that reads an open SSE stream, observes a mid-stream state, or cancels mid-stream uses `live_server` (uvicorn is already a dependency; no new one) (depends on T010, T011, T012)

**Checkpoint**: Chat completions are recorded in SQLite; no UI yet.

---

## Phase 3: User Story 1 - Watch requests arrive and complete in real time (Priority: P1) 🎯 MVP

**Goal**: Observability tab with a live feed (list endpoint + SSE notifications), with in-progress → final state updating in place, errors marked failed, and history shown on open.

**Independent Test**: Open the tab, send a chat completion; a row appears within 1 s as in progress, then updates to final status and duration. Rejected request shows as failed with its message. Opening the tab after traffic shows history.

### Backend

- [X] T014 [P] [US1] Create `apps/api/src/api/observability/schemas.py` with list/detail/step response models (fields exactly per `contracts/observability.md`: list item `id` (int), `endpoint`, `method`, `started_at` (unix s), `started_at_ms`, `duration_ms`, `http_status`, `outcome`, `summary`, `response_id`, `error_message` — nullable fields serialized as `null`, never omitted; step `position`, `kind`, `source`, `destination`, `status`, `offset_ms` (computed `step.started_at − request.started_at` in ms), `duration_ms`, `content` untyped JSON, `error_message`; detail = list item + `steps`; list envelope `object: "list"`, `data`, `first_id`, `last_id`, `has_more`). Use `StrEnum`s from `db.models` for enums, `extra="ignore"`, timestamp int conversion in the schema not the model. Local naming (non-OpenAI; no OpenAI schema names apply).
- [X] T015 [US1] Create `apps/api/src/api/observability/router.py`: `GET /observability/requests` with query `limit` (1–100, default 20), `after`, `endpoint`, repeatable `outcome`, `since`, `until` (invalid `outcome`/`limit` → standard 422; unknown `after` → 404 `not_found` via `UnknownCursorError`, same handling as `apps/api/src/api/analytics/router.py`); empty result → `data: []`, `first_id`/`last_id` null, `has_more` false. Router only calls `db.repositories.tracing` functions (no `service.py`). Depends on T006, T014
- [X] T016 [US1] Add `GET /observability/events` to `apps/api/src/api/observability/router.py`: `StreamingResponse` with `Content-Type: text/event-stream`, wire format `event: request.created\ndata: {"id": <int>}\n\n` / `event: request.updated`, a `: keep-alive` comment about every 15 s, no `[DONE]`, ends on client disconnect or `hub.close()`; typed event model in `schemas.py` serialized by a thin wrapper (don't yield raw strings from the generator). Depends on T009, T014, T015
- [X] T017 [US1] Include the observability router in `apps/api/src/api/app.py` under the `/v1` router (depends on T015, T016)
- [X] T018 [P] [US1] Endpoint tests in `apps/api/tests/test_observability_endpoints.py`: list newest-first + envelope shape + nullable fields present as `null`, `limit` bounds → 422, unknown `after` → 404 envelope, empty list shape, SSE emits `request.created` then `request.updated` after a chat request (use the `live_server` fixture from T013, read the stream with a timeout; assert the commit is visible on immediate refetch), observability's own calls create no rows (depends on T017)
- [X] T019 [P] [US1] Extend `apps/api/tests/test_observability_tracing.py`: validation rejection (e.g. missing `messages`) → `request_received` + `error` only, outcome `error`, `error_message` set, no Ollama steps; unknown model same; recording failure swallowed — monkeypatch a repository function to raise inside the writer and assert the chat request still returns 200 (FR-014) (depends on T013)
- [X] T020 [US1] Regenerate the frontend schema: with the API running, `pnpm gen:api` in `apps/web` to update `apps/web/src/api/schema.d.ts`; commit the generated file (depends on T017)

### Frontend

- [X] T021 [P] [US1] Create `apps/web/src/api/observability.ts`: TanStack Query `useInfiniteQuery` hook for `/v1/observability/requests` (cursor `after` = `last_id`, `has_more`) via the typed `openapi-fetch` client in `src/api/client.ts`, accepting a filters object (used by US3); all observability query keys (list and detail) share one `["observability", …]` prefix, exported for the events hook; no `refetchInterval`; types from `schema.d.ts` only (depends on T020)
- [X] T022 [US1] Create `apps/web/src/hooks/use-observability-events.ts`: owns a native `EventSource("/v1/observability/events")` (the one allowed non-`openapi-fetch` transport; add a one-line WHY comment), exposes connection state `connecting | connected | disconnected`, and invalidates the shared `["observability"]` key prefix (so list and any open detail refresh) on every `request.created`/`request.updated` event and on every `open` (reconnect catch-up, FR-015); parses the event payload into one small local `type` (the SSE stream isn't in the generated schema; say so in a comment); closes on unmount. Pause support is added in US3 (depends on T021 for query keys)
- [X] T023 [P] [US1] Create `apps/web/src/components/observability-feed.tsx`: table (endpoint, method, start time, duration, status code, outcome badge, summary, error message for failed rows), in-progress rows visibly marked, failed rows visually distinct, "Load more" using `has_more`, empty state explaining what appears and how to generate traffic (FR-017), connection-state indicator. Use existing `components/ui` (table, badge, button, skeleton); reuse `src/lib/format.ts` helpers where they fit (depends on T021, T022)
- [X] T024 [US1] Create `apps/web/src/pages/observability.tsx` (`ObservabilityPage`, named export) hosting the feed; add route `/observability` in `apps/web/src/App.tsx` and a third nav item "Observability" (lucide icon, `useMatch("/observability")`) in `apps/web/src/components/app-sidebar.tsx` (depends on T023)
- [X] T025 [P] [US1] Test `apps/web/tests/observability-events.test.tsx`: fake `EventSource` — event triggers a refetch, `open` triggers a refetch, connection state transitions, closed on unmount (use `renderWithProviders`; MSW handler via `server.use(...)`; import test fns from `vitest`) (depends on T022)
- [X] T026 [P] [US1] Test `apps/web/tests/observability-feed.test.tsx`: renders rows with in-progress/success/error states, error message shown for failed rows, empty state, load-more uses `last_id` as `after` (depends on T024)

**Checkpoint**: US1 is functional and demoable (quickstart scenarios 1, 3 first half, 6).

---

## Phase 4: User Story 2 - Follow one request's workflow between the API and Ollama (Priority: P1)

**Goal**: Selecting a request opens a client / API / Ollama sequence view with per-step offset/duration, expandable truncated content, live fill-in of in-progress streaming steps, and highlighted failures.

**Independent Test**: Send a streaming completion, select its row: four ordered steps with offsets/durations and full assembled content; a validation-rejected request shows only API-side steps; an Ollama failure highlights the failed Ollama step plus the translated error.

### Backend

- [X] T027 [US2] Add `GET /observability/requests/{id}` to `apps/api/src/api/observability/router.py` returning the detail model (list item + ordered `steps`, `offset_ms` computed by the API; `in_progress` step has `duration_ms: null` and `content: null`); unknown id → 404 `not_found` standard envelope (depends on T015)
- [X] T028 [P] [US2] Extend `apps/api/tests/test_observability_endpoints.py`: detail shape matches `contracts/observability.md` (field names, `offset_ms`, step order), 404 for unknown id (depends on T027)
- [X] T029 [P] [US2] Extend `apps/api/tests/test_observability_tracing.py`: streaming success stores a single assembled `received_from_ollama` step (no per-chunk steps) and the `in_progress` state is observable mid-stream (use `live_server`); Ollama failure/unreachable → `request_received`, `sent_to_ollama`, failed `received_from_ollama` with `error_message`, then `error` step api→client; `n=2` → two sent/received pairs in call order; failed stream (HTTP 200) → failed `received_from_ollama`, `error` step api→client, outcome `error`, request `error_message` set, no `response_returned`; mid-stream cancel (use `live_server`; the test client closes the connection) → open step ends `canceled` with partial content, outcome `canceled`, no `response_returned` (depends on T013)
- [X] T030 [US2] Regenerate `apps/web/src/api/schema.d.ts` with `pnpm gen:api` (depends on T027)

### Frontend

- [X] T031 [P] [US2] Add detail query hook `useTracedRequest(id)` to `apps/web/src/api/observability.ts` (typed `openapi-fetch`, no polling) (depends on T030)
- [X] T032 [P] [US2] Create the pure helper `apps/web/src/lib/sequence-layout.ts` exporting `layoutSteps(steps)`: maps each step to its lane columns (client=0, api=1, ollama=2), arrow from/to and direction, and flags (`failed`, `inProgress`); typed from the generated schema (depends on T030)
- [X] T033 [P] [US2] Test `apps/web/tests/sequence-layout.test.ts`: success sequence lanes/directions, rejected-request sequence (no Ollama lane steps), failed Ollama step flag, in-progress flag, `n>1` ordering (depends on T032)
- [X] T034 [US2] Create `apps/web/src/components/observability-sequence.tsx`: three lane headers (Client, API, Ollama) in a CSS grid, one row per step with a directional arrow, kind label, offset/duration labels, status styling (failed highlighted with error message, in-progress marked, canceled/interrupted distinct), expandable content panel (pretty-printed JSON, first ~2,000 chars with a "Show full content" toggle, R8). Keyboard-operable/a11y-compliant (Biome a11y) (depends on T031, T032)
- [X] T035 [US2] Wire selection: selecting a feed row opens the detail (side panel or below the feed) in `apps/web/src/pages/observability.tsx` / `observability-feed.tsx`; selected request id in the URL search param or `useState` (simplest that works); while open, the existing event hook's invalidation must also refresh the detail query key so in-progress steps fill in (FR-006, SC-003); no hook change needed thanks to the shared key prefix from T021 (depends on T034, T024)
- [X] T036 [P] [US2] Test `apps/web/tests/observability-detail.test.tsx`: selecting a row renders the steps in order, expanding shows content, long content is truncated with the toggle, failed step highlighted, in-progress step re-renders with content after the next detail refetch (depends on T035)

**Checkpoint**: US1 + US2 work independently (quickstart 2, 3, 4).

---

## Phase 5: User Story 3 - Find and filter specific requests (Priority: P2)

**Goal**: Filter feed by endpoint, outcome, time range; pause/resume live updates with a "N new" count.

**Independent Test**: Mixed traffic → endpoint filter and errors-only filter narrow the list while new matching requests still arrive live; pausing keeps the list unchanged and shows the waiting count; resume reveals them.

- [X] T037 [P] [US3] Create `apps/web/src/components/observability-filters.tsx`: endpoint select (options from the tracked endpoints present, at minimum `/v1/chat/completions`), outcome multi-select/toggle incl. "errors only" = `error`, time range (`since`/`until` converted to unix seconds). Controlled component; filters held in `ObservabilityPage` `useState` and passed to the list hook from T021
- [X] T038 [US3] Add pause support to `apps/web/src/hooks/use-observability-events.ts`: `paused` flag; while paused, events increment a `pendingCount` and do NOT invalidate list queries; `resume()` invalidates once and resets the count (detail query for an open request still refreshes). Expose `{ connection, paused, pendingCount, pause, resume }` (depends on T022, T035)
- [X] T039 [US3] Integrate into `observability-feed.tsx` / `pages/observability.tsx`: filter bar, Pause/Resume button, "N new requests waiting" indicator; filter changes reset the cursor (new query key) (depends on T037, T038, T023, T035)
- [X] T040 [P] [US3] Backend filter tests in `apps/api/tests/test_observability_endpoints.py`: `endpoint` exact match, repeatable `outcome`, `since` inclusive / `until` exclusive boundaries, filters combined with `after` pagination (depends on T015)
- [X] T041 [P] [US3] Test `apps/web/tests/observability-filters.test.tsx`: changing filters issues requests with the right query params; while paused, an incoming event doesn't refetch the list and the count increments; resume refetches once and clears the count (depends on T039)

**Checkpoint**: US1–US3 independent (quickstart 5).

---

## Phase 6: User Story 4 - Review history after a restart (Priority: P3)

**Goal**: Everything survives restart; in-progress rows are shown as interrupted; the feed pages through full history.

**Independent Test**: Send requests, kill the server mid-stream, restart: earlier requests keep full detail; the in-flight request and its open step show `interrupted`.

- [X] T042 [US4] Restart tests in `apps/api/tests/test_observability_restart.py`: seed an `in_progress` request with an `in_progress` step in the test DB, run the app lifespan startup, assert both are `interrupted` and completed rows are untouched; assert the writer drains pending commands on shutdown (no lost rows); recording-failure case lives in T019 (depends on T011)
- [X] T043 [P] [US4] Frontend: make sure the outcome/status badges and sequence view render `interrupted` distinctly (in `observability-feed.tsx` and `observability-sequence.tsx`) and cover it in `apps/web/tests/observability-feed.test.tsx` (depends on T026, T034)
- [X] T044 [US4] Verify SC-006 per quickstart §11: seed ~20k `traced_requests` rows with a throwaway script in the scratchpad directory (do NOT commit), measure first page and detail response < 200 ms; if it fails, add the composite index described in `data-model.md` via a new autogenerated migration (depends on T017, T027)

**Checkpoint**: All four stories complete.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T045 [P] Ruff lint + format and `mypy` on the whole Python workspace; fix findings (no new `# type: ignore` without a WHY comment)
- [ ] T046 [P] `pnpm check`, `pnpm typecheck`, `pnpm test` in `apps/web`; fix findings
- [ ] T047 Run `uv run pytest` (full backend suite incl. existing chat/contract tests, proving the middleware doesn't alter existing behavior) and `pre-commit run --all-files`
- [ ] T048 Walk through `quickstart.md` manual scenarios 1–11 against a real Ollama (incl. SC-002: request → Ollama payload/response in ≤ 3 clicks; incl. scenario 10 latency within 5 %, scenario 7 `kill -9` restart, scenario 8 reconnect) and note any deviations
- [ ] T049 README: update only if setup/run steps changed (migration command or new env var). Expected: no change, skip if so

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (1)**: none.
- **Foundational (2)**: after Setup; blocks all stories. Internal order: T003 → T004 → T005/T006 → T009 → T010 → T011; T012 after T009; T013 last.
- **US1 (3)**: after Phase 2. **US2 (4)**: after Phase 2; shares the router/page files with US1 (T027 after T015; T035 after T024). **US3 (5)**: needs US1's feed/hook (T022, T023) and, for T038/T039, US2's detail wiring (T035) so a paused feed still refreshes an open detail; so US3 follows US2. **US4 (6)**: needs Phase 2; UI bits need US1/US2 components.
- **Polish (7)**: after desired stories.

### Within a story

Backend schemas → router → app wiring → schema regen (`pnpm gen:api`) → frontend hooks → components → page integration → tests.

### Parallel Opportunities

- T001/T002; T007/T008 once T006/T005 land; T014 alongside T009–T012 (different files).
- US1 frontend: T021, then T022 (needs its query keys), then T023; T025/T026 in parallel.
- US3 backend filter tests (T040) and T037 can run alongside US2 frontend work; T038/T039 wait for T035.
- US2: T031/T032/T033 together after T030; T028/T029 in parallel with frontend work.
- US3: T037/T040 in parallel.

## Parallel Example: User Story 1

```text
Task: "T014 schemas.py"                     (apps/api/src/api/observability/schemas.py)
Task: "T018 endpoint tests"                 (apps/api/tests/test_observability_endpoints.py)
Task: "T019 rejection/failure tests"        (apps/api/tests/test_observability_tracing.py)
Task: "T021 query hook"                     (apps/web/src/api/observability.ts)
Task: "T022 EventSource hook"               (apps/web/src/hooks/use-observability-events.ts)
```

## Implementation Strategy

### MVP First (US1)

1. Phase 1 → Phase 2 (stop and verify rows land in SQLite via T013).
2. Phase 3 (US1) → validate with quickstart scenarios 1, 3, 6.

### Incremental Delivery

US1 (live feed) → US2 (workflow detail; the main value) → US3 (filters/pause) → US4 (restart/scale checks) → Polish. Suggested commits (one atomic commit per logical change, Conventional Commits): DB models+migration+repo; tracing core + chat service hooks; observability endpoints; frontend feed; sequence view; filters/pause; tests/polish as appropriate.

## Notes

- `[P]` = different files, no dependency on incomplete tasks.
- Recording must never fail or slow a request (FR-014); never persist stream chunks.
- Every `pnpm gen:api` regeneration is committed with the endpoint change that caused it.
- No `service.py` for observability and no extra abstractions (YAGNI).

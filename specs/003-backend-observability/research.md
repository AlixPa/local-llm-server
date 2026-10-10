# Research: Backend Observability Tab

No `NEEDS CLARIFICATION` items remained in the spec; the decisions below resolve the design
choices the spec deliberately left open.

## R1. Capturing requests, including ones rejected before the handler

- **Decision**: A pure-ASGI middleware (not `BaseHTTPMiddleware`) wraps the app. For a request
  matching the explicit `TRACKED` set (`POST /v1/chat/completions`), it creates a `Trace`,
  stores it in a `ContextVar`, wraps `receive` to capture the request body and `send` to capture
  the status code and (for non-streaming responses) the response body, and finalizes the
  request in a `finally` after the app returns.
- **Rationale**: Schema-validation failures happen before the route handler runs, so only
  middleware sees 100 % of requests (SC-004). Pure ASGI is the only form that does not buffer or
  re-wrap streaming responses (Principle I: SSE bytes unchanged) and does not run the app in a
  separate task, which would break context propagation and cancellation semantics.
- **Alternatives**: a route-level dependency (misses validation rejections); `BaseHTTPMiddleware`
  (known problems with streaming bodies and cancellation); instrumenting only the service
  (misses rejections, mixes concerns).

## R2. Recording Ollama steps

- **Decision**: The chat service calls a small `Trace` API at the existing Ollama call sites:
  `step_sent(payload)` before each Ollama call (inserted immediately, so it is visible while in
  flight), and `step_received(content)` when the call ends. Non-streaming: after `_generate_all`
  returns. Streaming: once, in the existing `finally` of `_stream_body`, with the assembled
  content (partial if canceled/failed) — never per chunk. When `n > 1`, there is one sent/received
  pair per Ollama call. `get_trace()` returns a no-op handle when no trace is active (untracked
  paths, unit tests), so the service never branches on it.
- **Rationale**: The service already owns the exact payload and the assembled result, and
  already has the cancel-safe recording spot (`_record_shielded`). A `ContextVar` avoids
  threading a parameter through every service function. The `Trace` object is mutable and shared,
  so Starlette running the streaming body in a child task is not an issue.
- **Alternatives**: instrumenting `llm.OllamaClient` (it sees only the translated payload per
  HTTP call and cannot know the assembled OpenAI-level result; also would couple the `llm`
  package to API tracing); httpx event hooks (same limits, no stream assembly).

## R3. Persistence path: one background writer

- **Decision**: `Trace` methods enqueue small write commands onto an `asyncio.Queue`; a single
  writer task (started in the lifespan) applies them in order with its own short sessions from
  the db package's session factory, via repository functions, and then publishes a notification
  to the hub. Every command is wrapped in `try/except` that logs and continues (FR-014). On
  shutdown the lifespan stops accepting new work and drains the queue before the engine goes away.
- **Rationale**: (1) keeps SQLite writes off the request path, protecting SC-005; (2) ordering
  per request is guaranteed by the single FIFO; (3) a writer task is not cancelled when a client
  disconnects, so cancel/failure rows are never lost and no `CancelScope(shield=True)` is needed;
  (4) one writer avoids "database is locked" contention among concurrent requests and with the
  chat service's own usage-record insert; (5) publishing after commit means a UI refetch always
  sees the data.
- **Alternatives**: awaiting inline writes (adds latency, contention, cancel hazards);
  `BackgroundTasks` (not per-event, wrong lifecycle); a thread pool with the sync engine (more
  moving parts, no benefit at this scale).

## R4. Live updates transport

- **Decision**: Server-Sent Events from `GET /v1/observability/events`, backed by an in-memory
  hub (set of per-subscriber `asyncio.Queue`s). An event is a tiny notification
  (`request.created` / `request.updated`, with the request's `id`), not the data. The browser
  uses native `EventSource` (auto-reconnect built in) and, on every event *and every (re)open*,
  invalidates the relevant TanStack Query keys so state is re-read from the DB-backed endpoints.
  The server sends a `: keep-alive` comment periodically.
- **Rationale**: One-way server→client fits SSE; no WebSocket dependency; the project already
  speaks SSE. Notification-only events make the DB the single source of truth (Principle V),
  make reconnect catch-up trivial (FR-015: refetch on open, no event-replay log), and keep the
  hub free of payload size concerns. Single process ⇒ in-memory hub is sufficient (batch workers
  are out of scope; when they arrive and write from another process they would need a different
  notifier — decided then, YAGNI).
- **Alternatives**: WebSockets (more machinery); polling with `refetchInterval` (violates the
  "polling only for in-progress batches" convention and cannot meet SC-001 cheaply);
  replayable event log with `Last-Event-ID` (speculative).
- **Shutdown note**: long-lived SSE connections block uvicorn's graceful shutdown. The hub
  exposes a `close()` that the lifespan calls first, ending every subscriber generator.
- **Frontend exception**: CLAUDE.md allows raw `fetch` only for the chat SSE stream;
  `EventSource` for this notification stream is the same category (`openapi-fetch` can't stream)
  and is isolated in `use-observability-events.ts`.

## R5. Request outcome and HTTP status

- **Decision**: Outcomes: `in_progress`, `success`, `error`, `canceled`, `interrupted`. The
  middleware derives the default from the captured HTTP status (2xx → success, ≥ 400 → error).
  `canceled` is best effort: it comes from `asyncio.CancelledError` in the middleware or from
  `trace.set_outcome(...)`, never from a status code (the server never emits 499). The service
  overrides via `trace.set_outcome(...)` because a stream that
  fails or is canceled mid-way still has HTTP 200 (the error is an in-band SSE event). The
  response-returned step carries the body: for non-streaming, the captured response bytes (parsed
  JSON, including error envelopes); for streaming, the assembled response the service already
  builds (`run.streamed_response()`), handed over via `trace.set_response(...)`.
- **Rationale**: Reuses facts the service already has; no re-parsing of SSE.

## R6. Interrupted requests

- **Decision**: In the lifespan startup, before serving, call repository
  `mark_in_progress_interrupted()`: all `traced_requests` and `workflow_steps` with status
  `in_progress` become `interrupted`. Started before the writer so nothing races.
- **Rationale**: Single-process server ⇒ any in-progress row at startup is by definition dead
  (FR-011, User Story 4 scenario 3).

## R7. Linking to the LLM usage record

- **Decision**: `traced_requests.response_id` stores the resource's external id
  (`chatcmpl-…`, equal to `chat_completion_records.external_id`). No foreign key; the API joins
  by value when it needs the link.
- **Rationale**: The usage record is inserted at the *end* of a request, after the trace row
  exists, and is skipped for rejected requests; an FK would force write-order coupling. The value
  link is enough for the UI ("view usage record") and generic across future tracked endpoints.
- **Alternatives**: nullable FK to `chat_completion_records.id` (couples generic tracing tables to
  one endpoint's table and to its insert timing).

## R8. Large content

- **Decision**: The detail endpoint returns full step content; the UI truncates at render
  (e.g. first ~2,000 characters with a "show full content" toggle).
- **Rationale**: Local single-user, payloads are prompts/generations (KBs to low MBs); a
  separate per-step content endpoint would be speculative (YAGNI). If payloads prove too large,
  that endpoint is added then.

## R9. Excluding the tab's own traffic

- **Decision**: Satisfied by construction — `TRACKED` is an explicit allow-list; observability,
  models, analytics, and health routes are never in it (FR-013, FR-002a).

## R10. Sequence view rendering

- **Decision**: Hand-built layout with plain React + Tailwind (CSS grid, three lanes: Client,
  API, Ollama; one row per step with an arrow indicating direction, offset/duration labels,
  expandable content panel). A pure `layoutSteps(steps)` helper maps steps to lane/arrow
  direction and is unit-tested. No charting/diagram library.
- **Rationale**: Three fixed participants and a linear step list; a library is unjustified
  (Principle III, YAGNI).

## R11. Filters, pagination, pause

- **Decision**: List is cursor-paginated (`after` = last request `id`, OpenAI list envelope),
  ordered newest first; filters `endpoint`, `outcome`, `since`/`until` (unix seconds) are query
  params applied in SQL. Pause is purely client-side: while paused, events are counted but the
  list queries are not invalidated; the count is shown and resume invalidates once.
- **Rationale**: Matches the existing analytics list conventions; keeps the server stateless
  with respect to UI state.

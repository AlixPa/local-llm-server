# Feature Specification: Backend Observability Tab

**Feature Branch**: `003-backend-observability`

**Created**: 2026-10-03

**Status**: Draft

**Input**: User description: "Let's build some better observability tools. Because the whole project is running locally, and it is not yet the goal to have multiple grafana or whatever integration, I'd like to add a third tab to handle the backend observability. Both for the api server, seeing what endpoints are triggered etc, and ollama, seeing what is being sent/received. Ideally I would like it to be easy to follow. Because the ollama running is linked to an api request we should see in real time the logging, as well as have an easy way to visually follow the workflows, the communications in between api and ollama, etc."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Watch requests arrive and complete in real time (Priority: P1)

As the developer running the server locally, I open a new "Observability" tab (alongside the existing Playground and Analytics tabs) and see a live feed of every request to a tracked endpoint (see FR-002): which endpoint was hit, when, how long it took, and its outcome. New requests appear on their own, without me refreshing, and a request that is still running is visibly shown as in progress until it finishes.

**Why this priority**: Seeing what the server is doing right now is the core of the request. Without a live request feed, nothing else in the tab has an entry point.

**Independent Test**: Open the tab, send a chat completion request from the Playground or any OpenAI client, and confirm a new row appears within a second showing the endpoint, an in-progress state, then the final status and duration.

**Acceptance Scenarios**:

1. **Given** the tab is open and idle, **When** a request is sent to a tracked endpoint, **Then** a new entry appears in the feed without any manual refresh, showing endpoint, method, start time, and an "in progress" state.
2. **Given** a request is in progress in the feed, **When** it completes, **Then** the same entry updates in place to show its final status (success or error), HTTP status code, and total duration.
3. **Given** a request to a tracked endpoint ends in an error (validation failure, upstream failure), **When** I look at the feed, **Then** the entry is clearly marked as failed and shows the error message returned to the caller.
4. **Given** many requests were sent while the tab was closed, **When** I open the tab, **Then** I see the recent history of those requests, not an empty feed.

---

### User Story 2 - Follow one request's full workflow between the API and Ollama (Priority: P1)

As the developer, I select any request in the feed and see a visual, step-by-step view of everything that happened for it: the request received by the API, the call the API made to Ollama (what was sent), the response coming back from Ollama (for a streaming call, the full assembled result once the stream has ended), and the response finally returned to the caller. The steps are laid out in order on a timeline/sequence view so I can see at a glance who talked to whom, in what order, and how long each hop took.

**Why this priority**: The user explicitly wants to "visually follow the workflows" and "the communications in between api and ollama". This is the differentiating value over a plain log.

**Independent Test**: Send a streaming chat completion, select its entry, and confirm the detail view shows the incoming request, the outgoing Ollama request payload, the complete Ollama response (assembled from the stream), the final response to the caller, and per-step timing, all in chronological order.

**Acceptance Scenarios**:

1. **Given** a completed chat completion request, **When** I select it, **Then** I see a visual sequence of steps between the client, the API, and Ollama, each labeled with direction, time offset from the request start, and duration.
2. **Given** a step in the sequence, **When** I expand it, **Then** I see the full content that was sent or received at that step (e.g. the prompt messages and options sent to Ollama, the generated text received back).
3. **Given** a streaming request still in progress, **When** I have its detail view open, **Then** the steps that have already happened (e.g. request received, request sent to Ollama) are shown, the streaming step is marked as in progress, and it fills in with the full content once the stream completes or is canceled.
4. **Given** a request that never reached Ollama (e.g. rejected by validation), **When** I select it, **Then** the sequence shows only the API-side steps and the error, with no Ollama steps.
5. **Given** a request where Ollama failed or was unreachable, **When** I select it, **Then** the failing Ollama step is clearly highlighted along with the error and how it was translated into the response to the caller.

---

### User Story 3 - Find and filter specific requests (Priority: P2)

As the developer, when many requests have accumulated, I can narrow the feed by endpoint, outcome (in progress, success, error), and time range, and pause the live updates while I inspect something so the list does not shift under me.

**Why this priority**: Valuable once the feed has real volume, but the feed and detail view are useful on their own first.

**Independent Test**: Send a mix of successful and failing requests to different endpoints, apply an endpoint filter and an "errors only" filter, and confirm only matching entries remain; pause the feed, send a new request, and confirm the list does not change until resumed.

**Acceptance Scenarios**:

1. **Given** a feed with requests across several endpoints, **When** I filter by one endpoint, **Then** only requests to that endpoint are shown, and new matching requests still arrive live.
2. **Given** the feed contains successes and failures, **When** I filter to errors only, **Then** only failed requests are shown.
3. **Given** live updates are paused, **When** new requests arrive, **Then** the list stays unchanged and I am told how many new requests are waiting; resuming reveals them.

---

### User Story 4 - Review history after a restart (Priority: P3)

As the developer, after restarting the server (or after a crash), I can still open the tab and inspect requests and their workflows from before the restart.

**Why this priority**: Helpful for debugging crashes after the fact, but live inspection is the primary need. Aligns with the project rule that observable state survives restarts.

**Independent Test**: Send several requests, restart the server, open the tab, and confirm earlier requests and their full workflow detail are still viewable.

**Acceptance Scenarios**:

1. **Given** requests were handled before a restart, **When** the server is back up and I open the tab, **Then** those requests appear in the feed with their full detail.
2. **Given** many requests have accumulated over time, **When** I open the tab, **Then** all of them remain available (nothing is discarded automatically) and the feed loads in pages.
3. **Given** a request was in progress when the server stopped, **When** I view it after restart, **Then** it is shown as interrupted rather than as forever in progress.

---

### Edge Cases

- The live connection between the browser and the server drops (server restart, laptop sleep): the tab shows a clear "disconnected" indicator, reconnects automatically, and catches up on anything missed.
- Very large payloads (long prompts, long generations): the detail view stays responsive, showing a truncated preview with an explicit way to see the full content.
- Many concurrent requests at the same time: each is tracked separately and the feed stays readable.
- Requests canceled by the caller mid-stream: shown as canceled, with the steps that did occur and whatever content had been received up to the cancel preserved.
- The observability tab's own traffic (loading the feed, live updates, history) must not flood the feed with its own entries and obscure the requests being watched.
- Requests that contain sensitive-looking content: the server is local and single-user, so content is shown as-is; nothing is sent outside the machine.
- An empty state (no requests yet) explains what will appear and how to generate traffic.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The web app MUST provide a third top-level tab, "Observability", reachable from the same navigation as the existing tabs.
- **FR-002**: The system MUST record, from the API's point of view, every request to a *tracked endpoint*, capturing at least: endpoint path, method, start time, duration, HTTP status, and outcome (in progress, success, error, canceled, interrupted). Initially the tracked endpoints are the inference endpoints (currently chat completions); endpoints with little diagnostic value (model listing, analytics, health) and observability's own endpoints (FR-013) are deliberately not tracked.
- **FR-002a**: Whether an endpoint is tracked MUST be an explicit per-endpoint decision. Each future endpoint's spec MUST state whether it is tracked (and what its workflow steps are), and whether the Observability tab supports displaying it.
- **FR-003**: For each request, the system MUST record an ordered list of workflow steps covering: request received from the caller, request sent to Ollama, response received from Ollama, and response returned to the caller, plus any error encountered. For streaming calls, the step records the full assembled content once the stream ends (completed, failed, or canceled); individual stream chunks are NOT recorded as separate steps.
- **FR-004**: Each recorded step MUST include its direction (who sent it, to whom), timestamp, offset from request start, duration where applicable, and the content that was transferred.
- **FR-005**: The tab MUST show a live feed of requests that updates automatically when new requests start and when in-flight requests change state or finish, without manual refresh.
- **FR-006**: The tab MUST show an in-flight request's workflow steps as they are recorded while its detail view is open; a streaming step appears as in progress and is filled in when the stream ends.
- **FR-007**: Selecting a request MUST open a visual sequence view of its workflow showing the participants (client, API, Ollama), the steps in chronological order, and per-step timing, so the flow of communication can be followed at a glance.
- **FR-008**: Any step in the sequence view MUST be expandable to show the full transferred content, with large content truncated by default and fully viewable on demand.
- **FR-009**: Failed requests and failed steps MUST be visually distinct and show the error message and where in the workflow it occurred.
- **FR-010**: The feed MUST support filtering by endpoint, by outcome, and by time range, and MUST allow pausing and resuming live updates, indicating how many new requests arrived while paused.
- **FR-011**: Recorded requests and steps MUST be stored in the project database (the API-point-of-view counterpart of the existing LLM-point-of-view usage records, and the source for the feed and history), MUST be linkable to the corresponding LLM usage record when one exists, and MUST persist across server restarts; and requests that were in progress at shutdown MUST be shown as interrupted after restart.
- **FR-012**: The system MUST NOT automatically discard recorded requests or steps; history is kept in full.
- **FR-013**: Requests made by the Observability tab itself (feed, detail, live updates) MUST NOT appear in the feed (they are untracked by FR-002).
- **FR-014**: Recording observability data MUST NOT noticeably slow down (SC-005) or break request handling; a failure to record MUST NOT cause the observed request to fail.
- **FR-015**: The tab MUST show connection state for live updates, reconnect automatically after a drop, and recover any entries missed while disconnected.
- **FR-016**: All observability data shown in the UI MUST be served through the server's `/v1` HTTP endpoints (non-OpenAI additional endpoints), never by the web app reading storage directly.
- **FR-017**: The tab MUST show a helpful empty state when no requests have been recorded.

### Key Entities *(include if feature involves data)*

- **Traced Request**: One request handled by the API server. Attributes: endpoint, method, start time, duration, HTTP status, outcome, and a short summary (e.g. model used, streaming or not). Owns an ordered set of workflow steps.
- **Workflow Step**: One communication or event within a traced request. Attributes: sequence position, source and destination participant (client, API, Ollama), kind (request received, sent to Ollama, received from Ollama (full content, assembled for streams), response returned, error), timestamp and offset, duration, transferred content.
- **LLM usage record** (existing): the LLM-point-of-view record (token usage per request). A Traced Request links to it when the request reached generation.
- **Live Update**: A notification that a traced request was created, a step was added, or a request changed state, used to keep open views current.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new request appears in an open Observability tab within 1 second of the server receiving it.
- **SC-002**: A developer can go from "I just sent a request" to seeing exactly what was sent to and received from Ollama for it in 3 clicks or fewer.
- **SC-003**: Once a streaming request ends (completed or canceled), its full streamed content is visible in the open detail view within 1 second.
- **SC-004**: 100% of requests to tracked endpoints appear in the feed, including rejected and failed ones; untracked endpoints never appear.
- **SC-005**: Chat completion latency (time to first streamed token and total time) with recording enabled is not noticeably worse than without it (within 5% on the same machine).
- **SC-006**: The feed and detail views remain responsive (interactions under 200 ms) as history grows to tens of thousands of recorded requests.
- **SC-007**: After a server restart, 100% of requests recorded before shutdown remain viewable with their full workflow.

## Assumptions

- Single local user on a single machine; no authentication, multi-user separation, or external observability integrations (Grafana, OpenTelemetry exporters, etc.) are in scope.
- Storage is the project's SQLite database, using tables that can hold workflow steps for any tracked endpoint (not chat-specific), so later endpoints can reuse them or extend them as their own specs decide.
- As part of this feature, the project constitution (Principle V) and `.claude/CLAUDE.md` are amended so that API-point-of-view recording of valuable endpoints becomes a standing rule, and every new endpoint's spec must decide on tracking.
- "Backend observability" covers the API server and its Ollama communication only; batch workers will be added to the same view when the batch feature exists, and are out of scope now.
- Full prompt and response content is recorded and shown, since the data never leaves the local machine.
- History is kept indefinitely in the database; no automatic pruning. Streaming responses are recorded once, in full, when the stream ends, which keeps storage and complexity modest. Manual cleanup tooling is out of scope.
- "Real time" means the tab updates when a request starts, when a workflow step is recorded, and when the request ends. It does not mean per-chunk streaming display.
- This tab is distinct from the existing Analytics tab: Analytics summarizes token usage; Observability shows individual request workflows.
- The "Observability" tab is desktop-first, follows OS light/dark, and is English only, like the rest of the web app.
- The feature adds non-OpenAI endpoints under `/v1`, so it does not alter any OpenAI-defined contract (constitution Principle I), makes no calls beyond local Ollama (Principle II), and does not interact with batch scheduling (Principle IV). Persistence in SQLite supports Principle V.

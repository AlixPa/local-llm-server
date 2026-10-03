# Implementation Plan: Backend Observability Tab

**Branch**: `003-backend-observability` | **Date**: 2026-10-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/003-backend-observability/spec.md`

## Summary

Record the API's point of view of every request to a *tracked endpoint* (initially only
`POST /v1/chat/completions`) as one `traced_requests` row plus an ordered set of
`workflow_steps` rows (request received → sent to Ollama → received from Ollama → response
returned, plus errors), in SQLite. A pure-ASGI middleware owns the request lifecycle (so
validation rejections are captured too); the chat service adds the Ollama steps through a
context-local `Trace` handle. All writes go through one in-process background writer (ordered,
non-blocking, immune to request cancellation), which publishes a notification to an in-memory
hub after each commit. Three non-OpenAI endpoints under `/v1/observability` expose the list,
the detail, and a Server-Sent Events notification stream. The React app gets a third
**Observability** tab: live feed with filters/pause, and a hand-built sequence-diagram detail
view (client / API / Ollama lanes).

## Technical Context

**Language/Version**: Python ≥ 3.14 (backend); TypeScript strict, React 19 (frontend)

**Primary Dependencies**: none new. FastAPI/Starlette (ASGI middleware, `StreamingResponse` for
SSE), SQLAlchemy async + Alembic (existing); frontend: browser-native `EventSource`, existing
TanStack Query/shadcn (add `tabs`/`collapsible`-style shadcn components only if needed)

**Storage**: SQLite via `packages/db`; two new tables, one Alembic migration

**Testing**: pytest + pytest-asyncio + httpx ASGI transport (Ollama mocked); `validate_schema`
for the error envelope, ordinary behavior tests for the non-OpenAI endpoints; Vitest + Testing
Library + MSW for the frontend (SSE hook tested with a fake `EventSource`)

**Target Platform**: single local macOS Apple-silicon machine, Ollama on localhost

**Project Type**: web application (FastAPI backend + Vite SPA) in a uv/pnpm monorepo

**Performance Goals**: new request visible in an open tab ≤ 1 s (SC-001); stream content visible
≤ 1 s after stream end (SC-003); chat latency within 5 % (SC-005); list/detail interactions
< 200 ms at tens of thousands of requests (SC-006)

**Constraints**: handlers `async def`; no DB statements outside `packages/db`; recording failures
never fail the observed request (FR-014); no pruning (FR-012); `mypy --strict`; no `any` in TS;
no new dependencies

**Scale/Scope**: single user; 1 tracked endpoint now; 3 new endpoints; 1 new frontend page

## Constitution Check

*GATE: pass before Phase 0; re-checked after Phase 1.*

| Principle | Status | Notes |
|---|---|---|
| I. OpenAI-compatible surface | Pass | Only additional endpoints under `/v1/observability/*` (no OpenAI counterpart, nothing shadowed); no OpenAI-defined contract changes. The middleware must be transparent to the chat endpoint's bytes on the wire. Non-OpenAI paths use the standard error envelope and standard 422 validation. |
| II. Fully local | Pass | No new network calls; nothing leaves the machine. |
| III. Lightweight, minimal deps | Pass | No new dependency or runtime service: SSE over plain FastAPI, in-process pub/sub, native `EventSource`. Schema change ships with its Alembic migration. |
| IV. Live priority over batch | Pass (N/A) | No batch workload. Recording is off the request path (queued writer), so it cannot add latency to live requests. |
| V. State & observability via SQLite | Pass | This feature *is* the API-point-of-view recording the constitution (v1.3.0) now requires. DB is the source of truth; the in-memory hub only carries "something changed" notifications and the UI always re-reads state from the DB-backed endpoints; in-flight rows left at shutdown are marked interrupted at next startup. Frontend only uses `/v1`. |

Project conventions: YAGNI honored — one writer/hub/trace module, no generic event framework, no
replay log, no truncation endpoint, no step-per-chunk. `service.py` for observability is *not*
added; the router just calls `db` repository functions. DB-only-in-db-package honored (the writer
calls repository functions; it holds sessions but no statements). Per-endpoint decisions
(CLAUDE.md "Logging"): chat completions tracked + supported by the tab; models, analytics,
health, observability endpoints untracked.

No violations → Complexity Tracking omitted. *Post-design re-check*: unchanged.

## Project Structure

### Documentation (this feature)

```text
specs/003-backend-observability/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── observability.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
packages/db/
├── alembic/versions/<ts>-<rev>_observability.py     # traced_requests, workflow_steps
├── src/db/models/tracing.py                          # TracedRequest, WorkflowStep + StrEnums
├── src/db/models/__init__.py                         # export new models/enums
├── src/db/repositories/tracing.py                    # create/update request, add/finish step,
│                                                     # list (filters + cursor), get detail,
│                                                     # mark_in_progress_interrupted
└── tests/test_tracing_repository.py

apps/api/src/api/
├── observability/
│   ├── __init__.py
│   ├── tracing.py       # Trace handle + contextvar, TRACKED endpoints, ASGI middleware,
│   │                    # background writer, notification hub
│   ├── router.py        # GET /observability/requests, /requests/{id}, /events (SSE)
│   └── schemas.py       # list/detail/step response models, event model
├── app.py               # lifespan: start writer, mark interrupted, stop/drain; add middleware
└── chat/service.py      # add Trace calls at the Ollama call sites (no behavior change)

apps/api/tests/
├── test_observability_tracing.py     # success, stream, validation reject, ollama failure, cancel,
│                                     # recording failure swallowed
├── test_observability_endpoints.py   # list/filter/cursor/detail/404, SSE notification
└── test_observability_restart.py     # interrupted on startup; writer drains on shutdown

apps/web/src/
├── api/observability.ts              # query hooks (list infinite query, detail)
├── hooks/use-observability-events.ts # EventSource, connection state, invalidation, pause buffer
├── lib/                              # sequence layout helper (pure, unit-tested)
├── components/
│   ├── observability-feed.tsx        # table, filters, pause/resume, empty state
│   ├── observability-filters.tsx
│   └── observability-sequence.tsx    # lanes + steps + expandable content
├── pages/observability.tsx
├── App.tsx                           # route
├── components/app-sidebar.tsx        # third nav item
└── api/schema.d.ts                   # regenerated (pnpm gen:api)
apps/web/tests/                       # sequence layout, SSE hook, feed filter/pause tests
```

**Structure Decision**: Backend feature folder `api/observability/` (feature-based, like `chat/`,
`analytics/`); tracing mechanics and router in the same feature since they are only used
together. DB models/repository follow the existing `models/<feature>.py` +
`repositories/<feature>.py` pattern. Frontend stays layer-based per CLAUDE.md.

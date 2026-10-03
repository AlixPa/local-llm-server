# Implementation Plan: Chat Completions End to End

**Branch**: `002-chat-completions` | **Date**: 2026-10-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-chat-completions/spec.md`

## Summary

Implement OpenAI's `POST /v1/chat/completions` in full (streaming and non-streaming, every
request option honored, emulated, ignored, or rejected per [research.md](research.md) R5), served
by a local Ollama `qwen3.5:9b` (the only row of a seeded `models` table; any other model name gets OpenAI's `model_not_found`) through a new `llm` workspace package. Every request that reaches
the endpoint logic is persisted via the `db` package (metadata and content in separate tables).
`GET /v1/models` (OpenAI's contract) lists the served models. Two non-OpenAI endpoints under `/v1/analytics/chat-completions` expose content-free metadata and
summary figures. The React app gets a sidebar with a Playground tab (all options, streaming,
cancel, session history) and an Analytics tab (summary + cursor-paginated list).

## Technical Context

**Language/Version**: Python ≥ 3.14 (backend); TypeScript strict, React 19 (frontend)

**Primary Dependencies**: FastAPI, SQLAlchemy async + Alembic (existing); `httpx` (runtime dep of
the new `llm` package — already in the lockfile as a dev dep); frontend: existing stack plus
shadcn components (`textarea`, `select`, `switch`, `slider`, `label`, `table`, `card`, `badge`)

**Storage**: SQLite via `packages/db`; three new tables, one Alembic migration

**Testing**: pytest + pytest-asyncio + httpx ASGI transport, `validate_contract`/`validate_schema`
fixtures, Ollama mocked with `httpx.MockTransport`, one `integration`-marked real-Ollama test;
Vitest + Testing Library + MSW on the frontend

**Target Platform**: single local macOS Apple-silicon machine, Ollama on localhost

**Project Type**: web application (FastAPI backend + Vite SPA) in a uv/pnpm monorepo

**Performance Goals**: first streamed content in the Playground ≤ 2 s once the model is loaded
(SC-004); analytics list visible ≤ 2 s at 10,000 records (SC-008)

**Constraints**: local-only inference; handlers `async def`; one shared `httpx.AsyncClient`
(created in the app lifespan, closed on shutdown); no DB statements outside `packages/db`;
`mypy --strict`; no `any` in TS

**Scale/Scope**: single user; ~35 request options; 2 frontend pages

## Constitution Check

*GATE: pass before Phase 0; re-checked after Phase 1.*

| Principle | Status | Notes |
|---|---|---|
| I. OpenAI-compatible surface | Pass | Path, schemas (verbatim names), SSE format, error envelope match the vendored spec; contract tests mandatory. Analytics endpoints use a non-shadowing prefix (`/v1/analytics/…`) since OpenAI defines `/v1/chat/completions[/{id}]`. |
| II. Fully local (Ollama only) | Pass | Only Ollama calls, via the `llm` package; unreachable Ollama is an error, never a fallback. |
| III. Lightweight, minimal deps | Pass | No new runtime service; one new workspace package (`llm`), explicitly requested by the user by that name and anticipated by CLAUDE.md "Runtime / infra", so no further approval is needed; schema change ships with its Alembic migration. |
| IV. Live priority over batch | Pass (N/A) | No batch workload exists yet. |
| V. State & observability via SQLite | Pass | Constitution v1.2.1 scopes recording to every request that reaches generation: schema-validation rejections attempt no inference and are not recorded (spec Assumptions). Usage and timings persisted; Analytics fed by `/v1` endpoints reading the DB; frontend never touches SQLite. |

Project conventions: YAGNI honored (no speculative repos; `service.py` added only because
translation, `n` emulation, and recording are real logic); DB-only-in-db-package honored.
No violations → Complexity Tracking omitted.

*Post-design re-check*: unchanged — design adds no principle conflicts.

## Project Structure

### Documentation (this feature)

```text
specs/002-chat-completions/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── chat-completions.md
│   └── analytics.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
packages/llm/                         # NEW workspace package (added to root pyproject members/sources)
├── pyproject.toml
├── src/llm/
│   ├── __init__.py
│   ├── py.typed
│   ├── config.py                     # pydantic-settings: LOCAL_LLM_OLLAMA_HOST/NUM_CTX
│   ├── schemas.py                    # Ollama wire models (chat request/response/stream chunk, errors)
│   └── client.py                     # OllamaClient: chat(), chat_stream() over a shared httpx.AsyncClient
└── tests/test_ollama_client.py       # MockTransport; + one integration-marked test

packages/db/src/db/
├── models/chat_completions.py        # ChatCompletionRecord, ChatCompletionContent, status StrEnum
├── models/models.py                  # Model (served models, seeded by the migration)
├── models/__init__.py                # export new models for Alembic
├── repositories/chat_completions.py  # create / list metadata / summary (see data-model.md)
└── repositories/models.py            # list_models / get_model
packages/db/alembic/versions/…_chat_completions.py   # autogenerated + reviewed
packages/db/tests/test_chat_completions_repository.py

apps/api/src/api/
├── app.py                            # lifespan owns OllamaClient/httpx client; include new routers
├── errors.py                         # 400 on OpenAI paths for validation errors; OpenAI error codes; ApiError helper
├── chat/
│   ├── router.py                     # POST /chat/completions (stream branch → StreamingResponse)
│   ├── schemas.py                    # OpenAI schema names, verbatim; SSE chunk models
│   └── service.py                    # option policy (R5), OpenAI↔Ollama translation, n emulation, recording
├── models/
│   ├── router.py                     # GET /models (OpenAI ListModelsResponse)
│   └── schemas.py                    # Model, ListModelsResponse (OpenAI names)
└── analytics/
    ├── router.py                     # GET /analytics/chat-completions, …/summary
    └── schemas.py                    # list item + summary models (list envelope)
apps/api/tests/
├── test_chat_completions.py          # contract + behavior (mocked Ollama)
├── test_chat_completions_options.py  # R5 policy table
├── test_chat_completions_stream.py   # SSE chunks, cancel, mid-stream error
├── test_analytics.py
├── test_models.py
├── test_openai_sdk_integration.py    # @pytest.mark.integration
└── test_ollama_integration.py        # @pytest.mark.integration

apps/web/src/
├── App.tsx                           # routes: / → /playground, /playground, /analytics
├── components/app-sidebar.tsx        # nav links
├── components/ (playground-*, analytics-*, ui/ additions)
├── pages/playground.tsx
├── pages/analytics.tsx
├── api/ (schema.d.ts regenerated; chat, models + analytics query hooks)
├── hooks/use-chat-stream.ts          # streaming + AbortController
└── lib/parse-sse.ts                  # pure SSE parser
apps/web/tests/                       # parse-sse, playground flow, analytics (no-content assertion)

.env.example, README.md               # new LOCAL_LLM_OLLAMA_* vars, model pull step (setup steps changed)
```

**Structure Decision**: follows the existing monorepo. `llm` knows only Ollama's wire format and
returns typed Ollama results; OpenAI-shaped types and all translation stay in `apps/api/chat`
(OpenAI schemas live with the feature, per CLAUDE.md). `db` owns every query. The API receives
`OllamaClient` and the session through FastAPI dependencies, so tests override both.

## Key Design Points

1. **Request flow**: router validates (`CreateChatCompletionRequest`) → `service` applies the
   field policy (reject early with 400), validates `model` against the `models` table (404), builds Ollama requests, calls `OllamaClient`, assembles
   the OpenAI response/chunks, measures `duration_ms`/TTFT, then calls the db function to record.
2. **Streaming + recording**: the streaming generator records in a `finally`, deciding
   `succeeded`/`failed`/`cancelled` from how it exited (client disconnect raises
   `CancelledError`/`GeneratorExit`); the DB write is shielded so cancel still persists.
   Disconnect closes the upstream httpx stream, which stops Ollama generation (FR-011).
3. **Error handling**: a small `ApiError` exception (status, type, code, param, message) handled
   by the existing handler module; `RequestValidationError` becomes 400 on OpenAI paths and 422
   elsewhere (the standing TODO in CLAUDE.md, done here). OpenAI paths = `/v1/chat/completions`.
4. **Frontend streaming**: `parse-sse.ts` is a pure function over a `ReadableStream`; the hook
   owns the abort controller; options form sends only fields the user changed.
5. **Cancellation**: a client disconnect cancels the handler (a small disconnect watcher races the
   non-streaming handler against `request.is_disconnected()`; the streaming generator is closed by
   Starlette). `n` upstream calls run in an `asyncio.TaskGroup`, so cancelling cancels all of them,
   and closing each httpx request makes Ollama stop generating. The record is written as `cancelled`.
6. **Upstream timeouts**: the shared `httpx.AsyncClient` has a short connect timeout but no read
   timeout (cold model loads and long generations legitimately take minutes; Ollama blocks until the
   model is loaded).
7. **Streaming pre-flight**: for `stream=true`, policy checks, model validation, and the first
   Ollama chunk happen before `StreamingResponse` is returned so pre-stream failures are real
   HTTP errors (research R13).
8. **Spec deltas made during planning**: images (inline base64) are supported, audio is not;
   schema-validation failures are not recorded (see spec Assumptions); served models are a DB
   table with `GET /v1/models` (R12).

## Open Items to Verify During Implementation

Tracked in `research.md` as **verify**: penalty options accepted by Ollama's native API, context
overflow behavior (R3), Ollama error body shapes, `done_reason: "length"`, tools/thinking/vision
support of `qwen3.5:9b`. Each has an integration test (T010 is a gate before the service tasks) or quickstart step; policy rows adjust if
a check fails.

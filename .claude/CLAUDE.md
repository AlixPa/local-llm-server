# CLAUDE.md

Project-specific conventions for working in `local-llm-server`. These are binding defaults —
follow them without re-deriving a preference each time. The project constitution
(`.specify/memory/constitution.md`) governs *what* the system must be (API compatibility,
local-only inference, live-request priority, etc.); this file governs *how* day-to-day
development is done.

## Guiding principle: YAGNI (overrides everything else below)

This is the number one rule of this repo. Do not build structure, abstractions, or layers ahead
of an actual, present need:

- No service layer until a router actually accumulates business logic. A router that just
  validates input, calls the DB, and returns a response does not get a `service.py`.
- No worker package/process until the batch feature is actually being built — its location and
  shape are decided then (see "Deliberately left open" below), not pre-scaffolded now.
- No frontend state store, E2E suite, i18n, shared-component extraction, or production static
  serving until an actual need appears (see "Frontend").
- No speculative fields, config options, abstraction layers, or "we'll probably need this later."
- When a convention below says "decide case-by-case" or "decided at plan time," that is YAGNI in
  practice, not a gap to fill in preemptively.

## Guiding principle: contract fidelity vs. internal freedom

A second axis, orthogonal to YAGNI, that resolves most "should this match OpenAI?" questions:

- **Anything an OpenAI SDK client can observe is the external contract and matches OpenAI
  exactly, with zero deviation**: HTTP paths (including the `/v1` prefix), schema names, fields,
  types, and optionality, enum values, the error envelope shape, HTTP status codes, the
  streaming wire format (SSE chunk shape, `[DONE]` sentinel), resource ID format. This is
  non-negotiable — it's the entire reason this project exists (constitution Principle I).
- **Anything only visible inside this codebase is this project's own convention and has no
  obligation to resemble how OpenAI (or anyone else) happens to be built internally**:
  file/folder layout, internal module/function naming, service-layer structure, DB schema and
  column types, logging format, test layout, commit workflow. Match OpenAI there only if it's
  genuinely convenient, never because "OpenAI does it this way."
- **Additional (non-OpenAI) endpoints are allowed.** An endpoint OpenAI doesn't define (e.g.
  `/v1/health`) can't break an SDK client, so it is free to exist. It still lives under `/v1`
  and uses the standard error envelope, but its own behavior (paths, bodies, status codes,
  error `type`/`code` values) follows strict industry conventions for that kind of endpoint,
  not OpenAI's. The moment OpenAI does define an endpoint, ours MUST match OpenAI's contract
  exactly, so check the vendored spec before inventing anything.
- When in doubt: would a client importing the OpenAI SDK and pointing it at this server notice a
  difference? If yes, it's contract — match exactly. If no, it's internal — use this repo's own
  conventions below.

## Project structure

- **Feature-based organization**, not layer-based. Each feature gets its own folder with its own
  `router.py`, `schemas.py`, and (only once needed, per YAGNI) `service.py`:
  ```
  apps/api/src/api/
    chat/
      router.py      # APIRouter, route functions
      schemas.py      # Pydantic models for this feature
      service.py       # only added once router.py has real business logic to extract
    batches/
      router.py
      schemas.py
      ...
    app.py            # creates the FastAPI app, includes each feature's router
  ```
- Schemas are **not** centralized and do **not** mirror OpenAI's own file/module layout — they
  live with the feature that uses them.
- `packages/db` follows the same feature-oriented spirit for models: add a model module when a
  feature needs one (e.g. `models/batches.py`), don't pre-create empty structure for features
  that don't exist yet. The database *plumbing* is not speculative and exists from day one:
  settings, the async engine/session factory/`get_session` (API), the sync engine/session
  factory (Alembic, future workers), and the declarative `Base`. Models and repositories are
  what start empty and arrive with the first feature that needs them.
- **Deliberately left open / decided later, per YAGNI:**
  - Where batch worker code lives (`apps/worker` vs `packages/worker` vs inside `apps/api`) —
    decide this when the batch-processing feature is actually planned (`/speckit-plan`).
  - The concrete mechanism for the live-request-priority guarantee (constitution Principle IV) —
    same, decided at plan time based on what the design needs.
  - Soft delete vs. hard delete, and whether a resource needs extra lifecycle timestamp columns
    (e.g. `cancelled_at`, `completed_at`) vs. a separate history table — there is no blanket rule;
    this is a per-resource decision made in that resource's spec, based on what it actually needs
    (e.g. a cancellable batch job plausibly needs `cancelled_at`; a simple synchronous resource
    probably needs neither).

## Code style & tooling

This section covers the **Python** side. The frontend has its own section ("Frontend") and the
two toolchains do not mix.

- **Package manager**: `uv` workspace (root `pyproject.toml` `[tool.uv.workspace]` with members
  `apps/api`, `packages/db`, and future packages). Add/upgrade dependencies with `uv add`/
  `uv remove` scoped to the relevant package (`--project apps/api` etc., `--dev` for dev tools)
  — never a bare `pip install`, and never hand-edit a dependency list in a `pyproject.toml`.
  Prefer the plain package over "batteries" extras (e.g. `uvicorn`, not `uvicorn[standard]`)
  unless an extra is actually needed.
- **Formatter/linter**: Ruff only, for both linting and formatting, over all Python files
  including Alembic migrations. Do not introduce Black, isort, or Flake8 — Ruff replaces all of
  them. Alembic's `script.py.mako` is kept in line with the modern-syntax rules below so
  generated migrations pass Ruff without hand-fixing.
- **Line length**: 88 characters (Ruff/Black default).
- **Type checking**: `mypy --strict` on every module, except `packages/db/alembic/` (generated
  code whose logic we don't edit to satisfy a type checker). New or modified code MUST be fully
  typed (no implicit `Any`, no untyped defs). Fix type errors rather than suppressing them with
  `# type: ignore` unless the ignore has a comment explaining why it's unavoidable.
- **Docstrings/comments**: minimal. Do not write docstrings or comments that restate what the
  code does. Only add a short comment when there's a non-obvious WHY — a hidden constraint, a
  workaround, a subtle invariant. Pydantic `Field(description=...)` follows the same rule: only
  add it when the field's meaning, units, or constraints aren't obvious from its name and type.
- **Imports**: absolute imports from the workspace packages (`api`, `db`); no deep relative
  imports across package boundaries.
- **Modern syntax, strictly enforced** (project requires Python >=3.14):
  - `X | None`, never `Optional[X]`.
  - Builtin generics (`list[str]`, `dict[str, int]`), never `List`/`Dict` from `typing`.
  - f-strings only, never `%`-formatting or `.format()`.
  - `StrEnum` for closed sets of string values; `match` statements where they genuinely fit.
- **Pre-commit hooks** (the frontend hooks are covered in "Frontend"): a
  `.pre-commit-config.yaml` at the repo root, following standard pre-commit practice: pinned hook repos, hooks receive only the staged files and are filtered by
  file type, so a docs-only commit skips the Python hooks entirely. It runs Ruff (lint with
  `--fix`, and format) via `astral-sh/ruff-pre-commit`, mypy as a `uv run` local hook (so it
  sees workspace packages) on staged Python files outside Alembic, and the usual hygiene hooks
  (`pre-commit-hooks`: trailing whitespace, end-of-file, YAML/TOML validity, merge-conflict
  markers, large files; vendored `openai-spec/` excluded). Set this up once and keep it
  passing — it's the enforcement mechanism for everything in this section.

## API & schema conventions

- **Schema naming**: Pydantic classes use OpenAI's own schema names from its published OpenAPI
  spec, verbatim (e.g. `CreateChatCompletionRequest`, `CreateChatCompletionResponse`,
  `ChatCompletionChunk`, `Batch`, `BatchRequestInput`). Do not invent a local naming scheme
  (`{Resource}In`/`Out` etc.) — if OpenAI has a name for it, use that name.
- **Schema content**: field-for-field parity with OpenAI's schema (same names, types,
  optionality). Local-only fields never get bolted onto an OpenAI-shaped model; if one is truly
  needed it goes in its own separate, clearly-named model.
- **Unknown fields**: Pydantic models use `extra="ignore"` — tolerate a client (or a newer OpenAI
  SDK) sending fields we don't support yet rather than hard-rejecting the request.
- **Enums**: OpenAI's string enum values (status fields like `"queued"`, `"in_progress"`,
  `"completed"`) are represented as Python `StrEnum` classes whose member values match OpenAI's
  documented strings exactly.
- **List responses**: a paginated list endpoint (`/batches`, `/files`, etc.) returns OpenAI's list
  envelope — `{"object": "list", "data": [...], "has_more": ..., "first_id": ..., "last_id": ...}`
  — never a bare array.
- **Error format**: all error responses use OpenAI's error envelope:
  `{"error": {"message": ..., "type": ..., "param": ..., "code": ...}}`. Install an exception
  handler that normalizes to this shape — never return FastAPI's default `{"detail": ...}` for an
  API error. For OpenAI endpoints, the specific `type`/`code` values and HTTP status for a given
  failure follow OpenAI's documented behavior for that condition. For all other endpoints and
  generic framework errors (unknown route, wrong method, …) they follow standard HTTP
  semantics, with `code` being the snake_case HTTP reason (`not_found`,
  `method_not_allowed`) and `null` for unexpected 500s. No local enum of error kinds.
  Request-validation failures follow the same split: **400 `invalid_request_error`** on OpenAI
  paths (the SDK maps 400 and 422 to different exceptions), standard **422** on non-OpenAI paths.
  (`api/errors.py` currently returns 422 everywhere — fix it with the first OpenAI endpoint.)
- **Routing**: every endpoint — including local-only ones with no OpenAI counterpart — is
  mounted under `/v1`, no exceptions. Where an OpenAI counterpart exists, the path matches it
  exactly (e.g. `/v1/chat/completions`, `/v1/batches`, `/v1/files`). This is what makes the
  server a true drop-in for the OpenAI SDK — a client only changes `base_url` (e.g.
  `http://localhost:8000/v1`), the same pattern Ollama's own OpenAI-compatible endpoint uses.
- **Handlers**: every route handler is `async def`. All I/O (Ollama calls, DB access) uses async
  clients/drivers (`httpx.AsyncClient`, async SQLAlchemy) — never a blocking call on the event
  loop. The sync DB engine exists only for code that is not on the event loop (Alembic,
  worker processes).
- **Route declarations**: rely on the function's return type annotation (e.g.
  `-> CreateChatCompletionResponse`) for the response schema. Don't also pass a redundant
  `response_model=`. For an endpoint whose request has a `stream` flag (chat completions,
  completions), branch inside one handler and return `StreamingResponse` on the streaming path —
  FastAPI can't express "one Pydantic model or an SSE stream" as a single schema, so the return
  annotation is a union (`CreateChatCompletionResponse | StreamingResponse`) and the streaming
  branch's actual shape is governed by the **Streaming** convention below, not by the annotation.
- **Streaming**: a `stream=true` endpoint is an `async def` generator yielding typed chunk models
  (e.g. `ChatCompletionChunk` instances), serialized to `data: {...}\n\n` by a thin
  `StreamingResponse` wrapper and terminated with `data: [DONE]\n\n`. Don't yield raw
  pre-formatted strings from the generator itself.
- **Resource IDs**: mirror OpenAI's prefixed ID format exactly (e.g. `chatcmpl-<random>`,
  `batch_<random>`, `file-<random>`), generated with a short random suffix.
- **Auth**: no API key required for now. The server is fully local, single-user. Don't add auth
  scaffolding speculatively.

## Database & migrations

- **ORM naming**: singular PascalCase model class → plural snake_case table, e.g.
  `class BatchJob(Base): __tablename__ = "batch_jobs"`.
- **Primary keys**: a surrogate integer primary key, plus a separate unique-indexed external id
  column holding the OpenAI-style string id (e.g. `id: int` PK, `external_id: str` unique). The
  external id is what the API exposes; the integer PK is for internal joins/FKs.
- **SQLite safeguards (already in place, don't undo)**: `Base.metadata` has a constraint naming
  convention (needed for batch migrations); Alembic runs with `render_as_batch=True`;
  every engine enables `PRAGMA foreign_keys=ON`; datetime columns use `db.types.UtcDateTime`
  (SQLite drops tzinfo; it rejects naive datetimes and restores UTC on read).
- **Timestamps**: API responses expose integer unix timestamps (matching OpenAI's `created`
  field etc.); the underlying DB column is a proper timezone-aware `datetime`, converted to an
  int only at the API boundary (in the schema, not the model).
- **Delete strategy / lifecycle columns**: no blanket rule — decided per resource, in that
  resource's spec, based on what it actually needs (see "Project structure" above).
- **Migrations**: always generate via `alembic revision --autogenerate`, then review and correct
  the generated migration yourself (Claude) before it's committed — autogenerate commonly misses
  server-side defaults, enum changes, etc. There's no separate "pause and wait for a human" step
  for migrations specifically; a human reviews it through the normal PR review, same as any other
  change.
- **Config/secrets**: `pydantic-settings` reading from a `.env` file for all configuration (DB
  path/URL, Ollama host, etc.). Env vars are prefixed `LOCAL_LLM_` (e.g. `LOCAL_LLM_DB_PATH`,
  `LOCAL_LLM_OLLAMA_HOST`) to avoid collisions. A `.env.example` with placeholder values is
  committed; the real `.env` is gitignored. Do not hardcode connection strings or hosts in source
  (replace the existing pattern in `packages/db/src/db/config.py` the next time that module is
  touched).

## Testing

- **When**: be practical — a feature or fix ships with tests when it carries logic or risk worth
  protecting (behavior, contracts, parsing, migrations, bug regressions). Pure plumbing and
  trivial wiring (logging setup, config loading, one-line fixes) don't need their own tests.
  Order is flexible — before or after the implementation; strict TDD is not required.
- **Stack**: pytest + pytest-asyncio + `httpx.AsyncClient` (via FastAPI's ASGI transport) for API
  tests.
- **Coverage**: no enforced minimum percentage. Judge sufficiency per change, not against a gate.
- **Contract tests (required for every new/changed OpenAI-defined endpoint)**: send a real
  request through the app and pass the `httpx` response to the `validate_contract` fixture
  (`openapi-core` against OpenAI's vendored spec, see below). It checks path, method, request
  body, status code, and response body in one call — this is the non-negotiable minimum for
  Principle I compliance. `validate_schema(body, "SchemaName")` validates a bare body against one
  named schema (for chunks of a stream, which `validate_contract` can't read, and for the error
  envelope on non-OpenAI paths). The fixtures normalize the spec at load (see `conftest.py`:
  `nullable` rewritten to the 3.1 form, discriminators dropped, auth removed); extend that
  normalization rather than working around the spec in individual tests. Additional non-OpenAI endpoints get an
  ordinary behavior test instead. Additional unit/integration tests are added
  where the change's risk warrants them.
- **Ollama**: mocked by default in the regular test suite — fast, deterministic, runs anywhere.
  A small set of tests marked `@pytest.mark.integration` hit a real local Ollama instance and are
  run separately/manually, not as part of the default fast run.
- **Test database**: a fresh in-memory SQLite database (`sqlite+aiosqlite:///:memory:`) per test,
  with tables created fresh each time — full isolation, no cleanup logic needed.
- **Layout**: a single flat `tests/` directory per workspace package (not mirroring the
  feature-folder source structure 1:1); descriptive file names (e.g.
  `test_chat_completions.py`). One root-level `conftest.py` per package holds shared fixtures
  (test DB session, test client, settings override) — no per-feature `conftest.py` files.
- **Vendored OpenAI spec**: lives at `/openai-spec/openapi.yaml` at the repo root, used by
  contract tests to validate schemas. No automated sync job — refreshed by hand when a mismatch
  is noticed or a new endpoint is being implemented.

## Logging & observability

- **Library**: Python's stdlib `logging` module with a small custom `Formatter` subclass that
  emits JSON — no new dependency (`structlog` etc.) for this.
- **Format**: structured JSON logs (one JSON object per line) from both the API process and
  batch workers, so logs are machine-parseable for later tooling/dashboards.
- Token usage for inference requests and batch/worker orchestration state are persisted to the
  SQLite DB (constitution Principle V) — logs are for operational visibility, not the source of
  truth for status or usage accounting. Whether any other endpoint records anything is decided
  per endpoint, based on what it does (a health check records nothing).

## Runtime / infra

- **Ollama access** will live in a future `llm` workspace package, not in `apps/api`; its shape
  (including the shared `httpx.AsyncClient` — one client reused for every request, closed on
  shutdown, never one per call) is decided when that package is planned.

## Frontend

A React single-page app for two things only: exercising the API endpoints (playground) and
browsing DB-backed data (logs, token usage, batches). It is a pure client of the `/v1` HTTP API —
it never touches SQLite, and any data it needs that no endpoint exposes means adding a (non-OpenAI)
`/v1` endpoint first (see "Contract fidelity" above).

- **Location**: `apps/web`. A standalone JS project, not a uv workspace member; the Python and JS
  toolchains stay separate.
- **Stack**: TypeScript (strict) + React + Vite + React Router + TanStack Query + Tailwind CSS +
  shadcn/ui. Adding any other framework/library follows the Dependencies rule above (routine
  additions are fine; keep it lightweight and YAGNI).
- **Package manager**: `pnpm`, pinned via the `packageManager` field (corepack). Add/remove
  dependencies with `pnpm add`/`pnpm remove` — never hand-edit `package.json` dependencies, never
  `npm`/`yarn`/`bun`. The lockfile is committed. Node LTS is pinned in `.node-version` and
  `engines`.
- **Source layout (layer-based, deliberately unlike the backend)**: `src/components/` (incl.
  `components/ui/` for shadcn), `src/hooks/`, `src/pages/` (one per route), `src/api/` (client,
  query hooks, generated schema), `src/lib/` (pure helpers). Don't create a folder until it has
  content. This is internal to the repo, so it doesn't need to mirror the backend's feature-based
  layout.
- **Routing**: `react-router` with all routes declared in `src/App.tsx`; one page per top-level view
  (playground, usage, batches, logs as they are built). No file-based routing.
- **Server state vs. client state**: all data from the API goes through TanStack Query (no
  `useEffect` fetching). Client-only state uses React built-ins (`useState`/`useReducer`/context);
  add a store (e.g. Zustand) only once prop-drilling concretely hurts. Polling (`refetchInterval`)
  only for in-progress batches, stopped once they reach a terminal status.
- **API client & types**: types are generated from the server's OpenAPI by `pnpm gen:api` into
  `src/api/schema.d.ts` (via `openapi-typescript`), **committed**, and regenerated in the same
  change that adds/modifies an endpoint. Never hand-write a type for an API shape. Calls go
  through the single typed `openapi-fetch` client in `src/api/client.ts`; no per-call raw
  `fetch` in components (the SSE stream is the one exception, since `openapi-fetch` can't stream).
  A response middleware in `client.ts` throws an `ApiError` carrying the OpenAI error envelope's
  `error.message`, which the UI shows as-is.
- **Streaming**: the playground supports `stream` on/off; the SSE parser reads `data: {...}`
  lines through the `[DONE]` sentinel and is cancellable with `AbortController`. The parser is
  pure logic and is unit-tested.
- **Lists**: data views paginate with the OpenAI list envelope (`data`, `has_more`, `last_id`) via
  cursor (`after`), never by assuming offset pagination.
- **Config**: one variable, `VITE_LOCAL_LLM_API_URL` (default `http://localhost:8000`), used by the
  Vite dev proxy only (the client uses relative `/v1` URLs). `pnpm gen:api` reads it from the
  shell environment, not from `.env`. `apps/web/.env.example` is committed; the real `.env` is
  gitignored. No other config until needed.
- **Serving**: dev only — `pnpm dev` (Vite) alongside the API, with Vite proxying `/v1` to the API
  (no CORS config on the server). No production serving yet; if wanted later, it's decided then
  (it must respect the "everything under `/v1`" routing rule and the no-extra-runtime-service
  rule).
- **Lint/format**: **Biome only** (no ESLint, no Prettier) for linting, formatting, and import
  sorting; `pnpm check` (`biome check`) is the single command, and `pnpm check:fix` applies fixes.
  `useSortedClasses` is a Biome nursery rule — verified working; if a Biome upgrade renames
  or drops it, fix the config rather than disabling class sorting. Recommended rules at error level, with the a11y
  and React rules on and Tailwind class sorting (`useSortedClasses`, covering `cn`/`cva`). Line
  width 88, 2-space indent, double quotes, semicolons. Generated `schema.d.ts` and
  `components/ui/` (shadcn-copied) are excluded from Biome. Fix violations rather than
  suppressing them; a `biome-ignore` needs an explanatory comment.
- **Type checking**: `tsc -b` (`pnpm typecheck`) with `strict: true` and `noUncheckedIndexedAccess: true`
  (`pnpm typecheck`; Biome does not type-check). No `any` and no `as` casts / `@ts-ignore` without a comment
  explaining why it's unavoidable. New or modified code is fully typed.
- **Code conventions**: function components only; named exports only (default exports only where
  a tool requires one, e.g. config files); files are kebab-case, components PascalCase, hooks
  `use-*.ts` files exporting `useX`; `type` over `interface` unless extending; `import type` for
  type-only imports; absolute imports via the `@/` alias to `src/`. Comments follow the same
  minimal rule as Python: only a non-obvious WHY.
- **UI baseline**: desktop-first, follows OS light/dark, English only, no i18n. Accessible by
  default (semantic elements, labels, keyboard operability — enforced partly by Biome a11y).
- **Testing**: Vitest + Testing Library + MSW (API mocked at the network layer). Same practical
  rule as the backend: test logic or risk (SSE parsing, data shaping, key interactions), not
  trivial wiring or shadcn wrappers. No E2E suite for now, no coverage gate. Flat `tests/`
  directory with descriptive file names. `tests/setup.ts` starts the shared MSW server
  (`tests/server.ts`, unhandled requests error, handlers reset per test — add handlers with
  `server.use(...)`); component tests render through `renderWithProviders` in
  `tests/render.tsx` (QueryClient with retries off + router + tooltip provider). Test functions are
  imported explicitly from `vitest` (no globals).
- **Pre-commit**: local hooks in the root `.pre-commit-config.yaml`, scoped to `apps/web/**`:
  `biome check --write` on staged files and `pnpm typecheck`. A Python-only
  commit skips them and vice versa. Generated schema and lockfile are excluded from Biome.
- **Done means**: for a frontend change, `pnpm check`, `pnpm typecheck`, and `pnpm test` pass
  (the substitute for CI, same as for Python).

## Documentation

- **README**: update it only when setup/run steps actually change (adding a command, changing a
  port, a new required env var). It is not required to document every feature — it's a setup
  guide, not a feature overview.

## Git & commit lifecycle

- **Workflow**: feature branch + pull request for every change, including solo work — no direct
  commits to `main`.
- **Commit messages**: Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`,
  `chore:`, etc.), short imperative summary line.
- **Commit granularity**: one atomic commit per logical change. Don't bundle unrelated changes
  into a single commit.
- **Merge strategy**: squash merge — a PR becomes one commit on `main` regardless of how many
  commits it had on the branch.
- **When Claude commits**: only when explicitly asked, per Claude Code's standard behavior.
  Claude does not commit proactively just because a task finished.
- **Pre-commit**: the `pre-commit` framework (see "Code style & tooling") gates every commit
  locally with Ruff + mypy (Python) and Biome + tsc (frontend) — this is the project's substitute for CI for now.

## Spec-kit workflow & agent autonomy

- **When spec-kit is required**: any new feature or endpoint goes through the full flow —
  `/speckit-specify` → (`/speckit-clarify` as needed) → `/speckit-plan` → `/speckit-tasks` →
  `/speckit-implement`. Small fixes (typos, a config tweak, a one-line bug fix) can be edited
  directly without going through spec-kit.
- **Local environment actions**: Claude has full autonomy to start/stop the dev server, run
  `ollama pull`, and apply Alembic migrations as part of normal task execution, without asking
  first.
- **Dependencies**: Claude may add or upgrade a dependency within an existing workspace package
  (or in `apps/web` via `pnpm add`) on its own judgment, as long as it fits the lightweight-server constraint (constitution
  Principle III) and YAGNI — no need to ask first for routine additions. Adding a new workspace
  package, or any dependency that pulls in an external runtime service (broker, queue, separate
  DB engine, etc.), requires asking first — that's an architectural decision, not a routine one.
- **CI**: none yet. `pre-commit` (see "Code style & tooling") plus a `pytest` run before
  considering a change done is the substitute — there is no GitHub Actions gate doing this
  automatically.
- **Subagents/forks**: for research-heavy work in this repo (multi-file investigations,
  codebase-wide audits, "where does X happen across the workspace" questions), proactively use a
  fork rather than doing it all inline — this project explicitly opts into that, overriding the
  more conservative global default of only forking when asked.

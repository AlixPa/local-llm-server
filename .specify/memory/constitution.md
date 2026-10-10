# Local LLM Server Constitution

## Core Principles

### I. OpenAI-Compatible API Surface
The server MUST implement the OpenAI-compatible OpenAPI contract for every endpoint it exposes,
starting with chat/completions and completions and extending to the batch endpoints (file upload,
batch create, batch retrieve/cancel, etc.). Request and response schemas MUST match the
corresponding OpenAI API shape closely enough that existing OpenAI SDK clients work against this
server by changing only the base URL. Where OpenAI defines an endpoint, ours MUST follow its
contract exactly. Additional endpoints with no OpenAI counterpart are allowed, since they cannot
break an OpenAI SDK client; they MUST NOT shadow or alter any OpenAI-defined path, and follow
standard industry conventions for their own behavior.

Rationale: drop-in compatibility with OpenAI's client ecosystem is this project's core value
proposition — it is what lets existing OpenAI-client tooling point at a private, local deployment
with no code changes.

### II. Fully Local Inference (Ollama-Only)
All model inference MUST run on local compute through Ollama. The server MUST NOT call out to any
remote or hosted inference API (OpenAI, Anthropic, or otherwise) to satisfy a completion, chat, or
embedding request. Ollama is the only supported inference backend for now. Any future backend MUST
be added as an additional adapter alongside Ollama, never as a silent replacement, and MUST NOT
compromise the fully-local guarantee for a user who has only configured Ollama.

Rationale: local-only, private operation is the reason this project exists; a silent fallback to a
hosted API would violate that guarantee and the user's trust.

### III. Lightweight Server, Minimal Dependencies
The HTTP layer MUST be built on FastAPI and kept intentionally thin. Heavyweight frameworks,
message brokers, or additional infrastructure services (e.g., Celery+Redis, Kafka, a separate
queueing service) MUST NOT be introduced when a simpler Python-native mechanism satisfies the
requirement. Persistent state MUST be stored in SQLite; schema changes MUST go through Alembic
migrations in `packages/db`. Prefer the standard library and the existing workspace packages over
adding new external runtime services.

The frontend (see Technology Stack Constraints) MUST be a client-side SPA served as static assets
or by a dev server; it MUST NOT introduce an SSR framework or any additional runtime service in
production.

Rationale: the project targets a single-machine, fully local deployment; operational simplicity is
a deliberate feature, not a shortcut to be removed later.

### IV. Live Requests Take Priority Over Batch (NON-NEGOTIABLE)
Synchronous, user-facing completion-style requests (chat/completions, completions, embeddings, and
equivalents) MUST always be serviced ahead of batch workload. Batch jobs run in separate Python
worker processes/tasks that MUST yield model/compute capacity whenever a live request is pending or
in flight — batch throughput is secondary to live-request latency. The live-request handling path
MUST NOT block on batch queue operations, and a stalled or backlogged batch queue MUST NOT degrade
live endpoint latency or availability.

Rationale: the batch API exists to make use of otherwise-idle local capacity; it must never be
allowed to starve the interactive, user-facing use case that the server primarily exists to serve.

### V. State & Observability via SQLite
Every inference request and every worker execution MUST be recorded in the SQLite database:
per-request token usage (prompt/completion/total) attributable to its endpoint, and batch
job/worker orchestration state (queued, running, completed, failed, retried). Recording is from
an LLM-usage point of view, not a server point of view: a request is recorded once it reaches
generation logic (including later failures and cancellations), while requests rejected by schema
validation before that point attempt no inference and need not be recorded. In addition, the API's
own point of view MUST be recorded for every endpoint whose workflow has diagnostic value (e.g.
inference endpoints): the request received, each exchange with Ollama (what was sent and
received), and the response returned, so workflows can be reconstructed from the database.
Endpoints with little diagnostic value (model listing, analytics, health checks) are not
recorded. Each new endpoint's spec MUST explicitly decide whether it is tracked (extending the
schema or reusing the generic tracing tables) and whether the observability UI supports it. This database is the single
source of truth for status endpoints and usage accounting — reported status MUST be derived from
the database, not from in-memory state alone, so it survives process restarts and crashes. Any UI view of
usage, logs, or batch status MUST be fed by API endpoints reading this database.

Rationale: batch processing and worker orchestration are inherently asynchronous and
multi-process; they must be auditable and recoverable across restarts without relying on fragile
in-memory state.

## Technology Stack Constraints

- Server framework: FastAPI (Python), ASGI only.
- Inference backend: Ollama, accessed as a local-only dependency — no cloud inference calls.
- Persistence: SQLite, managed through the `packages/db` workspace package and Alembic migrations.
- Batch execution: plain Python worker processes/tasks coordinated through the shared SQLite
  database — no external broker or queue service.
- Frontend: a single-page application (SPA) built with React, living in this repository. It
  exists to test the API endpoints and to browse database-backed data (logs, token usage, running
  and completed batches). It MUST talk to the server only through `/v1` HTTP endpoints and MUST
  NOT read SQLite directly. Any non-OpenAI endpoint it needs follows the additional-endpoint rules
  of Principle I.
- Frontend tooling: Biome is the single linter, formatter, and import sorter for the frontend
  code (no ESLint or Prettier); TypeScript in strict mode is the type checker; Vitest is the test
  runner. Concrete conventions live in `.claude/CLAUDE.md`.
- Dependency management: the `uv` workspace (`apps/api`, `packages/db`, and future packages).
  New runtime dependencies that fall outside this workspace model require explicit discussion
  before being added.

## Development Workflow

- A new or changed endpoint MUST be checked against the OpenAI OpenAPI spec for schema parity
  before merging (Principle I).
- A change to worker or scheduling logic MUST include a test or manual verification demonstrating
  that a live request is still served promptly while a batch job is running (Principle IV).
- A database schema change MUST ship with its Alembic migration in the same change (Principle III,
  Principle V).

- Frontend changes MUST pass Biome checks, the TypeScript type check, and the frontend tests
  before merging.

## Governance

This constitution supersedes other project conventions and prior practice when they conflict.
Amendments are made by editing this file and bumping the version according to semantic versioning: MAJOR for a
backward-incompatible removal or redefinition of a principle, MINOR for a new principle or
materially expanded guidance, PATCH for clarifications or wording fixes with no semantic change.
Every feature spec and plan SHOULD state its compliance with these principles, with particular
attention to Principle II (local-only inference) and Principle IV (live-request priority); any
deviation MUST be called out explicitly and justified in the relevant spec or plan rather than left
implicit.

**Version**: 1.3.0 | **Ratified**: 2026-10-03 | **Last Amended**: 2026-10-03

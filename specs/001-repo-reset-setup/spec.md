# Feature Specification: Repository Reset & Foundation Setup

**Feature Branch**: `cleanup`

**Created**: 2026-10-03

**Status**: Draft

**Input**: User description: "I changed all the conventions of the repository, but the code is old so mismatching. We restart the project from 0 (including db and already existing apis), so I want a full cleanup and setup of the repo: reset to zero, set everything up to be ready (a basic health endpoint and an empty database) and prepare all the tooling (pre-commit etc.). Only the folder structure is correct (api in apps, db in packages); a later llm package will handle the Ollama server."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Clean slate with no legacy code (Priority: P1)

As the maintainer, I want every piece of pre-convention code, database schema, migration, stored data, and infrastructure leftover removed, so that all future work starts from the new conventions rather than being constrained by (or mixed with) code that violates them.

**Why this priority**: Everything else builds on a clean base. Leftover legacy code would conflict with the new conventions and the quality gates in Story 3.

**Independent Test**: Inspect the repository after the work: the only application code left is the minimal foundation described in Stories 2 and 3; no legacy endpoints, models, migrations, storage code, sample data, or unused infrastructure definitions remain.

**Acceptance Scenarios**:

1. **Given** the repository contains the old chat, completions, files, batches, and storage code, **When** the reset is complete, **Then** none of those features remain in source, and none are reachable through the running server.
2. **Given** the old database schema and migration history, **When** the reset is complete, **Then** no legacy tables or migration history remain, and the database starts empty.
3. **Given** old sample/runtime data and infrastructure definitions that no longer match the project's direction, **When** the reset is complete, **Then** they are removed (or replaced by definitions that match the new direction).
4. **Given** the agreed folder structure (the API application under `apps`, the database package under `packages`), **When** the reset is complete, **Then** that structure is unchanged.

---

### User Story 2 - Runnable foundation: health endpoint and empty database (Priority: P1)

As a developer, I want to start the server from a fresh checkout and immediately get a successful health response, backed by an empty but fully initialised database, so I have a verified, working base to add the first real feature to.

**Why this priority**: This is the minimum working system and proves the foundation (server, configuration, database, migrations, tests) is wired correctly end to end.

**Independent Test**: From a fresh clone, follow the README setup steps, start the server, and request the health endpoint; it returns a success response. The database file exists, is initialised via the migration tooling, and contains no application tables' data.

**Acceptance Scenarios**:

1. **Given** a fresh checkout with setup steps followed, **When** the server is started, **Then** it starts without errors.
2. **Given** the server is running, **When** a client requests the health endpoint under the versioned path prefix, **Then** it receives a success response indicating the service is up.
3. **Given** no database exists yet, **When** the developer applies migrations, **Then** an empty database is created through the migration tooling, with the migration baseline in place and ready for the first real schema change.
4. **Given** configuration is supplied through environment settings, **When** the developer copies the provided example settings file, **Then** the server and database tooling run with no hardcoded hosts, paths, or connection strings.
5. **Given** an unknown path or invalid request, **When** it is sent to the server, **Then** the error response uses the project's standard error format rather than the framework default.

---

### User Story 3 - Automated quality gates and test harness (Priority: P2)

As a developer, I want linting, formatting, strict type checking, and tests wired up and enforced before every commit, so that all new code automatically conforms to the repository conventions without manual policing.

**Why this priority**: With no CI, local gates are the only enforcement of the conventions. Needed before real features land, but it relies on the foundation from Stories 1–2 to have something to check.

**Independent Test**: Run the pre-commit hooks and the test suite on the clean repository; all pass. Then stage a file with a lint, format, or typing violation and attempt to commit; the commit is blocked.

**Acceptance Scenarios**:

1. **Given** the hooks are installed, **When** a commit contains code violating lint, format, or strict typing rules, **Then** the commit is rejected with a clear message.
2. **Given** the hooks are installed, **When** a commit contains conforming code, **Then** the commit succeeds.
3. **Given** the clean repository, **When** the test suite is run, **Then** it passes, including a test for the health endpoint that validates the response against the vendored reference API specification where applicable, using an isolated, throwaway in-memory database per test.
4. **Given** the integration-test marker, **When** the default test run is executed, **Then** tests requiring a real local model server are excluded.

---

### User Story 4 - Workspace ready for the upcoming model-server package (Priority: P3)

As the maintainer, I want the workspace and documentation set up so that adding the planned LLM package (which will handle the Ollama server) later is a drop-in addition, without pre-building anything for it now.

**Why this priority**: Only a documentation/structure concern; nothing is built ahead of need.

**Independent Test**: Read the README and workspace configuration: setup, run, test, and migration instructions are accurate and work as written; no empty placeholder LLM package or speculative scaffolding exists.

**Acceptance Scenarios**:

1. **Given** the README, **When** a new developer follows it step by step, **Then** they reach a running server and a passing test suite without undocumented steps.
2. **Given** the workspace, **When** a new package is later added, **Then** the existing configuration accommodates it without restructuring.

---

### Edge Cases

- A developer starts the server before applying migrations: the health endpoint should still respond, or the failure should clearly point to the missing migration step.
- The database location does not exist yet (fresh checkout): it is created on first migration rather than failing obscurely.
- A required environment setting is missing: startup fails with a message naming the missing setting, or a documented default applies.
- Previously generated local artifacts (old virtual environment lock state, old local database or data folders) exist in a developer's working copy: they are ignored by version control and safe to delete.
- Pre-commit hooks run on a commit that touches only non-code files (docs, specs): hooks complete quickly and do not fail.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The repository MUST contain no code, schemas, migrations, tests, sample data, or documentation describing the legacy chat, completions, files, batches, or storage features.
- **FR-002**: The repository MUST retain the existing top-level structure: API application under `apps`, database package under `packages`, with the workspace configuration listing exactly the packages that exist.
- **FR-003**: The server MUST expose a health endpoint under the versioned path prefix that returns a success response while the service is running.
- **FR-004**: The server MUST report errors (including unknown routes and validation failures) in the project's standard error envelope, never the framework's default error shape.
- **FR-005**: The database package MUST provide an initialised, empty database, created through the migration tooling, with a baseline migration state ready for the first schema change. It MUST include the complete database plumbing (settings, async engine/session for the API, sync engine/session for migrations and future workers, declarative base) but no models or repositories yet.
- **FR-006**: All configuration (database location, etc.) MUST be read from environment settings using the project's prefix, with a committed example settings file containing placeholder values; real settings files MUST be ignored by version control.
- **FR-007**: The database engine configuration MUST target the project's chosen local, file-based database, replacing the legacy network-database configuration; legacy network-database infrastructure definitions MUST be removed.
- **FR-008**: The server MUST NOT include a shared outbound model-server HTTP client yet; it is added with the first feature that calls the model server.
- **FR-009**: The server MUST emit structured, one-object-per-line JSON logs.
- **FR-010**: Pre-commit hooks MUST follow standard practice: pinned hook repositories, run only on staged files of the relevant file types (so a docs-only commit skips the Python hooks), and block the commit on any failure. They MUST cover linting, formatting, strict type checking, and basic file hygiene.
- **FR-011**: Linting and formatting MUST use a single tool at the project's line-length of 88 characters, applied to all Python files including migrations; no additional linters or formatters may be introduced. Strict type checking applies to all Python except generated migration code.
- **FR-012**: A test harness MUST exist with shared fixtures for a throwaway in-memory database per test, an API test client, and settings overrides, plus a marker separating real-model-server integration tests from the default run.
- **FR-013**: The reference OpenAI API specification MUST be vendored in the repository at `openai-spec/openapi.yaml` (it is not currently present) and be usable by contract tests.
- **FR-014**: The test suite MUST include a test of the health endpoint and the standard error envelope, and MUST pass on the clean repository.
- **FR-015**: The README MUST describe accurate, working steps to set up, configure, migrate, run, and test the project, and MUST NOT describe removed features.
- **FR-016**: The dependency lockfile and workspace metadata MUST be regenerated to reflect only the dependencies actually required by the retained code.
- **FR-017**: No placeholder worker, LLM, service-layer, or other speculative package/module MUST be created; only what Stories 1–3 require.

### Key Entities

- **Health status**: The service's reported up/running state, returned by the health endpoint.
- **Error envelope**: The standard error response shape (message, type, param, code) used for all error responses.
- **Migration baseline**: The empty starting state of the database schema against which all future migrations are generated.
- **Settings**: Environment-provided configuration values (prefixed, with a committed example file).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new developer can go from a fresh clone to a running server returning a successful health response in under 10 minutes by following only the README.
- **SC-002**: 100% of legacy feature code, data, migrations, and infrastructure definitions are absent from the repository after the work (verified by inspection against the removal list in the plan).
- **SC-003**: Pre-commit hooks and the full default test suite pass on the clean repository with zero errors and zero suppressed type-check ignores lacking a justification.
- **SC-004**: 100% of committed attempts containing a lint, format, or strict-typing violation are blocked by the hooks.
- **SC-005**: The default test run completes in under 30 seconds and requires no external services.
- **SC-006**: Applying migrations on a fresh checkout yields an empty database in a single command with no manual steps.

## Assumptions

- The "users" of this feature are the maintainer and future contributors; there is no end-user-visible behaviour beyond the health endpoint.
- The project's conventions document and constitution are the source of truth for the target conventions (local file-based database, versioned `/v1` routes, standard error envelope, prefixed environment settings, JSON logging, strict typing, single lint/format tool).
- The health endpoint is an additional endpoint with no OpenAI counterpart (verified against the vendored spec); additional endpoints are allowed because they cannot break OpenAI SDK clients. It is mounted under `/v1` per the routing convention and follows standard industry conventions for health checks.
- Legacy data (existing database contents, uploaded files, sample data) has no value and need not be migrated or backed up.
- Git history is preserved; the reset is a forward commit on the `cleanup` branch, not a history rewrite.
- No authentication is added (per project conventions).
- The future LLM package will be specified and added in its own feature; this feature creates no scaffolding for it.
- The shared HTTP client for the model server is deferred to the first feature that needs it (YAGNI); resolved in planning.

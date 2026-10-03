---

description: "Task list for Repository Reset & Foundation Setup"
---

# Tasks: Repository Reset & Foundation Setup

**Input**: Design documents from `/specs/001-repo-reset-setup/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/health.md, quickstart.md

**Tests**: Only where they protect logic or contracts (FR-012, FR-014; error envelope, health, migrations). No tests for pure plumbing such as logging or config loading, per CLAUDE.md.

**Organization**: Grouped by user story. Conventions that apply to every task: `mypy --strict` typing, Ruff (line length 88), `X | None`, builtin generics, f-strings, `async def` handlers, minimal comments, absolute imports (`api`, `db`). All dependency changes use `uv add`/`uv remove` (never hand-edit dependency lists). Do NOT commit unless asked.

## Format: `[ID] [P?] [Story] Description`

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Root tooling config: keep workspace members `apps/api` and `packages/db`; add dev tools with `uv add --dev ruff mypy pytest pytest-asyncio httpx pre-commit jsonschema pyyaml types-PyYAML types-jsonschema`; add to root `pyproject.toml` `[tool.ruff]` (`line-length = 88`, lint select `E,F,I,UP,B,ASYNC,RUF`; applies to all Python incl. Alembic), `[tool.mypy]` (`strict = true`, `exclude = ["packages/db/alembic/"]` with a comment: generated code), and `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`, marker `integration`, `addopts = "-m 'not integration'"`, `testpaths = ["apps/api/tests", "packages/db/tests"]`)
- [X] T002 [P] API dependencies via `uv`: `uv remove --project apps/api asyncpg httpx python-multipart rich` (and any other unused), then ensure only `db`, `fastapi`, `uvicorn` (plain, no `[standard]`) remain via `uv add --project apps/api`; `pydantic-settings` moves to `db` (T003); `uv.lock` regenerated at the end of T003
- [X] T003 [P] DB dependencies via `uv`: `uv remove --project packages/db psycopg` (and other Postgres drivers); `uv add --project packages/db alembic aiosqlite pydantic-settings "sqlalchemy[asyncio]"`; then run `uv sync` to regenerate `uv.lock`
- [X] T004 [P] Create `.env.example` at repo root containing `LOCAL_LLM_DB_PATH=data/local_llm.db`; confirm `.env` and `/data/` are already in `.gitignore` (no `.gitignore` change expected)

---

## Phase 2: User Story 1 - Clean slate with no legacy code (Priority: P1)

**Goal**: Remove all legacy features, schema, data and infra; keep the `apps/` / `packages/` structure.

**Independent Test**: `git ls-files` shows none of the removed paths; quickstart outcome 6.

- [X] T005 [US1] Delete legacy API feature packages: `apps/api/src/api/batches/`, `chat/`, `completions/`, `config/`, `files/`, `storage/` and `apps/api/log_config.yaml`
- [X] T006 [US1] Delete legacy DB code: `packages/db/src/db/models/files.py`, `packages/db/src/db/models/batch_input_file_chunks.py`, all three files in `packages/db/alembic/versions/`, and `packages/db/alembic/README`
- [X] T007 [P] [US1] Delete `docker-compose.yaml` and, from disk, the gitignored `config/` and `data/` contents (old pgAdmin servers.json, `batch_input_files/`, `test.jsonl`)
- [X] T008 [P] [US1] Reduce `apps/api/README.md` and `packages/db/README.md` to a one-line description each (no feature descriptions)

**Checkpoint**: Repo contains no legacy feature code (it will not run until Phase 3).

---

## Phase 3: User Story 2 - Runnable foundation: health endpoint and empty database (Priority: P1) 🎯 MVP

**Goal**: Server starts, `GET /v1/health` returns `{"status": "ok"}`, errors use the OpenAI envelope, empty SQLite DB created via Alembic.

**Independent Test**: quickstart outcomes 1–3.

### Tests for User Story 2

- [X] T009 [P] [US2] Create `apps/api/tests/conftest.py` with fixtures: in-memory `sqlite+aiosqlite:///:memory:` engine (`StaticPool`) with `Base.metadata.create_all` per test, an `AsyncSession` fixture, a settings override (monkeypatching `LOCAL_LLM_*` env for `db.config`; relies on settings/engines being built lazily, see T014/T015), an `httpx.AsyncClient` over `ASGITransport(app=app)` with `get_session` overridden, and an `openai_schema` helper that loads `openai-spec/openapi.yaml` once and validates a body against a named component schema (see T011)
- [X] T010 [P] [US2] Create `apps/api/tests/test_health.py`: `GET /v1/health` returns 200 and `{"status": "ok"}`
- [X] T011 [P] [US2] Create `apps/api/tests/test_errors.py`: unknown route → 404, wrong method → 405, invalid request → 422 (use a temporary test-only route with a typed query param), per `contracts/health.md` table; each body has all four keys `message`, `type`, `param`, `code` and validates against `components.schemas.ErrorResponse` using `jsonschema` with `{"$ref": "#/components/schemas/ErrorResponse", "components": spec["components"]}` as the schema (so `$ref`s resolve)
- [X] T012 [P] [US2] Create `packages/db/tests/test_migrations.py`: run `alembic upgrade head` (programmatic `alembic.command`, temp-file DB via `LOCAL_LLM_DB_PATH`) and assert the file exists and contains only the `alembic_version` table

### Implementation for User Story 2

- [X] T013 [P] [US2] Vendor the OpenAI OpenAPI document: download `openapi.yaml` from github.com/openai/openai-openapi (`curl -L`) into `openai-spec/openapi.yaml`; confirm it contains `ErrorResponse` and `Error` schemas and defines no health endpoint; record source URL, commit SHA and download date in `openai-spec/README.md`
- [X] T014 [P] [US2] Rewrite `packages/db/src/db/config.py` as a `pydantic-settings` `BaseSettings` (`env_prefix="LOCAL_LLM_"`, `env_file=".env"`) with `db_path: Path = Path("data/local_llm.db")` (relative to the working directory; run from repo root), plus helpers returning the async URL `sqlite+aiosqlite:///<db_path>` and the sync URL `sqlite:///<db_path>`, creating the parent directory. Build settings lazily (cached getter, not a module-level instance) so tests can override env
- [X] T015 [US2] Rewrite `packages/db/src/db/engine.py`: async engine + `async_sessionmaker` + `get_session` (API) and sync engine + `sessionmaker` (Alembic/future workers), all from the T014 URLs, created lazily via factory functions (nothing at import time, so importing `db.engine` never touches the filesystem) (no `pool_pre_ping`, no Postgres); remove the usage comments. No models or repositories. Review `packages/db/src/db/__init__.py` (and `apps/api/src/api/__init__.py`) and drop any legacy re-exports. Reduce `packages/db/src/db/models/base.py` to a bare `DeclarativeBase` subclass `Base` and update `packages/db/src/db/models/__init__.py` to export only `Base`
- [X] T016 [US2] Update `packages/db/alembic/env.py` to use the sync engine/URL from T014/T015 and `Base.metadata` (standard env.py, no `run_sync`); update `alembic/script.py.mako` to emit modern typing (`X | None`, builtin generics) so generated migrations pass Ruff; keep `alembic.ini`; run `uv run alembic -c packages/db/alembic.ini revision --autogenerate -m "baseline"`, review that `upgrade`/`downgrade` are empty (`pass`), and run `uv run ruff format`/`ruff check --fix` on the new migration (not mypy)
- [X] T017 [US2] Decision recorded (no API settings module yet): nothing in `apps/api` reads configuration, so do not create `apps/api/src/api/settings.py`. Config lives in `db.config` only; the T009 settings-override fixture monkeypatches env for it
- [X] T018 [P] [US2] Create `apps/api/src/api/logging.py`: `JsonFormatter(logging.Formatter)` emitting one JSON object per line with `timestamp`, `level`, `logger`, `message` and `exc_info` when present, plus `configure_logging()` routing root and `uvicorn*` loggers through it
- [X] T019 [P] [US2] Create `apps/api/src/api/errors.py`: pydantic models `Error` (`message: str`, `type: str`, `param: str | None`, `code: str | None`) and `ErrorResponse` (`error: Error`) with `extra="ignore"`; handlers registered by `register_error_handlers(app)` for `StarletteHTTPException` (any status: `code` = `http.HTTPStatus(status).phrase` lowercased with non-alphanumerics replaced by `_`, e.g. 404 → `not_found`, 405 → `method_not_allowed`, and `null` if the status is not a standard `HTTPStatus`; `type` = `invalid_request_error` for 4xx, `server_error` for 5xx), `RequestValidationError` (status 422 kept, not remapped; `invalid_request_error`, `code` derived like any other status, i.e. `unprocessable_content`; `param` = first error's last `loc` element), and unhandled `Exception` (500, `server_error`, `code` null); responses are `JSONResponse` of the envelope with all four keys always present
- [X] T020 [US2] Create `apps/api/src/api/health/schemas.py` (`HealthResponse` with `status: Literal["ok"]`, `extra="ignore"`) and rewrite `apps/api/src/api/health/router.py`: `router = APIRouter()`, `@router.get("/health")` `async def get_health() -> HealthResponse`; drop the `Request` arg. Export from `apps/api/src/api/health/__init__.py`
- [X] T021 [US2] Rewrite `apps/api/src/api/app.py`: call `configure_logging()`, create `FastAPI()` (no lifespan), `register_error_handlers`, mount `health` router on `APIRouter(prefix="/v1")`, include it. No `/health` at root
- [X] T022 [US2] Run `uv run alembic -c packages/db/alembic.ini upgrade head` and `uv run pytest`, and start `uv run uvicorn api.app:app` to curl `/v1/health` and `/v1/nope`; fix failures

**Checkpoint**: MVP works; US1 + US2 together are a runnable clean repo.

---

## Phase 4: User Story 3 - Automated quality gates and test harness (Priority: P2)

**Goal**: Pre-commit enforces Ruff + mypy strict; default tests pass without external services.

**Independent Test**: quickstart outcome 5.

- [X] T023 [US3] Create `.pre-commit-config.yaml` following standard practice: `astral-sh/ruff-pre-commit` pinned to the locked ruff version (`ruff-check` with `--fix --exit-non-zero-on-fix`, and `ruff-format`) on staged Python files (including Alembic); `pre-commit-hooks` (`trailing-whitespace`, `end-of-file-fixer`, `check-yaml`, `check-toml`, `check-merge-conflict`, `check-added-large-files` with `--maxkb` above the vendored spec's size) excluding `^openai-spec/`; and one `repo: local` mypy hook (`language: system`, `entry: uv run mypy`, `types: [python]`, filenames passed, `exclude: ^packages/db/alembic/`)
- [X] T024 [US3] Run `uv run ruff format .`, `uv run ruff check --fix .`, and `uv run mypy` (config from T001, which already excludes `alembic/`); fix all findings in non-generated code without adding unexplained `# type: ignore`
- [X] T025 [US3] Run `uv run pre-commit install` then `uv run pre-commit run --all-files`; confirm pass; also stage only a markdown change and confirm the Python hooks are skipped
- [X] T026 [US3] Verify the gate blocks violations: stage a temporary file with an unused import and a missing type annotation, confirm `pre-commit run` fails, then delete the file (do not commit)
- [X] T027 [P] [US3] Confirm `uv run pytest` excludes `integration`-marked tests by default: add a trivial `@pytest.mark.integration` test in `apps/api/tests/test_integration_marker.py` that is deselected, and `uv run pytest -m integration --collect-only` collects it. Delete this file if a real integration test is not wanted yet (marker stays registered)

---

## Phase 5: User Story 4 - Workspace ready for the upcoming model-server package (Priority: P3)

**Goal**: Accurate README; workspace accommodates future packages with no scaffolding.

**Independent Test**: A new developer follows the README to a running server and passing tests.

- [ ] T028 [US4] Rewrite root `README.md` as a setup guide only: prerequisites (uv, Python 3.14), `uv sync`, `cp .env.example .env`, `uv run pre-commit install`, `uv run alembic -c packages/db/alembic.ini upgrade head`, `uv run uvicorn api.app:app --reload`, `uv run pytest`, and the `LOCAL_LLM_DB_PATH` setting (relative to the working directory, so all commands run from the repo root); no feature descriptions, no mention of removed features
- [ ] T029 [P] [US4] Verify FR-017: confirm no `llm`, `worker`, or `service.py` files exist and that root `pyproject.toml` workspace members list only `apps/api` and `packages/db` (adding a package later needs only a new `members` entry)

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T030 Walk through `specs/001-repo-reset-setup/quickstart.md` from a fresh clone (or `git clean -xdf` of ignored files except `.venv`) and confirm outcomes 1–6; record any deviation by fixing the offending file
- [ ] T031 [P] Check the default `uv run pytest` run time is under 30 s and needs no network/Ollama
- [X] T032 Constitution amendment (Principle I: additional endpoints allowed; Principle V: inference/worker recording only) done as v1.1.0 before implementation; `CLAUDE.md` updated accordingly

---

## Dependencies & Execution Order

- **Phase 1 (Setup)** first: T001 gates T024; T002/T003/T004 are parallel (T002/T003 touch different `pyproject.toml` files but both run `uv`; serialize if `uv.lock` contention occurs).
- **Phase 2 (US1)** before Phase 3: deleting legacy code first avoids mixing old and new files. T005→T006 sequential is not required; T007/T008 are parallel with them.
- **Phase 3 (US2)**: T013, T014, T018, T019 are parallel (different files). T015 depends on T014; T016 on T015; T020 on T019 only for imports (none), T021 on T018–T020 (T017 is a recorded decision, no work); T022 last. Tests T009–T012 are written first and fail until implementation lands (T009 needs T015/T021; T010 needs T021; T011 needs T013 and T019; T012 needs T016).
- **Phase 4 (US3)** after Phase 3, since there must be code to check; T023 can be written earlier but T024–T026 need the code. T027 is parallel.
- **Phase 5 (US4)** after US2 so the README steps can be verified; T029 is parallel.
- **Phase 6** last.

## Parallel Example: User Story 2

```text
T013 vendor spec        T014 db settings
T018 json logging       T019 error envelope   T009–T012 test files
```

## Implementation Strategy

1. **MVP** = Phases 1–3 (US1 + US2): clean repo that serves `/v1/health` on an empty SQLite DB.
2. Add Phase 4 (gates), then Phase 5 (README), then Phase 6 verification.
3. Stop after each checkpoint to run `uv run pytest`. Commit only when explicitly asked, on the `cleanup` branch, as atomic Conventional Commits.

# Research: Repository Reset & Foundation Setup

## 1. Health endpoint path and body
- **Decision**: `GET /v1/health` → `200 {"status": "ok"}`. No DB or Ollama check.
- **Rationale**: Matches the existing body; `/v1` mandated for all endpoints. OpenAI defines no health endpoint, so this is an additional endpoint (allowed; follows industry liveness-check convention). A liveness check that also touches the DB would make it flaky for no present need.
- **Alternatives**: `/health` at root (violates routing rule); readiness probe checking DB (YAGNI).

## 2. Shared Ollama HTTP client (spec FR-008)
- **Decision**: Defer. No lifespan client in this feature.
- **Rationale**: YAGNI is the repo's top rule and nothing calls Ollama yet. Ollama access will live in a future `llm` package, planned separately. Spec FR-008 updated accordingly.
- **Alternatives**: Add now, unused (speculative).

## 3. Database: SQLite driver and location
- **Decision**: `db` provides both engines: async (`sqlite+aiosqlite`, session factory, `get_session`) for the API, and sync (`sqlite`, sessionmaker) for Alembic and future workers. Both are built from the single `LOCAL_LLM_DB_PATH`. No models or repositories yet. Path from `LOCAL_LLM_DB_PATH`, default `data/local_llm.db` (relative to repo root; parent directory created on demand). `data/` stays gitignored.
- **Rationale**: Both are certain to be needed (API vs. migrations/workers), so this is not speculative. The sync engine keeps Alembic's `env.py` standard. Removes asyncpg/psycopg.
- **Alternatives**: async-only with `run_sync` in Alembic (non-standard env.py, nothing for workers).

## 4. Empty database / migration baseline
- **Decision**: Delete all existing migrations. Generate a single baseline with `alembic revision --autogenerate -m "baseline"` against empty metadata; it will be an empty `upgrade`/`downgrade`. Keep it so `alembic upgrade head` creates the DB file and version table, and the first real feature autogenerates against a known head.
- **Rationale**: Satisfies FR-005/SC-006 literally. Old migrations hold Postgres-specific schemas (`init_schemas`) and cannot apply to SQLite.
- **Alternatives**: no baseline (first feature's migration would double as the baseline; DB can't be initialised now).

## 5. Settings
- **Decision**: `pydantic-settings` `BaseSettings` with `env_prefix="LOCAL_LLM_"`, `.env` file. Fields now: `db_path` only, in `db.config`. Model-server settings belong to the future `llm` package. `.env.example` lists `LOCAL_LLM_DB_PATH`.
- **Rationale**: Only add config that is consumed. The API reads nothing itself yet, so it gets no settings module until it does; each package owns its own settings.
- **Alternatives**: single shared settings package (new workspace package needs approval, YAGNI).

## 6. Error envelope
- **Decision**: `api/errors.py` defines an `ErrorResponse`/`Error` pair named per OpenAI's schema and registers handlers for `StarletteHTTPException`, `RequestValidationError`, and unhandled `Exception`. Mapping for generic/non-OpenAI errors follows standard HTTP semantics: `code` = snake_case HTTP reason for any HTTPException (404 → `not_found`, 405 → `method_not_allowed`), `type="invalid_request_error"` for 4xx; OpenAI-defined endpoints will follow OpenAI's documented behavior instead (e.g. 400 for malformed requests). Non-OpenAI endpoints are not remapped: validation failures keep FastAPI's 422 with `code` = `HTTPStatus(422).phrase` snake_cased (`unprocessable_content`), `invalid_request_error`, `param` = first offending field; 500 → `server_error`.
- **Rationale**: Only the envelope shape is OpenAI-mandated here; status/code for non-OpenAI endpoints follow standard HTTP. The 422→400 remap belongs to the first OpenAI-defined endpoint's feature.
- **Alternatives**: leaving FastAPI's `{"detail": ...}` (forbidden by CLAUDE.md).

## 7. Logging
- **Decision**: `api/logging.py` with a `JsonFormatter(logging.Formatter)` (keys: timestamp, level, logger, message, plus `exc_info`), configured once at app creation; uvicorn loggers routed through it. Delete `log_config.yaml`.
- **Rationale**: Stdlib only per CLAUDE.md.

## 8. Tooling
- **Decision**: Root `pyproject.toml` holds `[tool.ruff]` (line-length 88; rule set `E,F,I,UP,B,ASYNC,RUF`), `[tool.mypy] strict = true`, `[tool.pytest.ini_options]` (asyncio_mode auto, `integration` marker, default `-m "not integration"`). Dev deps in a root `[dependency-groups] dev`. `.pre-commit-config.yaml` follows industry practice: `astral-sh/ruff-pre-commit` (pinned to the locked ruff version; `ruff-check --fix --exit-non-zero-on-fix` and `ruff-format`) on staged Python files including Alembic; a local `uv run mypy` hook (`types: [python]`, filenames passed, `exclude: ^packages/db/alembic/`) so mypy sees workspace packages; and `pre-commit-hooks` (trailing-whitespace, end-of-file-fixer, check-yaml, check-toml, check-merge-conflict, check-added-large-files with a limit above the vendored spec size), excluding `openai-spec/`. Mypy config excludes `alembic/` too, so a bare `uv run mypy` matches the hook. `script.py.mako` is updated to emit modern typing so generated migrations pass Ruff. Install with `uv run pre-commit install`.
- **Rationale**: Hooks only see staged files of matching types, so a README-only commit is near-instant; `ruff` alone replaces black/isort/flake8 (`I` = import sorting). Alembic code is linted/formatted but not type-checked (generated, logic not edited).
- **Alternatives**: all-local hooks (version drift risk is handled by pinning rev to the lock); mypy hook running on the whole tree every commit (slow, ignores staged files).

## 9. Vendored OpenAI spec — currently missing
- **Finding**: `/openai-spec/openapi.yaml` does not exist in the repo, though CLAUDE.md and spec FR-013 assume it ("remain vendored").
- **Decision**: Download OpenAI's published OpenAPI document (github.com/openai/openai-openapi, `openapi.yaml`) into `openai-spec/openapi.yaml` and commit it, recording source URL, commit SHA and date in `openai-spec/README.md`. Spec FR-013 reworded to "MUST be vendored".
- **Rationale**: Contract tests (error envelope here, every endpoint later) need it.
- **Alternatives**: defer until first OpenAI-shaped endpoint (the error envelope is OpenAI-shaped and in scope now, so no).

## 10. Contract test approach
- **Decision**: `jsonschema` + `pyyaml`. A test helper loads the spec once and validates a body against `{"$ref": "#/components/schemas/ErrorResponse", "components": spec["components"]}` so `$ref`s resolve inside the document. Health has no OpenAI counterpart, so it gets a plain behavior test, not a contract test.
- **Rationale**: `ErrorResponse` is a component schema with no matching route, so operation-based validators like `openapi-core` don't fit; this stays small and reusable for later endpoints' response models.
- **Alternatives**: `openapi-core` (operation-oriented, heavy for a schema-only check).

## 11. Test database fixture
- **Decision**: `conftest.py` in `apps/api/tests` builds an in-memory `sqlite+aiosqlite` engine with `StaticPool`, runs `Base.metadata.create_all`, and overrides `get_session`.  `get_session` is real plumbing the first DB-backed route will use, so it is implemented now. Migrations are covered by `packages/db/tests/test_migrations.py` (temp file DB). No tests for logging or config loading (plumbing, per practical-testing convention).
- **Rationale**: Spec requirement; minimal.

## 12. Cleanup of untracked/ignored artifacts
- **Decision**: Delete `data/` and `config/` contents (gitignored, old Postgres/pgAdmin and batch files) and the stale `.venv` re-sync via `uv sync`; regenerate `uv.lock`.

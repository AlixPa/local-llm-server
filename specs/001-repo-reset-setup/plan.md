# Implementation Plan: Repository Reset & Foundation Setup

**Branch**: `cleanup` | **Date**: 2026-10-03 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-repo-reset-setup/spec.md`

## Summary

Delete all legacy feature code, the Postgres schema/migrations, sample data and Postgres
docker-compose, then rebuild the minimum foundation under the new conventions: a FastAPI app
with `GET /v1/health`, the OpenAI error-envelope handlers, JSON logging, `pydantic-settings`
config (`LOCAL_LLM_` prefix), the full SQLite plumbing in `packages/db` (async + sync engines,
session helpers, `Base`, no models/repositories) with an empty Alembic baseline, a pytest
harness, the vendored OpenAI spec, and pre-commit (Ruff + mypy strict).
Nothing is scaffolded for the future `llm` or worker packages.

## Technical Context

**Language/Version**: Python >=3.14 (`.python-version` = 3.14)

**Primary Dependencies**: FastAPI, uvicorn (api); pydantic-settings, SQLAlchemy[asyncio],
aiosqlite, Alembic (db). Dev: ruff, mypy, pytest, pytest-asyncio, httpx, pre-commit,
jsonschema + pyyaml (contract tests), types-PyYAML, types-jsonschema. Removed: asyncpg, psycopg,
python-multipart, rich, httpx as a runtime dep. All changes via `uv add`/`uv remove`.

**Storage**: SQLite file (default `data/local_llm.db`, `LOCAL_LLM_DB_PATH`), no tables yet

**Testing**: pytest + pytest-asyncio, `httpx.AsyncClient` over ASGI transport, in-memory SQLite
per test, `integration` marker excluded by default

**Target Platform**: Single local machine (macOS/Linux), no containers

**Project Type**: uv workspace — web service (`apps/api`) + library (`packages/db`)

**Performance Goals**: Default test run < 30 s; none for runtime

**Constraints**: mypy --strict, Ruff line length 88, no CI (pre-commit is the gate), YAGNI

**Scale/Scope**: ~10 source files total after reset

## Constitution Check

| Principle | Status | Note |
|-----------|--------|------|
| I. OpenAI-compatible surface | PASS | Error envelope matches OpenAI. `/v1/health` is an additional endpoint with no OpenAI counterpart (allowed by constitution v1.1.0). |
| II. Local-only inference | PASS | No inference code in this feature. |
| III. Lightweight, SQLite, Alembic | PASS | Postgres removed; SQLite + Alembic baseline. |
| IV. Live priority over batch | N/A | No batch or live inference yet. |
| V. State via SQLite | PASS | DB initialised; usage tables arrive with the first inference feature. Health records nothing. |

Post-design re-check: PASS, no change.

## Project Structure

### Documentation (this feature)

```text
specs/001-repo-reset-setup/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── health.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
.pre-commit-config.yaml          # new
.env.example                     # new
.gitignore                       # unchanged if `.env` and `/data/` already ignored
pyproject.toml                   # root: ruff, mypy, pytest config; dev dependency group
README.md                        # rewritten
openai-spec/openapi.yaml         # new (vendored)
openai-spec/README.md            # source URL, commit SHA, download date
apps/api/
├── pyproject.toml
├── README.md                    # one line
├── src/api/
│   ├── app.py                   # app, lifespan-free, handlers, router include
│   ├── errors.py                # OpenAI error envelope + exception handlers
│   ├── logging.py               # JSON Formatter + setup
│   └── health/
│       ├── router.py
│       └── schemas.py
└── tests/
    ├── conftest.py
    ├── test_health.py
    └── test_errors.py
packages/db/
├── pyproject.toml
├── README.md                    # one line
├── alembic.ini
├── alembic/{env.py,script.py.mako,versions/baseline}
├── src/db/
│   ├── config.py                # DB settings (LOCAL_LLM_DB_PATH)
│   ├── engine.py                # async + sync engines, session factories, get_session
│   └── models/base.py           # DeclarativeBase only
└── tests/
    └── test_migrations.py       # upgrade head on empty DB succeeds
```

Deleted: `apps/api/src/api/{batches,chat,completions,config,files,storage}`,
`apps/api/log_config.yaml`, `packages/db/src/db/models/{files,batch_input_file_chunks}.py`,
all three existing Alembic versions, `docker-compose.yaml`, `config/`, `data/` contents.

**Structure Decision**: Keep the existing feature-folder layout. `health/` is the only feature
folder; app-wide plumbing (`errors`, `logging`) are flat modules in `api/`. The API has no settings
module yet: nothing in it reads configuration; `db.config` owns `LOCAL_LLM_DB_PATH`.
Per-package `tests/` with a flat layout, per CLAUDE.md; `conftest.py` only where fixtures are shared (`apps/api/tests` now; `packages/db/tests` gets one when it needs shared fixtures).

## Complexity Tracking

No constitution violations to justify.

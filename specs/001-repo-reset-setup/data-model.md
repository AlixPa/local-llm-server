# Data Model: Repository Reset & Foundation Setup

## Database

No application tables. The schema consists of:

- Async and sync engines/session factories in `db.engine`, built from one SQLite URL.
- `DeclarativeBase` subclass `Base` in `db.models.base` with empty metadata (the target for all future autogenerate runs).
- One Alembic baseline revision (empty upgrade/downgrade). After `alembic upgrade head` the SQLite file contains only Alembic's `alembic_version` table.

## API-visible shapes

| Name | Fields | Notes |
|------|--------|-------|
| `HealthResponse` (local-only) | `status: Literal["ok"]` | No OpenAI counterpart. |
| `Error` | `message: str`, `type: str`, `param: str \| None`, `code: str \| None` | OpenAI schema name `Error`; all four fields always present in the body. |
| `ErrorResponse` | `error: Error` | OpenAI schema name `ErrorResponse`. |

## Settings

| Variable | Used by | Default |
|----------|---------|---------|
| `LOCAL_LLM_DB_PATH` | `db` (read via `db.config`; the API gets the engine from `db`) | `data/local_llm.db` |

No state transitions.

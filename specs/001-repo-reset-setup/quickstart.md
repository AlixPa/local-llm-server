# Quickstart: validating the reset

Prerequisites: `uv`, Python 3.14.

```sh
uv sync
cp .env.example .env
uv run pre-commit install
uv run alembic -c packages/db/alembic.ini upgrade head   # creates the empty SQLite DB
uv run uvicorn api.app:app --port 8000
```

Expected outcomes:

1. `curl localhost:8000/v1/health` → `200 {"status":"ok"}` (see [contracts/health.md](contracts/health.md)).
2. `curl -i localhost:8000/v1/nope` → `404` with the error envelope, not `{"detail": ...}`.
3. The DB file at `LOCAL_LLM_DB_PATH` exists and contains only `alembic_version`.
4. `uv run pytest` passes in under 30 s with no external services.
5. `uv run pre-commit run --all-files` passes; staging a file with a lint, format or typing error and committing is blocked.
6. `git ls-files` shows no `batches`, `chat`, `completions`, `files`, `storage` directories, no `docker-compose.yaml`, and `openai-spec/openapi.yaml` is present.

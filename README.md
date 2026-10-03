# local-llm-server

Prerequisites: [uv](https://docs.astral.sh/uv/), Python 3.14, and
[Ollama](https://ollama.com/) running locally. Run every command from the repo root.

```sh
ollama pull qwen3.5:9b
uv sync
cp .env.example .env
uv run pre-commit install
uv run alembic -c packages/db/alembic.ini upgrade head
uv run uvicorn api.app:app --reload
uv run pytest
```

## Frontend

Prerequisites: Node 22+ and [pnpm](https://pnpm.io/) (via `corepack enable`). Run from
`apps/web`, with the API running on port 8000.

```sh
pnpm install
cp .env.example .env
pnpm dev
pnpm check && pnpm typecheck && pnpm test
pnpm gen:api   # regenerate src/api/schema.d.ts after an endpoint change
               # (reads VITE_LOCAL_LLM_API_URL from your shell, not from .env)
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_LOCAL_LLM_API_URL` | `http://localhost:8000` | API origin for the frontend (`apps/web/.env`) |
| `LOCAL_LLM_DB_PATH` | `data/local_llm.db` | SQLite file, relative to the working directory |
| `LOCAL_LLM_OLLAMA_HOST` | `http://localhost:11434` | Ollama base URL |
| `LOCAL_LLM_OLLAMA_NUM_CTX` | `32768` | Context window (`num_ctx`) sent to Ollama |

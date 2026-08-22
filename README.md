# Running api server

```sh
cd <root>
uv run --project apps/api uvicorn api.app:app --host 0.0.0.0 --port 8000 --log-config apps/api/log_config.yaml --reload-dir apps/api
```

# Ollama

```sh
# Server ollama
ollama serve

# Add models
ollama pull qwen3.5:9b
```

# Alembic

```sh
# Create migration from models
cd packages/db
uv run --project packages/db alembic revision --autogenerate -m "desc"

# Create empty migration file
cd packages/db
uv run --project packages/db alembic revision -m "desc"

# Apply migrations
cd packages/db
uv run --project packages/db alembic upgrade head
```

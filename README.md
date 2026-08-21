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

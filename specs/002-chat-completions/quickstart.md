# Quickstart: validating Chat Completions End to End

## Prerequisites

- Ollama installed and running (`ollama serve`); `ollama pull qwen3.5:9b`.
- `uv sync`; `cd apps/web && pnpm install`.
- `.env` from `.env.example` (adds `LOCAL_LLM_OLLAMA_HOST`, `LOCAL_LLM_OLLAMA_NUM_CTX`).
- `uv run --project packages/db alembic upgrade head`.

## Automated

- `uv run pytest` — mocked-Ollama suite incl. contract tests (fast).
- `uv run pytest -m integration` — real Ollama (non-stream, stream, tools, `n=2`, context overflow, OpenAI SDK drop-in).
- `uv run pre-commit run --all-files`.
- `cd apps/web && pnpm check && pnpm typecheck && pnpm test`.

## Manual end to end

1. Start the API (`uv run uvicorn api.app:app`) and the web app (`pnpm dev`).
2. **SDK drop-in (SC-001)**: with the OpenAI Python SDK, `base_url="http://localhost:8000/v1"`,
   run `models.list()`, then a non-streaming and a streaming `chat.completions.create`; all succeed. A call with `model="gpt-4o"` raises `NotFoundError`.
3. **Playground (US2)**: open `/playground`, pick the model from the selector, send a message with streaming on, cancel one
   mid-way, send again with streaming off and a changed temperature; history lists all three.
4. **Errors (US1.4–5)**: send `audio` option → 400 naming it; stop Ollama and send → 503 with
   OpenAI envelope, shown unchanged in the Playground.
5. **Analytics (US3)**: open `/analytics`; every request above appears (success, cancelled,
   failed) with token counts equal to those returned to the client; summary totals match; browser
   network tab shows no message text in any analytics response (SC-005, SC-006).
6. **Persistence (FR-014)**: restart the API; the analytics list is unchanged.

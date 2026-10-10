# Quickstart: Validating Backend Observability

Prerequisites: Ollama running with `qwen3.5:9b` pulled; `uv sync`; `pnpm install` in `apps/web`.
Contracts: [contracts/observability.md](contracts/observability.md). Entities:
[data-model.md](data-model.md).

## 1. Setup

```bash
uv run --project packages/db alembic upgrade head      # from packages/db: creates the two tables
uv run uvicorn api.app:app --port 8000                 # API
pnpm --dir apps/web dev                                 # UI on http://localhost:5173
```

## 2. Automated checks (done criteria)

```bash
uv run pytest                      # backend, Ollama mocked
uv run ruff check . && uv run ruff format --check . && uv run mypy
pnpm --dir apps/web check && pnpm --dir apps/web typecheck && pnpm --dir apps/web test
```

## 3. Manual scenarios

1. **Live feed (US1, SC-001)** — open the **Observability** tab (empty state explains how to
   generate traffic). From Playground (or `curl`) send a chat completion. A row appears within
   ~1 s as *in progress*, then updates in place to success + status + duration.
2. **Workflow detail (US2, SC-002/003)** — send a *streaming* completion; select the row (≤ 3
   clicks from sending). Lanes Client / API / Ollama show: request received → sent to Ollama →
   received from Ollama (in progress, then full assembled text at stream end) → response
   returned, each with offset and duration. Expand a step for full content; a long one is
   truncated with "show full content".
3. **Errors (US1.3, US2.4–5)** — send an invalid body (`messages` missing): row marked failed with
   the error message, only API-side steps. Send with an unknown `model`: same. Stop Ollama and
   send a request: the Ollama step is highlighted failed, followed by the translated error to the
   caller.
4. **Cancel** — start a long streaming request and abort the client: row ends *canceled*, the
   Ollama step keeps the partial content.
5. **Filter/pause (US3)** — filter by endpoint, by "errors only", by time range; pause, send a
   request, observe "N new" and an unchanged list; resume shows it.
6. **Untracked traffic (FR-013, SC-004)** — load the Analytics tab, hit `/v1/models` and
   `/v1/health`: no new rows. Every chat request (including rejected) has one.
7. **Restart (US4, SC-007)** — send a streaming request, kill the server mid-stream (`kill -9`),
   restart: that row shows *interrupted* (request and its open step), earlier rows intact.
8. **Reconnect (FR-015)** — stop/start the API with the tab open: a "disconnected" indicator
   appears, then clears on its own, and requests sent meanwhile are listed.
9. **Recording failure (FR-014)** — covered by `test_observability_tracing.py` (a repository
   error inside the writer is logged; the chat request still succeeds).
10. **Latency (SC-005)** — compare mean total time and TTFT over ~20 identical short requests
    with the middleware included vs. `TRACKED` emptied temporarily; difference < 5 %.
11. **Scale (SC-006)** — seed ~20k `traced_requests` rows (script in the scratchpad, not
    committed), confirm the feed's first page and a detail open respond in < 200 ms.

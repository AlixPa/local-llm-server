# Quickstart: validating the Responses feature

Prerequisites: Ollama running with the served model pulled (`ollama pull qwen3.5:9b`), `uv sync`,
`pnpm install` in `apps/web`. Commands are run from the repo root.

## 1. Migrate and start

```sh
uv run alembic -c packages/db/alembic.ini upgrade head
uv run uvicorn api.app:app --reload
pnpm --dir apps/web dev          # second terminal, http://localhost:5173
```

Expect the new `response_records` and `response_contents` tables (and no change to the chat tables).

## 2. Endpoint, SDK-style

```sh
curl -s localhost:8000/v1/responses -H 'content-type: application/json' \
  -d '{"model":"qwen3.5:9b","input":"Say hi","instructions":"Be brief."}'
curl -sN localhost:8000/v1/responses -H 'content-type: application/json' \
  -d '{"model":"qwen3.5:9b","input":"Count to 3","stream":true}'
```

Expect a `resp_…` Response object (status `completed`, `usage` present); for the stream, `event:`
frames from `response.created` through `response.completed`, no `[DONE]`. Also run the OpenAI
Python SDK with `base_url=http://localhost:8000/v1`: `client.responses.create(...)` and
`client.responses.create(..., stream=True)` iterate to completion.

Failure checks: unknown model → 404 `model_not_found`; `previous_response_id` set → 400
`unsupported_parameter`; `GET /v1/responses/resp_x` → standard unknown-route error.

## 3. Web app

1. Sidebar shows **Playground → Chat / Responses**, then Analytics and Observability; `/` lands on
   `/playground/chat`; `/playground` alone no longer exists.
2. **Playground → Responses**: send with streaming on (text appears progressively, Cancel works)
   and off; trigger an error (bad model) and see the server message in the history entry.
3. **Analytics**: one table with chat and Responses rows (Endpoint column, no content); filter by
   endpoint, status and date; summary figures follow the filters.
4. **Observability**: the Responses request appears live, in progress then final; filter by
   `/v1/responses` and by status; open its sequence detail (request → Ollama → response).

## 4. Automated gates ("done means")

```sh
uv run pytest                                   # fast suite (Ollama mocked)
uv run pytest -m integration                    # manual, needs Ollama (+ SDK responses tests)
uv run pre-commit run --all-files               # ruff, mypy --strict, biome, tsc
pnpm --dir apps/web check && pnpm --dir apps/web typecheck && pnpm --dir apps/web test
```

Contract coverage to confirm: `validate_contract` on `POST /v1/responses` (success and each error
class), `validate_schema(event, "ResponseStreamEvent")` on every streamed event, and the policy
table test covering all 32 `CreateResponse` properties.

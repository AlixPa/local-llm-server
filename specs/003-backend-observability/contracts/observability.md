# Contract: observability endpoints (non-OpenAI)

Mounted under `/v1/observability`, standard error envelope, standard HTTP semantics (422 on
validation errors). None of these endpoints is tracked (FR-013). They return recorded content
as-is (local, single-user). OpenAI defines nothing under this prefix.

## GET /v1/observability/requests

Query (all optional):

| Param | Type | Meaning |
|---|---|---|
| `limit` | int 1–100, default 20 | page size |
| `after` | int | `id` of the last item of the previous page |
| `endpoint` | string | exact path, e.g. `/v1/chat/completions` |
| `outcome` | `in_progress \| success \| error \| canceled \| interrupted` | repeatable; `errors only` in the UI = `error` |
| `since` / `until` | int (unix seconds) | `started_at` range, inclusive / exclusive |

200 (OpenAI list envelope, newest first):

```json
{
  "object": "list",
  "data": [
    {
      "id": 42,
      "endpoint": "/v1/chat/completions",
      "method": "POST",
      "started_at": 1790000000,
      "started_at_ms": 1790000000123,
      "duration_ms": 3150,
      "http_status": 200,
      "outcome": "success",
      "summary": "qwen3.5:9b · stream",
      "response_id": "chatcmpl-abc123",
      "error_message": null
    }
  ],
  "first_id": 42,
  "last_id": 42,
  "has_more": false
}
```

- Nullable fields are `null`, never omitted. `duration_ms`/`http_status` are `null` while
  `in_progress` (and `http_status` after `interrupted`). A `canceled` request keeps whatever status was already sent (e.g. 200 for a stream), or `null` if none.
- Unknown `after` → 404 `not_found` (same as analytics). Invalid `outcome`/`limit` → 422.
- Empty database/no matches → `data: []`, `first_id`/`last_id` null, `has_more` false.

## GET /v1/observability/requests/{id}

200: the list item above plus the ordered steps.

```json
{
  "id": 42,
  "endpoint": "/v1/chat/completions",
  "method": "POST",
  "started_at": 1790000000,
  "started_at_ms": 1790000000123,
  "duration_ms": 3150,
  "http_status": 200,
  "outcome": "success",
  "summary": "qwen3.5:9b · stream",
  "response_id": "chatcmpl-abc123",
  "error_message": null,
  "steps": [
    {
      "position": 0,
      "kind": "request_received",
      "source": "client",
      "destination": "api",
      "status": "completed",
      "offset_ms": 0,
      "duration_ms": null,
      "content": { "model": "qwen3.5:9b", "messages": [] },
      "error_message": null
    },
    {
      "position": 1,
      "kind": "sent_to_ollama",
      "source": "api",
      "destination": "ollama",
      "status": "completed",
      "offset_ms": 4,
      "duration_ms": null,
      "content": { "model": "qwen3.5:9b", "messages": [], "options": {} },
      "error_message": null
    },
    {
      "position": 2,
      "kind": "received_from_ollama",
      "source": "ollama",
      "destination": "api",
      "status": "completed",
      "offset_ms": 4,
      "duration_ms": 3100,
      "content": { "object": "chat.completion", "choices": [] },
      "error_message": null
    },
    {
      "position": 3,
      "kind": "response_returned",
      "source": "api",
      "destination": "client",
      "status": "completed",
      "offset_ms": 3110,
      "duration_ms": null,
      "content": { "object": "chat.completion", "choices": [] },
      "error_message": null
    }
  ]
}
```

- `kind` ∈ `request_received | sent_to_ollama | received_from_ollama | response_returned | error`;
  `source`/`destination` ∈ `client | api | ollama`; `status` ∈
  `in_progress | completed | failed | canceled | interrupted`.
- `offset_ms` = step start − request start, computed by the API. A step with
  `status: "in_progress"` has `duration_ms: null` and (for `received_from_ollama`) `content: null`.
- `content` is arbitrary JSON (request body, Ollama payload, assembled result, response body, or
  `{"message": "…"}`); the schema declares it as an untyped JSON value.
- Unknown id → 404 `not_found`; non-integer id → 422. Steps carry no `id`; `position` identifies them.

## GET /v1/observability/events

`Content-Type: text/event-stream`. Notification-only; clients re-read state through the two
endpoints above.

```text
event: request.created
data: {"id": 42}

event: request.updated
data: {"id": 42}

: keep-alive
```

- `request.created` — a traced request row was committed. `request.updated` — a step was
  added/finished or the request finished (committed).
- Sent after the corresponding commit, so an immediate refetch observes the change.
- A comment line (`: keep-alive`) is sent about every 15 s. No `[DONE]`; the stream ends only on
  client disconnect or server shutdown. No replay: a client that reconnects must refetch (the
  frontend does this on every `EventSource` `open`).
- Not representable as a typed response in `openapi.json`; the frontend consumes it with
  `EventSource` and does not generate types for it.

## Tracked-endpoint registry (FR-002a decision record)

| Endpoint | Tracked | Steps | Observability tab |
|---|---|---|---|
| `POST /v1/chat/completions` | yes | request received, sent/received per Ollama call, response returned, error | supported |
| `GET /v1/models`, `/v1/analytics/*`, `/v1/health`, `/v1/observability/*` | no | — | n/a |

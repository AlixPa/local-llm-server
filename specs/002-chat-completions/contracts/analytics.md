# Contract: analytics endpoints (non-OpenAI)

Mounted under `/v1`, standard error envelope, standard HTTP semantics (422 on validation
errors). Never returns request or response content.

## GET /v1/analytics/chat-completions

Query: `limit` (int, 1–100, default 20), `after` (string, optional — `id` of the last item of
the previous page).

200 response (OpenAI list envelope):

```json
{
  "object": "list",
  "data": [
    {
      "id": "chatcmpl-abc123",
      "created": 1790000000,
      "model": "qwen3.5:9b",
      "status": "succeeded",
      "stream": true,
      "n": 1,
      "prompt_tokens": 42,
      "completion_tokens": 128,
      "total_tokens": 170,
      "duration_ms": 3150,
      "time_to_first_token_ms": 410,
      "generation_duration_ms": 2600,
      "load_duration_ms": 12,
      "finish_reason": "stop",
      "error_type": null,
      "error_code": null
    }
  ],
  "first_id": "chatcmpl-abc123",
  "last_id": "chatcmpl-abc123",
  "has_more": false
}
```

- `status` ∈ `succeeded | failed | cancelled`. Nullable fields are `null`, never omitted.
- Ordering: newest first. Unknown `after` → 404 `not_found`.
- Empty database → `data: []`, `first_id`/`last_id` null, `has_more` false.

## GET /v1/analytics/chat-completions/summary

200:

```json
{
  "request_count": 10,
  "error_count": 1,
  "prompt_tokens": 420,
  "completion_tokens": 1280,
  "avg_duration_ms": 3000.5,
  "avg_time_to_first_token_ms": 400.0,
  "avg_generation_duration_ms": 2500.0
}
```

Averages are `null` when there is nothing to average. `error_count` counts `failed` only.

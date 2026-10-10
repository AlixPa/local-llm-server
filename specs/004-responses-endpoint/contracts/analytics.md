# Contract: analytics endpoints (non-OpenAI)

Mounted under `/v1`, standard error envelope, standard HTTP semantics (422 on validation errors).
Never returns request or response content. **Replaces** `GET /v1/analytics/chat-completions` and
`GET /v1/analytics/chat-completions/summary` (removed, no backward compatibility).

Filter query parameters (shared by both endpoints, all optional, combined with AND):

| Param | Type | Meaning |
|---|---|---|
| `endpoint` | `/v1/chat/completions` \| `/v1/responses` | only that endpoint |
| `status` | `succeeded` \| `failed` \| `cancelled` | only that status |
| `since` | int (unix seconds) | `created >= since` |
| `until` | int (unix seconds) | `created <= until` |

## GET /v1/analytics/requests

Extra query: `limit` (int 1–100, default 20), `after` (the `id` of the last item of the previous
page; unknown id → 404 `not_found`). Newest first across both endpoints.

```json
{
  "object": "list",
  "data": [
    {
      "id": "resp_9f2c…",
      "endpoint": "/v1/responses",
      "created": 1790000000,
      "model": "qwen3.5:9b",
      "status": "succeeded",
      "stream": true,
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
  "first_id": "resp_9f2c…",
  "last_id": "resp_9f2c…",
  "has_more": false
}
```

Chat rows have the same shape with `id` = `chatcmpl-…` and `endpoint` =
`/v1/chat/completions` (the former `n` field is dropped).

## GET /v1/analytics/requests/summary

Same filters; computed over exactly the set the list would return.

```json
{
  "request_count": 4, "error_count": 1,
  "prompt_tokens": 420, "completion_tokens": 1280,
  "avg_duration_ms": 2900.5, "avg_time_to_first_token_ms": 400.0,
  "avg_generation_duration_ms": 2400.0
}
```

Averages are `null` when no row matches.

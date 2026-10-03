# Contract: `GET /v1/health`

Additional endpoint (no OpenAI counterpart in the vendored spec), following standard liveness-check conventions.

**Request**: no parameters, no body.

**Response `200`** `application/json`:

```json
{"status": "ok"}
```

# Contract: Error envelope (all non-2xx responses)

Matches OpenAI's `ErrorResponse` schema:

```json
{"error": {"message": "...", "type": "...", "param": null, "code": null}}
```

Generic/non-OpenAI errors follow standard HTTP semantics (`code` = snake_case HTTP reason; any other HTTPException status maps the same way, `null` for 500). OpenAI-defined endpoints follow OpenAI's documented behavior instead.

| Condition | HTTP status | `type` | `code` |
|-----------|-------------|--------|--------|
| Unknown route | 404 | `invalid_request_error` | `not_found` |
| Wrong method | 405 | `invalid_request_error` | `method_not_allowed` |
| Request validation failure | 422 | `invalid_request_error` | `unprocessable_content` (`param` = offending field) |
| Unhandled exception | 500 | `server_error` | `null` |

The envelope is validated in tests against `openai-spec/openapi.yaml`.

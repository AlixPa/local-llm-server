# Data Model: Backend Observability Tab

Two new tables in `packages/db`, one Alembic migration (generated with `--autogenerate`, then
reviewed). Conventions per CLAUDE.md: singular model → plural snake_case table, surrogate integer
PK (no `external_id`: not an OpenAI resource, the int PK is exposed directly), `UtcDateTime` for datetimes, enums as `StrEnum` stored as strings
(non-native, no check constraint, same pattern as `ChatCompletionStatus`), FKs enforced.

## Enums (`db/models/tracing.py`)

| Enum | Values |
|---|---|
| `TraceOutcome` | `in_progress`, `success`, `error`, `canceled`, `interrupted` |
| `StepKind` | `request_received`, `sent_to_ollama`, `received_from_ollama`, `response_returned`, `error` |
| `StepStatus` | `in_progress`, `completed`, `failed`, `canceled`, `interrupted` |
| `Participant` | `client`, `api`, `ollama` |

## TracedRequest → `traced_requests`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | exposed by the API; also the list cursor (feed order is `id DESC`) |
| `endpoint` | str | path, e.g. `/v1/chat/completions` |
| `method` | str | `POST` |
| `started_at` | `UtcDateTime` | request start |
| `duration_ms` | int \| None | null while in progress |
| `http_status` | int \| None | null while in progress / interrupted |
| `outcome` | `TraceOutcome` | |
| `summary` | str \| None | short, e.g. `qwen3.5:9b · stream`; set by the service when known |
| `response_id` | str \| None | resource external id (`chatcmpl-…`) = `chat_completion_records.external_id`; value link, no FK |
| `error_message` | str \| None | message returned to the caller, for the feed row |

Indexes: none beyond the PK. Feed order and cursor use `id DESC` (ids grow with start time);
`since`/`until` filter on `started_at`, and `endpoint`/`outcome` filters are served adequately by the
scan at this scale (SC-006 is verified in the quickstart at 20k rows); add an index on
`started_at` or a composite one only if that check fails.

## WorkflowStep → `workflow_steps`

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | internal only; the API identifies steps by `position` |
| `request_id` | int FK → `traced_requests.id` ON DELETE CASCADE | indexed |
| `position` | int | 0-based order within the request; unique with `request_id` |
| `kind` | `StepKind` | |
| `source` | `Participant` | direction = source → destination |
| `destination` | `Participant` | |
| `status` | `StepStatus` | `in_progress` for a sent-to-Ollama/received pair half still open |
| `started_at` | `UtcDateTime` | API exposes `offset_ms = started_at − request.started_at` |
| `duration_ms` | int \| None | null while in progress / for instantaneous steps |
| `content` | JSON \| None (`none_as_null=True`) | transferred payload: request body, Ollama payload, assembled result, response body, or `{"message": …}` for errors |
| `error_message` | str \| None | set on failed steps |

Constraint: `UniqueConstraint(request_id, position)`.

## Step sequences (chat completions)

| Scenario | Steps (source → destination, kind) |
|---|---|
| Success, non-stream | client→api `request_received`; api→ollama `sent_to_ollama`; ollama→api `received_from_ollama`; api→client `response_returned` |
| Success, stream | same four; the `received_from_ollama` step starts `in_progress` (inserted together with the sent step as `in_progress`, see below) and completes at stream end with the assembled content |
| `n > 1` | one `sent_to_ollama`/`received_from_ollama` pair per Ollama call, in call order |
| Rejected before Ollama (validation, unsupported option, unknown model) | `request_received`; `error` (api→client, content = error envelope) |
| Ollama failure / unreachable | `request_received`; `sent_to_ollama`; `received_from_ollama` with status `failed` + `error_message`; `error` (api→client, translated envelope) |
| Canceled by caller | steps that occurred; open `received_from_ollama` ends `canceled` with partial assembled content; no `response_returned` |

Streaming "in progress" semantics: when the `sent_to_ollama` step is written, the matching
`received_from_ollama` row is inserted at the same time with `status = in_progress`,
`content = null`; finishing it fills `duration_ms`, `content`, and final `status`. This is what
lets the open detail view show the streaming step as in progress (FR-006).

## State transitions

```text
TracedRequest.outcome:  in_progress ─► success | error | canceled
                        in_progress ─► interrupted      (server restart)
WorkflowStep.status:    in_progress ─► completed | failed | canceled
                        in_progress ─► interrupted      (server restart)
```

Request finalization (`duration_ms`, `http_status`, `outcome`, `error_message`,
`response_id`) happens once, in the middleware's `finally`, after the service has set any
overrides on the `Trace`.

## Relationships / retention

- `TracedRequest 1—* WorkflowStep` (cascade delete; no deletes are issued by the app — FR-012).
- `TracedRequest.response_id` ↔ `ChatCompletionRecord.external_id`: optional value link.
- No pruning, no soft delete, no extra lifecycle columns (decided here per CLAUDE.md: history is
  append-only; only the in-progress → terminal updates above).

## Repository functions (`db/repositories/tracing.py`)

Only what a feature needs now: `create_request`, `add_steps` (insert one or more), `finish_step`,
`finish_request`, `list_requests(filters, limit, after)` → `(rows, has_more)`
(raises `UnknownCursorError` like the analytics repo), `get_request_with_steps(id)`,
`mark_in_progress_interrupted()`.

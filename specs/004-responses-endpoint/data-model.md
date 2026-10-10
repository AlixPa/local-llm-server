# Data Model: Responses Endpoint End to End

Internal conventions (CLAUDE.md "Database & migrations"): singular model → plural snake_case
table, surrogate integer PK, `external_id` (OpenAI-style id) because the resource is exposed via
an OpenAI endpoint, `UtcDateTime` datetime columns, integer unix timestamps only at the API
boundary. No backward compatibility is required.

## `RequestStatus` (shared StrEnum, `db/models/status.py`)

`succeeded` | `failed` | `cancelled`. Replaces `ChatCompletionStatus`; used by both record tables
and the analytics status filter. Stored as a non-native, constraint-free enum (length 16).

## `ResponseRecord` → `response_records` (metadata, never holds content)

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `external_id` | str, unique | `resp_<24 hex>`; the id returned to the client |
| `created_at` | `UtcDateTime` | request start (== `created_at` in the Response object) |
| `model` | str | |
| `status` | `RequestStatus` | |
| `stream` | bool | |
| `prompt_tokens` | int \| None | null when Ollama was never reached/answered |
| `completion_tokens` | int \| None | |
| `duration_ms` | int | wall-clock measured by the API |
| `time_to_first_token_ms` | int \| None | streaming only |
| `generation_duration_ms` | int \| None | Ollama `eval_duration` |
| `load_duration_ms` | int \| None | Ollama `load_duration` |
| `finish_reason` | str \| None | `length` when Ollama `done_reason` is `length` (response `status: incomplete`); `tool_calls` when the output contains a function call; otherwise `stop` |
| `error_type` | str \| None | |
| `error_code` | str \| None | |

Index: `(created_at DESC, external_id DESC)` named `ix_response_records_created_at_external_id`, matching the analytics ordering and cursor (R8). Differences from
`ChatCompletionRecord`: no `n` column (Responses has no `n`).

## `ResponseContent` → `response_contents` (payloads, never read by analytics)

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `record_id` | int FK → `response_records.id`, unique, `ON DELETE CASCADE` | 1:1 |
| `request` | JSON | the validated `CreateResponse` body (set fields only) |
| `response` | JSON \| None | the `Response` object (assembled for streams; partial for cancelled/failed streams) |
| `error_message` | str \| None | |

## Existing entities touched

- `ChatCompletionRecord` / `ChatCompletionContent`: only the status type is renamed to
  `RequestStatus` (no column change). Its index `ix_chat_completion_records_created_at_id` is replaced by `ix_chat_completion_records_created_at_external_id` on `(created_at DESC, external_id DESC)` so both union branches are served in analytics order by their index.
- `TracedRequest.endpoint` gains the value `/v1/responses`; `response_id` links by value to
  `response_records.external_id` or `chat_completion_records.external_id` (prefix tells which).
  The model comment is updated; no schema change.
- `Model`: unchanged, shared for validation.

## Read model: combined analytics row (`db/repositories/analytics.py`)

`RequestMetadata` (frozen dataclass, content-free): `external_id`, `endpoint`
(`/v1/chat/completions` | `/v1/responses`), `created_at`, `model`, `status`, `stream`,
`prompt_tokens`, `completion_tokens`, `duration_ms`, `time_to_first_token_ms`,
`generation_duration_ms`, `load_duration_ms`, `finish_reason`, `error_type`, `error_code`.
Produced by a `UNION ALL` over the two metadata tables; `RequestFilters(endpoint, status, since,
until)` apply to both the list and `RequestSummary` (`request_count`, `error_count`,
`prompt_tokens`, `completion_tokens`, `avg_duration_ms`, `avg_time_to_first_token_ms`,
`avg_generation_duration_ms`). `error_count` counts `failed` rows, as today.

## State transitions

A record is written once, at the end of a request, with a terminal status:

- reaches generation and completes → `succeeded` (including `status: incomplete` responses, which
  are successful HTTP responses; `finish_reason: length` shows it)
- rejected after validation, upstream failure, context overflow → `failed` with `error_type` /
  `error_code`
- client disconnect (streaming or not) → `cancelled`, partial content and known usage kept

Requests rejected by schema validation are not recorded in `response_records` (they still appear
in the Observability feed through the tracing middleware, as for chat).

## API schema entities (Pydantic, OpenAI names verbatim; see research R4)

Request: `CreateResponse` (all 32 properties), `InputParam`, `EasyInputMessage`, `InputMessage`,
`FunctionToolCall`, `FunctionCallOutputItemParam`, `ReasoningItem` (accepted, dropped),
`InputTextContent`, `InputImageContent`, `OutputTextContent`, `FunctionTool`, `Reasoning`,
`TextResponseFormatConfiguration` variants, tool-choice variants, plus a loose catch-all for
unsupported item/tool types. Response: `Response`, `OutputMessage`, `FunctionToolCall`,
`ResponseOutputText`, `ResponseLogProb`, `ResponseUsage`, `ResponseError`, and the stream events
`ResponseCreatedEvent`, `ResponseInProgressEvent`, `ResponseOutputItemAddedEvent`,
`ResponseContentPartAddedEvent`, `ResponseTextDeltaEvent`, `ResponseTextDoneEvent`,
`ResponseContentPartDoneEvent`, `ResponseFunctionCallArgumentsDeltaEvent`,
`ResponseFunctionCallArgumentsDoneEvent`, `ResponseOutputItemDoneEvent`,
`ResponseCompletedEvent`, `ResponseIncompleteEvent`, `ResponseFailedEvent`.
Analytics (non-OpenAI): `AnalyticsRequestItem`, `AnalyticsRequestList`, `AnalyticsRequestSummary`.

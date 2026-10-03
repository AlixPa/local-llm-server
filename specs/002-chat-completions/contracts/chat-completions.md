# Contract: POST /v1/chat/completions

OpenAI-defined, so the contract is OpenAI's, vendored at `/openai-spec/openapi.yaml` — no local
copy. Schema names are used verbatim: `CreateChatCompletionRequest`,
`CreateChatCompletionResponse`, `CreateChatCompletionStreamResponse` (a.k.a. chunk), plus the
nested message/tool/response-format schemas. Field-for-field parity, `extra="ignore"`.

Behavior beyond the schema (policy per field is in `research.md` R5, errors in R7):

- `stream=false` → JSON `CreateChatCompletionResponse`; `stream=true` → `text/event-stream`,
  `data: {chunk}\n\n` lines, `data: [DONE]\n\n` terminator, final usage chunk when
  `stream_options.include_usage` is true.
- `id` = `chatcmpl-<random>`, identical to `external_id` in the stored record.
- Errors: OpenAI envelope `{"error": {message, type, param, code}}`.
- Every request that reaches endpoint logic is recorded (success, failure, cancel).

Required contract tests: `validate_contract` for a minimal success, a success with options
(tools, response_format, n=2, logprobs), and each error row of R7; `validate_schema` on every
streamed chunk.

Model validation: `model` must be a served model (`models` table); otherwise 404
`model_not_found` with OpenAI's message, ``The model `X` does not exist or you do not have access
to it.`` Streaming requests return pre-stream failures as real HTTP errors (research R13).

# Contract: GET /v1/models

OpenAI-defined (`listModels`, response `ListModelsResponse` of `Model`), so the vendored spec is
the contract: `{"object": "list", "data": [{"id", "object": "model", "created", "owned_by"}]}`.
`validate_contract` test required. Data comes from the `models` table.

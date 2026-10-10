from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _Loose(BaseModel):
    # Any type we don't implement: parsed only so it can be rejected by name
    model_config = ConfigDict(extra="allow")

    type: str | None = None


class ResponseStatus(StrEnum):
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ReasoningEffort(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class IncludeEnum(StrEnum):
    FILE_SEARCH_CALL_RESULTS = "file_search_call.results"
    WEB_SEARCH_CALL_RESULTS = "web_search_call.results"
    WEB_SEARCH_CALL_ACTION_SOURCES = "web_search_call.action.sources"
    MESSAGE_INPUT_IMAGE_IMAGE_URL = "message.input_image.image_url"
    COMPUTER_CALL_OUTPUT_OUTPUT_IMAGE_URL = "computer_call_output.output.image_url"
    CODE_INTERPRETER_CALL_OUTPUTS = "code_interpreter_call.outputs"
    REASONING_ENCRYPTED_CONTENT = "reasoning.encrypted_content"
    MESSAGE_OUTPUT_TEXT_LOGPROBS = "message.output_text.logprobs"


class ToolChoiceOptions(StrEnum):
    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"


class InputTextContent(_Model):
    type: Literal["input_text"]
    text: str


class InputImageContent(_Model):
    type: Literal["input_image"]
    image_url: str | None = None
    file_id: str | None = None
    detail: str | None = None


class LogProbTop(_Model):
    token: str
    logprob: float
    bytes: list[int]


class LogProb(_Model):
    token: str
    logprob: float
    bytes: list[int]
    top_logprobs: list[LogProbTop]


class OutputTextContent(_Model):
    type: Literal["output_text"]
    text: str
    annotations: list[dict[str, Any]] = []
    logprobs: list[LogProb] = []


def _content_tag(value: Any) -> str:
    kind = _field(value, "type")
    if kind in ("input_text", "output_text", "input_image"):
        return str(kind)
    return "other"


type ContentPart = Annotated[
    Annotated[InputTextContent, Tag("input_text")]
    | Annotated[OutputTextContent, Tag("output_text")]
    | Annotated[InputImageContent, Tag("input_image")]
    | Annotated[_Loose, Tag("other")],
    Discriminator(_content_tag),
]


class EasyInputMessage(_Model):
    type: Literal["message"] | None = None
    role: Literal["user", "assistant", "system", "developer"]
    content: str | list[ContentPart]


class InputMessage(_Model):
    type: Literal["message"] | None = None
    role: Literal["user", "system", "developer"]
    status: ResponseStatus | None = None
    content: list[ContentPart]


class OutputMessage(_Model):
    id: str
    type: Literal["message"] = "message"
    role: Literal["assistant"] = "assistant"
    content: list[ContentPart]
    status: ResponseStatus


class FunctionToolCall(_Model):
    id: str | None = None
    type: Literal["function_call"] = "function_call"
    call_id: str
    name: str
    arguments: str
    status: ResponseStatus | None = None


class FunctionCallOutputItemParam(_Model):
    id: str | None = None
    call_id: str | None = None
    type: Literal["function_call_output"] = "function_call_output"
    output: str | list[dict[str, Any]]


class ReasoningItem(_Model):
    id: str
    type: Literal["reasoning"]
    summary: list[dict[str, Any]] = []


def _field(value: Any, name: str) -> Any:
    return value.get(name) if isinstance(value, dict) else getattr(value, name, None)


def _item_tag(value: Any) -> str:
    match _field(value, "type"):
        case "function_call":
            return "function_call"
        case "function_call_output":
            return "function_call_output"
        case "reasoning":
            return "reasoning"
        case None | "message":
            if (
                _field(value, "role") == "assistant"
                and _field(value, "id")
                and _field(value, "status")
            ):
                return "output"
            return "input" if _field(value, "status") else "easy"
        case _:
            return "other"


type InputItem = Annotated[
    Annotated[EasyInputMessage, Tag("easy")]
    | Annotated[InputMessage, Tag("input")]
    | Annotated[OutputMessage, Tag("output")]
    | Annotated[FunctionToolCall, Tag("function_call")]
    | Annotated[FunctionCallOutputItemParam, Tag("function_call_output")]
    | Annotated[ReasoningItem, Tag("reasoning")]
    | Annotated[_Loose, Tag("other")],
    Discriminator(_item_tag),
]

type InputParam = str | list[InputItem]


class FunctionTool(_Model):
    type: Literal["function"]
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


def _tool_tag(value: Any) -> str:
    kind = value.get("type") if isinstance(value, dict) else value.type
    return "function" if kind == "function" else "other"


type Tool = Annotated[
    Annotated[FunctionTool, Tag("function")] | Annotated[_Loose, Tag("other")],
    Discriminator(_tool_tag),
]


class ToolChoiceFunction(_Model):
    type: Literal["function"]
    name: str


class ToolChoiceAllowed(_Model):
    type: Literal["allowed_tools"]
    mode: Literal["auto", "required"]
    tools: list[dict[str, Any]]


def _tool_choice_tag(value: Any) -> str:
    if isinstance(value, str):
        return "mode"
    kind = value.get("type") if isinstance(value, dict) else value.type
    match kind:
        case "function":
            return "function"
        case "allowed_tools":
            return "allowed"
        case _:
            return "other"


type ToolChoiceParam = Annotated[
    Annotated[ToolChoiceOptions, Tag("mode")]
    | Annotated[ToolChoiceFunction, Tag("function")]
    | Annotated[ToolChoiceAllowed, Tag("allowed")]
    | Annotated[_Loose, Tag("other")],
    Discriminator(_tool_choice_tag),
]


class ResponseFormatText(_Model):
    type: Literal["text"]


class ResponseFormatJsonObject(_Model):
    type: Literal["json_object"]


class TextResponseFormatJsonSchema(_Model):
    type: Literal["json_schema"]
    name: str
    description: str | None = None
    schema_: dict[str, Any] = Field(alias="schema")
    strict: bool | None = None


type TextResponseFormatConfiguration = Annotated[
    ResponseFormatText | ResponseFormatJsonObject | TextResponseFormatJsonSchema,
    Field(discriminator="type"),
]


class ResponseTextParam(_Model):
    format: TextResponseFormatConfiguration | None = None
    verbosity: Literal["low", "medium", "high"] | None = None


class Reasoning(_Model):
    mode: str | None = None
    effort: ReasoningEffort | None = None
    summary: Literal["auto", "concise", "detailed"] | None = None
    context: Literal["auto", "current_turn", "all_turns"] | None = None
    generate_summary: Literal["auto", "concise", "detailed"] | None = None


class CreateResponse(_Model):
    metadata: dict[str, str] | None = None
    top_logprobs: int | None = Field(default=None, ge=0, le=20)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    user: str | None = None
    safety_identifier: str | None = None
    prompt_cache_key: str | None = None
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None
    prompt_cache_options: dict[str, Any] | None = None
    previous_response_id: str | None = None
    model: str | None = None
    background: bool | None = None
    max_tool_calls: int | None = None
    text: ResponseTextParam | None = None
    tools: list[Tool] | None = None
    tool_choice: ToolChoiceParam | None = None
    prompt: dict[str, Any] | None = None
    access_programs: dict[str, Any] | None = None
    service_tier: str | None = None
    truncation: Literal["auto", "disabled"] | None = None
    reasoning: Reasoning | None = None
    input: InputParam | None = None
    include: list[IncludeEnum] | None = None
    parallel_tool_calls: bool | None = None
    store: bool | None = None
    instructions: str | None = None
    moderation: dict[str, Any] | None = None
    stream: bool | None = None
    stream_options: dict[str, Any] | None = None
    conversation: str | dict[str, Any] | None = None
    context_management: list[dict[str, Any]] | None = None
    max_output_tokens: int | None = Field(default=None, ge=16)


class InputTokensDetails(_Model):
    cached_tokens: int = 0
    cache_write_tokens: int = 0


class OutputTokensDetails(_Model):
    reasoning_tokens: int = 0


class ResponseUsage(_Model):
    input_tokens: int
    input_tokens_details: InputTokensDetails = InputTokensDetails()
    output_tokens: int
    output_tokens_details: OutputTokensDetails = OutputTokensDetails()
    total_tokens: int


class IncompleteDetails(_Model):
    reason: Literal["max_output_tokens"]


class ResponseError(_Model):
    code: str
    message: str


class ResponseLogProbTop(_Model):
    token: str
    logprob: float


class ResponseLogProb(_Model):
    token: str
    logprob: float
    top_logprobs: list[ResponseLogProbTop] = []


type OutputItem = OutputMessage | FunctionToolCall


class Response(_Model):
    id: str
    object: Literal["response"] = "response"
    created_at: int
    completed_at: int | None
    status: ResponseStatus
    model: str
    output: list[OutputItem]
    usage: ResponseUsage | None
    error: ResponseError | None
    incomplete_details: IncompleteDetails | None
    instructions: str | None
    metadata: dict[str, str]
    tools: list[dict[str, Any]]
    tool_choice: str | dict[str, Any]
    temperature: float | None
    top_p: float | None
    parallel_tool_calls: bool
    max_output_tokens: int | None
    text: dict[str, Any]
    truncation: Literal["auto", "disabled"]
    reasoning: dict[str, Any] | None
    top_logprobs: int | None
    access_programs: dict[str, Any] | None = None
    background: bool = False
    previous_response_id: str | None = None


class ResponseCreatedEvent(_Model):
    type: Literal["response.created"] = "response.created"
    response: Response
    sequence_number: int


class ResponseInProgressEvent(_Model):
    type: Literal["response.in_progress"] = "response.in_progress"
    response: Response
    sequence_number: int


class ResponseOutputItemAddedEvent(_Model):
    type: Literal["response.output_item.added"] = "response.output_item.added"
    output_index: int
    item: OutputItem
    sequence_number: int


class ResponseContentPartAddedEvent(_Model):
    type: Literal["response.content_part.added"] = "response.content_part.added"
    item_id: str
    output_index: int
    content_index: int
    part: OutputTextContent
    sequence_number: int


class ResponseTextDeltaEvent(_Model):
    type: Literal["response.output_text.delta"] = "response.output_text.delta"
    item_id: str
    output_index: int
    content_index: int
    delta: str
    sequence_number: int
    logprobs: list[ResponseLogProb]


class ResponseTextDoneEvent(_Model):
    type: Literal["response.output_text.done"] = "response.output_text.done"
    item_id: str
    output_index: int
    content_index: int
    text: str
    sequence_number: int
    logprobs: list[ResponseLogProb]


class ResponseContentPartDoneEvent(_Model):
    type: Literal["response.content_part.done"] = "response.content_part.done"
    item_id: str
    output_index: int
    content_index: int
    part: OutputTextContent
    sequence_number: int


class ResponseFunctionCallArgumentsDeltaEvent(_Model):
    type: Literal["response.function_call_arguments.delta"] = (
        "response.function_call_arguments.delta"
    )
    item_id: str
    output_index: int
    delta: str
    sequence_number: int


class ResponseFunctionCallArgumentsDoneEvent(_Model):
    type: Literal["response.function_call_arguments.done"] = (
        "response.function_call_arguments.done"
    )
    item_id: str
    output_index: int
    arguments: str
    sequence_number: int


class ResponseOutputItemDoneEvent(_Model):
    type: Literal["response.output_item.done"] = "response.output_item.done"
    output_index: int
    item: OutputItem
    sequence_number: int


class ResponseCompletedEvent(_Model):
    type: Literal["response.completed"] = "response.completed"
    response: Response
    sequence_number: int


class ResponseIncompleteEvent(_Model):
    type: Literal["response.incomplete"] = "response.incomplete"
    response: Response
    sequence_number: int


class ResponseFailedEvent(_Model):
    type: Literal["response.failed"] = "response.failed"
    response: Response
    sequence_number: int


type ResponseStreamEvent = (
    ResponseCreatedEvent
    | ResponseInProgressEvent
    | ResponseOutputItemAddedEvent
    | ResponseContentPartAddedEvent
    | ResponseTextDeltaEvent
    | ResponseTextDoneEvent
    | ResponseContentPartDoneEvent
    | ResponseFunctionCallArgumentsDeltaEvent
    | ResponseFunctionCallArgumentsDoneEvent
    | ResponseOutputItemDoneEvent
    | ResponseCompletedEvent
    | ResponseIncompleteEvent
    | ResponseFailedEvent
)

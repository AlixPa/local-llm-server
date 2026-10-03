from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from api.errors import Error


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class ServiceTier(StrEnum):
    AUTO = "auto"
    DEFAULT = "default"
    FLEX = "flex"
    SCALE = "scale"
    PRIORITY = "priority"
    FAST = "fast"


class Verbosity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ReasoningEffort(StrEnum):
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"


class ResponseModality(StrEnum):
    TEXT = "text"
    AUDIO = "audio"


class ImageDetail(StrEnum):
    AUTO = "auto"
    LOW = "low"
    HIGH = "high"
    ORIGINAL = "original"


class FinishReason(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    FUNCTION_CALL = "function_call"


class PromptCacheBreakpointParam(_Model):
    mode: Literal["explicit"]


class PromptCacheOptionsParam(_Model):
    ttl: Literal["30m"] | None = None
    mode: Literal["implicit", "explicit"] | None = None


class ChatCompletionRequestMessageContentPartText(_Model):
    type: Literal["text"]
    text: str
    prompt_cache_breakpoint: PromptCacheBreakpointParam | None = None


class ImageUrl(_Model):
    url: str
    detail: ImageDetail | None = None


class ChatCompletionRequestMessageContentPartImage(_Model):
    type: Literal["image_url"]
    image_url: ImageUrl
    prompt_cache_breakpoint: PromptCacheBreakpointParam | None = None


class InputAudio(_Model):
    data: str
    format: Literal["wav", "mp3"]


class ChatCompletionRequestMessageContentPartAudio(_Model):
    type: Literal["input_audio"]
    input_audio: InputAudio
    prompt_cache_breakpoint: PromptCacheBreakpointParam | None = None


class FileContent(_Model):
    filename: str | None = None
    file_data: str | None = None
    file_id: str | None = None


class ChatCompletionRequestMessageContentPartFile(_Model):
    type: Literal["file"]
    file: FileContent
    prompt_cache_breakpoint: PromptCacheBreakpointParam | None = None


class ChatCompletionRequestMessageContentPartRefusal(_Model):
    type: Literal["refusal"]
    refusal: str


type TextParts = Annotated[
    list[ChatCompletionRequestMessageContentPartText], Field(min_length=1)
]

type ChatCompletionRequestUserMessageContentPart = Annotated[
    ChatCompletionRequestMessageContentPartText
    | ChatCompletionRequestMessageContentPartImage
    | ChatCompletionRequestMessageContentPartAudio
    | ChatCompletionRequestMessageContentPartFile,
    Field(discriminator="type"),
]

type ChatCompletionRequestAssistantMessageContentPart = Annotated[
    ChatCompletionRequestMessageContentPartText
    | ChatCompletionRequestMessageContentPartRefusal,
    Field(discriminator="type"),
]


class ChatCompletionRequestDeveloperMessage(_Model):
    role: Literal["developer"]
    content: str | TextParts
    name: str | None = None


class ChatCompletionRequestSystemMessage(_Model):
    role: Literal["system"]
    content: str | TextParts
    name: str | None = None


class ChatCompletionRequestUserMessage(_Model):
    role: Literal["user"]
    content: (
        str
        | Annotated[
            list[ChatCompletionRequestUserMessageContentPart], Field(min_length=1)
        ]
    )
    name: str | None = None


class ChatCompletionMessageToolCallFunction(_Model):
    name: str
    arguments: str


class ChatCompletionMessageToolCall(_Model):
    id: str
    type: Literal["function"]
    function: ChatCompletionMessageToolCallFunction


class ChatCompletionMessageCustomToolCallBody(_Model):
    name: str
    input: str


class ChatCompletionMessageCustomToolCall(_Model):
    id: str
    type: Literal["custom"]
    custom: ChatCompletionMessageCustomToolCallBody


type ChatCompletionMessageToolCalls = list[
    Annotated[
        ChatCompletionMessageToolCall | ChatCompletionMessageCustomToolCall,
        Field(discriminator="type"),
    ]
]


class FunctionCall(_Model):
    name: str
    arguments: str


class AssistantAudioReference(_Model):
    id: str


class ChatCompletionRequestAssistantMessage(_Model):
    role: Literal["assistant"]
    content: (
        str
        | Annotated[
            list[ChatCompletionRequestAssistantMessageContentPart],
            Field(min_length=1),
        ]
        | None
    ) = None
    refusal: str | None = None
    name: str | None = None
    audio: AssistantAudioReference | None = None
    tool_calls: ChatCompletionMessageToolCalls | None = None
    function_call: FunctionCall | None = None


class ChatCompletionRequestToolMessage(_Model):
    role: Literal["tool"]
    content: str | TextParts
    tool_call_id: str


class ChatCompletionRequestFunctionMessage(_Model):
    role: Literal["function"]
    content: str | None
    name: str


type ChatCompletionRequestMessage = Annotated[
    ChatCompletionRequestDeveloperMessage
    | ChatCompletionRequestSystemMessage
    | ChatCompletionRequestUserMessage
    | ChatCompletionRequestAssistantMessage
    | ChatCompletionRequestToolMessage
    | ChatCompletionRequestFunctionMessage,
    Field(discriminator="role"),
]


class FunctionObject(_Model):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None
    strict: bool | None = None


class ChatCompletionTool(_Model):
    type: Literal["function"]
    function: FunctionObject


class CustomToolChatCompletionsBody(_Model):
    name: str
    description: str | None = None
    format: dict[str, Any] | None = None


class CustomToolChatCompletions(_Model):
    type: Literal["custom"]
    custom: CustomToolChatCompletionsBody


class ChatCompletionFunctions(_Model):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class ChatCompletionFunctionCallOption(_Model):
    name: str


class ChatCompletionNamedToolChoiceFunction(_Model):
    name: str


class ChatCompletionNamedToolChoice(_Model):
    type: Literal["function"]
    function: ChatCompletionNamedToolChoiceFunction


class ChatCompletionNamedToolChoiceCustomBody(_Model):
    name: str


class ChatCompletionNamedToolChoiceCustom(_Model):
    type: Literal["custom"]
    custom: ChatCompletionNamedToolChoiceCustomBody


class ChatCompletionAllowedTools(_Model):
    mode: Literal["auto", "required"]
    tools: list[dict[str, Any]]


class ChatCompletionAllowedToolsChoice(_Model):
    type: Literal["allowed_tools"]
    allowed_tools: ChatCompletionAllowedTools


class ToolChoiceMode(StrEnum):
    NONE = "none"
    AUTO = "auto"
    REQUIRED = "required"


class FunctionCallMode(StrEnum):
    NONE = "none"
    AUTO = "auto"


class ResponseFormatText(_Model):
    type: Literal["text"]


class ResponseFormatJsonObject(_Model):
    type: Literal["json_object"]


class JsonSchemaFormat(_Model):
    name: str
    description: str | None = None
    schema_: dict[str, Any] | None = Field(default=None, alias="schema")
    strict: bool | None = None


class ResponseFormatJsonSchema(_Model):
    type: Literal["json_schema"]
    json_schema: JsonSchemaFormat


class ChatCompletionStreamOptions(_Model):
    include_usage: bool | None = None
    include_obfuscation: bool | None = None


class PredictionContent(_Model):
    type: Literal["content"]
    content: str | TextParts


class WebSearchLocation(_Model):
    country: str | None = None
    region: str | None = None
    city: str | None = None
    timezone: str | None = None


class WebSearchUserLocation(_Model):
    type: Literal["approximate"]
    approximate: WebSearchLocation


class WebSearchOptions(_Model):
    user_location: WebSearchUserLocation | None = None
    search_context_size: Literal["low", "medium", "high"] | None = None


class AudioOutputParameters(_Model):
    voice: str | dict[str, Any]
    format: Literal["wav", "aac", "mp3", "flac", "opus", "pcm16"]


class ModerationParam(_Model):
    model: str
    policy: dict[str, Any] | None = None


class CreateChatCompletionRequest(_Model):
    messages: Annotated[list[ChatCompletionRequestMessage], Field(min_length=1)]
    model: str
    metadata: dict[str, str] | None = None
    top_logprobs: Annotated[int, Field(ge=0, le=20)] | None = None
    temperature: Annotated[float, Field(ge=0, le=2)] | None = None
    top_p: Annotated[float, Field(ge=0, le=1)] | None = None
    user: str | None = None
    safety_identifier: Annotated[str, Field(max_length=64)] | None = None
    prompt_cache_key: str | None = None
    prompt_cache_retention: Literal["in_memory", "24h"] | None = None
    prompt_cache_options: PromptCacheOptionsParam | None = None
    service_tier: ServiceTier | None = None
    modalities: list[ResponseModality] | None = None
    verbosity: Verbosity | None = None
    reasoning_effort: ReasoningEffort | None = None
    max_completion_tokens: int | None = None
    frequency_penalty: Annotated[float, Field(ge=-2, le=2)] | None = None
    presence_penalty: Annotated[float, Field(ge=-2, le=2)] | None = None
    web_search_options: WebSearchOptions | None = None
    response_format: (
        Annotated[
            ResponseFormatText | ResponseFormatJsonSchema | ResponseFormatJsonObject,
            Field(discriminator="type"),
        ]
        | None
    ) = None
    audio: AudioOutputParameters | None = None
    store: bool | None = None
    moderation: ModerationParam | None = None
    stream: bool | None = None
    stop: str | Annotated[list[str], Field(min_length=1, max_length=4)] | None = None
    logit_bias: dict[str, int] | None = None
    logprobs: bool | None = None
    max_tokens: int | None = None
    n: Annotated[int, Field(ge=1, le=128)] | None = None
    prediction: PredictionContent | None = None
    seed: int | None = None
    stream_options: ChatCompletionStreamOptions | None = None
    tools: (
        list[
            Annotated[
                ChatCompletionTool | CustomToolChatCompletions,
                Field(discriminator="type"),
            ]
        ]
        | None
    ) = None
    tool_choice: (
        ToolChoiceMode
        | ChatCompletionAllowedToolsChoice
        | ChatCompletionNamedToolChoice
        | ChatCompletionNamedToolChoiceCustom
        | None
    ) = None
    parallel_tool_calls: bool | None = None
    function_call: FunctionCallMode | ChatCompletionFunctionCallOption | None = None
    functions: (
        Annotated[list[ChatCompletionFunctions], Field(min_length=1, max_length=128)]
        | None
    ) = None


class ChatCompletionTokenTopLogprob(_Model):
    token: str
    logprob: float
    bytes: list[int] | None


class ChatCompletionTokenLogprob(ChatCompletionTokenTopLogprob):
    top_logprobs: list[ChatCompletionTokenTopLogprob]


class ChoiceLogprobs(_Model):
    content: list[ChatCompletionTokenLogprob] | None
    refusal: list[ChatCompletionTokenLogprob] | None


class ChatCompletionResponseMessage(_Model):
    role: Literal["assistant"]
    content: str | None
    refusal: str | None = None
    tool_calls: ChatCompletionMessageToolCalls | None = None
    function_call: FunctionCall | None = None


class CreateChatCompletionResponseChoice(_Model):
    index: int
    message: ChatCompletionResponseMessage
    logprobs: ChoiceLogprobs | None
    finish_reason: FinishReason


class CompletionUsage(_Model):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class CreateChatCompletionResponse(_Model):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[CreateChatCompletionResponseChoice]
    usage: CompletionUsage | None = None


class ChatCompletionMessageToolCallChunkFunction(_Model):
    name: str | None = None
    arguments: str | None = None


class ChatCompletionMessageToolCallChunk(_Model):
    index: int
    id: str | None = None
    type: Literal["function"] | None = None
    function: ChatCompletionMessageToolCallChunkFunction | None = None


class ChatCompletionStreamResponseDelta(_Model):
    role: Literal["assistant"] | None = None
    content: str | None = None
    refusal: str | None = None
    tool_calls: list[ChatCompletionMessageToolCallChunk] | None = None


class CreateChatCompletionStreamResponseChoice(_Model):
    index: int
    delta: ChatCompletionStreamResponseDelta
    logprobs: ChoiceLogprobs | None = None
    finish_reason: FinishReason | None


class CreateChatCompletionStreamResponse(_Model):
    id: str
    object: Literal["chat.completion.chunk"]
    created: int
    model: str
    choices: list[CreateChatCompletionStreamResponseChoice]
    usage: CompletionUsage | None = None


class ChatCompletionStreamError(_Model):
    error: Error

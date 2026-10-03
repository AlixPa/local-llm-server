import json
from typing import Any

import pytest
from api.chat.schemas import CreateChatCompletionRequest
from api.chat.service import FIELD_POLICY, Policy
from httpx import AsyncClient
from ollama_fakes import OllamaMock, chat_response

MODEL = "qwen3.5:9b"
USER = {"role": "user", "content": "Hi"}
BASE = {"model": MODEL, "messages": [USER]}
PIXEL = "data:image/png;base64,iVBORw0KGgo="
WEATHER = {
    "type": "function",
    "function": {"name": "get_weather", "parameters": {"type": "object"}},
}
TIME = {
    "type": "function",
    "function": {"name": "get_time", "parameters": {"type": "object"}},
}
OLLAMA_KEYS = {
    "model",
    "messages",
    "tools",
    "format",
    "options",
    "stream",
    "think",
    "logprobs",
    "top_logprobs",
}


async def _send(
    client: AsyncClient, ollama_mock: OllamaMock, extra: dict[str, Any]
) -> dict[str, Any]:
    ollama_mock.handler = lambda _: chat_response()
    response = await client.post("/v1/chat/completions", json={**BASE, **extra})
    assert response.status_code == 200, response.text
    sent: dict[str, Any] = json.loads(ollama_mock.requests[-1].content)
    return sent


@pytest.mark.parametrize(
    ("extra", "options"),
    [
        ({"temperature": 0.3}, {"temperature": 0.3}),
        ({"top_p": 0.5}, {"top_p": 0.5}),
        ({"seed": 7}, {"seed": 7}),
        ({"stop": "END"}, {"stop": ["END"]}),
        ({"stop": ["a", "b"]}, {"stop": ["a", "b"]}),
        ({"frequency_penalty": 0.5}, {"frequency_penalty": 0.5}),
        ({"presence_penalty": -0.5}, {"presence_penalty": -0.5}),
        ({"max_tokens": 10}, {"num_predict": 10}),
        ({"max_completion_tokens": 20}, {"num_predict": 20}),
        ({"max_tokens": 10, "max_completion_tokens": 20}, {"num_predict": 20}),
    ],
)
async def test_sampling_options_are_forwarded(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    extra: dict[str, Any],
    options: dict[str, Any],
) -> None:
    sent = await _send(client, ollama_mock, extra)

    assert options.items() <= sent["options"].items()
    assert sent["options"]["num_ctx"] == 32768


async def test_response_format_mapping(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}

    sent = await _send(
        client,
        ollama_mock,
        {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "x", "schema": schema},
            }
        },
    )
    assert sent["format"] == schema

    sent = await _send(client, ollama_mock, {"response_format": {"type": "text"}})
    assert "format" not in sent


async def test_messages_translation(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {
            "messages": [
                {"role": "developer", "content": "Be brief"},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is this?"},
                        {"type": "image_url", "image_url": {"url": PIXEL}},
                    ],
                },
                {"role": "user", "content": ""},
            ]
        },
    )

    assert sent["messages"] == [
        {"role": "system", "content": "Be brief"},
        {"role": "user", "content": "What is this?", "images": ["iVBORw0KGgo="]},
        {"role": "user", "content": ""},
    ]


async def test_tool_conversation_translation(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {
            "messages": [
                USER,
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "get_weather",
                                "arguments": '{"city": "Paris"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "Sunny"},
            ]
        },
    )

    assert sent["messages"][1] == {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "get_weather", "arguments": {"city": "Paris"}}}
        ],
    }
    assert sent["messages"][2] == {
        "role": "tool",
        "content": "Sunny",
        "tool_name": "get_weather",
    }


async def test_tool_choice_none_drops_tools(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(client, ollama_mock, {"tools": [WEATHER], "tool_choice": "none"})

    assert "tools" not in sent


async def test_tool_choice_auto_keeps_tools(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client, ollama_mock, {"tools": [WEATHER, TIME], "tool_choice": "auto"}
    )

    assert len(sent["tools"]) == 2
    assert sent["messages"][0]["role"] == "user"


async def test_tool_choice_named_restricts_tools(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {
            "tools": [WEATHER, TIME],
            "tool_choice": {"type": "function", "function": {"name": "get_time"}},
        },
    )

    assert [t["function"]["name"] for t in sent["tools"]] == ["get_time"]
    assert sent["messages"][0]["role"] == "system"
    assert "get_time" in sent["messages"][0]["content"]


async def test_tool_choice_required_adds_instruction(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {
            "messages": [{"role": "system", "content": "Be nice"}, USER],
            "tools": [WEATHER],
            "tool_choice": "required",
        },
    )

    assert len(sent["tools"]) == 1
    assert sent["messages"][0]["content"].startswith("Be nice\n\n")
    assert "must call" in sent["messages"][0]["content"]


async def test_tool_choice_naming_missing_function_is_rejected(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    response = await client.post(
        "/v1/chat/completions",
        json={
            **BASE,
            "tools": [WEATHER],
            "tool_choice": {"type": "function", "function": {"name": "nope"}},
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["param"] == "tool_choice"


async def test_legacy_functions_are_converted(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {
            "functions": [
                {"name": "get_weather", "parameters": {"type": "object"}},
                {"name": "get_time"},
            ],
            "function_call": {"name": "get_weather"},
        },
    )

    assert sent["tools"] == [WEATHER]


async def test_legacy_function_call_none_drops_tools(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {"functions": [{"name": "get_weather"}], "function_call": "none"},
    )

    assert "tools" not in sent


@pytest.mark.parametrize(
    ("effort", "think"),
    [
        (None, False),
        ("none", False),
        ("minimal", False),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "high"),
        ("max", "high"),
    ],
)
async def test_reasoning_effort_maps_to_think(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    effort: str | None,
    think: bool | str,
) -> None:
    extra = {} if effort is None else {"reasoning_effort": effort}

    sent = await _send(client, ollama_mock, extra)

    assert sent["think"] == think


@pytest.mark.parametrize(
    "extra",
    [
        {"parallel_tool_calls": False},
        {"verbosity": "low"},
        {"prediction": {"type": "content", "content": "x"}},
        {"metadata": {"a": "b"}},
        {"store": True},
        {"user": "u"},
        {"safety_identifier": "s"},
        {"service_tier": "flex"},
        {"prompt_cache_key": "k"},
        {"prompt_cache_retention": "24h"},
        {"prompt_cache_options": {"mode": "implicit"}},
        {"logit_bias": {}},
        {"modalities": ["text"]},
        {"stream_options": {"include_usage": True}},
    ],
)
async def test_ignored_options_are_accepted_and_not_forwarded(
    client: AsyncClient, ollama_mock: OllamaMock, extra: dict[str, Any]
) -> None:
    sent = await _send(client, ollama_mock, extra)

    assert sent.keys() <= OLLAMA_KEYS
    assert sent["options"].keys() <= {"num_ctx"}


@pytest.mark.parametrize(
    ("extra", "param"),
    [
        ({"logit_bias": {"50256": -100}}, "logit_bias"),
        ({"audio": {"voice": "alloy", "format": "wav"}}, "audio"),
        ({"web_search_options": {}}, "web_search_options"),
        ({"moderation": {"model": "m"}}, "moderation"),
        ({"modalities": ["text", "audio"]}, "modalities"),
        (
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "https://example.com/a.png"},
                            }
                        ],
                    }
                ]
            },
            "messages",
        ),
        (
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_audio",
                                "input_audio": {"data": "AAAA", "format": "wav"},
                            }
                        ],
                    }
                ]
            },
            "messages",
        ),
        (
            {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "file", "file": {"file_id": "file-1"}}],
                    }
                ]
            },
            "messages",
        ),
        (
            {"tools": [{"type": "custom", "custom": {"name": "c"}}]},
            "tools",
        ),
    ],
)
async def test_rejected_options_name_the_option(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    extra: dict[str, Any],
    param: str,
) -> None:
    response = await client.post("/v1/chat/completions", json={**BASE, **extra})

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "unsupported_parameter"
    assert error["param"] == param
    assert ollama_mock.requests == []


async def test_non_conforming_json_is_returned_as_generated(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    ollama_mock.handler = lambda _: chat_response("not json at all")

    response = await client.post(
        "/v1/chat/completions",
        json={**BASE, "response_format": {"type": "json_object"}},
    )

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "not json at all"


def _request_properties(spec: dict[str, Any], schema: dict[str, Any]) -> set[str]:
    schemas = spec["components"]["schemas"]
    found: set[str] = set(schema.get("properties", {}))
    for part in schema.get("allOf", []):
        if "$ref" in part:
            part = schemas[part["$ref"].rsplit("/", 1)[-1]]
        found |= _request_properties(spec, part)
    return found


def test_every_request_property_has_a_policy(
    openai_spec: dict[str, Any],
) -> None:
    schema = openai_spec["components"]["schemas"]["CreateChatCompletionRequest"]

    properties = _request_properties(openai_spec, schema)

    assert properties - FIELD_POLICY.keys() == set()
    assert FIELD_POLICY.keys() - properties == set()
    assert {p for p, v in FIELD_POLICY.items() if v is Policy.REJECT} == {
        "logit_bias",
        "audio",
        "web_search_options",
        "moderation",
    }


def test_schema_covers_every_request_property(
    openai_spec: dict[str, Any],
) -> None:
    schema = openai_spec["components"]["schemas"]["CreateChatCompletionRequest"]

    properties = _request_properties(openai_spec, schema)

    assert properties == set(CreateChatCompletionRequest.model_fields)

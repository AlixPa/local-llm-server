import json
from typing import Any

import pytest
from api.inference import Policy
from api.responses.schemas import CreateResponse
from api.responses.service import FIELD_POLICY
from httpx import AsyncClient
from ollama_fakes import OllamaMock, chat_response

MODEL = "qwen3.5:9b"
BASE = {"model": MODEL, "input": "Hi"}
WEATHER = {
    "type": "function",
    "name": "get_weather",
    "parameters": {"type": "object"},
    "strict": False,
}
TIME = {**WEATHER, "name": "get_time"}


async def _send(
    client: AsyncClient, ollama_mock: OllamaMock, extra: dict[str, Any]
) -> dict[str, Any]:
    ollama_mock.handler = lambda _: chat_response()
    response = await client.post("/v1/responses", json={**BASE, **extra})
    assert response.status_code == 200, response.text
    sent: dict[str, Any] = json.loads(ollama_mock.requests[-1].content)
    return sent


async def _error(client: AsyncClient, extra: dict[str, Any]) -> dict[str, Any]:
    response = await client.post("/v1/responses", json={**BASE, **extra})
    assert response.status_code == 400, response.text
    error: dict[str, Any] = response.json()["error"]
    return error


def _request_properties(spec: dict[str, Any], schema: dict[str, Any]) -> set[str]:
    schemas = spec["components"]["schemas"]
    found: set[str] = set(schema.get("properties", {}))
    for part in schema.get("allOf", []):
        if "$ref" in part:
            part = schemas[part["$ref"].rsplit("/", 1)[-1]]
        found |= _request_properties(spec, part)
    return found


def test_every_create_response_property_has_a_policy(
    openai_spec: dict[str, Any],
) -> None:
    schema = openai_spec["components"]["schemas"]["CreateResponse"]

    properties = _request_properties(openai_spec, schema)

    assert len(properties) == 32
    assert properties == FIELD_POLICY.keys()
    assert properties == set(CreateResponse.model_fields)
    assert {p for p, v in FIELD_POLICY.items() if v is Policy.REJECT} == {
        "previous_response_id",
        "conversation",
        "background",
        "prompt",
        "context_management",
        "moderation",
    }


@pytest.mark.parametrize(
    ("extra", "options"),
    [
        ({"temperature": 0.3}, {"temperature": 0.3}),
        ({"top_p": 0.5}, {"top_p": 0.5}),
        ({"max_output_tokens": 20}, {"num_predict": 20}),
    ],
)
async def test_sampling_options_map_to_ollama_options(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    extra: dict[str, Any],
    options: dict[str, Any],
) -> None:
    sent = await _send(client, ollama_mock, extra)

    assert sent["options"] == {"num_ctx": 32768, **options}


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ({"type": "text"}, None),
        ({"type": "json_object"}, "json"),
        (
            {
                "type": "json_schema",
                "name": "x",
                "schema": {"type": "object", "properties": {"a": {"type": "string"}}},
            },
            {"type": "object", "properties": {"a": {"type": "string"}}},
        ),
    ],
)
async def test_text_format_maps_to_ollama_format(
    client: AsyncClient, ollama_mock: OllamaMock, fmt: Any, expected: Any
) -> None:
    sent = await _send(client, ollama_mock, {"text": {"format": fmt}})

    assert sent.get("format") == expected


async def test_function_tools_are_honored(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(client, ollama_mock, {"tools": [WEATHER]})

    assert sent["tools"] == [
        {
            "type": "function",
            "function": {"name": "get_weather", "parameters": {"type": "object"}},
        }
    ]


async def test_hosted_tool_is_rejected(client: AsyncClient) -> None:
    error = await _error(client, {"tools": [{"type": "web_search"}]})

    assert error["code"] == "unsupported_parameter"
    assert error["param"] == "tools"


async def test_tool_choice_none_drops_tools(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(client, ollama_mock, {"tools": [WEATHER], "tool_choice": "none"})

    assert "tools" not in sent or sent["tools"] is None


async def test_tool_choice_auto_keeps_tools_without_instruction(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(client, ollama_mock, {"tools": [WEATHER], "tool_choice": "auto"})

    assert len(sent["tools"]) == 1
    assert [m["role"] for m in sent["messages"]] == ["user"]


async def test_tool_choice_required_adds_instruction(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client, ollama_mock, {"tools": [WEATHER], "tool_choice": "required"}
    )

    assert sent["messages"][0]["role"] == "system"
    assert "must call" in sent["messages"][0]["content"]


async def test_tool_choice_function_restricts_tools_and_merges_instructions(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {
            "tools": [WEATHER, TIME],
            "tool_choice": {"type": "function", "name": "get_time"},
            "instructions": "Be brief.",
        },
    )

    assert [t["function"]["name"] for t in sent["tools"]] == ["get_time"]
    assert sent["messages"][0]["content"].startswith("Be brief.")
    assert "`get_time`" in sent["messages"][0]["content"]
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]


async def test_allowed_tools_choice_is_rejected(client: AsyncClient) -> None:
    error = await _error(
        client,
        {
            "tools": [WEATHER],
            "tool_choice": {
                "type": "allowed_tools",
                "mode": "auto",
                "tools": [{"type": "function", "name": "get_weather"}],
            },
        },
    )

    assert error["param"] == "tool_choice"


@pytest.mark.parametrize(
    ("effort", "think"),
    [
        (None, False),
        ("none", False),
        ("low", "low"),
        ("high", "high"),
        ("xhigh", "high"),
    ],
)
async def test_reasoning_effort_maps_to_think(
    client: AsyncClient,
    ollama_mock: OllamaMock,
    effort: str | None,
    think: bool | str,
) -> None:
    extra = {"reasoning": {"effort": effort}} if effort else {}

    sent = await _send(client, ollama_mock, extra)

    assert sent["think"] == think


async def test_logprobs_via_include(
    client: AsyncClient, ollama_mock: OllamaMock, validate_schema: Any
) -> None:
    ollama_mock.handler = lambda _: chat_response(
        "Hi",
        logprobs=[
            {
                "token": "Hi",
                "logprob": -0.1,
                "bytes": [72, 105],
                "top_logprobs": [{"token": "Hi", "logprob": -0.1, "bytes": [72]}],
            }
        ],
    )

    response = await client.post(
        "/v1/responses",
        json={**BASE, "include": ["message.output_text.logprobs"], "top_logprobs": 2},
    )

    sent = json.loads(ollama_mock.requests[-1].content)
    assert sent["logprobs"] is True
    assert sent["top_logprobs"] == 2
    logprobs = response.json()["output"][0]["content"][0]["logprobs"]
    assert logprobs[0]["token"] == "Hi"
    assert logprobs[0]["top_logprobs"][0]["token"] == "Hi"


async def test_logprobs_absent_by_default(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(client, ollama_mock, {"top_logprobs": 3})

    assert "logprobs" not in sent or sent["logprobs"] is None
    assert "top_logprobs" not in sent or sent["top_logprobs"] is None


async def test_truncation_auto_suppresses_overflow(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    ollama_mock.handler = lambda _: chat_response(prompt=32768 // 2 + 2)

    response = await client.post("/v1/responses", json={**BASE, "truncation": "auto"})

    assert response.status_code == 200
    assert response.json()["truncation"] == "auto"


async def test_ignored_options_are_accepted_and_metadata_echoed(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    ollama_mock.handler = lambda _: chat_response()

    response = await client.post(
        "/v1/responses",
        json={
            **BASE,
            "store": False,
            "metadata": {"k": "v"},
            "parallel_tool_calls": False,
            "user": "u",
            "max_tool_calls": 2,
            "service_tier": "auto",
            "safety_identifier": "s",
            "prompt_cache_key": "k",
            "stream_options": {"include_obfuscation": False},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"] == {"k": "v"}
    assert body["parallel_tool_calls"] is False


@pytest.mark.parametrize(
    "extra",
    [
        {"previous_response_id": "resp_1"},
        {"conversation": "conv_1"},
        {"background": True},
        {"prompt": {"id": "p"}},
        {"context_management": [{"type": "compaction"}]},
        {"moderation": {"model": "m"}},
    ],
)
async def test_rejected_options_return_400(
    client: AsyncClient, extra: dict[str, Any]
) -> None:
    error = await _error(client, extra)

    assert error["code"] == "unsupported_parameter"
    assert error["param"] == next(iter(extra))


@pytest.mark.parametrize(
    "extra",
    [
        {"previous_response_id": None},
        {"conversation": None},
        {"background": False},
        {"background": None},
        {"prompt": None},
        {"context_management": None},
        {"context_management": []},
        {"moderation": None},
        {"moderation": {}},
    ],
)
async def test_empty_values_of_rejected_options_are_accepted(
    client: AsyncClient, ollama_mock: OllamaMock, extra: dict[str, Any]
) -> None:
    await _send(client, ollama_mock, extra)


@pytest.mark.parametrize(
    ("item", "param"),
    [
        ({"type": "item_reference", "id": "x"}, "input"),
        ({"type": "web_search_call", "id": "x", "status": "completed"}, "input"),
        (
            {
                "role": "user",
                "content": [{"type": "input_image", "image_url": "https://x/y.png"}],
            },
            "input",
        ),
        (
            {"role": "user", "content": [{"type": "input_image", "file_id": "f"}]},
            "input",
        ),
        (
            {"role": "user", "content": [{"type": "input_file", "file_id": "f"}]},
            "input",
        ),
    ],
)
async def test_unsupported_input_items_return_400(
    client: AsyncClient, item: dict[str, Any], param: str
) -> None:
    error = await _error(client, {"input": [item]})

    assert error["code"] == "unsupported_parameter"
    assert error["param"] == param


async def test_reasoning_items_are_dropped(
    client: AsyncClient, ollama_mock: OllamaMock
) -> None:
    sent = await _send(
        client,
        ollama_mock,
        {
            "input": [
                {"type": "reasoning", "id": "rs_1", "summary": []},
                {"role": "user", "content": "Hi"},
            ]
        },
    )

    assert [m["role"] for m in sent["messages"]] == ["user"]

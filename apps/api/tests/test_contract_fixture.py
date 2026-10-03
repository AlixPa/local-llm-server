from collections.abc import Callable
from typing import Any

import pytest
from httpx import Request, Response
from openapi_core.exceptions import OpenAPIError

CHAT_REQUEST: dict[str, Any] = {
    "model": "llama3",
    "messages": [{"role": "user", "content": "hi"}],
}
CHAT_RESPONSE: dict[str, Any] = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "created": 1_700_000_000,
    "model": "llama3",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "hello", "refusal": None},
            "finish_reason": "stop",
            "logprobs": None,
        }
    ],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _exchange(
    request_json: dict[str, Any],
    response_json: dict[str, Any],
    status: int = 200,
    path: str = "/v1/chat/completions",
) -> Response:
    return Response(
        status,
        json=response_json,
        request=Request("POST", f"http://test{path}", json=request_json),
    )


def test_accepts_a_known_good_chat_completion(
    validate_contract: Callable[[Response], None],
) -> None:
    validate_contract(_exchange(CHAT_REQUEST, CHAT_RESPONSE))


def test_accepts_explicit_null_for_nullable_request_fields(
    validate_contract: Callable[[Response], None],
) -> None:
    request = {**CHAT_REQUEST, "max_completion_tokens": None, "frequency_penalty": None}
    validate_contract(_exchange(request, CHAT_RESPONSE))


def test_rejects_a_response_missing_required_fields(
    validate_contract: Callable[[Response], None],
) -> None:
    broken = {k: v for k, v in CHAT_RESPONSE.items() if k != "choices"}
    with pytest.raises(OpenAPIError):
        validate_contract(_exchange(CHAT_REQUEST, broken))


def test_rejects_a_request_with_a_wrong_type(
    validate_contract: Callable[[Response], None],
) -> None:
    request = {**CHAT_REQUEST, "temperature": "hot"}
    with pytest.raises(OpenAPIError):
        validate_contract(_exchange(request, CHAT_RESPONSE))


def test_rejects_a_path_the_spec_does_not_define(
    validate_contract: Callable[[Response], None],
) -> None:
    with pytest.raises(OpenAPIError):
        validate_contract(
            _exchange(CHAT_REQUEST, CHAT_RESPONSE, path="/v1/chat/completionz")
        )


def test_rejects_an_undocumented_status_code(
    validate_contract: Callable[[Response], None],
) -> None:
    with pytest.raises(OpenAPIError):
        validate_contract(_exchange(CHAT_REQUEST, CHAT_RESPONSE, status=418))

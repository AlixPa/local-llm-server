from collections.abc import Callable, Iterator
from typing import Any

import pytest
from api.errors import ApiError
from fastapi import FastAPI
from httpx import AsyncClient
from pydantic import BaseModel

ENVELOPE_KEYS = {"message", "type", "param", "code"}


class Body(BaseModel):
    count: int


@pytest.fixture(autouse=True)
def error_routes(test_app: FastAPI) -> Iterator[None]:
    async def typed(count: int) -> dict[str, int]:
        return {"count": count}

    async def boom() -> None:
        raise RuntimeError("boom")

    test_app.add_api_route("/v1/_test/typed", typed)

    async def api_error() -> None:
        raise ApiError(404, "invalid_request_error", "model_not_found", None, "nope")

    async def create(body: Body) -> Body:
        return body

    test_app.add_api_route("/v1/_test/boom", boom)
    test_app.add_api_route("/v1/_test/api-error", api_error)
    test_app.add_api_route("/v1/_test/body", create, methods=["POST"])
    yield
    test_app.router.routes[:] = [
        r for r in test_app.router.routes if "/_test/" not in getattr(r, "path", "")
    ]


async def _check(
    response: Any,
    validate_schema: Callable[[Any, str], None],
    status: int,
    type_: str,
    code: str | None,
) -> dict[str, Any]:
    assert response.status_code == status
    body = response.json()
    assert set(body["error"]) == ENVELOPE_KEYS
    assert body["error"]["type"] == type_
    assert body["error"]["code"] == code
    validate_schema(body, "ErrorResponse")
    error: dict[str, Any] = body["error"]
    return error


async def test_unknown_route(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.get("/v1/nope")
    await _check(response, validate_schema, 404, "invalid_request_error", "not_found")


async def test_wrong_method(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.post("/v1/health")
    await _check(
        response, validate_schema, 405, "invalid_request_error", "method_not_allowed"
    )


async def test_validation_error(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.get("/v1/_test/typed", params={"count": "abc"})
    error = await _check(
        response,
        validate_schema,
        422,
        "invalid_request_error",
        "unprocessable_content",
    )
    assert error["param"] == "count"


async def test_unhandled_exception(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.get("/v1/_test/boom")
    await _check(response, validate_schema, 500, "server_error", None)


async def test_api_error(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.get("/v1/_test/api-error")
    error = await _check(
        response, validate_schema, 404, "invalid_request_error", "model_not_found"
    )
    assert error["param"] is None
    assert error["message"] == "nope"


async def test_validation_error_on_openai_path_is_400(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.post("/v1/chat/completions", json={"messages": "abc"})
    error = await _check(response, validate_schema, 400, "invalid_request_error", None)
    assert error["param"] == "messages"


async def test_validation_error_on_other_path_stays_422(
    client: AsyncClient, validate_schema: Callable[[Any, str], None]
) -> None:
    response = await client.post("/v1/_test/body", json={"count": "abc"})
    await _check(
        response,
        validate_schema,
        422,
        "invalid_request_error",
        "unprocessable_content",
    )

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

ENVELOPE_KEYS = {"message", "type", "param", "code"}


@pytest.fixture(autouse=True)
def error_routes(test_app: FastAPI) -> Iterator[None]:
    async def typed(count: int) -> dict[str, int]:
        return {"count": count}

    async def boom() -> None:
        raise RuntimeError("boom")

    test_app.add_api_route("/v1/_test/typed", typed)
    test_app.add_api_route("/v1/_test/boom", boom)
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

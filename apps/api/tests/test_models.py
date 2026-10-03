from collections.abc import Callable

from httpx import AsyncClient, Response

type Contract = Callable[[Response], None]


async def test_list_models(client: AsyncClient, validate_contract: Contract) -> None:
    response = await client.get("/v1/models")

    validate_contract(response)
    body = response.json()
    assert body["object"] == "list"
    [model] = body["data"]
    assert model["id"] == "qwen3.5:9b"
    assert model["object"] == "model"
    assert model["created"] == 1767225600
    assert model["owned_by"] == "qwen"

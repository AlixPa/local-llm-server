from httpx import AsyncClient


async def test_health_ok(client: AsyncClient) -> None:
    response = await client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

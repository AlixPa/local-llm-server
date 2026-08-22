import httpx
from fastapi import APIRouter, Request, Response

from api.config.constants import OLLAMA_URL

completions_router = APIRouter(prefix="/completions")


@completions_router.post("")
async def chat_completions(request: Request):
    client: httpx.AsyncClient = request.app.state.http_client

    response = await client.post(
        f"{OLLAMA_URL}/v1/completions",
        content=await request.body(),
    )

    return Response(
        content=response.content,
        status_code=response.status_code,
        media_type=response.headers.get("content-type"),
    )

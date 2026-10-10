from collections.abc import AsyncGenerator
from typing import Annotated

from db.engine import get_session
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from llm.client import OllamaClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_ollama_client
from api.responses import service
from api.responses.schemas import CreateResponse, Response, ResponseStreamEvent

router = APIRouter()


async def _sse(events: AsyncGenerator[ResponseStreamEvent]) -> AsyncGenerator[str]:
    async for event in events:
        yield f"event: {event.type}\ndata: {event.model_dump_json()}\n\n"


# FastAPI can't derive a response model from the model-or-stream union
@router.post("/responses", response_model=None, responses={200: {"model": Response}})
async def create_response(
    body: CreateResponse,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    ollama: Annotated[OllamaClient, Depends(get_ollama_client)],
) -> Response | StreamingResponse:
    if body.stream:
        events = await service.start_stream(body, session=session, ollama=ollama)
        return StreamingResponse(_sse(events), media_type="text/event-stream")
    return await service.create_response(
        body, session=session, ollama=ollama, is_disconnected=request.is_disconnected
    )

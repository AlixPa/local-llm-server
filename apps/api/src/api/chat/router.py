from collections.abc import AsyncGenerator
from typing import Annotated

from db.engine import get_session
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from llm.client import OllamaClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.chat import service
from api.chat.schemas import CreateChatCompletionRequest, CreateChatCompletionResponse
from api.dependencies import get_ollama_client

router = APIRouter()


async def _sse(events: AsyncGenerator[service.StreamEvent]) -> AsyncGenerator[str]:
    async for event in events:
        yield f"data: {event.model_dump_json(exclude_unset=True)}\n\n"
    yield "data: [DONE]\n\n"


# FastAPI can't derive a response model from the model-or-stream union
@router.post(
    "/chat/completions",
    response_model=None,
    responses={200: {"model": CreateChatCompletionResponse}},
)
async def create_chat_completion(
    body: CreateChatCompletionRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    ollama: Annotated[OllamaClient, Depends(get_ollama_client)],
) -> CreateChatCompletionResponse | StreamingResponse:
    if body.stream:
        events = await service.start_stream(body, session=session, ollama=ollama)
        return StreamingResponse(_sse(events), media_type="text/event-stream")
    return await service.create_chat_completion(
        body, session=session, ollama=ollama, is_disconnected=request.is_disconnected
    )

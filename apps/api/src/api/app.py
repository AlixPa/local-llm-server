from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from db.engine import get_async_session_factory
from db.repositories import tracing as tracing_repo
from fastapi import APIRouter, FastAPI
from llm.client import OllamaClient
from llm.config import OllamaSettings

from api.analytics import router as analytics_router
from api.chat import router as chat_router
from api.errors import register_error_handlers
from api.health import router as health_router
from api.logging import configure_logging
from api.models import router as models_router
from api.observability.tracing import TracingMiddleware, hub, writer

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with get_async_session_factory()() as session:
        await tracing_repo.mark_in_progress_interrupted(session)
    hub.open()
    writer.start()
    try:
        async with httpx.AsyncClient() as http_client:
            app.state.ollama_client = OllamaClient(http_client, OllamaSettings())
            yield
    finally:
        hub.close()
        await writer.stop()


app = FastAPI(lifespan=lifespan)
register_error_handlers(app)
app.add_middleware(TracingMiddleware)

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(chat_router)
v1_router.include_router(models_router)
v1_router.include_router(analytics_router)
app.include_router(v1_router)

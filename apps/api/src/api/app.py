from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI
from llm.client import OllamaClient
from llm.config import OllamaSettings

from api.analytics import router as analytics_router
from api.chat import router as chat_router
from api.errors import register_error_handlers
from api.health import router as health_router
from api.logging import configure_logging
from api.models import router as models_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient() as http_client:
        app.state.ollama_client = OllamaClient(http_client, OllamaSettings())
        yield


app = FastAPI(lifespan=lifespan)
register_error_handlers(app)

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
v1_router.include_router(chat_router)
v1_router.include_router(models_router)
v1_router.include_router(analytics_router)
app.include_router(v1_router)

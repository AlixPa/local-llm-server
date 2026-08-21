from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, FastAPI

from api.batches import batches_router
from api.chat import chat_completions_router
from api.completions import completions_router
from api.files import files_router
from api.health import health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0),
    )
    yield
    await app.state.http_client.aclose()


app = FastAPI(lifespan=lifespan)

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(batches_router)
v1_router.include_router(chat_completions_router)
v1_router.include_router(completions_router)
v1_router.include_router(files_router)

app.include_router(v1_router)
app.include_router(health_router)

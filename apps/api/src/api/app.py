from fastapi import APIRouter, FastAPI

from api.errors import register_error_handlers
from api.health import router as health_router
from api.logging import configure_logging

configure_logging()

app = FastAPI()
register_error_handlers(app)

v1_router = APIRouter(prefix="/v1")
v1_router.include_router(health_router)
app.include_router(v1_router)

from fastapi import APIRouter

from api.health.schemas import HealthResponse

router = APIRouter()


@router.get("/health")
async def get_health() -> HealthResponse:
    return HealthResponse(status="ok")

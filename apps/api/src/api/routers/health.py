from fastapi import APIRouter, Request

health_router = APIRouter(prefix="/health")


@health_router.get("")
async def get_health(request: Request):
    return {"status": "ok"}

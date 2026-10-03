import http
import logging
import re

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class Error(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str
    type: str
    param: str | None
    code: str | None


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    error: Error


def _code_for(status_code: int) -> str | None:
    try:
        phrase = http.HTTPStatus(status_code).phrase
    except ValueError:
        return None
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_")


def _type_for(status_code: int) -> str:
    return "server_error" if status_code >= 500 else "invalid_request_error"


def _response(
    status_code: int,
    message: str,
    *,
    param: str | None = None,
    code: str | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=Error(
            message=message, type=_type_for(status_code), param=param, code=code
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _response(
            exc.status_code, str(exc.detail), code=_code_for(exc.status_code)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        first = exc.errors()[0]
        param = str(first["loc"][-1]) if first["loc"] else None
        return _response(422, first["msg"], param=param, code=_code_for(422))

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("unhandled exception", exc_info=exc)
        return _response(500, "Internal server error")

from collections.abc import AsyncGenerator

import httpx
from pydantic import ValidationError

from llm.config import OllamaSettings
from llm.schemas import (
    OllamaChatChunk,
    OllamaChatRequest,
    OllamaChatResponse,
    OllamaErrorBody,
)

# Model loads and long generations take minutes, so only the connect is bounded
_TIMEOUT = httpx.Timeout(None, connect=5.0)


class OllamaUnreachableError(Exception):
    pass


class OllamaModelNotFoundError(Exception):
    pass


class OllamaServerError(Exception):
    pass


def _error_message(body: bytes) -> str:
    try:
        return OllamaErrorBody.model_validate_json(body).error
    except ValidationError:
        return body.decode(errors="replace") or "Ollama request failed"


def _raise_for_status(response: httpx.Response, body: bytes) -> None:
    if response.status_code == 404:
        raise OllamaModelNotFoundError(_error_message(body))
    if response.status_code >= 400:
        raise OllamaServerError(_error_message(body))


class OllamaClient:
    def __init__(self, client: httpx.AsyncClient, settings: OllamaSettings) -> None:
        self._client = client
        self.num_ctx = settings.num_ctx
        self._url = f"{settings.host.rstrip('/')}/api/chat"

    def _body(self, request: OllamaChatRequest, *, stream: bool) -> bytes:
        return (
            request.model_copy(update={"stream": stream})
            .model_dump_json(exclude_none=True)
            .encode()
        )

    async def chat(self, request: OllamaChatRequest) -> OllamaChatResponse:
        try:
            response = await self._client.post(
                self._url,
                content=self._body(request, stream=False),
                headers={"Content-Type": "application/json"},
                timeout=_TIMEOUT,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise OllamaUnreachableError(str(exc)) from exc
        _raise_for_status(response, response.content)
        return _parse(OllamaChatResponse, response.content)

    async def chat_stream(
        self, request: OllamaChatRequest
    ) -> AsyncGenerator[OllamaChatChunk]:
        try:
            async with self._client.stream(
                "POST",
                self._url,
                content=self._body(request, stream=True),
                headers={"Content-Type": "application/json"},
                timeout=_TIMEOUT,
            ) as response:
                if response.status_code >= 400:
                    _raise_for_status(response, await response.aread())
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    if '"error"' in line and _is_error(line):
                        raise OllamaServerError(_error_message(line.encode()))
                    yield _parse(OllamaChatChunk, line.encode())
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise OllamaUnreachableError(str(exc)) from exc


def _is_error(line: str) -> bool:
    try:
        OllamaErrorBody.model_validate_json(line)
    except ValidationError:
        return False
    return True


def _parse[T: OllamaChatChunk](model: type[T], body: bytes) -> T:
    try:
        return model.model_validate_json(body)
    except ValidationError as exc:
        raise OllamaServerError(f"Unexpected Ollama response: {exc}") from exc

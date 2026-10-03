from db.engine import get_session
from fastapi import Request
from llm.client import OllamaClient

__all__ = ["get_ollama_client", "get_session"]


def get_ollama_client(request: Request) -> OllamaClient:
    client: OllamaClient = request.app.state.ollama_client
    return client

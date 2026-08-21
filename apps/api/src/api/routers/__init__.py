from .batches import batches_router
from .chat_completions import chat_completions_router
from .completions import completions_router
from .files import files_router
from .health import health_router

__all__ = [
    "batches_router",
    "chat_completions_router",
    "completions_router",
    "files_router",
    "health_router",
]

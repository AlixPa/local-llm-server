from .base import Storage
from .local import LocalStorage


def get_storage() -> Storage:
    return LocalStorage()

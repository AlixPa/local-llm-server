from typing import Protocol
from uuid import UUID

from fastapi import UploadFile

from .models import StoredFileMetadata


class Storage(Protocol):
    async def save_batch_input_file(
        self, file_id: UUID, file: UploadFile
    ) -> StoredFileMetadata: ...

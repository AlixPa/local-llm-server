from enum import StrEnum
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from .models import StoredFileMetadata


class FileType(StrEnum):
    BATCH_INPUT = "BATCH_INPUT"


class Paths:
    def __init__(self, root_path: Path) -> None:
        self._data = root_path / "data"
        self._batch_input_files = self._data / "batch_input_files"

    def ensure_dirs(self) -> None:
        self._data.mkdir(parents=True, exist_ok=True)
        self._batch_input_files.mkdir(parents=True, exist_ok=True)

    def build_file_metadata(self, filename: str, type: FileType) -> tuple[Path, str]:
        """Build the path and storage_key of the file depending on its type"""
        match type:
            case FileType.BATCH_INPUT:
                return (
                    self._batch_input_files / filename,
                    f"{self._batch_input_files.name}/{filename}",
                )


paths = Paths(Path(__file__).resolve().parents[5])
paths.ensure_dirs()


class LocalStorage:
    async def save_batch_input_file(
        self, file_id: UUID, file: UploadFile
    ) -> StoredFileMetadata:
        stored_filename = f"{file_id.hex}.jsonl"
        destination_path, storage_key = paths.build_file_metadata(
            filename=stored_filename, type=FileType.BATCH_INPUT
        )

        size_bytes = 0
        with destination_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                destination.write(chunk)
                size_bytes += len(chunk)

        return StoredFileMetadata(
            path=destination_path, storage_key=storage_key, size_bytes=size_bytes
        )

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredFileMetadata:
    path: Path
    storage_key: str
    size_bytes: int

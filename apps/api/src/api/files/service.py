from uuid import uuid7

from db.models import File as DbFile
from db.models.files import Format, Purpose
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from api.storage import Storage

from .schemas import FileObject


async def create_file(
    file: UploadFile, purpose: Purpose, session: AsyncSession, storage: Storage
) -> FileObject:
    file_id = uuid7()

    stored_file_metadata = await storage.save_batch_input_file(file_id, file)

    batch_input_file = DbFile(
        file_id=file_id,
        size_bytes=stored_file_metadata.size_bytes,
        original_filename=file.filename,
        storage_key=stored_file_metadata.storage_key,
        format=Format.JSONL,
        purpose=purpose,
    )
    session.add(batch_input_file)
    await session.commit()

    return FileObject(
        id=batch_input_file.file_id.hex,
        object="file",
        bytes=batch_input_file.size_bytes,
        created_at=int(batch_input_file.created_at.timestamp()),
        filename=batch_input_file.original_filename or "unknown",
        purpose=batch_input_file.purpose,
    )

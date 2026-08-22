from typing import Annotated

from db.engine import get_session
from db.models.files import Purpose
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from api.storage import Storage, get_storage

from .schemas import FileObject
from .service import create_file

files_router = APIRouter(prefix="/files")


@files_router.post("", response_model=FileObject)
async def create_file_endpoint(
    file: Annotated[UploadFile, File()],
    purpose: Annotated[Purpose, Form()],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[Storage, Depends(get_storage)],
) -> FileObject:
    return await create_file(file, purpose, session, storage)

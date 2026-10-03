from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from db.models.base import Base
from db.types import UtcDateTime


class Model(Base):
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    owned_by: Mapped[str]

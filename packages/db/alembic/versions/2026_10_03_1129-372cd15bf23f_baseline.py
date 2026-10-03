"""baseline

Revision ID: 372cd15bf23f
Revises:
Create Date: 2026-10-03 11:29:18.889695

"""

from collections.abc import Sequence

revision: str = "372cd15bf23f"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

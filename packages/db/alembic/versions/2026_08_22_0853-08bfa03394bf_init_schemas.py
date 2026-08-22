"""init schemas

Revision ID: 08bfa03394bf
Revises:
Create Date: 2026-08-22 08:53:03.154250

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "08bfa03394bf"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS app")
    op.execute("CREATE SCHEMA IF NOT EXISTS core")


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS core")
    op.execute("DROP SCHEMA IF EXISTS app")

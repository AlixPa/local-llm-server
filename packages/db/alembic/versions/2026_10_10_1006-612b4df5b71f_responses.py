"""responses

Revision ID: 612b4df5b71f
Revises: a6cd24351db8
Create Date: 2026-10-10 10:06:32.461023

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from db.types import UtcDateTime

# revision identifiers, used by Alembic.
revision: str = "612b4df5b71f"
down_revision: str | Sequence[str] | None = "a6cd24351db8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "response_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("created_at", UtcDateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "succeeded",
                "failed",
                "cancelled",
                name="requeststatus",
                native_enum=False,
                length=16,
            ),
            nullable=False,
        ),
        sa.Column("stream", sa.Boolean(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("time_to_first_token_ms", sa.Integer(), nullable=True),
        sa.Column("generation_duration_ms", sa.Integer(), nullable=True),
        sa.Column("load_duration_ms", sa.Integer(), nullable=True),
        sa.Column("finish_reason", sa.String(), nullable=True),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_response_records")),
        sa.UniqueConstraint(
            "external_id", name=op.f("uq_response_records_external_id")
        ),
    )
    op.create_table(
        "response_contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("request", sa.JSON(), nullable=False),
        sa.Column("response", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["response_records.id"],
            name=op.f("fk_response_contents_record_id_response_records"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_response_contents")),
        sa.UniqueConstraint("record_id", name=op.f("uq_response_contents_record_id")),
    )
    op.drop_index("ix_chat_completion_records_created_at_id", "chat_completion_records")

    op.create_index(
        "ix_chat_completion_records_created_at_external_id",
        "chat_completion_records",
        [sa.text("created_at DESC"), sa.text("external_id DESC")],
    )
    op.create_index(
        "ix_response_records_created_at_external_id",
        "response_records",
        [sa.text("created_at DESC"), sa.text("external_id DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_response_records_created_at_external_id", "response_records")
    op.drop_index(
        "ix_chat_completion_records_created_at_external_id", "chat_completion_records"
    )
    op.create_index(
        "ix_chat_completion_records_created_at_id",
        "chat_completion_records",
        [sa.text("created_at DESC"), sa.text("id DESC")],
    )
    op.drop_table("response_contents")
    op.drop_table("response_records")

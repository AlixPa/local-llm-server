"""observability

Revision ID: a6cd24351db8
Revises: 14214498735f
Create Date: 2026-10-03 23:31:49.651064

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from db.types import UtcDateTime

# revision identifiers, used by Alembic.
revision: str = "a6cd24351db8"
down_revision: str | Sequence[str] | None = "14214498735f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "traced_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("started_at", UtcDateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column(
            "outcome",
            sa.Enum(
                "in_progress",
                "success",
                "error",
                "canceled",
                "interrupted",
                name="traceoutcome",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("summary", sa.String(), nullable=True),
        sa.Column("response_id", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_traced_requests")),
    )
    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "request_received",
                "sent_to_ollama",
                "received_from_ollama",
                "response_returned",
                "error",
                name="stepkind",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "client",
                "api",
                "ollama",
                name="participant",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "destination",
            sa.Enum(
                "client",
                "api",
                "ollama",
                name="participant",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "in_progress",
                "completed",
                "failed",
                "canceled",
                "interrupted",
                name="stepstatus",
                native_enum=False,
                length=24,
            ),
            nullable=False,
        ),
        sa.Column("started_at", UtcDateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("content", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["traced_requests.id"],
            name=op.f("fk_workflow_steps_request_id_traced_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_steps")),
        sa.UniqueConstraint(
            "request_id", "position", name=op.f("uq_workflow_steps_request_id")
        ),
    )
    with op.batch_alter_table("workflow_steps", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_workflow_steps_request_id"), ["request_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("workflow_steps", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workflow_steps_request_id"))

    op.drop_table("workflow_steps")
    op.drop_table("traced_requests")

"""Persist invention plans and requested market valuations."""

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "invention_plans",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("plans", sa.JSON(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "invention_requests",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("result", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_type", sa.String(), nullable=True),
    )
    op.create_index("ix_invention_requests_expires_at", "invention_requests", ["expires_at"])


def downgrade() -> None:
    op.drop_table("invention_requests")
    op.drop_table("invention_plans")

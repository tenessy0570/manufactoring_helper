"""Cache public market item names and transport volumes."""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_metadata",
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("volume_m3", sa.Numeric(24, 8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_trade_metadata_expires_at", "trade_metadata", ["expires_at"])


def downgrade() -> None:
    op.drop_table("trade_metadata")

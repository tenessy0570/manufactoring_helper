"""Store daily regional trading history and refresh state."""

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "market_history",
        sa.Column("region_id", sa.Integer(), primary_key=True),
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("average", sa.Numeric(38, 12), nullable=False),
        sa.Column("highest", sa.Numeric(38, 12), nullable=False),
        sa.Column("lowest", sa.Numeric(38, 12), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("order_count", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "market_history_states",
        sa.Column("region_id", sa.Integer(), primary_key=True),
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_history")
    op.drop_table("market_history_states")

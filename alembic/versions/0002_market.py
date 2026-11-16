"""Store independent price snapshots for public trade hubs."""

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "market_prices",
        sa.Column("hub_id", sa.String(), primary_key=True),
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("buy_price", sa.Numeric(24, 2), nullable=True),
        sa.Column("sell_price", sa.Numeric(24, 2), nullable=True),
        sa.Column("buy_volume", sa.BigInteger(), nullable=False),
        sa.Column("sell_volume", sa.BigInteger(), nullable=False),
        sa.Column("spread", sa.Numeric(24, 2), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_market_prices_expires_at", "market_prices", ["expires_at"])
    op.create_table(
        "market_states",
        sa.Column("hub_id", sa.String(), primary_key=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("items", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_prices")
    op.drop_table("market_states")

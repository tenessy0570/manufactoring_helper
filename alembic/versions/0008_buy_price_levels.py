"""Persist aggregated station buy price levels for configurable demand valuation."""

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("market_prices", sa.Column("buy_levels", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("market_prices", "buy_levels")

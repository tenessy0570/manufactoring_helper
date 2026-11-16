"""Expose order concentration alongside best-price volumes."""

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None

COLUMNS = ("buy_order_count", "sell_order_count", "buy_orders_at_best", "sell_orders_at_best")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("market_prices", sa.Column(name, sa.Integer(), nullable=True))


def downgrade() -> None:
    for name in reversed(COLUMNS):
        op.drop_column("market_prices", name)

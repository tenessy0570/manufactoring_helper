"""Store sell order price levels."""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_prices", sa.Column("sell_levels", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("market_prices", "sell_levels")

"""Remove unused persisted production blueprint runs."""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("productions", "actual_runs")


def downgrade() -> None:
    op.add_column("productions", sa.Column("actual_runs", sa.Integer(), nullable=True))

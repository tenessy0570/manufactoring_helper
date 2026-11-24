"""Track actual production units separately from the original plan."""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("productions", sa.Column("actual_units", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("productions", "actual_units")

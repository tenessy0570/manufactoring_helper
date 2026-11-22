"""Persist per-user opportunity exclusions."""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_opportunity_exclusions",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("items", sa.JSON(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("user_opportunity_exclusions")

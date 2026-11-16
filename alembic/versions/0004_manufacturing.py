"""Cache public manufacturing recipes and refresh state."""

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "manufacturing_recipes",
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("recipe", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("manufacturing_recipes")

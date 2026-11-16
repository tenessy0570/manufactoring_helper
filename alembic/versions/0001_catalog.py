"""Create the manufacturing candidate catalog."""

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "item_types",
        sa.Column("type_id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("market_group_id", sa.Integer(), nullable=False),
        sa.Column("market_group_name", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("group_path", sa.JSON(), nullable=False),
        sa.Column("is_rig", sa.Boolean(), nullable=False),
        sa.Column("meta_group_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "name",
        "market_group_id",
        "category",
        "is_rig",
        "meta_group_id",
        "is_active",
        "synced_at",
    ):
        op.create_index(f"ix_item_types_{column}", "item_types", [column])


def downgrade() -> None:
    op.drop_table("item_types")

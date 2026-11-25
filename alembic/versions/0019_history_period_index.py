"""Index regional history windows without blocking background history writes."""

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(
                "ix_history_region_date_type",
                "market_history",
                ["region_id", "date", "type_id"],
                postgresql_include=["average", "volume"],
                postgresql_concurrently=True,
            )
    else:
        op.create_index(
            "ix_history_region_date_type", "market_history", ["region_id", "date", "type_id"]
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(
                "ix_history_region_date_type",
                table_name="market_history",
                postgresql_concurrently=True,
            )
    else:
        op.drop_index("ix_history_region_date_type", table_name="market_history")

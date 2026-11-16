"""Persist calculation profiles and one default selection."""

from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    profiles = op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    default = op.create_table(
        "profile_default",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_id", sa.Uuid(), sa.ForeignKey("profiles.id"), nullable=False),
        sa.CheckConstraint("id = 1", name="singleton"),
    )
    now = datetime.now(UTC)
    profile_id = UUID("00000000-0000-0000-0000-000000000001")
    op.bulk_insert(
        profiles,
        [
            {
                "id": profile_id,
                "name": "Default",
                "settings": {
                    "material_order_type": "sell",
                    "product_order_type": "sell",
                    "sales_tax": "0",
                    "broker_fee": "0",
                },
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(default, [{"id": 1, "profile_id": profile_id}])


def downgrade() -> None:
    op.drop_table("profile_default")
    op.drop_table("profiles")

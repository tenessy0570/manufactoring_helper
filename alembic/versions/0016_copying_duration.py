"""Refresh legacy cached invention plans to include copying duration."""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE invention_plans SET expires_at = '2000-01-01' "
        "WHERE CAST(plans AS TEXT) NOT LIKE '%copying_seconds_per_run%'"
    )
    op.execute(
        "UPDATE invention_requests SET expires_at = '2000-01-01' "
        "WHERE result IS NOT NULL AND CAST(result AS TEXT) NOT LIKE '%copying_seconds_per_run%'"
    )


def downgrade() -> None:
    pass

"""Refresh legacy cached invention plans to include duration."""

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE invention_plans SET expires_at = '2000-01-01' "
        "WHERE CAST(plans AS TEXT) NOT LIKE '%seconds_per_attempt%'"
    )
    op.execute(
        "UPDATE invention_requests SET expires_at = '2000-01-01' "
        "WHERE result IS NOT NULL AND CAST(result AS TEXT) NOT LIKE '%seconds_per_attempt%'"
    )


def downgrade() -> None:
    pass

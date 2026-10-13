"""weather_snapshot

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weather_snapshot",
        sa.Column("tm", sa.Text(), primary_key=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stations", postgresql.JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("weather_snapshot")

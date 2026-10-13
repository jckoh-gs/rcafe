"""collection_request

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "collection_request",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("cell_key", sa.Text(), nullable=False, unique=True),
        sa.Column("center_lat", sa.Float(), nullable=False),
        sa.Column("center_lng", sa.Float(), nullable=False),
        sa.Column("radius_m", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cafes_found", sa.Integer()),
        sa.Column("note", sa.Text()),
    )
    op.create_index("ix_collection_request_status", "collection_request", ["status"])


def downgrade() -> None:
    op.drop_index("ix_collection_request_status", table_name="collection_request")
    op.drop_table("collection_request")

"""cafe, cafe_menu, cafe_review

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")  # used from the taste milestone on
    op.create_table(
        "cafe",
        sa.Column("place_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("road_address", sa.Text()),
        sa.Column("jibun_address", sa.Text()),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rank_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("has_booking", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("phone", sa.Text()),
        sa.Column("rating", sa.Float()),
        sa.Column("micro_review", sa.Text()),
        sa.Column("business_status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("business_status_text", sa.Text()),
        sa.Column("business_hours", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("cover_photo_url", sa.Text()),
        sa.Column("photo_urls", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("conveniences", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("menu_mentions", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detail_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("last_crawled_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cafe_lat_lng", "cafe", ["lat", "lng"])
    op.create_index("ix_cafe_detail_fetched_at", "cafe", ["detail_fetched_at"])
    op.create_table(
        "cafe_menu",
        sa.Column(
            "place_id",
            sa.Text(),
            sa.ForeignKey("cafe.place_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("menu_key", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price", sa.Integer()),
        sa.Column("description", sa.Text()),
        sa.Column("image_url", sa.Text()),
        sa.Column("mention_count", sa.Integer()),
    )
    op.create_table(
        "cafe_review",
        sa.Column(
            "place_id",
            sa.Text(),
            sa.ForeignKey("cafe.place_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("review_key", sa.Text(), primary_key=True),
        sa.Column("rating", sa.SmallInteger()),
        sa.Column("text_snippet", sa.Text(), nullable=False),
        sa.Column("raw_body", sa.Text()),
        sa.Column("visited_label", sa.Text()),
        sa.Column("ordered_item", sa.Text()),
        sa.Column("photo_url", sa.Text()),
        sa.Column("voted_keywords", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("is_noise", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("taste_tags", postgresql.JSONB()),
    )


def downgrade() -> None:
    op.drop_table("cafe_review")
    op.drop_table("cafe_menu")
    op.drop_index("ix_cafe_detail_fetched_at", table_name="cafe")
    op.drop_index("ix_cafe_lat_lng", table_name="cafe")
    op.drop_table("cafe")

"""menu position, cafe_taste, taste_axis_stats, taste_archetype

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cafe_menu", sa.Column("position", sa.Integer()))
    op.create_table(
        "cafe_taste",
        sa.Column(
            "place_id",
            sa.Text(),
            sa.ForeignKey("cafe.place_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("taste_vec", Vector(10), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_weight", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "taste_axis_stats",
        sa.Column("axis", sa.Text(), primary_key=True),
        sa.Column("mean", sa.Float(), nullable=False),
        sa.Column("scale", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "taste_archetype",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("name_ko", sa.Text(), nullable=False),
        sa.Column("feels_like", sa.Float(), nullable=False),
        sa.Column("raining", sa.Boolean(), nullable=False),
        sa.Column("hour", sa.Integer(), nullable=False),
        sa.Column("weather_vec", Vector(6), nullable=False),
        sa.Column("taste_vec", Vector(10), nullable=False),
    )
    op.create_index(
        "ix_taste_archetype_weather_vec",
        "taste_archetype",
        ["weather_vec"],
        postgresql_using="hnsw",
        postgresql_ops={"weather_vec": "vector_l2_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_taste_archetype_weather_vec", table_name="taste_archetype")
    op.drop_table("taste_archetype")
    op.drop_table("taste_axis_stats")
    op.drop_table("cafe_taste")
    op.drop_column("cafe_menu", "position")

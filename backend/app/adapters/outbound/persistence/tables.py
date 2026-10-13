"""SQLAlchemy Core table definitions (kept in sync with migrations/)."""

from __future__ import annotations

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

cafe = Table(
    "cafe",
    metadata,
    Column("place_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("category", Text, nullable=False, server_default=""),
    Column("lat", Float, nullable=False),
    Column("lng", Float, nullable=False),
    Column("road_address", Text),
    Column("jibun_address", Text),
    Column("review_count", Integer, nullable=False, server_default="0"),
    Column("rank_score", Float, nullable=False, server_default="0"),
    Column("has_booking", Boolean, nullable=False, server_default="false"),
    # detail (filled by the second crawl phase)
    Column("phone", Text),
    Column("rating", Float),
    Column("micro_review", Text),
    Column("business_status", Text, nullable=False, server_default="unknown"),
    Column("business_status_text", Text),
    Column("business_hours", JSONB, nullable=False, server_default="[]"),
    Column("cover_photo_url", Text),
    Column("photo_urls", JSONB, nullable=False, server_default="[]"),
    Column("conveniences", JSONB, nullable=False, server_default="[]"),
    Column("menu_mentions", JSONB, nullable=False, server_default="[]"),
    Column("content_hash", Text),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("detail_fetched_at", DateTime(timezone=True)),
    Column("last_crawled_at", DateTime(timezone=True), nullable=False),
    Index("ix_cafe_lat_lng", "lat", "lng"),
    Index("ix_cafe_detail_fetched_at", "detail_fetched_at"),
)

cafe_menu = Table(
    "cafe_menu",
    metadata,
    Column("place_id", Text, ForeignKey("cafe.place_id", ondelete="CASCADE"), primary_key=True),
    Column("menu_key", Text, primary_key=True),
    Column("position", Integer),
    Column("name", Text, nullable=False),
    Column("price", Integer),
    Column("description", Text),
    Column("image_url", Text),
    Column("mention_count", Integer),
)

cafe_review = Table(
    "cafe_review",
    metadata,
    Column("place_id", Text, ForeignKey("cafe.place_id", ondelete="CASCADE"), primary_key=True),
    Column("review_key", Text, primary_key=True),
    Column("rating", SmallInteger),
    Column("text_snippet", Text, nullable=False),
    # Full text is kept only until taste tagging has run, then purged (policy: tags + snippet).
    Column("raw_body", Text),
    Column("visited_label", Text),
    Column("ordered_item", Text),
    Column("photo_url", Text),
    Column("voted_keywords", JSONB, nullable=False, server_default="[]"),
    Column("is_noise", Boolean, nullable=False, server_default="false"),
    Column("taste_tags", JSONB),
)

cafe_taste = Table(
    "cafe_taste",
    metadata,
    Column("place_id", Text, ForeignKey("cafe.place_id", ondelete="CASCADE"), primary_key=True),
    Column("taste_vec", Vector(10), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("evidence_weight", Float, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

taste_axis_stats = Table(
    "taste_axis_stats",
    metadata,
    Column("axis", Text, primary_key=True),
    Column("mean", Float, nullable=False),
    Column("scale", Float, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

taste_archetype = Table(
    "taste_archetype",
    metadata,
    Column("key", Text, primary_key=True),
    Column("name_ko", Text, nullable=False),
    Column("feels_like", Float, nullable=False),
    Column("raining", Boolean, nullable=False),
    Column("hour", Integer, nullable=False),
    Column("weather_vec", Vector(6), nullable=False),
    Column("taste_vec", Vector(10), nullable=False),
    Index(
        "ix_taste_archetype_weather_vec",
        "weather_vec",
        postgresql_using="hnsw",
        postgresql_ops={"weather_vec": "vector_l2_ops"},
    ),
)

collection_request = Table(
    "collection_request",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("cell_key", Text, nullable=False, unique=True),
    Column("center_lat", Float, nullable=False),
    Column("center_lng", Float, nullable=False),
    Column("radius_m", Integer, nullable=False),
    Column("status", Text, nullable=False, server_default="pending"),
    Column("request_count", Integer, nullable=False, server_default="1"),
    Column("requested_at", DateTime(timezone=True), nullable=False),
    Column("last_requested_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True)),
    Column("finished_at", DateTime(timezone=True)),
    Column("cafes_found", Integer),
    Column("note", Text),
    Index("ix_collection_request_status", "status"),
)

weather_snapshot = Table(
    "weather_snapshot",
    metadata,
    Column("tm", Text, primary_key=True),
    Column("fetched_at", DateTime(timezone=True), nullable=False),
    Column("stations", JSONB, nullable=False),
)

__all__ = [
    "cafe",
    "cafe_menu",
    "cafe_review",
    "cafe_taste",
    "collection_request",
    "metadata",
    "taste_archetype",
    "taste_axis_stats",
    "weather_snapshot",
]

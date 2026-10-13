#!/usr/bin/env bash
# Prepares the collected data for the cluster and writes a gzipped data-only SQL dump.
#   1. recompute cafe tastes and seed the weather scenarios
#   2. drop the temporary full review text (policy: keep tags + a 200-character snippet only)
#   3. clear implausible menu prices left by older parsers
#   4. dump the tables the service reads (not weather snapshots)
# Usage: scripts/export_data.sh [output.sql.gz]
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=${1:-/tmp/aicafe-data.sql.gz}
export AICAFE_DATABASE_URL=${AICAFE_DATABASE_URL:-postgresql+asyncpg://aicafe:aicafe@localhost:55432/aicafe}
DB_CONTAINER=${DB_CONTAINER:-aicafe-db-1}

uv run python -m app.adapters.inbound.cli seed-archetypes
uv run python -m app.adapters.inbound.cli taste
uv run python -m app.adapters.inbound.cli purge-review-text
docker exec "$DB_CONTAINER" psql -U aicafe -d aicafe -v ON_ERROR_STOP=1 \
  -c "update cafe_menu set price = null where price > 1000000"
# pg_dump from the same major version as the cluster database (pgvector/pgvector:pg16).
docker exec "$DB_CONTAINER" pg_dump -U aicafe -d aicafe --data-only --no-owner \
  -t cafe -t cafe_menu -t cafe_review -t cafe_taste -t taste_axis_stats -t taste_archetype \
  | gzip > "$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"

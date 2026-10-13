#!/usr/bin/env bash
# Yeoksam crawl, resumable and polite: grid discovery (~2 km), then details for every cafe that
# has none (or stale ones). Search every ~2 s, detail pages every ~3 s. Safe to rerun.
set -euo pipefail
cd "$(dirname "$0")/.."
export AICAFE_DATABASE_URL=${AICAFE_DATABASE_URL:-postgresql+asyncpg://aicafe:aicafe@localhost:55432/aicafe}
uv run python -m app.adapters.inbound.cli discover
uv run python -m app.adapters.inbound.cli details --limit 5000

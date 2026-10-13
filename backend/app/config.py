"""Runtime settings read from environment variables (never hardcode secrets)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AICAFE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://aicafe:aicafe@localhost:55432/aicafe"
    # Seconds between requests per host. Slow on purpose: Naver throttled us at 1 request/second.
    naver_search_interval_s: float = 2.0
    naver_detail_interval_s: float = 3.0
    naver_timeout_s: float = 30.0
    # Yeoksam Station
    center_lat: float = 37.5006431
    center_lng: float = 127.0363766
    radius_m: float = 2000.0
    spacing_m: float = 400.0
    review_limit: int = 10

    # Weather (KMA API Hub). The key is a secret: set AICAFE_KMA_AUTH_KEY, never commit it.
    kma_auth_key: str = ""
    kma_stations_csv: str = "data/kma_stations.csv"
    # Web
    cors_origins: list[str] = ["http://localhost:5173"]
    recommendation_cache_ttl_s: float = 600.0
    default_radius_m: float = 1000.0

    # Administrator page (collection requests). All three come from the Secret `aicafe-backend`;
    # with any of them missing the admin API answers 404 as if it did not exist.
    admin_user: str = ""
    admin_password: str = ""
    admin_session_key: str = ""
    admin_session_hours: float = 8.0
    # The CronJob a manual "run now" copies its Job from.
    collector_cronjob: str = "aicafe-collector"

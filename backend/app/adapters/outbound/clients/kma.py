"""KMA API Hub client: hourly surface observations (kma_sfctm2) with snapshot reuse.

One call returns every station for one hour, so the snapshot is cached per hour (in memory and
in the database) and shared by all requests. The API has a small call quota.
"""

from __future__ import annotations

import asyncio
import csv
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import httpx

from app.domain.models import GeoPoint, Station
from app.domain.services import haversine_m
from app.domain.weather import WeatherObservation

log = logging.getLogger(__name__)
# httpx logs full request URLs at INFO; ours contain the auth key, so keep that logger quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

KST = timezone(timedelta(hours=9))
SFCTM2_URL = "https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"
MAX_STATION_KM = 40.0
MAX_FALLBACK_HOURS = 3
CURRENT_HOUR_TIMEOUT_S = 8.0
NEGATIVE_CACHE_S = 300.0
# Column names in the order documented by `help=1` (46 columns).
COLUMNS = [
    "TM",
    "STN",
    "WD",
    "WS",
    "GST_WD",
    "GST_WS",
    "GST_TM",
    "PA",
    "PS",
    "PT",
    "PR",
    "TA",
    "TD",
    "HM",
    "PV",
    "RN",
    "RN_DAY",
    "RN_JUN",
    "RN_INT",
    "SD_HR3",
    "SD_DAY",
    "SD_TOT",
    "WC",
    "WP",
    "WW",
    "CA_TOT",
    "CA_MID",
    "CH_MIN",
    "CT",
    "CT_TOP",
    "CT_MID",
    "CT_LOW",
    "VS",
    "SS",
    "SI",
    "ST_GD",
    "TS",
    "TE_005",
    "TE_01",
    "TE_02",
    "TE_03",
    "ST_SEA",
    "WH",
    "BF",
    "IR",
    "IX",
]
_ROW = re.compile(r"^\d{12}\s")
_TOKEN = re.compile(r"\S+")


def load_stations(path: Path) -> list[Station]:
    stations: list[Station] = []
    with path.open(encoding="utf-8") as handle:
        rows = csv.DictReader(line for line in handle if not line.startswith("#"))
        for row in rows:
            stations.append(
                Station(row["stn_id"], row["name"], GeoPoint(float(row["lat"]), float(row["lng"])))
            )
    return stations


def nearest_station(
    stations: list[Station], point: GeoPoint, available: set[str] | None = None
) -> Station | None:
    """The closest station within MAX_STATION_KM (restricted to `available` ids if given)."""
    candidates = [s for s in stations if available is None or s.station_id in available]
    if not candidates:
        return None
    best = min(candidates, key=lambda s: haversine_m(point, s.point))
    return best if haversine_m(point, best.point) <= MAX_STATION_KM * 1000 else None


def parse_sfctm2(text: str) -> dict[str, dict[str, str]]:
    """station id -> {column: raw string}. Uses the header's column right edges (fixed width)."""
    lines = text.splitlines()
    header = next((ln for ln in lines if ln.startswith("#") and "YYMMDDHHMI" in ln), None)
    if header is None:
        return {}
    edges = [m.end() + 1 for m in _TOKEN.finditer(header[1:])]
    if len(edges) != len(COLUMNS):
        log.warning("unexpected KMA column count: %d", len(edges))
        return {}
    rows: dict[str, dict[str, str]] = {}
    for line in lines:
        if not _ROW.match(line):
            continue
        record: dict[str, str] = {}
        previous = 0
        for name, edge in zip(COLUMNS, edges, strict=True):
            record[name] = line[previous:edge].strip()
            previous = edge
        rows[record["STN"]] = record
    return rows


def _number(raw: str | None) -> float | None:
    """KMA marks missing values as -9 / -99 (also -9.0, -99.0)."""
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return None if value in (-9.0, -99.0) else value


def to_observation(record: dict[str, str]) -> WeatherObservation | None:
    temp = _number(record.get("TA"))
    if temp is None:
        return None
    observed = datetime.strptime(record["TM"], "%Y%m%d%H%M").replace(tzinfo=KST)
    # RN_INT (mm/h) is the best rain signal; -9 means "not observed", not "dry".
    rain = _number(record.get("RN_INT"))
    if rain is None:
        rn = _number(record.get("RN"))
        rain = rn if rn is not None and rn > 0 else None
    return WeatherObservation(
        station_id=record["STN"],
        observed_at=observed,
        temp_c=temp,
        humidity_pct=_number(record.get("HM")),
        wind_ms=_number(record.get("WS")),
        rain_mm_h=rain,
        cloud_tenths=_number(record.get("CA_TOT")),
    )


class SnapshotStore(Protocol):
    async def load(self, tm: str) -> dict[str, dict[str, str]] | None: ...

    async def save(
        self, tm: str, rows: dict[str, dict[str, str]], fetched_at: datetime
    ) -> None: ...


def _describe_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


class KmaWeatherClient:
    """WeatherPort backed by kma_sfctm2 with per-hour snapshot reuse."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        auth_key: str,
        stations: list[Station],
        store: SnapshotStore | None = None,
        timeout_s: float = 60.0,
    ) -> None:
        self._http = http
        self._auth_key = auth_key
        self._stations = stations
        self._store = store
        self._timeout_s = timeout_s
        self._memory: dict[str, dict[str, dict[str, str]]] = {}
        self._not_before: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def _fetch(self, tm: str, timeout_s: float) -> dict[str, dict[str, str]]:
        response = await self._http.get(
            SFCTM2_URL,
            params={"tm": tm, "stn": "0", "help": "0", "authKey": self._auth_key},
            timeout=timeout_s,
        )
        response.raise_for_status()
        return parse_sfctm2(response.content.decode("cp949", errors="replace"))

    async def snapshot(
        self, tm: str, now: datetime, timeout_s: float | None = None
    ) -> dict[str, dict[str, str]]:
        async with self._lock:
            if tm in self._memory:
                return self._memory[tm]
            if self._store is not None and (stored := await self._store.load(tm)) is not None:
                self._memory[tm] = stored
                return stored
            if self._not_before.get(tm, 0.0) > time.monotonic():
                return {}  # asked a moment ago and it was not published yet: do not wait again
            try:
                rows = await self._fetch(tm, timeout_s or self._timeout_s)
            except httpx.HTTPError:
                self._not_before[tm] = time.monotonic() + NEGATIVE_CACHE_S
                raise
            if not rows:
                self._not_before[tm] = time.monotonic() + NEGATIVE_CACHE_S
            if rows:  # an hour that is not published yet comes back empty; never cache that
                self._memory[tm] = rows
                if self._store is not None:
                    await self._store.save(tm, rows, now)
                if len(self._memory) > 6:
                    del self._memory[min(self._memory)]
            return rows

    async def observation_at(self, point: GeoPoint, now: datetime) -> WeatherObservation | None:
        local = now.astimezone(KST)
        for back in range(MAX_FALLBACK_HOURS + 1):
            tm = (local - timedelta(hours=back)).strftime("%Y%m%d%H00")
            try:
                rows = await self.snapshot(tm, now, CURRENT_HOUR_TIMEOUT_S if back == 0 else None)
            except httpx.HTTPError as exc:
                # Never log `exc` itself: httpx puts the full URL, including authKey, in the text.
                log.warning("KMA fetch failed for %s (%s)", tm, _describe_error(exc))
                continue
            station = nearest_station(self._stations, point, set(rows))
            if station is None:
                continue
            observation = to_observation(rows[station.station_id])
            if observation is not None:
                return observation
        return None

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from app.adapters.outbound.clients.kma import (
    SFCTM2_URL,
    KmaWeatherClient,
    load_stations,
    nearest_station,
    parse_sfctm2,
    to_observation,
)
from app.domain.models import GeoPoint, Station
from tests.conftest import FIXTURES

KST = timezone(timedelta(hours=9))
SAMPLE = (FIXTURES / "kma_sfctm2.txt").read_text(encoding="utf-8")
STATIONS = load_stations(Path(__file__).parent.parent / "data" / "kma_stations.csv")
YEOKSAM = GeoPoint(37.5006431, 127.0363766)
NOW = datetime(2026, 10, 9, 22, 20, tzinfo=KST)


def test_parse_fixed_width_rows_and_missing_values() -> None:
    rows = parse_sfctm2(SAMPLE)
    assert set(rows) == {"108", "112", "119", "98"}
    seoul = rows["108"]
    assert seoul["TM"] == "202610092200" and seoul["TA"] == "18.4" and seoul["HM"] == "63.0"
    assert seoul["WS"] == "2.0" and seoul["CA_TOT"] == "7" and seoul["RN_INT"] == "-9.0"
    assert parse_sfctm2("no header here") == {}


def test_observation_conversion_treats_minus_nine_as_unknown() -> None:
    obs = to_observation(parse_sfctm2(SAMPLE)["108"])
    assert obs is not None
    assert obs.temp_c == 18.4 and obs.humidity_pct == 63.0 and obs.wind_ms == 2.0
    assert obs.rain_mm_h is None  # -9 = not observed, not "dry"
    assert obs.cloud_tenths == 7 and obs.observed_at == datetime(2026, 10, 9, 22, 0, tzinfo=KST)
    broken = dict(parse_sfctm2(SAMPLE)["108"], TA="-99.0")
    assert to_observation(broken) is None


def test_rain_signal_prefers_intensity_then_accumulation() -> None:
    base = parse_sfctm2(SAMPLE)["108"]
    assert to_observation(dict(base, RN_INT="2.5"))
    obs_int = to_observation(dict(base, RN_INT="2.5"))
    assert obs_int is not None and obs_int.rain_mm_h == 2.5
    obs_acc = to_observation(dict(base, RN_INT="-9.0", RN="1.0"))
    assert obs_acc is not None and obs_acc.rain_mm_h == 1.0
    dry = to_observation(dict(base, RN_INT="0.0"))
    assert dry is not None and dry.rain_mm_h == 0.0


def test_nearest_station_respects_coverage_and_availability() -> None:
    assert nearest_station(STATIONS, YEOKSAM) == next(s for s in STATIONS if s.station_id == "108")
    busan = GeoPoint(35.1796, 129.0756)
    assert nearest_station(STATIONS, busan) is None  # outside the covered area
    only_incheon = nearest_station(STATIONS, YEOKSAM, {"112"})
    assert only_incheon is not None and only_incheon.station_id == "112"
    assert nearest_station([], YEOKSAM) is None
    assert nearest_station([Station("1", "x", GeoPoint(37.5, 127.0))], YEOKSAM, {"2"}) is None


class MemoryStore:
    def __init__(self) -> None:
        self.saved: dict[str, dict[str, dict[str, str]]] = {}

    async def load(self, tm: str) -> dict[str, dict[str, str]] | None:
        return self.saved.get(tm)

    async def save(self, tm: str, rows: dict[str, dict[str, str]], fetched_at: datetime) -> None:
        self.saved[tm] = rows


def _body(text: str = SAMPLE) -> bytes:
    return text.encode("cp949")


@respx.mock
async def test_client_fetches_once_per_hour_and_reuses_the_snapshot() -> None:
    route = respx.get(SFCTM2_URL).mock(return_value=httpx.Response(200, content=_body()))
    store = MemoryStore()
    async with httpx.AsyncClient() as http:
        client = KmaWeatherClient(http, "secret", STATIONS, store)
        first = await client.observation_at(YEOKSAM, NOW)
        second = await client.observation_at(GeoPoint(37.51, 127.04), NOW + timedelta(minutes=20))
    assert first is not None and second is not None and first.station_id == "108"
    assert route.call_count == 1  # the KMA quota is small: one call serves every request this hour
    assert route.calls[0].request.url.params["tm"] == "202610092200"
    assert "202610092200" in store.saved
    # a restarted process reuses the stored snapshot without calling KMA
    async with httpx.AsyncClient() as http:
        fresh = KmaWeatherClient(http, "secret", STATIONS, store)
        assert await fresh.observation_at(YEOKSAM, NOW) is not None
    assert route.call_count == 1


@respx.mock
async def test_client_falls_back_to_the_previous_hour_when_not_published() -> None:
    empty = httpx.Response(200, content=_body("#START7777\n#7777END\n"))
    respx.get(SFCTM2_URL, params={"tm": "202610092300"}).mock(return_value=empty)
    ok = respx.get(SFCTM2_URL, params={"tm": "202610092200"}).mock(
        return_value=httpx.Response(200, content=_body())
    )
    store = MemoryStore()
    async with httpx.AsyncClient() as http:
        obs = await KmaWeatherClient(http, "k", STATIONS, store).observation_at(
            YEOKSAM, datetime(2026, 10, 9, 23, 5, tzinfo=KST)
        )
    assert obs is not None and obs.observed_at.hour == 22 and ok.call_count == 1
    assert "202610092300" not in store.saved  # empty hours are never cached


@respx.mock
async def test_client_returns_none_when_kma_is_down_or_out_of_area() -> None:
    respx.get(SFCTM2_URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as http:
        client = KmaWeatherClient(http, "k", STATIONS)
        assert await client.observation_at(YEOKSAM, NOW) is None
    respx.reset()
    respx.get(SFCTM2_URL).mock(return_value=httpx.Response(200, content=_body()))
    async with httpx.AsyncClient() as http:
        client = KmaWeatherClient(http, "k", STATIONS)
        assert await client.observation_at(GeoPoint(35.1796, 129.0756), NOW) is None


@respx.mock
async def test_unpublished_hour_is_remembered_and_the_key_never_reaches_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    newest = respx.get(SFCTM2_URL, params={"tm": "202610092300"}).mock(
        return_value=httpx.Response(504)
    )
    respx.get(SFCTM2_URL, params={"tm": "202610092200"}).mock(
        return_value=httpx.Response(200, content=_body())
    )
    late = datetime(2026, 10, 9, 23, 5, tzinfo=KST)
    with caplog.at_level("DEBUG"):
        async with httpx.AsyncClient() as http:
            client = KmaWeatherClient(http, "SUPER-SECRET-KEY", STATIONS)
            assert await client.observation_at(YEOKSAM, late) is not None
            assert await client.observation_at(YEOKSAM, late) is not None
    assert newest.call_count == 1  # the second request did not wait on the failing hour again
    assert "SUPER-SECRET-KEY" not in caplog.text
    assert "HTTP 504" in caplog.text

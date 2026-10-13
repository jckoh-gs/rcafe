"""Command line entry point: `python -m app.adapters.inbound.cli <command>`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.outbound.clients.naver_place import NaverPlaceClient
from app.adapters.outbound.clients.naver_search import NaverSearchClient
from app.adapters.outbound.clients.throttled_http import (
    BROWSER_HEADERS,
    BlockedError,
    ThrottledClient,
)
from app.adapters.outbound.clock import SystemClock
from app.adapters.outbound.persistence.collection_repository import (
    PostgresCollectionRequestRepository,
)
from app.adapters.outbound.persistence.repository import PostgresCafeRepository, make_engine
from app.adapters.outbound.persistence.taste_repository import (
    PostgresArchetypeRepository,
    PostgresTasteRepository,
)
from app.application.collection import RunCollectionRequests
from app.application.ingest import (
    DEFAULT_KEYWORDS,
    DetailReport,
    DiscoverCafes,
    DiscoverParams,
    DiscoverReport,
    FetchCafeDetails,
)
from app.application.taste import ComputeCafeTastes, FindWeatherTaste, SeedArchetypes
from app.config import Settings
from app.domain.models import GeoPoint
from app.domain.taste import AXES, AXIS_LABELS_KO, best_menu_for, taste_similarity
from app.domain.weather import WeatherObservation, describe

log = logging.getLogger("aicafe.cli")


def _parser(settings: Settings) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aicafe")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="sweep the map search and upsert cafes")
    discover.add_argument("--lat", type=float, default=settings.center_lat)
    discover.add_argument("--lng", type=float, default=settings.center_lng)
    discover.add_argument("--radius-m", type=float, default=settings.radius_m)
    discover.add_argument("--spacing-m", type=float, default=settings.spacing_m)
    discover.add_argument("--keywords", nargs="+", default=list(DEFAULT_KEYWORDS))
    discover.add_argument("--max-requests", type=int, default=None)

    details = sub.add_parser("details", help="fetch menus/reviews/status for known cafes")
    details.add_argument("--limit", type=int, default=100)
    details.add_argument("--max-age-days", type=float, default=7.0)

    collect = sub.add_parser(
        "collect-requests", help="collect the areas visitors asked for (run in quiet hours)"
    )
    collect.add_argument("--budget-minutes", type=float, default=150.0)
    collect.add_argument("--max-requests", type=int, default=10)
    collect.add_argument(
        "--request-id", type=int, default=None, help="collect only this request (admin run-now)"
    )
    sub.add_parser("requests", help="list the collection request queue")

    sub.add_parser("taste", help="compute taste vectors for all cafes with details")
    sub.add_parser("seed-archetypes", help="(re)build the weather-scenario archetypes")
    sub.add_parser("purge-review-text", help="delete temporary full review text (keeps tags)")

    preview = sub.add_parser("preview", help="show wanted taste and best cafes for a weather")
    preview.add_argument("--temp", type=float, required=True, help="air temperature, C")
    preview.add_argument("--humidity", type=float, default=60.0)
    preview.add_argument("--wind", type=float, default=1.0, help="m/s")
    preview.add_argument("--rain", type=float, default=0.0, help="mm/h")
    preview.add_argument("--cloud", type=float, default=5.0, help="0..10")
    preview.add_argument("--hour", type=float, default=14.0)
    preview.add_argument("--top", type=int, default=5)
    return parser


def _print_discover(r: DiscoverReport) -> None:
    log.info("discover: %d requests, %d unique cafes so far", r.requests, r.unique_places)


def _print_details(r: DetailReport) -> None:
    log.info("details: %d done (%d missing, %d failed)", r.attempted, r.missing, r.failed)


async def _run_taste(args: argparse.Namespace, engine: AsyncEngine) -> int:
    taste_repo = PostgresTasteRepository(engine)
    archetype_repo = PostgresArchetypeRepository(engine)
    if args.command == "taste":
        report = await ComputeCafeTastes(taste_repo, SystemClock()).run()
        log.info(
            "taste: %d cafes (%d with reviews, %d reviews tagged)",
            report.cafes,
            report.cafes_with_reviews,
            report.reviews_tagged,
        )
        for i, axis in enumerate(AXES):
            log.info(
                "  %-15s mean=%.3f p95=%.3f", axis, report.stats.mean[i], report.stats.scale[i]
            )
    elif args.command == "seed-archetypes":
        log.info("archetypes upserted: %d", await SeedArchetypes(archetype_repo).run())
    elif args.command == "purge-review-text":
        log.info(
            "raw review text removed from %d reviews", await taste_repo.purge_raw_review_text()
        )
    else:
        await _preview(args, taste_repo, archetype_repo)
    return 0


async def _preview(
    args: argparse.Namespace,
    taste_repo: PostgresTasteRepository,
    archetype_repo: PostgresArchetypeRepository,
) -> None:
    kst = timezone(timedelta(hours=9))
    when = datetime.now(kst).replace(hour=int(args.hour), minute=int((args.hour % 1) * 60))
    observation = WeatherObservation(
        station_id="preview",
        observed_at=when,
        temp_c=args.temp,
        humidity_pct=args.humidity,
        wind_ms=args.wind,
        rain_mm_h=args.rain,
        cloud_tenths=args.cloud,
    )
    result = await FindWeatherTaste(archetype_repo).run(observation)
    print(
        f"weather : {describe(result.conditions)} (feels like {result.conditions.feels_like:.1f}C)"
    )
    print(f"nearest : {result.nearest.name_ko} (distance {result.nearest_distance:.2f})")
    ranked = sorted(zip(AXES, result.taste, strict=True), key=lambda p: p[1], reverse=True)
    print("wanted  : " + ", ".join(f"{AXIS_LABELS_KO[a]} {v:.2f}" for a, v in ranked[:5]))
    stats = await taste_repo.load_axis_stats()
    profiles = await taste_repo.list_profiles()
    if stats is None or not profiles:
        print("no cafe tastes yet; run `taste` first")
        return
    scored = sorted(
        (
            (taste_similarity(result.taste, p.taste, stats) * (0.5 + 0.5 * p.confidence), p)
            for p in profiles
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    for score, profile in scored[: args.top]:
        menu = best_menu_for(result.taste, profile.menus, stats)
        print(f"  {score:.3f}  {profile.name}  -> {menu[0].name if menu else '-'}")


async def _list_requests(engine: AsyncEngine) -> int:
    repo = PostgresCollectionRequestRepository(engine)
    pending = await repo.next_pending(1000)
    print(f"{await repo.count_pending()} waiting or running; next in line:")
    for request in pending[:20]:
        print(
            f"  {request.cell_key:>12s}  {request.status:8s} x{request.request_count:<3d}"
            f" ({request.center.lat:.3f}, {request.center.lng:.3f})  {request.note or ''}"
        )
    return 0


async def _run(args: argparse.Namespace, settings: Settings) -> int:
    engine = make_engine(settings.database_url)
    if args.command in {"taste", "seed-archetypes", "purge-review-text", "preview"}:
        try:
            return await _run_taste(args, engine)
        finally:
            await engine.dispose()
    if args.command == "requests":
        try:
            return await _list_requests(engine)
        finally:
            await engine.dispose()
    repo = PostgresCafeRepository(engine)
    clock = SystemClock()
    timeout = httpx.Timeout(settings.naver_timeout_s)
    try:
        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS, timeout=timeout, follow_redirects=True
        ) as client:
            search_http = ThrottledClient(client, min_interval_s=settings.naver_search_interval_s)
            detail_http = ThrottledClient(client, min_interval_s=settings.naver_detail_interval_s)
            if args.command == "discover":
                params = DiscoverParams(
                    center=GeoPoint(args.lat, args.lng),
                    radius_m=args.radius_m,
                    spacing_m=args.spacing_m,
                    keywords=tuple(args.keywords),
                    max_requests=args.max_requests,
                )
                report = await DiscoverCafes(NaverSearchClient(search_http), repo, clock).run(
                    params, _print_discover
                )
                log.info("discover finished: %s", report)
            elif args.command == "collect-requests":
                taste_repo = PostgresTasteRepository(engine)
                crawler_details = FetchCafeDetails(
                    NaverPlaceClient(detail_http, settings.review_limit), repo, clock
                )
                runner = RunCollectionRequests(
                    PostgresCollectionRequestRepository(engine),
                    DiscoverCafes(NaverSearchClient(search_http), repo, clock),
                    crawler_details,
                    ComputeCafeTastes(taste_repo, clock),
                    taste_repo,
                    clock,
                    blocked_errors=(BlockedError,),
                )
                run_report = await runner.run(
                    timedelta(minutes=args.budget_minutes),
                    args.max_requests,
                    lambda message: log.info("%s", message),
                    request_id=args.request_id,
                )
                log.info("collect-requests finished: %s", run_report)
                return 2 if run_report.stopped_by_block else 0
            else:
                detail_report = await FetchCafeDetails(
                    NaverPlaceClient(detail_http, settings.review_limit), repo, clock
                ).run(args.limit, timedelta(days=args.max_age_days), _print_details)
                log.info("details finished: %s", detail_report)
    except BlockedError as exc:
        log.error("upstream blocked us (%s); stopping. Wait before retrying.", exc)
        return 2
    finally:
        await engine.dispose()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings()
    args = _parser(settings).parse_args()
    return asyncio.run(_run(args, settings))


if __name__ == "__main__":
    sys.exit(main())

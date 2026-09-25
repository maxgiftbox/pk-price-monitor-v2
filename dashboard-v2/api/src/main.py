import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from src.data_sources.google_sheets import (
    DataSourceUnavailable,
    GoogleSheetsRepository,
)
from src.services.pricing import filters, gap, meta, trend
from src.data_sources.consumer_voice import ConsumerVoiceRepository
from src.services.consumer_voice import dashboard as consumer_voice_dashboard
from src.services.consumer_voice import filters as consumer_voice_filters
from src.services.response_cache import ResponseCache


app = FastAPI(
    title="Mob Price Monitor V2 API",
    docs_url=None,
    redoc_url=None,
)


origins = [
    x.strip()
    for x in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173"
    ).split(",")
    if x.strip()
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["Accept", "Content-Type"],
)


app.state.repository = GoogleSheetsRepository(
    ttl_seconds=int(os.getenv("PRICING_CACHE_TTL_SECONDS", "900")),
    initial_load_timeout_seconds=int(
        os.getenv("PRICING_INITIAL_LOAD_TIMEOUT_SECONDS", "12")
    ),
)
app.state.consumer_voice_repository = ConsumerVoiceRepository(
    ttl_seconds=int(os.getenv("CONSUMER_VOICE_CACHE_TTL_SECONDS", "21600")),
    initial_load_timeout_seconds=int(
        os.getenv("CONSUMER_VOICE_INITIAL_LOAD_TIMEOUT_SECONDS", "12")
    ),
)
app.state.response_cache = ResponseCache(
    ttl_seconds=int(os.getenv("PRICING_RESPONSE_CACHE_TTL_SECONDS", "900")),
    max_entries=int(os.getenv("PRICING_RESPONSE_CACHE_MAX_ENTRIES", "256")),
)


def _cache_key(endpoint: str, snapshot, *parts):
    return (
        endpoint,
        snapshot.generated_at.isoformat(),
        snapshot.stale,
        *parts,
    )


def _values(values):
    return tuple(sorted(values or []))


@app.exception_handler(DataSourceUnavailable)
def unavailable(
    _request: Request,
    _exc: DataSourceUnavailable,
):
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "code": "DATA_SOURCE_UNAVAILABLE",
                "message": "Pricing data is temporarily unavailable.",
            }
        },
    )


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/pricing/filters")
def pricing_filters(
    country: list[str] = Query([]),
    brand: list[str] = Query([]),
    sku: list[str] = Query([]),
    memory: list[str] = Query([]),
    dateFrom: str | None = None,
    dateTo: str | None = None,
):
    snapshot = app.state.repository.get()
    key = _cache_key(
        "filters", snapshot, _values(country), _values(brand),
        _values(sku), _values(memory), dateFrom, dateTo,
    )
    return app.state.response_cache.get_or_compute(
        key,
        lambda: filters(snapshot, country, brand, sku, memory, dateFrom, dateTo),
    )


@app.get("/api/pricing/gap")
def pricing_gap(
    country: list[str] = Query([]),
    brand: list[str] = Query([]),
    sku: list[str] = Query([]),
    memory: list[str] = Query([]),
    competitor: list[str] = Query([]),
    alert: list[str] = Query([]),
    dateFrom: str | None = None,
    dateTo: str | None = None,
    page: int = 1,
    pageSize: int = Query(100, ge=1, le=500),
    windowDays: int = Query(7, ge=1, le=7),
    sort: str | None = None,
    direction: str = Query("desc", pattern="^(asc|desc)$"),
):
    snapshot = app.state.repository.get()
    params = {
            "country": country,
            "brand": brand,
            "sku": sku,
            "memory": memory,
            "competitor": competitor,
            "alert": alert,
            "date_from": dateFrom,
            "date_to": dateTo,
            "page": page,
            "page_size": pageSize,
            "window_days": windowDays,
            "sort": sort,
            "direction": direction,
    }
    key = _cache_key(
        "gap", snapshot, _values(country), _values(brand), _values(sku),
        _values(memory), _values(competitor), _values(alert), dateFrom, dateTo,
        page, pageSize, windowDays, sort, direction,
    )
    return app.state.response_cache.get_or_compute(
        key,
        lambda: gap(snapshot, params),
    )


@app.get("/api/pricing/trend")
def pricing_trend(
    country: list[str] = Query([]),
    brand: list[str] = Query([]),
    sku: list[str] = Query([]),
    memory: list[str] = Query([]),
    platform: list[str] = Query([]),
    dateFrom: str | None = None,
    dateTo: str | None = None,
):
    snapshot = app.state.repository.get()
    params = {
            "country": country,
            "brand": brand,
            "sku": sku,
            "memory": memory,
            "platform": platform,
            "date_from": dateFrom,
            "date_to": dateTo,
    }
    key = _cache_key(
        "trend", snapshot, _values(country), _values(brand), _values(sku),
        _values(memory), _values(platform), dateFrom, dateTo,
    )
    return app.state.response_cache.get_or_compute(
        key,
        lambda: trend(snapshot, params),
    )


@app.get("/api/pricing/dashboard")
def pricing_dashboard():
    snapshot = app.state.repository.get()
    key = _cache_key("dashboard", snapshot)

    def build_dashboard():
        country_values = snapshot.data["country"].dropna().astype(str).unique()
        pk_country = next(
            (value for value in country_values if value.casefold() == "pk"),
            "pk",
        )
        return {
            "filters": filters(snapshot),
            "todayAction": gap(snapshot, {
                "country": [pk_country], "page": 1, "page_size": 500,
                "window_days": 1, "direction": "desc",
            }),
            "gap": gap(snapshot, {
                "page": 1, "page_size": 15, "window_days": 7,
                "direction": "desc",
            }),
            "trend": trend(snapshot, {}),
            "meta": meta(snapshot),
        }

    return app.state.response_cache.get_or_compute(key, build_dashboard)


@app.get("/api/consumer-voice/filters")
def consumer_voice_filter_options():
    snapshot = app.state.consumer_voice_repository.get()
    key = _cache_key("consumer-voice-filters", snapshot)
    return app.state.response_cache.get_or_compute(
        key,
        lambda: {
            **consumer_voice_filters(snapshot.data),
            "meta": _consumer_voice_meta(snapshot),
        },
    )


def _consumer_voice_meta(snapshot):
    dates = snapshot.data["created_at"].dropna()
    return {
        "dataAsOf": dates.max().date().isoformat() if not dates.empty else None,
        "cacheGeneratedAt": snapshot.generated_at.isoformat(),
        "stale": snapshot.stale,
    }


@app.get("/api/consumer-voice/dashboard")
def consumer_voice_dashboard_data(
    venture: list[str] = Query([]),
    brand: list[str] = Query([]),
    productId: list[str] = Query([]),
    sentiment: str = "all",
    sort: str = "recent",
    dateFrom: str | None = None,
    dateTo: str | None = None,
    section: str = "all",
    limit: int = Query(100, ge=1, le=100),
):
    snapshot = app.state.consumer_voice_repository.get()
    params = {
            "venture": venture,
            "brand": brand,
            "product_id": productId,
            "sentiment": sentiment,
            "sort": sort,
            "date_from": dateFrom,
            "date_to": dateTo,
            "section": section,
            "limit": limit,
    }
    key = _cache_key(
        "consumer-voice-dashboard", snapshot, _values(venture), _values(brand),
        _values(productId), sentiment, sort, dateFrom, dateTo, section, limit,
    )
    return app.state.response_cache.get_or_compute(
        key,
        lambda: _consumer_voice_payload(snapshot, params),
    )


def _consumer_voice_payload(snapshot, params):
    payload = consumer_voice_dashboard(snapshot.data, params)
    payload.setdefault("meta", {}).update(_consumer_voice_meta(snapshot))
    return payload


# ==============================
# Serve React Frontend
# ==============================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

frontend_dist = os.path.join(
    BASE_DIR,
    "..",
    "frontend",
    "dist",
)


if os.path.exists(
    os.path.join(frontend_dist, "assets")
):
    app.mount(
        "/assets",
        StaticFiles(
            directory=os.path.join(
                frontend_dist,
                "assets",
            )
        ),
        name="assets",
    )


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    return FileResponse(
        os.path.join(
            frontend_dist,
            "index.html",
        )
    )

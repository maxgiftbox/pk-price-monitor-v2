import base64
import binascii
import hashlib
import hmac
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.data_sources.google_sheets import (
    DataSourceUnavailable,
    GoogleSheetsRepository,
)
from src.services.pricing import filters, gap, meta, trend
from src.data_sources.consumer_voice import ConsumerVoiceRepository
from src.data_sources.product_features import ProductFeaturesRepository
from src.data_sources.social_intelligence import SocialIntelligenceRepository
from src.services.consumer_voice import dashboard as consumer_voice_dashboard
from src.services.consumer_voice import filters as consumer_voice_filters
from src.services.product import compare as product_compare
from src.services.product import filters as product_filters
from src.services.response_cache import ResponseCache
from src.services.social_intelligence import dashboard as social_intelligence_dashboard
from src.services.social_intelligence import filters as social_intelligence_filters


app = FastAPI(
    title="Mob Price Monitor V2 API",
    docs_url=None,
    redoc_url=None,
)


origins = [
    x.strip()
    for x in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:5176"
    ).split(",")
    if x.strip()
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Accept", "Authorization", "Content-Type"],
)

PRICING_ACCESS_PASSWORD = os.getenv("PRICING_ACCESS_PASSWORD", "")
PRICING_SESSION_SECONDS = int(os.getenv("PRICING_SESSION_SECONDS", "28800"))
PRICING_COOKIE_NAME = "el_pricing_session"


def _pricing_signature(expires_at: str) -> str:
    return hmac.new(
        PRICING_ACCESS_PASSWORD.encode(), expires_at.encode(), hashlib.sha256
    ).hexdigest()


def _pricing_session_token(expires_at: int) -> str:
    payload = str(expires_at)
    raw = f"{payload}.{_pricing_signature(payload)}".encode()
    return base64.urlsafe_b64encode(raw).decode()


def _has_pricing_access(request: Request) -> bool:
    if not PRICING_ACCESS_PASSWORD:
        return False
    authorization = request.headers.get("authorization", "")
    bearer_token = authorization[7:] if authorization.lower().startswith("bearer ") else ""
    token = bearer_token or request.cookies.get(PRICING_COOKIE_NAME, "")
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        expires_at, signature = decoded.split(".", 1)
        return (
            int(expires_at) > int(time.time())
            and hmac.compare_digest(signature, _pricing_signature(expires_at))
        )
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return False


@app.middleware("http")
async def protect_pricing_api(request: Request, call_next):
    if (
        request.method != "OPTIONS"
        and
        request.url.path.startswith("/api/pricing/")
        and request.url.path != "/api/pricing/auth"
        and not _has_pricing_access(request)
    ):
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "PRICING_AUTH_REQUIRED", "message": "Pricing access requires a password."}},
        )
    return await call_next(request)


class PricingLogin(BaseModel):
    password: str


@app.get("/api/pricing/auth")
def pricing_auth_status(request: Request):
    return {"authenticated": _has_pricing_access(request)}


@app.post("/api/pricing/auth")
def pricing_auth_login(credentials: PricingLogin, request: Request, response: Response):
    if not PRICING_ACCESS_PASSWORD:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "PRICING_AUTH_NOT_CONFIGURED", "message": "Pricing access is not configured."}},
        )
    if not hmac.compare_digest(credentials.password, PRICING_ACCESS_PASSWORD):
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "INVALID_PASSWORD", "message": "Incorrect password."}},
        )
    expires_at = int(time.time()) + PRICING_SESSION_SECONDS
    response.set_cookie(
        PRICING_COOKIE_NAME,
        _pricing_session_token(expires_at),
        max_age=PRICING_SESSION_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="none" if request.url.scheme == "https" else "lax",
        path="/api/pricing",
    )
    return {"authenticated": True, "token": _pricing_session_token(expires_at)}


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
app.state.product_repository = ProductFeaturesRepository(
    ttl_seconds=int(os.getenv("PRODUCT_FEATURES_CACHE_TTL_SECONDS", "21600")),
    initial_load_timeout_seconds=int(
        os.getenv("PRODUCT_FEATURES_INITIAL_LOAD_TIMEOUT_SECONDS", "12")
    ),
)
app.state.social_intelligence_repository = SocialIntelligenceRepository(
    ttl_seconds=int(os.getenv("SOCIAL_INTELLIGENCE_CACHE_TTL_SECONDS", "900")),
    initial_load_timeout_seconds=int(os.getenv("SOCIAL_INTELLIGENCE_INITIAL_LOAD_TIMEOUT_SECONDS", "30")),
)
app.state.response_cache = ResponseCache(
    ttl_seconds=int(os.getenv("PRICING_RESPONSE_CACHE_TTL_SECONDS", "900")),
    max_entries=int(os.getenv("PRICING_RESPONSE_CACHE_MAX_ENTRIES", "256")),
)

SOCIAL_MEDIA_DIR = Path(
    os.getenv(
        "SOCIAL_INTELLIGENCE_MEDIA_DIR",
        str(Path(__file__).resolve().parents[1] / "data" / "social_media_assets"),
    )
)
SOCIAL_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/api/social-intelligence/media",
    StaticFiles(directory=str(SOCIAL_MEDIA_DIR)),
    name="social-intelligence-media",
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


def _social_meta(snapshot):
    dates = snapshot.data["published_at"].dropna()
    return {"dataAsOf": dates.max().isoformat() if not dates.empty else None, "cacheGeneratedAt": snapshot.generated_at.isoformat(), "stale": snapshot.stale}


@app.get("/api/social-intelligence/filters")
def social_intelligence_filter_options():
    snapshot = app.state.social_intelligence_repository.get()
    key = _cache_key("social-intelligence-filters", snapshot)
    return app.state.response_cache.get_or_compute(key, lambda: {**social_intelligence_filters(snapshot.data), "meta": _social_meta(snapshot)})


@app.get("/api/social-intelligence/dashboard")
def social_intelligence_dashboard_data(
    country: list[str] = Query([]), platform: list[str] = Query([]), monitorType: list[str] = Query([]),
    brand: list[str] = Query([]), accountType: list[str] = Query([]), mediaType: list[str] = Query([]),
    dateFrom: str | None = None, dateTo: str | None = None, query: str = "", sort: str = "recent",
    limit: int = Query(40, ge=1, le=100),
):
    snapshot = app.state.social_intelligence_repository.get()
    params = {"country": country, "platform": platform, "monitor_type": monitorType, "brand": brand, "account_type": accountType, "media_type": mediaType, "date_from": dateFrom, "date_to": dateTo, "query": query, "sort": sort, "limit": limit}
    key = _cache_key("social-intelligence-dashboard", snapshot, _values(country), _values(platform), _values(monitorType), _values(brand), _values(accountType), _values(mediaType), dateFrom, dateTo, query, sort, limit)
    def build_social_dashboard():
        payload = social_intelligence_dashboard(snapshot.data, params)
        payload["meta"].update(_social_meta(snapshot))
        return payload
    return app.state.response_cache.get_or_compute(key, build_social_dashboard)


@app.get("/api/products/filters")
def product_filter_options(
    brand: list[str] = Query([]),
    model: list[str] = Query([]),
):
    snapshot = app.state.product_repository.get()
    key = _cache_key(
        "product-filters", snapshot, _values(brand), _values(model)
    )
    return app.state.response_cache.get_or_compute(
        key,
        lambda: product_filters(snapshot, brand, model),
    )


@app.get("/api/products/compare")
def product_comparison(
    skuId: list[str] = Query(..., min_length=1, max_length=6),
):
    snapshot = app.state.product_repository.get()
    key = _cache_key("product-compare", snapshot, _values(skuId))
    return app.state.response_cache.get_or_compute(
        key,
        lambda: product_compare(snapshot, skuId),
    )


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

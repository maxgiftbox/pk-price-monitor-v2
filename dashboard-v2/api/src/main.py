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
from src.services.pricing import filters, gap, trend
from src.data_sources.consumer_voice import ConsumerVoiceRepository
from src.services.consumer_voice import dashboard as consumer_voice_dashboard
from src.services.consumer_voice import filters as consumer_voice_filters


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
app.state.consumer_voice_repository = ConsumerVoiceRepository()


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
    return filters(
        app.state.repository.get(),
        country,
        brand,
        sku,
        memory,
        dateFrom,
        dateTo,
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
    return gap(
        app.state.repository.get(),
        {
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
        },
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
    return trend(
        app.state.repository.get(),
        {
            "country": country,
            "brand": brand,
            "sku": sku,
            "memory": memory,
            "platform": platform,
            "date_from": dateFrom,
            "date_to": dateTo,
        },
    )


@app.get("/api/consumer-voice/filters")
def consumer_voice_filter_options():
    return consumer_voice_filters(app.state.consumer_voice_repository.get())


@app.get("/api/consumer-voice/dashboard")
def consumer_voice_dashboard_data(
    venture: list[str] = Query([]),
    brand: list[str] = Query([]),
    productId: list[str] = Query([]),
    sentiment: str = "all",
    sort: str = "recent",
    dateFrom: str | None = None,
    dateTo: str | None = None,
):
    return consumer_voice_dashboard(
        app.state.consumer_voice_repository.get(),
        {
            "venture": venture,
            "brand": brand,
            "product_id": productId,
            "sentiment": sentiment,
            "sort": sort,
            "date_from": dateFrom,
            "date_to": dateTo,
        },
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

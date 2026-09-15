from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src.domain.pricing import calculate_gap_table


SORTS = {
    "date": "crawl_date",
    "country": "country",
    "brand": "brand",
    "sku": "model",
    "memory": "memory",
    "mrp": "mrp",
    "discountPct": "discount_pct",
    "darazPrice": "daraz_price",
    "competitorPlatform": "competitor_platform",
    "competitorPrice": "competitor_price",
    "gapAmount": "gap_amount",
    "gapPct": "gap_pct",
    "alert": "alert",
}


# ============================================================
# Gap table cache
#
# calculate_gap_table(snapshot.data) is relatively expensive.
# The same snapshot can be requested multiple times by
# Today Action SKU and Price Gap Analysis.
#
# Cache the calculated gap table and only rebuild it when
# snapshot.generated_at changes.
# ============================================================

_gap_cache_key = None
_gap_cache_frame = None


def _get_gap_frame(snapshot):
    global _gap_cache_key, _gap_cache_frame

    cache_key = snapshot.generated_at

    if (
        _gap_cache_frame is None
        or _gap_cache_key != cache_key
    ):
        _gap_cache_frame = calculate_gap_table(snapshot.data)
        _gap_cache_key = cache_key

    # Return a shallow copy so filtering/pagination in gap()
    # does not mutate the cached DataFrame itself.
    return _gap_cache_frame.copy(deep=False)


def _filter(df, column, values):
    return df[df[column].isin(values)] if values and column in df else df


def meta(snapshot):
    dates = (
        pd.to_datetime(
            snapshot.data.get("crawl_date"),
            errors="coerce",
        ).dropna()
        if "crawl_date" in snapshot.data
        else pd.Series(dtype="datetime64[ns]")
    )

    return {
        "dataAsOf": (
            dates.max().date().isoformat()
            if not dates.empty
            else None
        ),
        "cacheGeneratedAt": snapshot.generated_at.isoformat(),
        "stale": snapshot.stale,
    }


def filters(
    snapshot,
    country=None,
    brand=None,
    sku=None,
    memory=None,
    date_from=None,
    date_to=None,
):
    base = snapshot.data

    if date_from:
        base = base[
            pd.to_datetime(base.crawl_date)
            >= pd.Timestamp(date_from)
        ]

    if date_to:
        base = base[
            pd.to_datetime(base.crawl_date)
            <= pd.Timestamp(date_to)
        ]

    countries = sorted(
        base.country.dropna().unique().tolist()
    )

    by_country = _filter(
        base,
        "country",
        country,
    )

    brands = sorted(
        by_country.brand.dropna().unique().tolist()
    )

    by_brand = _filter(
        by_country,
        "brand",
        brand,
    )

    skus = sorted(
        by_brand.model.dropna().unique().tolist()
    )

    by_sku = _filter(
        by_brand,
        "model",
        sku,
    )

    memories = sorted(
        by_sku.memory.dropna().unique().tolist()
    )

    dates = pd.to_datetime(
        base.crawl_date,
        errors="coerce",
    ).dropna()

    competitors = sorted(
        p
        for p in base.platform.str.casefold().unique()
        if p in {"priceoye", "pickaboo"}
    )

    return {
        "options": {
            "countries": countries,
            "brands": brands,
            "skus": skus,
            "memories": memories,
            "dateRange": {
                "min": (
                    dates.min().date().isoformat()
                    if not dates.empty
                    else None
                ),
                "max": (
                    dates.max().date().isoformat()
                    if not dates.empty
                    else None
                ),
            },
            "competitors": competitors,
        },
        "meta": meta(snapshot),
    }


def gap(snapshot, params):
    # Use cached calculated gap table instead of recalculating
    # calculate_gap_table(snapshot.data) for every request.
    frame = _get_gap_frame(snapshot)

    for col, key in [
        ("country", "country"),
        ("brand", "brand"),
        ("model", "sku"),
        ("memory", "memory"),
        ("competitor_platform", "competitor"),
        ("alert", "alert"),
    ]:
        if params.get(key):
            frame = frame[
                frame[col].isin(params[key])
            ]

    # Date filter
    if params.get("date_from"):
        frame = frame[
            pd.to_datetime(frame["crawl_date"])
            >= pd.Timestamp(params["date_from"])
        ]

    elif params.get("date_to"):
        frame = frame[
            pd.to_datetime(frame["crawl_date"])
            <= pd.Timestamp(params["date_to"])
        ]

    else:
        # Default: latest available date only
        latest_date = pd.to_datetime(
            frame["crawl_date"],
            errors="coerce",
        ).max()

        if pd.notna(latest_date):
            frame = frame[
                pd.to_datetime(frame["crawl_date"])
                == latest_date
            ]

    page = params.get("page", 1)
    size = params.get("page_size", 50)

    total = len(frame)

    frame = frame.iloc[
        (page - 1) * size : page * size
    ]

    def nullable(value):
        if pd.isna(value):
            return None

        if hasattr(value, "item"):
            return value.item()

        return value

    rows = []

    for _, r in frame.iterrows():
        rows.append(
            {
                "productId": nullable(
                    r.get("product_id")
                ),

                "date": nullable(
                    r.get("crawl_date")
                ),

                "country": nullable(
                    r.get("country")
                ),

                "brand": nullable(
                    r.get("brand")
                ),

                "sku": nullable(
                    r.get("model")
                ),

                "memory": nullable(
                    r.get("memory")
                ),

                # MRP
                "mrp": nullable(
                    r.get("mrp")
                ),

                # Discount %
                "discountPct": nullable(
                    r.get("discount_pct")
                ),

                # Daraz
                "darazPrice": nullable(
                    r.get("daraz_price")
                ),

                "darazUrl": nullable(
                    r.get("daraz_url")
                ),

                # Competitor
                "competitorPlatform": nullable(
                    r.get("competitor_platform")
                ),

                "competitorPrice": nullable(
                    r.get("competitor_price")
                ),

                "competitorUrl": nullable(
                    r.get("competitor_url")
                ),

                # Gap
                "gapAmount": nullable(
                    r.get("gap_amount")
                ),

                "gapPct": nullable(
                    r.get("gap_pct")
                ),

                "alert": nullable(
                    r.get("alert")
                ),
            }
        )

    return {
        "rows": rows,

        "pagination": {
            "page": page,
            "pageSize": size,
            "total": total,
            "totalPages": max(
                1,
                (total + size - 1) // size,
            ),
        },

        "meta": meta(snapshot),
    }


def trend(snapshot, params):
    df = snapshot.data.copy()

    # filter
    for col, key in [
        ("country", "country"),
        ("brand", "brand"),
        ("model", "sku"),
        ("memory", "memory"),
    ]:
        values = params.get(key)

        if values and col in df:
            df = df[
                df[col].isin(values)
            ]

    # platform filter
    if params.get("platform"):
        df = df[
            df["competitor_platform"].isin(
                params["platform"]
            )
        ]

    # date range
    if params.get("date_from"):
        df = df[
            pd.to_datetime(df["crawl_date"])
            >= pd.Timestamp(params["date_from"])
        ]

    if params.get("date_to"):
        df = df[
            pd.to_datetime(df["crawl_date"])
            <= pd.Timestamp(params["date_to"])
        ]

    result = []

    for _, r in df.iterrows():
        price = r.get("product_price")

        # Skip rows without a valid price
        if pd.isna(price):
            continue

        crawl_date = r.get("crawl_date")

        if pd.isna(crawl_date):
            continue

        result.append(
            {
                "date": (
                    crawl_date.isoformat()
                    if hasattr(crawl_date, "isoformat")
                    else str(crawl_date)
                ),
                "country": r.get("country"),
                "brand": r.get("brand"),
                "platform": str(
                    r.get("platform")
                ).lower(),
                "sku": r.get("model"),
                "memory": r.get("memory"),
                "price": float(price),
            }
        )

    return {
        "rows": result,
        "total": len(result),
    }

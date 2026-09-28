"""Product Intelligence filter and comparison services."""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.domain.product import FEATURE_GROUPS


def _nullable(value: Any):
    if pd.isna(value) or value == "":
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def meta(snapshot):
    updated = pd.to_datetime(snapshot.data.get("last_updated"), errors="coerce").dropna()
    return {
        "dataAsOf": updated.max().date().isoformat() if not updated.empty else None,
        "cacheGeneratedAt": snapshot.generated_at.isoformat(),
        "stale": snapshot.stale,
    }


def filters(snapshot, brand=None, model=None):
    frame = snapshot.data
    brands = sorted(frame["brand"].dropna().unique().tolist(), key=str.casefold)
    if brand:
        frame = frame[frame["brand"].isin(brand)]
    models = sorted(frame["model"].dropna().unique().tolist(), key=str.casefold)
    if model:
        frame = frame[frame["model"].isin(model)]
    memories = sorted(
        [value for value in frame["memory"].dropna().unique().tolist() if value],
        key=str.casefold,
    )
    skus = [
        {
            "skuId": row.sku_id,
            "brand": row.brand,
            "model": row.model,
            "memory": row.memory or None,
            "label": " ".join(part for part in [row.model, row.memory] if part),
        }
        for row in frame.sort_values(["brand", "model", "memory"]).itertuples()
    ]
    return {
        "options": {
            "ventures": ["PK"],
            "brands": brands,
            "models": models,
            "memories": memories,
            "skus": skus,
        },
        "meta": meta(snapshot),
    }


def compare(snapshot, sku_ids):
    requested = list(dict.fromkeys(sku_ids))
    frame = snapshot.data.set_index("sku_id", drop=False)
    products = []
    field_map = {
        "memory": "memory",
        "mrpPrice": "mrp_price",
        "sellingPrice": "selling_price",
        "displayType": "display_type",
        "displaySize": "display_size",
        "resolution": "resolution",
        "refreshRateHz": "refresh_rate_hz",
        "os": "os",
        "chipset": "chipset",
        "cpu": "cpu",
        "gpu": "gpu",
        "mainCamera": "main_camera",
        "selfieCamera": "selfie_camera",
        "battery": "battery",
        "charging": "charging",
        "colors": "colors",
    }
    for sku_id in requested:
        if sku_id not in frame.index:
            continue
        row = frame.loc[sku_id]
        products.append({
            "skuId": sku_id,
            "venture": row["venture"],
            "brand": row["brand"],
            "model": row["model"],
            "memory": _nullable(row["memory"]),
            "productUrl": _nullable(row["product_url"]),
            "specs": {
                target: _nullable(row[source])
                for target, source in field_map.items()
            },
        })
    missing = [sku_id for sku_id in requested if sku_id not in frame.index]
    return {
        "products": products,
        "groups": FEATURE_GROUPS,
        "warnings": [f"Unknown SKU: {sku_id}" for sku_id in missing],
        "meta": meta(snapshot),
    }


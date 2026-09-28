"""Product Intelligence field normalization and comparison contracts."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd


TEXT_COLUMNS = [
    "brand", "model", "memory", "standard_model_memory", "product_id",
    "product_url", "display_type", "display_size", "resolution", "os",
    "chipset", "cpu", "gpu", "main_camera", "selfie_camera", "battery",
    "charging", "colors", "source", "last_updated",
]

NUMERIC_RANGES = {
    "refresh_rate_hz": (30, 240),
    "main_camera_mp": (1, 250),
    "selfie_camera_mp": (1, 250),
    "battery_mah": (1_000, 15_000),
    "charging_w": (1, 300),
    "mrp_price": (1, None),
    "selling_price": (1, None),
}

FEATURE_GROUPS = [
    {
        "id": "commercial", "label": "Commercial",
        "fields": [
            {"key": "memory", "label": "Memory"},
            {"key": "mrpPrice", "label": "MRP"},
            {"key": "sellingPrice", "label": "Selling Price"},
        ],
    },
    {
        "id": "display", "label": "Display",
        "fields": [
            {"key": "displaySize", "label": "Display Size"},
            {"key": "displayType", "label": "Display Type"},
            {"key": "resolution", "label": "Resolution"},
            {"key": "refreshRateHz", "label": "Refresh Rate", "suffix": "Hz"},
        ],
    },
    {
        "id": "performance", "label": "Performance",
        "fields": [
            {"key": "chipset", "label": "Chipset"},
            {"key": "cpu", "label": "CPU"},
            {"key": "gpu", "label": "GPU"},
            {"key": "os", "label": "Operating System"},
        ],
    },
    {
        "id": "camera", "label": "Camera",
        "fields": [
            {"key": "mainCamera", "label": "Main Camera"},
            {"key": "selfieCamera", "label": "Selfie Camera"},
        ],
    },
    {
        "id": "battery", "label": "Battery & Charging",
        "fields": [
            {"key": "battery", "label": "Battery"},
            {"key": "charging", "label": "Charging"},
        ],
    },
    {
        "id": "design", "label": "Design",
        "fields": [{"key": "colors", "label": "Colors"}],
    },
]


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _slug(value: Any) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", _text(value))
        .encode("ascii", "ignore")
        .decode()
        .lower()
    )
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", ascii_value))


def normalize_memory(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(tb|gb)?", text, re.I)
    if len(parts) < 2:
        return text
    normalized = []
    for number, unit in parts[:2]:
        parsed = float(number) * (1024 if unit.casefold() == "tb" else 1)
        normalized.append(str(int(parsed)) if parsed.is_integer() else str(parsed))
    return "/".join(normalized)


def product_sku_id(venture: Any, brand: Any, model: Any, memory: Any) -> str:
    parts = [_slug(venture), _slug(brand), _slug(model), _slug(normalize_memory(memory))]
    return "-".join(part for part in parts if part)


def prepare_product_features(raw: pd.DataFrame) -> pd.DataFrame:
    if raw.empty:
        return raw.copy()

    frame = raw.copy()
    frame.columns = [_text(column).casefold() for column in frame.columns]
    for column in TEXT_COLUMNS:
        if column not in frame:
            frame[column] = ""
        frame[column] = frame[column].apply(_text)

    for column, (minimum, maximum) in NUMERIC_RANGES.items():
        source = frame[column] if column in frame else pd.Series(pd.NA, index=frame.index)
        values = pd.to_numeric(source, errors="coerce")
        valid = values.ge(minimum)
        if maximum is not None:
            valid &= values.le(maximum)
        frame[column] = values.where(valid)

    frame["venture"] = "PK"
    frame["memory"] = frame["memory"].apply(normalize_memory)
    frame["sku_id"] = frame.apply(
        lambda row: product_sku_id(
            row["venture"], row["brand"], row["model"], row["memory"]
        ),
        axis=1,
    )
    frame = frame.drop_duplicates("sku_id", keep="first")

    required = {"brand", "model", "standard_model_memory", "sku_id"}
    if not required.issubset(frame.columns) or frame["sku_id"].eq("").any():
        raise ValueError("Product feature data contains unusable SKU identities")
    return frame.reset_index(drop=True)

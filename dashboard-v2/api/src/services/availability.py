"""Availability dashboard aggregation and filtering."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _clean(value: Any):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"true", "yes", "1"}


def _priority(frame: pd.DataFrame) -> pd.Series:
    return frame["l90_product_transaction_flag"].astype(str).str.strip().str.casefold().eq("yes").map({True: "high", False: "standard"})


def _apply(frame: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    result = frame.copy()
    result["priority"] = _priority(result)
    mappings = {
        "venture": "venture",
        "brand": "brand_name",
        "category": "category",
        "status": "availability_status",
        "priority": "priority",
    }
    for key, column in mappings.items():
        values = {str(v).casefold() for v in params.get(key, []) if str(v).strip()}
        if values:
            result = result[result[column].astype(str).str.casefold().isin(values)]
    search = str(params.get("search", "")).strip()
    if search:
        mask = pd.Series(False, index=result.index)
        for column in ("short_item_eng_name", "memory", "color", "daraz_sku", "brand_name"):
            if column in result:
                mask |= result[column].astype(str).str.contains(search, case=False, regex=False, na=False)
        result = result[mask]
    return result


def _counts(frame: pd.DataFrame) -> dict[str, Any]:
    statuses = frame["availability_status"].value_counts()
    available = int(statuses.get("available", 0))
    unavailable = int(statuses.get("unavailable", 0))
    unknown = int(statuses.get("unknown", 0))
    verified_total = available + unavailable
    return {
        "products": int(frame[["venture", "product_id"]].drop_duplicates().shape[0]),
        "variants": int(len(frame)),
        "available": available,
        "unavailable": unavailable,
        "unknown": unknown,
        "availabilityRate": available / verified_total if verified_total else None,
        "highPriorityUnavailable": int(((frame["priority"] == "high") & (frame["availability_status"] == "unavailable")).sum()),
    }


def dashboard(snapshot, params: dict[str, Any]) -> dict[str, Any]:
    frame = _apply(snapshot.data, params)
    brand_rows = []
    for brand, group in frame.groupby("brand_name", dropna=False):
        counts = _counts(group)
        brand_rows.append({"brand": str(brand), **counts})
    brand_rows.sort(key=lambda row: (-row["unavailable"], -row["variants"], row["brand"].casefold()))

    action = frame[frame["availability_status"].isin(["unavailable", "unknown"])].copy()
    action["_priority"] = action["priority"].eq("high").astype(int)
    action["_status"] = action["availability_status"].map({"unavailable": 0, "unknown": 1}).fillna(2)
    action["_gmv"] = pd.to_numeric(action.get("l90_gmv", 0).replace("-", 0), errors="coerce").fillna(0)
    action = action.sort_values(["_priority", "_status", "_gmv", "brand_name"], ascending=[False, True, False, True])

    rows = []
    for record in frame.to_dict("records"):
        rows.append({
            "runId": _clean(record.get("run_id")),
            "crawledAt": _clean(record.get("crawled_at")),
            "venture": _clean(record.get("venture")),
            "brand": _clean(record.get("brand_name")),
            "productId": str(record.get("product_id", "")),
            "darazSku": _clean(record.get("daraz_sku")),
            "productName": _clean(record.get("short_item_eng_name")),
            "memory": _clean(record.get("memory")),
            "color": _clean(record.get("color")),
            "category": _clean(record.get("category")),
            "url": _clean(record.get("url_daraz")),
            "status": _clean(record.get("availability_status")),
            "statusReason": _clean(record.get("status_reason")),
            "selectedSkuVerified": _as_bool(record.get("selected_sku_verified")),
            "l90Gmv": _clean(record.get("l90_gmv")),
            "priority": _clean(record.get("priority")),
        })
    action_skus = set(action["daraz_sku"].astype(str))
    actions = [row for row in rows if str(row["darazSku"]) in action_skus]
    action_order = {sku: index for index, sku in enumerate(action["daraz_sku"].astype(str))}
    actions.sort(key=lambda row: action_order.get(str(row["darazSku"]), 999999))

    source = snapshot.data
    crawled_at = pd.to_datetime(source["crawled_at"], errors="coerce", utc=True)
    data_as_of = crawled_at.max()
    return {
        "summary": _counts(frame),
        "brands": brand_rows,
        "actions": actions,
        "rows": rows,
        "options": {
            "ventures": sorted(source["venture"].dropna().astype(str).unique()),
            "brands": sorted(source["brand_name"].dropna().astype(str).unique()),
            "categories": sorted(source["category"].dropna().astype(str).unique()),
            "statuses": ["available", "unavailable", "unknown"],
            "priorities": ["high", "standard"],
        },
        "meta": {
            "dataAsOf": data_as_of.isoformat() if pd.notna(data_as_of) else None,
            "cacheGeneratedAt": snapshot.generated_at.isoformat(),
            "stale": snapshot.stale,
            "coverage": int(len(source)),
        },
    }

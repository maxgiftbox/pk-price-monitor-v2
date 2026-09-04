"""Framework-neutral pricing logic copied from V1 and adapted to typed API output."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any

import pandas as pd

PRICE_COLUMNS = ["original_price", "product_price", "voucher_amount", "effective_price"]
COMPETITORS = {"priceoye", "pickaboo"}


def _text(value: Any) -> str:
    return "" if pd.isna(value) else str(value).strip()


def normalize_memory(value: Any) -> str:
    value = _text(value)
    if not value:
        return ""
    if value.casefold() in {"n/a", "na", "none", "null"}:
        return "N/A"
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*(tb|gb)?", value, re.I)
    if not parts:
        return value
    output = []
    for number, unit in parts:
        parsed = float(number) * (1024 if unit.casefold() == "tb" else 1)
        output.append(str(int(parsed)) if parsed.is_integer() else str(parsed).rstrip("0").rstrip("."))
    return "/".join(output)


def normalize_url(value: Any) -> str:
    value = _text(value).casefold().split("?", 1)[0].split("#", 1)[0]
    return re.sub(r"^www\.", "", re.sub(r"^https?://", "", value)).rstrip("/")


def _slug(value: Any) -> str:
    ascii_value = unicodedata.normalize("NFKD", _text(value)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"(^-|-$)", "", re.sub(r"[^a-z0-9]+", "-", ascii_value))


def product_id(country: Any, brand: Any, model: Any, memory: Any) -> str:
    """Stable readable identity with a SHA-256 suffix if all identity components are blank."""
    parts = [_slug(country), _slug(brand), _slug(model), _slug(normalize_memory(memory))]
    readable = "-".join(part for part in parts if part)
    if readable:
        return readable
    return "product-" + hashlib.sha256("|||".join(map(_text, (country, brand, model, memory))).encode()).hexdigest()[:16]


def alert_level(gap_pct: Any) -> str | None:
    if pd.isna(gap_pct):
        return None
    value = float(gap_pct)
    if value >= 0.03:
        return "Red"
    if value > 0:
        return "Orange"
    return "Green"


def prepare_price_daily_df(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    df.columns = [_text(c) for c in df.columns]
    for col in PRICE_COLUMNS:
        if col in df:
            cleaned = df[col].fillna("").astype(str).str.replace(",", "", regex=False).str.replace(r"[^0-9.\-]", "", regex=True).replace("", pd.NA)
            df[col] = pd.to_numeric(cleaned, errors="coerce")
    for col in ["platform", "country", "brand", "model", "memory", "product_url", "stock_status"]:
        if col not in df:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    df["memory"] = df["memory"].apply(normalize_memory)
    df["crawl_date"] = pd.to_datetime(df.get("crawl_date"), errors="coerce").dt.date
    date_text = df["crawl_date"].astype(str)
    time_text = df.get("crawl_time", pd.Series("", index=df.index)).astype(str)
    df["crawl_datetime"] = pd.to_datetime(date_text + " " + time_text, errors="coerce")
    return df


def enrich_with_sku_master(df: pd.DataFrame, master: pd.DataFrame) -> pd.DataFrame:
    """Apply V1 primary identity match, then unique platform/country/URL fallback."""
    out = df.copy()
    out["raw_model"], out["raw_memory"] = out["model"], out["memory"]
    out["standard_model"], out["standard_memory"] = "", ""
    if not master.empty:
        right = master.copy()
        for col in ["platform", "country", "brand", "model", "memory", "product_url", "standard_model", "standard_memory"]:
            if col not in right: right[col] = ""
            right[col] = right[col].fillna("").astype(str).str.strip()
        right["memory"] = right["memory"].apply(normalize_memory)
        keys = ["platform", "country", "brand", "model", "memory"]
        for frame in (out, right):
            for key in keys: frame[f"_k_{key}"] = frame[key].str.casefold()
        keycols = [f"_k_{k}" for k in keys]
        lookup = right.drop_duplicates(keycols)[keycols + ["standard_model", "standard_memory"]]
        out = out.merge(lookup, on=keycols, how="left", suffixes=("", "_m"))
        for col in ["standard_model", "standard_memory"]:
            out[col] = out[f"{col}_m"].fillna("").where(out[f"{col}_m"].fillna("").ne(""), out[col])
        missing = out["standard_model"].eq("") | out["standard_memory"].eq("")
        right["_url"] = right["product_url"].apply(normalize_url)
        out["_url"] = out["product_url"].apply(normalize_url)
        urlkeys = ["_k_platform", "_k_country", "_url"]
        unique = right[right["_url"].ne("")].drop_duplicates(urlkeys, keep=False)
        fallback = out.loc[missing, urlkeys].merge(unique[urlkeys + ["standard_model", "standard_memory"]], on=urlkeys, how="left")
        out.loc[missing, ["standard_model", "standard_memory"]] = fallback[["standard_model", "standard_memory"]].fillna("").to_numpy()
    out["model"] = out["standard_model"].where(out["standard_model"].ne(""), out["raw_model"])
    out["memory"] = out["standard_memory"].where(out["standard_memory"].ne(""), out["raw_memory"]).apply(normalize_memory)
    return out


def calculate_gap_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    work["_platform"] = work["platform"].str.casefold()
    identity = ["crawl_date", "country", "brand", "model", "memory", "_platform"]
    priced = work[work["effective_price"].notna()].sort_values("crawl_datetime", ascending=False).drop_duplicates(identity)
    join = ["crawl_date", "country", "brand", "model", "memory"]
    daraz = priced[priced["_platform"].eq("daraz")].rename(columns={"effective_price":"daraz_price", "original_price":"mrp", "product_url":"daraz_url"})
    comp = priced[priced["_platform"].isin(COMPETITORS)].rename(columns={"effective_price":"competitor_price", "product_url":"competitor_url", "_platform":"competitor_platform"})
    cols = join + ["competitor_platform", "competitor_price", "competitor_url"]
    gap = daraz.merge(comp[cols], on=join, how="left")
    gap["gap_amount"] = gap["daraz_price"] - gap["competitor_price"]
    gap["gap_pct"] = gap["gap_amount"] / gap["daraz_price"]
    gap["discount_pct"] = (1 - gap["daraz_price"] / gap["mrp"]).where(gap["mrp"].gt(0))
    gap["alert"] = gap["gap_pct"].apply(alert_level)
    gap["product_id"] = gap.apply(lambda r: product_id(r.country, r.brand, r.model, r.memory), axis=1)
    return gap

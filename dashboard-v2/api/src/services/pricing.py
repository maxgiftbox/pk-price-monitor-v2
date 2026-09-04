from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
import pandas as pd
from src.domain.pricing import calculate_gap_table

SORTS = {"date":"crawl_date", "country":"country", "brand":"brand", "sku":"model", "memory":"memory", "mrp":"mrp", "discountPct":"discount_pct", "darazPrice":"daraz_price", "competitorPlatform":"competitor_platform", "competitorPrice":"competitor_price", "gapAmount":"gap_amount", "gapPct":"gap_pct", "alert":"alert"}

def _filter(df, column, values):
    return df[df[column].isin(values)] if values and column in df else df

def meta(snapshot):
    dates = pd.to_datetime(snapshot.data.get("crawl_date"), errors="coerce").dropna() if "crawl_date" in snapshot.data else pd.Series(dtype="datetime64[ns]")
    return {"dataAsOf": dates.max().date().isoformat() if not dates.empty else None, "cacheGeneratedAt": snapshot.generated_at.isoformat(), "stale": snapshot.stale}

def filters(snapshot, country=None, brand=None, sku=None, memory=None, date_from=None, date_to=None):
    base = snapshot.data
    if date_from: base = base[pd.to_datetime(base.crawl_date) >= pd.Timestamp(date_from)]
    if date_to: base = base[pd.to_datetime(base.crawl_date) <= pd.Timestamp(date_to)]
    countries = sorted(base.country.dropna().unique().tolist())
    by_country = _filter(base, "country", country)
    brands = sorted(by_country.brand.dropna().unique().tolist())
    by_brand = _filter(by_country, "brand", brand)
    skus = sorted(by_brand.model.dropna().unique().tolist())
    by_sku = _filter(by_brand, "model", sku)
    memories = sorted(by_sku.memory.dropna().unique().tolist())
    dates = pd.to_datetime(base.crawl_date, errors="coerce").dropna()
    competitors = sorted(p for p in base.platform.str.casefold().unique() if p in {"priceoye", "pickaboo"})
    return {"options":{"countries":countries,"brands":brands,"skus":skus,"memories":memories,"dateRange":{"min":dates.min().date().isoformat() if not dates.empty else None,"max":dates.max().date().isoformat() if not dates.empty else None},"competitors":competitors},"meta":meta(snapshot)}

def gap(snapshot, params):
    frame = calculate_gap_table(snapshot.data)
    for col, key in [("country","country"),("brand","brand"),("model","sku"),("memory","memory"),("competitor_platform","competitor"),("alert","alert")]: frame = _filter(frame, col, params.get(key))
    if params.get("date_from"): frame = frame[pd.to_datetime(frame.crawl_date) >= pd.Timestamp(params["date_from"])]
    if params.get("date_to"): frame = frame[pd.to_datetime(frame.crawl_date) <= pd.Timestamp(params["date_to"])]
    sort = SORTS.get(params.get("sort"), "crawl_date"); ascending = params.get("direction") == "asc"
    frame = frame.sort_values(sort, ascending=ascending, na_position="last", kind="stable")
    total = len(frame); page=params["page"]; size=params["page_size"]; frame=frame.iloc[(page-1)*size:page*size]
    def nullable(value):
        if pd.isna(value): return None
        if hasattr(value, "item"): value=value.item()
        return value
    rows=[]
    for _, r in frame.iterrows():
        rows.append({"productId":r.product_id,"date":r.crawl_date.isoformat(),"country":r.country,"brand":r.brand,"sku":r.model,"memory":r.memory,"mrp":nullable(r.get("mrp")),"discountPct":nullable(r.discount_pct),"darazPrice":nullable(r.daraz_price),"darazUrl":nullable(r.get("daraz_url")) or None,"competitorPlatform":nullable(r.competitor_platform),"competitorPrice":nullable(r.competitor_price),"competitorUrl":nullable(r.get("competitor_url")) or None,"gapAmount":nullable(r.gap_amount),"gapPct":nullable(r.gap_pct),"alert":nullable(r.alert)})
    return {"rows":rows,"pagination":{"page":page,"pageSize":size,"total":total,"totalPages":max(1,(total+size-1)//size)},"meta":meta(snapshot)}

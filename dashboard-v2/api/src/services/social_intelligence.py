from __future__ import annotations

from collections import Counter
from datetime import timedelta
import math
import re
from typing import Any

import pandas as pd


KEYWORD_STOPWORDS = {
    "about", "after", "again", "also", "among", "and", "are", "been", "being", "brand",
    "but", "can", "could", "day", "every", "for", "from", "has", "have", "here", "into",
    "its", "latest", "more", "new", "now", "our", "out", "over", "pakistan", "bangladesh",
    "phone", "phones", "mobile", "product", "post", "reported", "series", "that", "the", "their", "this", "through",
    "with", "your", "you", "will", "was", "were", "what", "when", "where", "which",
    "million", "compared", "company", "available", "officially", "month", "next", "detail",
}

GENERIC_TOPIC_TAGS = {"mobile", "product", "brand", "electronics", "market", "development", "manufacturing", "assembly"}
PHRASE_RULES = {
    "local manufacturing": r"\b(?:local\s+)?(?:manufactur(?:e|ing|ed)|assembl(?:y|ing|ed))\b",
    "battery life": r"\b(?:battery|\d{4,5}\s?mah|charging)\b",
    "camera & imaging": r"\b(?:camera|portrait|telephoto|megapixel|\d{2,3}\s?mp)\b",
    "5G & connectivity": r"\b(?:5g|4g|connectivity|telecom|network)\b",
    "durability": r"\b(?:durab|shock|resistan|ip6[7-9]|waterproof|dust)\w*\b",
    "launch & availability": r"\b(?:launch|unveil|arriv|available|debut)\w*\b",
    "pricing & tax": r"\b(?:price|pricing|tax|pta|import|regulation)\w*\b",
    "display": r"\b(?:display|screen|amoled|refresh\s+rate)\b",
    "AI features": r"\b(?:ai|artificial intelligence|google ai)\b",
    "gaming": r"\b(?:gaming|free fire|game)\w*\b",
}

BRAND_ALIASES = {
    "apple": "Apple", "honor": "HONOR", "infinix": "Infinix", "itel": "Itel",
    "nubia": "Nubia", "oppo": "OPPO", "realme": "realme", "redmi": "XIAOMI",
    "samsung": "Samsung", "tecno": "TECNO", "vivo": "vivo", "xiaomi": "XIAOMI",
    "huawei": "Huawei", "motorola": "Motorola", "nokia": "Nokia", "oneplus": "OnePlus",
    "google": "Google", "banglalink": "Banglalink", "grameenphone": "Grameenphone",
    "jazz": "Jazz", "zong": "Zong", "telenor": "Telenor", "ufone": "Ufone",
    "robi": "Robi", "airtel": "Airtel",
}
RATING_WEIGHTS = {"activity": 0.25, "reach": 0.20, "engagement": 0.30, "earned": 0.25}


def _keyword_cloud(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Build decision-useful themes instead of a bag of generic single words."""
    scores: Counter[str] = Counter()
    for row in frame.itertuples():
        text = f"{row.title} {row.content_summary}".casefold()
        for label, pattern in PHRASE_RULES.items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                scores[label] += 2
        brand = str(row.brand).strip()
        if brand and brand.casefold() not in {"nan", "all brand", "other"}:
            for item in re.split(r"[;,/]", brand):
                item = item.strip()
                if item:
                    scores[item] += 2
        # Product families and model names are usually the most actionable entities.
        for model in re.findall(r"\b(?:galaxy|redmi|note|reno|pova|hot|magic|iphone|realme|vivo|tecno|infinix|honor|oppo|nubia|itel)(?:\s+[a-z][a-z0-9+\-]*)?\s+[a-z0-9+\-]*\d[a-z0-9+\-]*(?:\s+5g)?\b", text, flags=re.IGNORECASE):
            scores[model.strip().title()] += 3
        for tag in str(row.topic_tags).split(";"):
            tag = tag.strip()
            if len(tag) >= 4 and tag.casefold() not in GENERIC_TOPIC_TAGS:
                scores[tag] += 1
    return [{"label": label, "count": count} for label, count in scores.most_common(24)]


def _filter(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    frame = data
    for column, key in [
        ("country", "country"), ("platform", "platform"), ("monitor_type", "monitor_type"),
        ("account_type", "account_type"), ("media_type", "media_type"),
    ]:
        values = params.get(key) or []
        if values:
            wanted = {str(value).casefold() for value in values}
            frame = frame[frame[column].astype(str).str.casefold().isin(wanted)]
    brand_values = params.get("brand") or []
    if brand_values:
        wanted_brands = {
            canonical.casefold()
            for value in brand_values
            for canonical in (_brands(value) or [str(value).strip()])
            if canonical
        }
        frame = frame[
            frame["brand"].map(
                lambda value: bool(wanted_brands.intersection(brand.casefold() for brand in _brands(value)))
            )
        ]
    if params.get("date_from"):
        frame = frame[frame["published_at"] >= pd.Timestamp(params["date_from"], tz="UTC")]
    if params.get("date_to"):
        frame = frame[frame["published_at"] < pd.Timestamp(params["date_to"], tz="UTC") + pd.Timedelta(days=1)]
    query = str(params.get("query") or "").strip()
    if query:
        searchable = frame[["title", "content_summary", "content", "account_name"]].fillna("").agg(" ".join, axis=1)
        frame = frame[searchable.str.contains(query, case=False, regex=False)]
    return frame


def _values(frame: pd.DataFrame, column: str) -> list[str]:
    return sorted(value for value in frame[column].dropna().astype(str).str.strip().unique().tolist() if value)


def _brands(value: Any) -> list[str]:
    """Return stable brand entities; a record may legitimately mention multiple brands."""
    found: list[str] = []
    for raw in re.split(r"[;,/]", str(value or "")):
        key = raw.strip().casefold()
        if not key or key in {"nan", "all brand", "all brands", "other"}:
            continue
        brand = BRAND_ALIASES.get(key)
        if brand and brand not in found:
            found.append(brand)
    return found


def _brand_values(frame: pd.DataFrame) -> list[str]:
    """Return one canonical option per brand, never a raw multi-brand cell."""
    return sorted(
        {brand for value in frame["brand"].dropna() for brand in _brands(value)},
        key=str.casefold,
    )


def _scale(values: dict[str, float]) -> dict[str, float]:
    """Log-normalized 0-100 score so one viral post cannot dominate the market."""
    transformed = {key: math.log1p(max(0.0, float(value))) for key, value in values.items()}
    if not transformed:
        return {}
    low, high = min(transformed.values()), max(transformed.values())
    if high == low:
        score = 100.0 if high > 0 else 0.0
        return {key: score for key in transformed}
    return {key: round((value - low) / (high - low) * 100, 2) for key, value in transformed.items()}


def _rating_day(frame: pd.DataFrame, day: pd.Timestamp, window_days: int) -> list[dict[str, Any]]:
    start = day - pd.Timedelta(days=window_days - 1)
    window = frame[(frame["published_at"] >= start) & (frame["published_at"] < day + pd.Timedelta(days=1))].copy()
    exploded: list[dict[str, Any]] = []
    for row in window.to_dict("records"):
        for brand in _brands(row.get("brand")):
            exploded.append({**row, "rating_brand": brand})
    if not exploded:
        return []
    rated = pd.DataFrame(exploded)
    metrics: dict[str, dict[str, Any]] = {}
    for brand, rows in rated.groupby("rating_brand"):
        owned = rows[(rows["account_type"].str.casefold() == "brand") & (rows["monitor_type"].str.casefold() == "watchlist")]
        earned = rows.drop(owned.index)
        likes = rows["likes"].dropna()
        views = rows["views"].dropna()
        metrics[brand] = {
            "voicePosts": int(owned["source_url"].nunique()),
            "earnedMentions": int(earned["source_url"].nunique()),
            "totalViews": int(views.sum()),
            "totalLikes": int(likes.sum()),
            "medianLikesPerPost": round(float(likes.median()), 1) if not likes.empty else None,
            "signalCount": int(rows["source_url"].nunique()),
            "viewsCoverage": round(float(rows["views"].notna().mean()), 4),
            "engagementCoverage": round(float(rows["likes"].notna().mean()), 4),
        }
    activity = _scale({brand: item["voicePosts"] for brand, item in metrics.items()})
    reach = _scale({brand: item["totalViews"] for brand, item in metrics.items() if item["viewsCoverage"] > 0})
    total_likes = _scale({brand: item["totalLikes"] for brand, item in metrics.items()})
    median_likes = _scale({brand: item["medianLikesPerPost"] or 0 for brand, item in metrics.items()})
    earned = _scale({brand: item["earnedMentions"] for brand, item in metrics.items()})
    results = []
    for brand, item in metrics.items():
        component = {
            "activityScore": activity.get(brand, 0.0),
            "reachScore": reach.get(brand),
            "engagementScore": round(total_likes.get(brand, 0.0) * .7 + median_likes.get(brand, 0.0) * .3, 2),
            "earnedScore": earned.get(brand, 0.0),
        }
        available = {
            "activity": component["activityScore"], "engagement": component["engagementScore"],
            "earned": component["earnedScore"],
        }
        if component["reachScore"] is not None:
            available["reach"] = component["reachScore"]
        weight_total = sum(RATING_WEIGHTS[key] for key in available)
        rating = sum(value * RATING_WEIGHTS[key] for key, value in available.items()) / weight_total if weight_total else 0
        coverage = (item["viewsCoverage"] + item["engagementCoverage"]) / 2
        confidence = "High" if item["signalCount"] >= 5 and coverage >= .5 else "Medium" if item["signalCount"] >= 2 else "Low"
        results.append({"date": day.date().isoformat(), "brand": brand, **item, **component, "socialRating": round(rating, 1), "confidenceLevel": confidence})
    results.sort(key=lambda item: (-item["socialRating"], -item["signalCount"], item["brand"].casefold()))
    for rank, item in enumerate(results, 1):
        item["rank"] = rank
    return results


def brand_ratings(data: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    """Calculate a daily rolling brand-rating trajectory from verified intelligence."""
    period_days = max(1, min(30, int(params.get("period_days") or 7)))
    top_n = max(3, min(10, int(params.get("top_n") or 6)))
    base_params = {
        "country": [params["country"]] if params.get("country") else [],
        "platform": [params["platform"]] if params.get("platform") else [],
        "monitor_type": [params["monitor_type"]] if params.get("monitor_type") else [],
    }
    frame = _filter(data, base_params)
    dated = frame["published_at"].dropna()
    if dated.empty:
        return {"dates": [], "brands": [], "series": [], "methodology": {"version": "1.0", "weights": RATING_WEIGHTS}}
    end = pd.Timestamp(params.get("date_to"), tz="UTC") if params.get("date_to") else dated.max().normalize()
    display_start = end - pd.Timedelta(days=period_days - 1)
    days = pd.date_range(display_start, end, freq="D", tz="UTC")
    daily = [_rating_day(frame, day, period_days) for day in days]
    latest = daily[-1] if daily else []
    selected = [item["brand"] for item in latest[:top_n]]
    # When today's latest set is sparse, retain brands that led during the displayed period.
    if len(selected) < top_n:
        frequency = Counter(item["brand"] for rows in daily for item in rows)
        selected.extend(brand for brand, _ in frequency.most_common() if brand not in selected and len(selected) < top_n)
    previous: dict[str, dict[str, Any]] = {}
    series = []
    for rows in daily:
        by_brand = {item["brand"]: item for item in rows}
        for brand in selected:
            item = by_brand.get(brand)
            if not item:
                continue
            prior = previous.get(brand)
            point = {**item, "rankChange": (prior["rank"] - item["rank"]) if prior else 0, "scoreChange": round(item["socialRating"] - prior["socialRating"], 1) if prior else 0.0}
            series.append(point)
            previous[brand] = item
    leaders = [item for item in latest if item["brand"] in selected]
    return {
        "dates": [day.date().isoformat() for day in days], "brands": selected, "series": series, "leaders": leaders,
        "methodology": {"version": "1.0", "windowDays": period_days, "weights": RATING_WEIGHTS, "missingReach": "Weights are rebalanced when verified views are unavailable."},
    }


def filters(data: pd.DataFrame) -> dict[str, Any]:
    dates = data["published_at"].dropna()
    return {"options": {
        "countries": _values(data, "country"), "platforms": _values(data, "platform"),
        "monitorTypes": _values(data, "monitor_type"), "brands": _brand_values(data),
        "accountTypes": _values(data, "account_type"), "mediaTypes": _values(data, "media_type"),
        "dateRange": {"min": dates.min().date().isoformat() if not dates.empty else None, "max": dates.max().date().isoformat() if not dates.empty else None},
    }}


def dashboard(data: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    frame = _filter(data, params)
    sort = params.get("sort", "recent")
    if sort == "views":
        frame = frame.sort_values(["views", "published_at"], ascending=[False, False], na_position="last")
    elif sort == "likes":
        frame = frame.sort_values(["likes", "published_at"], ascending=[False, False], na_position="last")
    else:
        frame = frame.sort_values("published_at", ascending=False, na_position="last")
    limit = int(params.get("limit", 40))
    impact = Counter(item.strip() for value in frame["business_impact"] for item in str(value).split(";") if item.strip())
    topics = Counter(value for value in frame["topic"].astype(str) if value)
    records = []
    for row in frame.head(limit).to_dict("records"):
        published = row.get("published_at")
        records.append({
            "recordId": row.get("record_id", ""), "publishedAt": published.isoformat() if pd.notna(published) else None,
            "country": row.get("country", ""), "platform": row.get("platform", ""), "monitorType": row.get("monitor_type", ""),
            "accountName": row.get("account_name", ""), "accountType": row.get("account_type", ""), "category": row.get("category", ""),
            "topic": row.get("topic", ""), "brand": row.get("brand", ""), "title": row.get("title", ""),
            "content": row.get("content", ""), "contentSummary": row.get("content_summary", ""), "whyItMatters": row.get("why_it_matters", ""),
            "businessImpact": [item.strip() for item in str(row.get("business_impact", "")).split(";") if item.strip()],
            "topicTags": [item.strip() for item in str(row.get("topic_tags", "")).split(";") if item.strip()],
            "views": None if pd.isna(row.get("views")) else int(row["views"]), "viewsStatus": row.get("views_status", ""),
            "likes": None if pd.isna(row.get("likes")) else int(row["likes"]), "sourceUrl": row.get("source_url", ""),
            "mediaType": row.get("media_type", ""), "mediaUrl": row.get("media_url", ""), "qualityStatus": row.get("quality_status", ""),
        })
    return {
        "metrics": {"signalCount": len(frame), "totalViews": int(frame["views"].dropna().sum()), "totalLikes": int(frame["likes"].dropna().sum()), "trendShare": round(float((frame["monitor_type"].str.casefold() == "trend_discovery").mean()), 4) if len(frame) else 0},
        "topTopics": [{"label": label, "count": count} for label, count in topics.most_common(5)],
        "keywordCloud": _keyword_cloud(frame),
        "businessImpact": [{"label": label, "count": count} for label, count in impact.most_common(8)],
        "records": records, "meta": {"filteredCount": len(frame), "sourceCount": len(data), "returnedCount": len(records)},
    }

from __future__ import annotations

from collections import Counter
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
        ("brand", "brand"), ("account_type", "account_type"), ("media_type", "media_type"),
    ]:
        values = params.get(key) or []
        if values:
            wanted = {str(value).casefold() for value in values}
            frame = frame[frame[column].astype(str).str.casefold().isin(wanted)]
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


def filters(data: pd.DataFrame) -> dict[str, Any]:
    dates = data["published_at"].dropna()
    return {"options": {
        "countries": _values(data, "country"), "platforms": _values(data, "platform"),
        "monitorTypes": _values(data, "monitor_type"), "brands": _values(data, "brand"),
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

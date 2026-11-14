from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from src.services.social_intelligence import _rating_day, _record_brands


COUNTRY_NAMES = {"PK": "Pakistan", "BD": "Bangladesh", "LK": "Sri Lanka", "MM": "Myanmar", "NP": "Nepal"}
BRAND_ALIASES = {"honor": "HONOR", "xiaomi": "XIAOMI", "redmi": "XIAOMI", "oppo": "OPPO", "tecno": "TECNO"}


def _brand(value: Any) -> str:
    text = str(value or "").strip()
    return BRAND_ALIASES.get(text.casefold(), text)


def _window(frame: pd.DataFrame, column: str, end: pd.Timestamp, offset: int = 0) -> pd.DataFrame:
    finish = end - pd.Timedelta(days=offset)
    start = finish - pd.Timedelta(days=6)
    dates = pd.to_datetime(frame[column], errors="coerce", utc=True).dt.tz_localize(None)
    return frame[(dates >= start) & (dates < finish + pd.Timedelta(days=1))]


def _consumer_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    rated = frame[frame["rating_valid"]]
    topics: Counter[tuple[str, str]] = Counter(signal for signals in frame["topic_signals"] for signal in signals)
    positive = [item for (item, sentiment), count in topics.most_common() if sentiment == "positive" for _ in range(count)]
    negative = [item for (item, sentiment), count in topics.most_common() if sentiment == "negative" for _ in range(count)]
    return {
        "averageRating": round(float(rated["rating"].mean()), 2) if not rated.empty else None,
        "reviewCount": int(len(frame)),
        "positiveRate": round(float((rated["rating"] >= 4).mean()), 4) if not rated.empty else None,
        "negativeRate": round(float((rated["rating"] <= 2).mean()), 4) if not rated.empty else None,
        "topPositiveTopics": list(dict.fromkeys(positive))[:2],
        "topRiskTopics": list(dict.fromkeys(negative))[:2],
    }


def _change(current: float | None, previous: float | None) -> float | None:
    return round(current - previous, 2) if current is not None and previous is not None else None


def _consumer_by_brand(data: pd.DataFrame, country: str, end: pd.Timestamp) -> dict[str, dict[str, Any]]:
    country_data = data[data["venture"].astype(str).str.casefold() == country.casefold()]
    result: dict[str, dict[str, Any]] = {}
    brands = {_brand(value) for value in country_data["brand"].dropna().unique() if _brand(value) and _brand(value) != "Other"}
    for brand in brands:
        rows = country_data[country_data["brand"].map(_brand) == brand]
        current = _consumer_metrics(_window(rows, "created_at", end))
        previous = _consumer_metrics(_window(rows, "created_at", end, 7))
        result[brand] = {
            **current,
            "ratingChange": _change(current["averageRating"], previous["averageRating"]),
            "reviewCountChange": current["reviewCount"] - previous["reviewCount"],
            "negativeRateChange": _change(current["negativeRate"], previous["negativeRate"]),
        }
    return result


def _social_by_brand(data: pd.DataFrame, country: str, end: pd.Timestamp) -> dict[str, dict[str, Any]]:
    rows = data[data["country"].astype(str).str.casefold() == country.casefold()].copy()
    if rows.empty:
        return {}
    rows["published_at"] = pd.to_datetime(rows["published_at"], errors="coerce", utc=True)
    current = {item["brand"]: item for item in _rating_day(rows, end.tz_localize("UTC"), 7)}
    previous = {item["brand"]: item for item in _rating_day(rows, (end - pd.Timedelta(days=7)).tz_localize("UTC"), 7)}
    result = {}
    for brand, item in current.items():
        prior = previous.get(brand)
        brand_rows = _window(rows, "published_at", end)
        brand_rows = brand_rows[brand_rows.apply(lambda row: brand in _record_brands(row), axis=1)]
        topics = Counter(
            tag.strip() for value in brand_rows["topic_tags"] for tag in str(value).split(";") if tag.strip()
        )
        result[brand] = {
            "socialRating": item["socialRating"],
            "ratingChange": _change(item["socialRating"], prior["socialRating"] if prior else None),
            "rank": item["rank"],
            "signalCount": item["signalCount"],
            "totalLikes": item["totalLikes"],
            "totalViews": item["totalViews"],
            "confidence": item["confidenceLevel"],
            "topTopics": [label for label, _count in topics.most_common(2)],
        }
    return result


def _status(consumer: dict[str, Any] | None, social: dict[str, Any] | None) -> tuple[str, str]:
    consumer_change = (consumer or {}).get("ratingChange")
    negative_change = (consumer or {}).get("negativeRateChange")
    social_change = (social or {}).get("ratingChange")
    if (consumer_change is not None and consumer_change <= -0.25) or (negative_change is not None and negative_change >= 0.1):
        return "watch_closely", "Watch closely"
    if social_change is not None and social_change >= 8:
        return "social_momentum", "Social-led momentum"
    if consumer_change is not None and consumer_change >= 0.25:
        return "consumer_momentum", "Consumer-led momentum"
    if consumer and social and (consumer.get("averageRating") or 0) >= 4.2 and (social.get("rank") or 99) <= 2:
        return "leading", "Leading"
    return "stable", "Stable"


def _confidence(consumer: dict[str, Any] | None, social: dict[str, Any] | None) -> str:
    consumer_ok = bool(consumer and consumer["reviewCount"] >= 10)
    social_ok = bool(social and social["signalCount"] >= 5)
    return "High" if consumer_ok and social_ok else "Medium" if consumer_ok or social_ok else "Low"


def _signal(brand: str, status: str, consumer: dict[str, Any] | None, social: dict[str, Any] | None) -> str:
    if status == "watch_closely":
        topic = ((consumer or {}).get("topRiskTopics") or ["negative feedback"])[0]
        return f"{topic} is the main consumer risk to review."
    if status == "social_momentum":
        return f"Social rating increased by {social['ratingChange']:+.1f} points."
    if status == "consumer_momentum":
        return f"Consumer rating increased by {consumer['ratingChange']:+.2f}."
    if status == "leading":
        return "Strong performance across both consumer and social voice."
    if consumer or social:
        return "No material week-on-week shift detected."
    return f"Insufficient verified data for {brand} this week."


def build_weekly_brief(consumer_data: pd.DataFrame, social_data: pd.DataFrame, country: str = "", week_end: str | None = None) -> dict[str, Any]:
    countries = sorted(set(consumer_data["venture"].dropna().astype(str)) | set(social_data["country"].dropna().astype(str)))
    selected = country if country in countries else ("PK" if "PK" in countries else countries[0] if countries else "")
    all_dates = pd.concat([
        pd.to_datetime(consumer_data["created_at"], errors="coerce").dropna(),
        pd.to_datetime(social_data["published_at"], errors="coerce", utc=True).dt.tz_localize(None).dropna(),
    ])
    end = pd.Timestamp(week_end).normalize() if week_end else all_dates.max().normalize()
    consumer = _consumer_by_brand(consumer_data, selected, end)
    social = _social_by_brand(social_data, selected, end)
    brands = []
    for brand in sorted(set(consumer) | set(social), key=str.casefold):
        cv, sv = consumer.get(brand), social.get(brand)
        status, status_label = _status(cv, sv)
        brands.append({
            "brand": brand, "status": status, "statusLabel": status_label,
            "confidence": _confidence(cv, sv), "keySignal": _signal(brand, status, cv, sv),
            "consumerVoice": cv, "socialVoice": sv,
        })
    priority = {"watch_closely": 0, "social_momentum": 1, "consumer_momentum": 1, "leading": 2, "stable": 3}
    brands.sort(key=lambda item: (priority[item["status"]], item["brand"].casefold()))
    material = [item for item in brands if item["status"] not in {"stable"} and item["confidence"] != "Low"]
    strongest = max(brands, key=lambda item: ((item["consumerVoice"] or {}).get("averageRating") or 0) * 20 + ((item["socialVoice"] or {}).get("socialRating") or 0), default=None)
    momentum = max(brands, key=lambda item: ((item["socialVoice"] or {}).get("ratingChange") or 0) + ((item["consumerVoice"] or {}).get("ratingChange") or 0) * 20, default=None)
    watch = next((item for item in brands if item["status"] == "watch_closely"), None)
    summary = "No material market shifts were detected this week."
    if material:
        summary = " ".join(f"{item['brand']}: {item['keySignal']}" for item in material[:2])
    return {
        "week": {"start": (end - pd.Timedelta(days=6)).date().isoformat(), "end": end.date().isoformat(), "comparisonStart": (end - pd.Timedelta(days=13)).date().isoformat(), "comparisonEnd": (end - pd.Timedelta(days=7)).date().isoformat()},
        "country": {"code": selected, "name": COUNTRY_NAMES.get(selected, selected)},
        "countries": [{"code": code, "name": COUNTRY_NAMES.get(code, code)} for code in countries],
        "marketSummary": summary,
        "callouts": {"strongest": strongest["brand"] if strongest else None, "momentum": momentum["brand"] if momentum else None, "watch": watch["brand"] if watch else None},
        "highlights": [{"brand": item["brand"], "status": item["status"], "statusLabel": item["statusLabel"], "text": item["keySignal"], "confidence": item["confidence"]} for item in material[:5]],
        "brands": brands,
        "meta": {"consumerRows": int(sum((item["consumerVoice"] or {}).get("reviewCount", 0) for item in brands)), "socialSignals": int(sum((item["socialVoice"] or {}).get("signalCount", 0) for item in brands))},
    }

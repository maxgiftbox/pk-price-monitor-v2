from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from src.domain.consumer_voice import TAG_RULES


def _filter(data: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    frame = data
    for column, key in [("venture", "venture"), ("brand", "brand"), ("product_id", "product_id")]:
        values = params.get(key) or []
        if values:
            frame = frame[frame[column].astype(str).isin([str(value) for value in values])]
    if params.get("date_from"):
        frame = frame[frame["created_at"] >= pd.Timestamp(params["date_from"])]
    if params.get("date_to"):
        frame = frame[frame["created_at"] <= pd.Timestamp(params["date_to"])]
    sentiment = params.get("sentiment")
    if sentiment and sentiment != "all":
        frame = frame[frame["sentiment"] == sentiment]
    return frame


def _options(frame: pd.DataFrame) -> dict[str, Any]:
    dates = frame["created_at"].dropna()
    products = (
        frame[["product_id", "product_name", "brand"]]
        .drop_duplicates("product_id")
        .sort_values(["brand", "product_name"])
    )
    return {
        "ventures": sorted(frame["venture"].dropna().astype(str).unique().tolist()),
        "brands": sorted(frame["brand"].dropna().astype(str).unique().tolist()),
        "products": [
            {"id": row.product_id, "name": row.product_name, "brand": row.brand}
            for row in products.itertuples()
        ],
        "dateRange": {
            "min": dates.min().date().isoformat() if not dates.empty else None,
            "max": dates.max().date().isoformat() if not dates.empty else None,
        },
    }


def filters(data: pd.DataFrame) -> dict[str, Any]:
    return {"options": _options(data)}


def dashboard(data: pd.DataFrame, params: dict[str, Any]) -> dict[str, Any]:
    frame = _filter(data, params)
    rated = frame[frame["rating_valid"]]
    total = len(frame)
    average_rating = float(rated["rating"].mean()) if not rated.empty else None
    positive_rate = float((rated["rating"] >= 4).mean()) if not rated.empty else None

    dimensions = []
    for column, label in [("product_rating", "Product"), ("seller_rating", "Seller"), ("logistics_rating", "Logistics")]:
        valid = frame[column].dropna()
        dimensions.append({"dimension": label, "score": round(float(valid.mean()), 2) if not valid.empty else None})

    stars = [
        {"rating": rating, "count": int((rated["rating"] == rating).sum())}
        for rating in range(1, 6)
    ]

    tag_counts: Counter[str] = Counter(tag for tags in frame["tags"] for tag in tags)
    tags = [
        {"label": label, "count": count, "sentiment": TAG_RULES[label][0]}
        for label, count in tag_counts.most_common(18)
    ]

    alerts = []
    for row in frame.sort_values(["rating", "upvotes"], ascending=[True, False]).itertuples():
        reasons = list(row.sensitive_terms)
        if row.rating_valid and row.rating <= 2:
            reasons.insert(0, f"{int(row.rating)}-star review")
        if row.rating_sentiment_mismatch:
            reasons.append("Rating and text mismatch")
        if not reasons:
            continue
        alerts.append({
            "productId": row.product_id,
            "productName": row.product_name,
            "venture": row.venture,
            "rating": int(row.rating) if row.rating_valid else None,
            "review": row.review_content,
            "reasons": list(dict.fromkeys(reasons)),
            "date": row.created_at.date().isoformat() if pd.notna(row.created_at) else None,
        })
        if len(alerts) == 8:
            break

    sort = params.get("sort", "recent")
    if sort == "helpful":
        review_frame = frame.sort_values(["upvotes", "created_at"], ascending=[False, False])
    else:
        review_frame = frame.sort_values("created_at", ascending=False)

    reviews = []
    for row in review_frame.itertuples():
        images = [getattr(row, f"image_{index}") for index in range(1, 7)]
        reviews.append({
            "id": f"{row.product_id}-{row.Index}",
            "productId": row.product_id,
            "productName": row.product_name,
            "brand": row.brand,
            "venture": row.venture,
            "date": row.created_at.date().isoformat() if pd.notna(row.created_at) else None,
            "rating": int(row.rating) if row.rating_valid else None,
            "sentiment": row.sentiment,
            "review": row.review_content,
            "upvotes": int(row.upvotes or 0),
            "tags": row.tags,
            "images": [image for image in images if image],
        })

    return {
        "metrics": {
            "averageRating": round(average_rating, 2) if average_rating is not None else None,
            "positiveRate": round(positive_rate, 4) if positive_rate is not None else None,
            "reviewCount": total,
            "ratedReviewCount": len(rated),
            "imageReviewCount": int((frame["image_count"] > 0).sum()),
        },
        "dimensions": dimensions,
        "stars": stars,
        "tags": tags,
        "alerts": alerts,
        "reviews": reviews,
        "meta": {"filteredCount": total, "sourceCount": len(data)},
    }

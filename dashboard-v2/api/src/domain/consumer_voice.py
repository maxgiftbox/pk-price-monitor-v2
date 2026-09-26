from __future__ import annotations

import re
from typing import Iterable

import pandas as pd


MISSING = {"", "\\n", "nan", "none", "null"}

TOPIC_RULES: dict[str, list[str]] = {
    "Performance & processor": ["performance", "processor", "chipset", "smooth", "lag", "hanging", "gaming"],
    "Camera quality": ["camera", "picture quality", "photo", "zoom"],
    "Battery life": ["battery", "battery life", "battery timing", "backup"],
    "Display & touch": ["display", "screen", "touch", "brightness", "amoled"],
    "Charging & adapter": ["charging", "charger", "adapter", "adaptor", "cable"],
    "Build & design": ["build quality", "design", "stylish", "slim", "premium look"],
    "Audio & speaker": ["speaker", "sound", "audio"],
    "Software & UI": ["software", "android", "one ui", "update", "interface"],
    "Network & PTA": ["pta", "network", "signal", "sim"],
    "Storage & memory": ["storage", "memory", " ram", " rom"],
    "Price & value": ["price", "value for money", "value of money", "worth", "budget"],
    "Authenticity": ["original", "authentic", "genuine", "brand new", "sealed"],
    "Packaging": ["packaging", "packed", "packing", "sealed pack"],
    "Delivery": ["delivery", "delivered"],
    "Seller service": ["seller", "customer service"],
    "Warranty": ["warranty"],
    "Gifts & vouchers": ["voucher", "gift", "powerbank", "power bank"],
    "Returns & refunds": ["return", "refund"],
}

NEGATIVE_CUES = [
    "not good", "not impressive", "not recommend", "no ", "missing", "without",
    "slow", "late", "delay", "poor", "bad", "worst", "issue", "problem",
    "defect", "does not", "doesn't", "drain", "heating", "overheat", "garam",
    "older", "out of stock", "damaged",
]
POSITIVE_CUES = [
    "good", "great", "best", "excellent", "fast", "smooth", "long", "bright",
    "vibrant", "crisp", "original", "authentic", "satisfied", "nice", "well",
    "safe", "recommended", "zabardast", "acha", "ভালো", "ভাল",
]

SENSITIVE_TERMS = {
    "Non PTA": ["non pta", "non-pta"],
    "Overheating": ["heat up", "heating", "overheat", "garam"],
    "Warranty": ["warranty", "expire"],
    "Return policy": ["return policy", "refund", "return"],
    "Voucher or gift": ["voucher", "gift deynai", "no gift", "did not get", "out of stock"],
    "Poor experience": ["pathetic", "ghatiya", "not recommend", "worst", "fraud", "fake"],
}


def _clean_text(value: object) -> str:
    text = str(value).strip()
    return "" if text.casefold() in MISSING else text


def _brand(product_name: str) -> str:
    value = product_name.casefold()
    for brand in ["Samsung", "Realme", "Oppo", "Xiaomi", "Vivo", "Tecno", "Infinix", "Apple"]:
        if brand.casefold() in value:
            return brand
    return "Other"


def _matches(text: str, terms: Iterable[str]) -> bool:
    haystack = re.sub(r"\s+", " ", text.casefold())
    return any(term in haystack for term in terms)


def _is_seller_reply(text: str) -> bool:
    value = re.sub(r"\s+", " ", text.casefold()).strip()
    return value.startswith(("dear customer", "moaziz sarif")) or "your kind review" in value


def _topic_signals(rating: float | None, text: str) -> list[tuple[str, str]]:
    if not text or _is_seller_reply(text):
        return []
    haystack = re.sub(r"\s+", " ", text.casefold())
    fallback = "negative" if rating and rating <= 2 else "positive" if rating and rating >= 4 else "neutral"
    signals = []
    for label, terms in TOPIC_RULES.items():
        positions = [haystack.find(term) for term in terms if term in haystack]
        if not positions:
            continue
        position = min(positions)
        window = haystack[max(0, position - 70):position + 130]
        sentiment = (
            "negative" if any(cue in window for cue in NEGATIVE_CUES)
            else "positive" if any(cue in window for cue in POSITIVE_CUES)
            else fallback
        )
        signals.append((label, sentiment))
    return signals


def _sensitive(text: str) -> list[str]:
    return [label for label, terms in SENSITIVE_TERMS.items() if _matches(text, terms)]


def _sentiment(rating: float | None, text: str) -> str:
    if rating and rating <= 2:
        return "negative"
    if rating and rating >= 4:
        return "positive"
    haystack = re.sub(r"\s+", " ", text.casefold())
    if any(cue in haystack for cue in NEGATIVE_CUES):
        return "negative"
    if any(cue in haystack for cue in POSITIVE_CUES):
        return "positive"
    return "neutral"


def prepare_reviews(raw: pd.DataFrame) -> pd.DataFrame:
    data = raw.copy()
    data.columns = [str(column).strip().casefold() for column in data.columns]
    if "product_name" not in data.columns and "standard_product_name" in data.columns:
        data["product_name"] = data["standard_product_name"]
    if "brand" not in data.columns:
        data["brand"] = ""
    for column in ["product_rating", "seller_rating", "logistics_rating", "upvotes", "downvotes", "image_count"]:
        if column not in data.columns:
            data[column] = None
    for column in [f"image_{index}" for index in range(1, 7)]:
        if column not in data.columns:
            data[column] = ""
    for column in ["rating", "product_rating", "seller_rating", "logistics_rating", "upvotes", "downvotes", "image_count"]:
        data[column] = pd.to_numeric(data[column].replace("\\N", None), errors="coerce")
    data["created_at"] = pd.to_datetime(data["create_date_short"], errors="coerce")
    data["product_id"] = data["product_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    data["product_name"] = data["product_name"].map(_clean_text)
    data["review_content"] = data["review_content"].map(_clean_text)
    supplied_brand = data["brand"].map(_clean_text)
    data["brand"] = supplied_brand.where(supplied_brand != "", data["product_name"].map(_brand))
    data["rating_valid"] = data["rating"].between(1, 5)
    data["sensitive_terms"] = data["review_content"].map(_sensitive)
    data["sentiment"] = [
        _sentiment(rating if valid else None, text)
        for rating, valid, text in zip(data["rating"], data["rating_valid"], data["review_content"])
    ]
    data["topic_signals"] = [
        _topic_signals(rating if valid else None, text)
        for rating, valid, text in zip(data["rating"], data["rating_valid"], data["review_content"])
    ]
    data["tags"] = data["topic_signals"].map(lambda signals: [label for label, _sentiment in signals])
    data["rating_sentiment_mismatch"] = (
        (data["rating_valid"])
        & (((data["rating"] >= 4) & (data["sentiment"] == "negative")) | ((data["rating"] <= 2) & (data["sentiment"] == "positive")))
    )
    for column in [f"image_{index}" for index in range(1, 7)]:
        data[column] = data[column].map(_clean_text)
    return data

from __future__ import annotations

import re
from typing import Iterable

import pandas as pd


MISSING = {"", "\\n", "nan", "none", "null"}

TAG_RULES: dict[str, tuple[str, list[str]]] = {
    "Good quality": ("positive", ["good quality", "great product", "excellent", "original", "ভালো", "ভাল"]),
    "Good value": ("positive", ["best deal", "price is low", "reasonable price", "worth", "value for money"]),
    "Fast delivery": ("positive", ["fast delivery", "quick delivery", "on time", "two day", "দুই দিনের ভিতরে"]),
    "Battery": ("neutral", ["battery", "battery timing", "backup"]),
    "Camera": ("neutral", ["camera", "picture quality"]),
    "Display": ("neutral", ["display", "screen", "brightness", "sharpness"]),
    "Overheating": ("negative", ["heat up", "heating", "overheat", "garam"]),
    "Warranty issue": ("negative", ["warranty", "expire", "activation"]),
    "Voucher or gift issue": ("negative", ["voucher", "gift deynai", "no gift", "did not get", "out of stock"]),
    "Poor quality": ("negative", ["bad quality", "poor quality", "pathetic", "ghatiya", "not recommend"]),
    "Delivery issue": ("negative", ["late delivery", "delay", "damaged", "missing", "out of stock"]),
    "Non PTA": ("negative", ["non pta", "non-pta"]),
}

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


def _tags(text: str) -> list[str]:
    return [label for label, (_, terms) in TAG_RULES.items() if _matches(text, terms)]


def _sensitive(text: str) -> list[str]:
    return [label for label, terms in SENSITIVE_TERMS.items() if _matches(text, terms)]


def _sentiment(rating: float | None, text: str) -> str:
    negative_text = any(_matches(text, terms) for sentiment, terms in TAG_RULES.values() if sentiment == "negative")
    positive_text = any(_matches(text, terms) for sentiment, terms in TAG_RULES.values() if sentiment == "positive")
    if rating and rating <= 2 or negative_text:
        return "negative"
    if rating and rating >= 4 or positive_text:
        return "positive"
    return "neutral"


def prepare_reviews(raw: pd.DataFrame) -> pd.DataFrame:
    data = raw.copy()
    data.columns = [str(column).strip().casefold() for column in data.columns]
    for column in ["rating", "product_rating", "seller_rating", "logistics_rating", "upvotes", "downvotes", "image_count"]:
        data[column] = pd.to_numeric(data[column].replace("\\N", None), errors="coerce")
    data["created_at"] = pd.to_datetime(data["create_date_short"], errors="coerce")
    data["product_id"] = data["product_id"].astype(str).str.replace(r"\.0$", "", regex=True)
    data["product_name"] = data["product_name"].map(_clean_text)
    data["review_content"] = data["review_content"].map(_clean_text)
    data["brand"] = data["product_name"].map(_brand)
    data["rating_valid"] = data["rating"].between(1, 5)
    data["tags"] = data["review_content"].map(_tags)
    data["sensitive_terms"] = data["review_content"].map(_sensitive)
    data["sentiment"] = [
        _sentiment(rating if valid else None, text)
        for rating, valid, text in zip(data["rating"], data["rating_valid"], data["review_content"])
    ]
    data["rating_sentiment_mismatch"] = (
        (data["rating_valid"])
        & (((data["rating"] >= 4) & (data["sentiment"] == "negative")) | ((data["rating"] <= 2) & (data["sentiment"] == "positive")))
    )
    for column in [f"image_{index}" for index in range(1, 7)]:
        data[column] = data[column].map(_clean_text)
    return data

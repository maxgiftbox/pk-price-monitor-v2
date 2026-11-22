from datetime import date

import pandas as pd

from src.services.weekly_brief import build_weekly_brief, latest_completed_saturday, normalize_brands


def review(date, brand="Samsung", product="Samsung A16", rating=5, text="Original product", country="PK"):
    return {"venture": country, "brand": brand, "created_at": date, "rating_valid": True, "rating": rating, "review_content": text, "product_name": product, "review_status": "approved", "type": "phone"}


def post(date, brand="Samsung", likes=100, country="PK", **overrides):
    value = {"country": country, "published_at": date, "brand": brand, "quality_status": "dashboard_ready", "account_type": "brand", "category": "Mobile", "platform": "Facebook", "title": "New launch.", "content_summary": "New launch announced. More detail follows.", "account_name": brand, "source_url": f"https://example.com/{brand}/{date}", "likes": likes}
    value.update(overrides)
    return value


def test_weekly_brief_uses_saturday_to_saturday_cycle_and_rules_only_outputs():
    consumer = pd.DataFrame([
        review("2026-11-09", rating=5), review("2026-11-10", rating=2, text="Late delivery and bad packaging"),
        review("2026-11-11", brand="Redmi", product="Redmi Note 14"), review("2026-11-02"),
        review("2026-11-12", brand="OPPO", country="BD"), {**review("2026-11-13"), "review_status": "rejected"},
    ])
    social = pd.DataFrame([
        post("2026-11-10T00:00:00Z", brand="Samsung; Xiaomi", likes=12000),
        post("2026-11-11T00:00:00Z", brand="Samsung", likes=50), post("2026-11-04T00:00:00Z", brand="Samsung", likes=10),
        {**post("2026-11-12T00:00:00Z"), "quality_status": "needs_review"},
    ])
    result = build_weekly_brief(consumer, social, country="PK", week="2026-W46")
    assert result["country"] == "PK"
    assert result["week"] == {"iso": "2026-W46", "start": "2026-11-07", "end": "2026-11-14"}
    assert result["totals"]["reviews"] == 3
    assert result["totals"]["reviews_prev"] == 1
    assert result["totals"]["posts"] == 2
    assert sum(item["count"] for item in result["daily_reviews"]) == 3
    assert result["display_mode"] == "count"
    assert result["brands"][0]["name"] == "Samsung"
    assert result["brands"][0]["top_posts"][0]["likes"] == 12000
    assert any(item["name"] == "Xiaomi" and item["reviews"] == 1 for item in result["brands"])
    assert all("status" not in item for item in result["brands"])
    assert result["coverage"][0]["count"] == 2
    assert [item["label"] for item in result["executive"]] == ["RISK", "OPPORTUNITY"]
    assert result["movers"][0]["name"] == "Samsung"


def test_cycle_includes_boundary_saturday_in_both_adjacent_periods():
    consumer = pd.DataFrame([review("2026-11-07")])
    social = pd.DataFrame([post("2026-11-07T00:00:00Z")])

    result = build_weekly_brief(consumer, social, week="2026-W46")

    assert len(result["daily_reviews"]) == 8
    assert result["totals"]["reviews"] == 1
    assert result["totals"]["reviews_prev"] == 1
    assert result["totals"]["posts"] == 1
    assert result["totals"]["posts_prev"] == 1


def test_market_news_excludes_brand_and_product_posts():
    consumer = pd.DataFrame([review("2026-11-09")])
    social = pd.DataFrame([post("2026-11-10T00:00:00Z"), post("2026-11-11T00:00:00Z", brand="", account_type="media", category="Policy", title="New tax policy.", content_summary="New tax policy was announced.")])
    result = build_weekly_brief(consumer, social, week="2026-W46")
    assert len(result["market"]) == 1
    assert result["market"][0]["category"] == "Policy"


def test_brand_normalization_expands_multibrand_and_parent_brands():
    assert normalize_brands("Samsung; Redmi; POCO; Samsung") == ["samsung", "xiaomi"]


def test_latest_completed_saturday_only_rolls_forward_on_sunday():
    assert latest_completed_saturday(date(2026, 11, 22)) == date(2026, 11, 21)
    assert latest_completed_saturday(date(2026, 11, 23)) == date(2026, 11, 21)
    assert latest_completed_saturday(date(2026, 11, 21)) == date(2026, 11, 14)

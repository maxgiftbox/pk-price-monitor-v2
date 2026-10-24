from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from src.data_sources.google_sheets import Snapshot
from src.main import app
from src.services.social_intelligence import brand_ratings, dashboard, filters


def fixture() -> pd.DataFrame:
    rows = [
        {"record_id": "1", "published_at": "2026-10-16T10:00:00Z", "country": "BD", "platform": "Facebook", "monitor_type": "watchlist", "account_name": "vivo", "account_type": "Brand", "brand": "vivo", "title": "Launch", "content": "", "content_summary": "", "source_url": "https://example.com/1", "views": None, "likes": 1000},
        {"record_id": "2", "published_at": "2026-10-17T10:00:00Z", "country": "BD", "platform": "Facebook", "monitor_type": "watchlist", "account_name": "vivo", "account_type": "Brand", "brand": "vivo", "title": "Camera", "content": "", "content_summary": "", "source_url": "https://example.com/2", "views": None, "likes": 800},
        {"record_id": "3", "published_at": "2026-10-17T11:00:00Z", "country": "BD", "platform": "X", "monitor_type": "trend_discovery", "account_name": "Media", "account_type": "News / Media", "brand": "vivo", "title": "Review", "content": "", "content_summary": "", "source_url": "https://example.com/3", "views": 500, "likes": 50},
        {"record_id": "4", "published_at": "2026-10-17T12:00:00Z", "country": "BD", "platform": "Facebook", "monitor_type": "watchlist", "account_name": "OPPO", "account_type": "Brand", "brand": "OPPO", "title": "Launch", "content": "", "content_summary": "", "source_url": "https://example.com/4", "views": None, "likes": 100},
    ]
    frame = pd.DataFrame(rows)
    for column in ["category", "topic", "why_it_matters", "business_impact", "topic_tags", "views_status", "media_type", "media_url", "quality_status"]:
        frame[column] = ""
    frame["published_at"] = pd.to_datetime(frame["published_at"], utc=True)
    return frame


def test_brand_ratings_rank_and_rebalance_missing_views():
    result = brand_ratings(fixture(), {"period_days": 7, "country": "BD", "date_to": "2026-10-17", "top_n": 6})
    assert result["brands"][0] == "vivo"
    latest = result["leaders"][0]
    assert latest["rank"] == 1
    assert latest["voicePosts"] == 2
    assert latest["earnedMentions"] == 1
    assert latest["socialRating"] > result["leaders"][1]["socialRating"]
    assert result["methodology"]["weights"]["engagement"] == .30


def test_social_ratings_endpoint(monkeypatch):
    snapshot = Snapshot(fixture(), datetime(2026, 10, 18, tzinfo=timezone.utc))
    monkeypatch.setattr(app.state, "social_intelligence_repository", type("Repo", (), {"get": lambda self: snapshot})())
    app.state.response_cache.clear()
    response = TestClient(app).get("/api/social-intelligence/ratings", params={"country": "BD", "periodDays": 7, "dateTo": "2026-10-17"})
    assert response.status_code == 200
    assert response.json()["leaders"][0]["brand"] == "vivo"
    assert response.json()["meta"]["stale"] is False


def test_brand_filter_options_are_canonical_individual_entities():
    frame = fixture()
    extra = frame.iloc[[0]].copy()
    extra["record_id"] = "multi-brand"
    extra["source_url"] = "https://example.com/multi-brand"
    extra["brand"] = "Apple; Samsung; Xiaomi"
    duplicates = frame.iloc[[0, 0]].copy()
    duplicates["record_id"] = ["honor-upper", "honor-title"]
    duplicates["source_url"] = ["https://example.com/honor-upper", "https://example.com/honor-title"]
    duplicates["brand"] = ["HONOR", "Honor"]
    data = pd.concat([frame, extra, duplicates], ignore_index=True)

    brands = filters(data)["options"]["brands"]

    assert brands == ["Apple", "HONOR", "OPPO", "Samsung", "vivo", "XIAOMI"]
    assert "Apple; Samsung; Xiaomi" not in brands


def test_single_brand_filter_matches_a_multi_brand_record():
    frame = fixture()
    extra = frame.iloc[[0]].copy()
    extra["record_id"] = "multi-brand"
    extra["source_url"] = "https://example.com/multi-brand"
    extra["brand"] = "Apple; Samsung; Xiaomi"
    data = pd.concat([frame, extra], ignore_index=True)

    result = dashboard(data, {"brand": ["Samsung"], "limit": 40})

    assert result["meta"]["filteredCount"] == 1
    assert result["records"][0]["recordId"] == "multi-brand"

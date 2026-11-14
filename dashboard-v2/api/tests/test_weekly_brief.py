import pandas as pd

from src.services.weekly_brief import build_weekly_brief


def test_weekly_brief_surfaces_material_consumer_momentum():
    consumer = pd.DataFrame([
        {"venture": "PK", "brand": "Samsung", "created_at": "2026-11-10", "rating_valid": True, "rating": 5, "topic_signals": [("Camera quality", "positive")]},
        {"venture": "PK", "brand": "Samsung", "created_at": "2026-11-03", "rating_valid": True, "rating": 3, "topic_signals": []},
    ])
    social = pd.DataFrame([
        {"country": "PK", "published_at": "2026-11-10T00:00:00Z", "brand": "Samsung", "account_type": "brand", "monitor_type": "watchlist", "source_url": "signal-1", "likes": 100, "views": 1000, "topic_tags": "launch", "title": "Launch", "content": "", "content_summary": "", "account_name": "Samsung"},
    ])

    result = build_weekly_brief(consumer, social, "PK", "2026-11-10")

    assert result["country"] == {"code": "PK", "name": "Pakistan"}
    assert result["brands"][0]["status"] == "consumer_momentum"
    assert result["brands"][0]["consumerVoice"]["ratingChange"] == 2.0
    assert result["meta"] == {"consumerRows": 1, "socialSignals": 1}

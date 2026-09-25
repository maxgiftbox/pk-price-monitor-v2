import pandas as pd
from fastapi.testclient import TestClient

from src.domain.consumer_voice import prepare_reviews
from src.main import app
from src.services.consumer_voice import dashboard


def fixture() -> pd.DataFrame:
    return prepare_reviews(pd.DataFrame([
        {"venture": "PK", "create_date_short": "2026-09-01", "product_id": "1", "product_name": "Samsung A", "seller_name": "Seller", "review_status": "approved", "rating": 5, "product_rating": 5, "seller_rating": 4, "logistics_rating": 5, "review_content": "Great product and fast delivery", "upvotes": 2, "downvotes": 0, "image_1": "https://example.com/a.jpg", "image_2": "\\N", "image_3": "\\N", "image_4": "\\N", "image_5": "\\N", "image_6": "\\N", "image_count": 1},
        {"venture": "PK", "create_date_short": "2026-09-02", "product_id": "2", "product_name": "Realme B", "seller_name": "Seller", "review_status": "approved", "rating": 1, "product_rating": 1, "seller_rating": 1, "logistics_rating": 5, "review_content": "Not recommend, phone has heating and warranty issue", "upvotes": 8, "downvotes": 0, "image_1": "\\N", "image_2": "\\N", "image_3": "\\N", "image_4": "\\N", "image_5": "\\N", "image_6": "\\N", "image_count": 0},
        {"venture": "BD", "create_date_short": "2026-09-03", "product_id": "3", "product_name": "Oppo C", "seller_name": "Seller", "review_status": "approved", "rating": 0, "product_rating": "\\N", "seller_rating": "\\N", "logistics_rating": "\\N", "review_content": "Seller reply", "upvotes": 0, "downvotes": 0, "image_1": "\\N", "image_2": "\\N", "image_3": "\\N", "image_4": "\\N", "image_5": "\\N", "image_6": "\\N", "image_count": 0},
    ]))


def test_zero_rating_is_excluded_from_rating_metrics():
    result = dashboard(fixture(), {})
    assert result["metrics"]["averageRating"] == 3
    assert result["metrics"]["positiveRate"] == 0.5
    assert result["metrics"]["reviewCount"] == 3
    assert result["metrics"]["ratedReviewCount"] == 2


def test_alerts_and_images_are_serialized():
    result = dashboard(fixture(), {"sort": "helpful"})
    assert result["alerts"][0]["rating"] == 1
    assert "Overheating" in result["alerts"][0]["reasons"]
    assert result["reviews"][1]["images"] == ["https://example.com/a.jpg"]


def test_consumer_voice_endpoints():
    app.state.consumer_voice_repository = type("Repo", (), {"get": lambda self: fixture()})()
    app.state.response_cache.clear()
    client = TestClient(app)
    assert client.get("/api/consumer-voice/filters").status_code == 200
    response = client.get("/api/consumer-voice/dashboard", params={"venture": "PK"})
    assert response.status_code == 200
    assert response.json()["metrics"]["reviewCount"] == 2

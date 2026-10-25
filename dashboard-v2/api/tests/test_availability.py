from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from src.data_sources.google_sheets import Snapshot
from src.main import app
from src.services.availability import dashboard


def fixture():
    return pd.DataFrame([
        {"run_id": "r1", "crawled_at": "2026-10-25T10:00:00Z", "venture": "PK", "brand_name": "Apple", "product_id": "1", "daraz_sku": "1_PK-1", "short_item_eng_name": "Phone 256GB", "memory": "256GB", "color": "Blue", "category": "Mobile", "url_daraz": "https://daraz/1", "availability_status": "available", "status_reason": "purchase_action_available", "selected_sku_verified": True, "l90_gmv": 100, "l90_product_transaction_flag": "Yes"},
        {"run_id": "r1", "crawled_at": "2026-10-25T10:01:00Z", "venture": "PK", "brand_name": "Apple", "product_id": "1", "daraz_sku": "1_PK-2", "short_item_eng_name": "Phone 256GB", "memory": "256GB", "color": "Black", "category": "Mobile", "url_daraz": "https://daraz/2", "availability_status": "unavailable", "status_reason": "out_of_stock", "selected_sku_verified": True, "l90_gmv": 500, "l90_product_transaction_flag": "Yes"},
        {"run_id": "r1", "crawled_at": "2026-10-25T10:02:00Z", "venture": "NP", "brand_name": "Xiaomi", "product_id": "2", "daraz_sku": "2_NP-1", "short_item_eng_name": "Note 128GB", "memory": "128GB", "color": "Green", "category": "Mobile", "url_daraz": "https://daraz/3", "availability_status": "unknown", "status_reason": "captcha", "selected_sku_verified": False, "l90_gmv": "-", "l90_product_transaction_flag": "No"},
    ])


def test_dashboard_counts_products_variants_and_priority():
    result = dashboard(Snapshot(fixture(), datetime.now(timezone.utc)), {})
    assert result["summary"] == {
        "products": 2, "variants": 3, "available": 1, "unavailable": 1,
        "unknown": 1, "availabilityRate": .5, "highPriorityUnavailable": 1,
    }
    assert [row["darazSku"] for row in result["actions"]] == ["1_PK-2", "2_NP-1"]


def test_dashboard_filters_priority_and_country():
    result = dashboard(Snapshot(fixture(), datetime.now(timezone.utc)), {"venture": ["NP"], "priority": ["standard"]})
    assert result["summary"]["variants"] == 1
    assert result["rows"][0]["darazSku"] == "2_NP-1"


def test_availability_endpoint_uses_pricing_access_gate():
    snap = Snapshot(fixture(), datetime.now(timezone.utc))
    app.state.availability_repository = type("Repo", (), {"get": lambda self: snap})()
    app.state.response_cache.clear()
    client = TestClient(app)
    assert client.get("/api/availability/dashboard").status_code == 401
    assert client.post("/api/pricing/auth", json={"password": "test-password"}).status_code == 200
    response = client.get("/api/availability/dashboard")
    assert response.status_code == 200
    assert response.json()["summary"]["variants"] == 3

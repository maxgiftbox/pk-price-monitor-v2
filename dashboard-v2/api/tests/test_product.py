from datetime import datetime, timezone

import pandas as pd
from fastapi.testclient import TestClient

from src.data_sources.google_sheets import Snapshot
from src.data_sources.product_features import ProductFeaturesRepository
from src.domain.product import prepare_product_features, product_sku_id
from src.main import app


def raw_products():
    return pd.DataFrame([
        {
            "brand": "Samsung", "model": "Galaxy A56", "memory": "8GB 256GB",
            "standard_model_memory": "Galaxy A56 8/256", "display_type": "AMOLED",
            "refresh_rate_hz": 120, "battery": "5000 mAh", "battery_mah": 5000,
            "charging": "45W wired", "charging_w": 45, "last_updated": "2026-09-27",
        },
        {
            "brand": "Xiaomi", "model": "Redmi 15", "memory": "8/128",
            "standard_model_memory": "Redmi 15 8/128", "display_type": "LCD",
            "refresh_rate_hz": 144, "selfie_camera_mp": 1080,
            "battery": "7000 mAh", "battery_mah": 7000,
            "charging": "33W wired", "charging_w": 7000, "last_updated": "2026-09-27",
        },
    ])


def snapshot():
    return Snapshot(
        data=prepare_product_features(raw_products()),
        generated_at=datetime.now(timezone.utc),
    )


def test_product_identity_and_numeric_guardrails():
    data = prepare_product_features(raw_products())
    assert data.iloc[0].memory == "8/256"
    assert product_sku_id("PK", "Samsung", "Galaxy A56", "8/256") == "pk-samsung-galaxy-a56-8-256"
    assert pd.isna(data.iloc[1].selfie_camera_mp)
    assert pd.isna(data.iloc[1].charging_w)


def test_product_filter_and_compare_endpoints():
    app.state.product_repository = type("Repo", (), {"get": lambda self: snapshot()})()
    app.state.response_cache.clear()
    client = TestClient(app)

    filters = client.get("/api/products/filters", params={"brand": "Samsung"})
    assert filters.status_code == 200
    payload = filters.json()
    assert payload["options"]["brands"] == ["Samsung", "Xiaomi"]
    assert payload["options"]["models"] == ["Galaxy A56"]
    assert payload["options"]["skus"][0]["skuId"] == "pk-samsung-galaxy-a56-8-256"

    compared = client.get(
        "/api/products/compare",
        params={"skuId": ["pk-samsung-galaxy-a56-8-256", "pk-xiaomi-redmi-15-8-128"]},
    )
    assert compared.status_code == 200
    result = compared.json()
    assert [item["model"] for item in result["products"]] == ["Galaxy A56", "Redmi 15"]
    assert result["products"][1]["specs"]["charging"] == "33W wired"
    assert len(result["groups"]) == 6


def test_compare_requires_one_to_six_skus():
    app.state.product_repository = type("Repo", (), {"get": lambda self: snapshot()})()
    client = TestClient(app)
    assert client.get("/api/products/compare").status_code == 422
    params = [("skuId", f"sku-{index}") for index in range(7)]
    assert client.get("/api/products/compare", params=params).status_code == 422


def test_bundled_phase_one_dataset_is_the_default(monkeypatch):
    monkeypatch.delenv("PRODUCT_FEATURES_SOURCE", raising=False)
    snapshot = ProductFeaturesRepository()._load_from_google()
    assert snapshot.stale is False
    assert len(snapshot.data) == 279
    assert set(snapshot.data["brand"]) == {
        "Apple", "HONOR", "Infinix", "Itel", "Oppo", "realme", "Samsung",
        "Tecno", "Vivo", "Xiaomi",
    }
    assert snapshot.data["sku_id"].is_unique
    smart_20 = snapshot.data[snapshot.data["model"] == "Infinix Smart 20"]
    assert set(smart_20["memory"]) == {"4/64", "4/128"}

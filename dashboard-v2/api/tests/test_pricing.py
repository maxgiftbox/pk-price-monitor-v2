from datetime import datetime, timezone
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from src.data_sources.google_sheets import Snapshot
from src.domain.pricing import alert_level, calculate_gap_table, enrich_with_sku_master, prepare_price_daily_df, product_id
from src.main import app

@pytest.mark.parametrize("value, expected", [(-.01,"Green"),(0,"Green"),(.0001,"Orange"),(.0299,"Orange"),(.03,"Red"),(.031,"Red")])
def test_alert_boundaries(value, expected): assert alert_level(value) == expected

def fixture():
    return pd.DataFrame([
      {"crawl_date":"2026-09-03","crawl_time":"09:00","country":"PK","brand":"Samsung","model":"A55 raw","memory":"8GB 256GB","platform":"Daraz","effective_price":"129,999","original_price":"139999","product_url":"https://daraz/a55"},
      {"crawl_date":"2026-09-03","crawl_time":"10:00","country":"PK","brand":"Samsung","model":"A55 raw","memory":"8GB 256GB","platform":"Daraz","effective_price":"130000","original_price":"139999","product_url":"https://daraz/a55"},
      {"crawl_date":"2026-09-03","crawl_time":"08:00","country":"PK","brand":"Samsung","model":"wrong","memory":"wrong","platform":"PriceOye","effective_price":"122000","product_url":"https://priceoye/a55?ref=x"},
      {"crawl_date":"2026-09-03","crawl_time":"08:00","country":"BD","brand":"Xiaomi","model":"Note","memory":"6/128","platform":"Daraz","effective_price":"30000","original_price":"32000","product_url":"d"},
      {"crawl_date":"2026-09-03","crawl_time":"08:00","country":"BD","brand":"Xiaomi","model":"Note","memory":"6/128","platform":"Pickaboo","effective_price":"30000","product_url":"p"},
      {"crawl_date":"2026-09-03","crawl_time":"08:00","country":"BD","brand":"Xiaomi","model":"Note","memory":"8/256","platform":"Daraz","effective_price":"35000","original_price":"37000","product_url":"d2"},
    ])

def prepared():
    master=pd.DataFrame([{"platform":"PriceOye","country":"PK","brand":"","model":"","memory":"","product_url":"https://priceoye/a55","standard_model":"Galaxy A55","standard_memory":"8/256"},{"platform":"Daraz","country":"PK","brand":"Samsung","model":"A55 raw","memory":"8/256","product_url":"https://daraz/a55","standard_model":"Galaxy A55","standard_memory":"8/256"}])
    return enrich_with_sku_master(prepare_price_daily_df(fixture()),master)

def missing_competitor_url_fixture():
    return prepared()[lambda rows: rows.country.eq("BD") & rows.memory.eq("8/256")]

def test_parity_mapping_latest_competitors_memories_and_missing_price():
    result=calculate_gap_table(prepared())
    pk=result[result.country.eq("PK")].iloc[0]
    assert pk.model == "Galaxy A55" and pk.daraz_price == 130000 and pk.competitor_platform == "priceoye"
    assert set(result[result.country.eq("BD")].memory)=={"6/128","8/256"}
    assert result[result.memory.eq("8/256") & result.country.eq("BD")].competitor_price.isna().all()
    assert result[result.country.eq("BD") & result.memory.eq("6/128")].iloc[0].competitor_platform == "pickaboo"

def test_product_id_is_order_independent():
    expected=product_id("PK","Samsung","Galaxy A55","8GB 256GB")
    assert expected == "pk-samsung-galaxy-a55-8-256" == product_id("PK","Samsung","Galaxy A55","8/256")

def test_endpoints_cascade_and_paginate():
    snap=Snapshot(prepared(),datetime.now(timezone.utc))
    app.state.repository=type("Repo",(),{"get":lambda self:snap})()
    client=TestClient(app)
    assert client.get("/api/health").json()=={"status":"ok"}
    opts=client.get("/api/pricing/filters",params={"country":"PK"}).json()["options"]
    assert opts["brands"]==["Samsung"] and opts["skus"]==["Galaxy A55"]
    response=client.get("/api/pricing/gap",params={"pageSize":1}).json()
    assert len(response["rows"])==1 and response["pagination"]["total"]==3

def test_gap_endpoint_serializes_missing_competitor_url_as_null():
    snap=Snapshot(missing_competitor_url_fixture(),datetime.now(timezone.utc))
    app.state.repository=type("Repo",(),{"get":lambda self:snap})()
    response=TestClient(app).get("/api/pricing/gap")
    assert response.status_code == 200
    assert response.json()["rows"][0]["competitorUrl"] is None

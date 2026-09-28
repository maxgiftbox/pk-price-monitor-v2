"""Google Sheets-backed Product Intelligence source with bundled fallback."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from src.data_sources.google_sheets import GoogleSheetsRepository, SCOPES, Snapshot
from src.domain.product import prepare_product_features


class ProductFeaturesRepository(GoogleSheetsRepository):
    def __init__(
        self,
        path: Path | None = None,
        ttl_seconds: int = 21_600,
        initial_load_timeout_seconds: int = 12,
    ):
        super().__init__(ttl_seconds, initial_load_timeout_seconds)
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "product_features.csv"

    @staticmethod
    def _credentials() -> Credentials:
        service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        service_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_json:
            return Credentials.from_service_account_info(json.loads(service_json), scopes=SCOPES)
        if service_file:
            return Credentials.from_service_account_file(service_file, scopes=SCOPES)
        raise ValueError("Google service account credentials not configured")

    def _load_bundle(self, stale: bool = False) -> Snapshot:
        data = prepare_product_features(pd.read_csv(self.path, keep_default_na=False))
        return Snapshot(
            data=data,
            generated_at=datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc),
            stale=stale,
        )

    def _load_from_google(self) -> Snapshot:
        if os.getenv("PRODUCT_FEATURES_SOURCE", "bundle").casefold() != "google":
            return self._load_bundle()
        try:
            spreadsheet_id = os.getenv(
                "PRODUCT_FEATURES_GOOGLE_SHEET_ID",
                "1g0dDuowGUAGYiuIzG8dlKrvnruqMxaYUw_JfURCY0qU",
            )
            client = gspread.authorize(self._credentials())
            sheet = client.open_by_key(spreadsheet_id)
            raw = pd.DataFrame(
                sheet.worksheet(
                    os.getenv("PRODUCT_FEATURES_WORKSHEET", "sku_features_master")
                ).get_all_records()
            )
            return Snapshot(
                data=prepare_product_features(raw),
                generated_at=datetime.now(timezone.utc),
                stale=False,
            )
        except Exception as exc:
            print("===== PRODUCT FEATURES GOOGLE SHEET ERROR =====")
            print(type(exc))
            print(repr(exc))
            print("===============================================")
            return self._load_bundle(stale=True)

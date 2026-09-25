from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from src.data_sources.google_sheets import GoogleSheetsRepository, SCOPES, Snapshot
from src.domain.consumer_voice import prepare_reviews


class ConsumerVoiceRepository(GoogleSheetsRepository):
    """Google Sheets-backed reviews with an immutable bundled fallback."""

    def __init__(
        self,
        path: Path | None = None,
        ttl_seconds: int = 21_600,
        initial_load_timeout_seconds: int = 12,
    ):
        super().__init__(ttl_seconds, initial_load_timeout_seconds)
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "consumer_voice_reviews.csv"

    @staticmethod
    def _credentials() -> Credentials:
        service_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        service_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_json:
            return Credentials.from_service_account_info(json.loads(service_json), scopes=SCOPES)
        if service_file:
            return Credentials.from_service_account_file(service_file, scopes=SCOPES)
        raise ValueError("Google service account credentials not configured")

    @staticmethod
    def _validate(raw: pd.DataFrame) -> pd.DataFrame:
        normalized = {str(column).strip().casefold() for column in raw.columns}
        required = {"venture", "create_date_short", "product_id", "rating", "review_content"}
        if raw.empty or not required.issubset(normalized):
            raise ValueError("Consumer Voice sheet contains no usable review data")
        if not ({"product_name", "standard_product_name"} & normalized):
            raise ValueError("Consumer Voice sheet is missing a product name column")
        return prepare_reviews(raw.drop_duplicates())

    def _load_fallback(self) -> Snapshot:
        data = self._validate(pd.read_csv(self.path, keep_default_na=False))
        generated_at = datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc)
        return Snapshot(data=data, generated_at=generated_at, stale=True)

    def _load_from_google(self) -> Snapshot:
        try:
            spreadsheet_id = os.getenv(
                "CONSUMER_VOICE_GOOGLE_SHEET_ID",
                "1g0dDuowGUAGYiuIzG8dlKrvnruqMxaYUw_JfURCY0qU",
            )
            client = gspread.authorize(self._credentials())
            sheet = client.open_by_key(spreadsheet_id)
            raw = pd.DataFrame(
                sheet.worksheet(
                    os.getenv("CONSUMER_VOICE_WORKSHEET", "Consumer_voice_dump")
                ).get_all_records()
            )
            return Snapshot(
                data=self._validate(raw),
                generated_at=datetime.now(timezone.utc),
                stale=False,
            )
        except Exception as exc:
            print("===== CONSUMER VOICE GOOGLE SHEET ERROR =====")
            print(type(exc))
            print(repr(exc))
            print("=============================================")
            return self._load_fallback()

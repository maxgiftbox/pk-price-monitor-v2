from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from src.data_sources.google_sheets import GoogleSheetsRepository, SCOPES, Snapshot


class SocialIntelligenceRepository(GoogleSheetsRepository):
    """Read the V2.2.1 intelligence master, with the latest pipeline CSV as fallback."""

    def __init__(self, path: Path | None = None, ttl_seconds: int = 900, initial_load_timeout_seconds: int = 12):
        super().__init__(ttl_seconds, initial_load_timeout_seconds)
        self.path = path or Path(__file__).resolve().parents[2] / "data" / "social_intelligence_v2_2.csv"

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
    def _prepare(raw: pd.DataFrame) -> pd.DataFrame:
        frame = raw.copy()
        frame.columns = [str(column).strip().casefold() for column in frame.columns]
        required = {"record_id", "published_at", "country", "platform", "monitor_type", "title", "source_url"}
        if frame.empty or not required.issubset(frame.columns):
            raise ValueError("Social Intelligence sheet contains no usable records")
        for column in [
            "account_name", "account_type", "category", "topic", "brand", "content",
            "content_summary", "why_it_matters", "business_impact", "topic_tags", "views_status",
            "media_type", "media_url", "translation_status", "quality_status",
        ]:
            if column not in frame:
                frame[column] = ""
            frame[column] = frame[column].fillna("").astype(str).str.strip()
        frame["published_at"] = pd.to_datetime(frame["published_at"], errors="coerce", utc=True)
        for column in ["views", "likes"]:
            if column not in frame:
                frame[column] = pd.NA
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.drop_duplicates(subset=["record_id"], keep="last")

    def _load_fallback(self) -> Snapshot:
        data = self._prepare(pd.read_csv(self.path, keep_default_na=False))
        return Snapshot(data=data, generated_at=datetime.fromtimestamp(self.path.stat().st_mtime, timezone.utc), stale=True)

    def _load_from_google(self) -> Snapshot:
        try:
            spreadsheet_id = os.getenv("SOCIAL_INTELLIGENCE_GOOGLE_SHEET_ID") or os.getenv("GOOGLE_SHEET_ID")
            client = gspread.authorize(self._credentials())
            sheet = client.open_by_key(spreadsheet_id) if spreadsheet_id else client.open(os.getenv("GOOGLE_SHEET_NAME", "Mob Price Monitor"))
            raw = pd.DataFrame(sheet.worksheet(os.getenv("SOCIAL_INTELLIGENCE_WORKSHEET", "social_intelligence_master")).get_all_records())
            return Snapshot(data=self._prepare(raw), generated_at=datetime.now(timezone.utc), stale=False)
        except Exception as exc:
            print("===== SOCIAL INTELLIGENCE GOOGLE SHEET ERROR =====")
            print(type(exc), repr(exc))
            print("==================================================")
            return self._load_fallback()

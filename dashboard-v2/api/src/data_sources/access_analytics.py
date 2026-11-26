from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound


WRITE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

HEADERS = [
    "event_time_utc",
    "event_time_local",
    "event_type",
    "session_id",
    "path",
    "ip_address",
]


@dataclass(frozen=True)
class AccessEvent:
    session_id: str
    event_type: str
    path: str
    ip_address: str
    occurred_at: datetime


class AccessAnalyticsWriter:
    """Append-only Google Sheets writer for anonymous dashboard access events."""

    def __init__(self) -> None:
        self.sheet_id = os.getenv("ACCESS_ANALYTICS_GOOGLE_SHEET_ID", "")
        self.sheet_name = os.getenv(
            "ACCESS_ANALYTICS_GOOGLE_SHEET_NAME",
            os.getenv("GOOGLE_SHEET_NAME", "Mob Price Monitor"),
        )
        self.worksheet_name = os.getenv(
            "ACCESS_ANALYTICS_WORKSHEET",
            "dashboard_access_log",
        )
        self.timezone = ZoneInfo(os.getenv("ACCESS_ANALYTICS_TIMEZONE", "Asia/Dhaka"))
        self._worksheet = None
        self._lock = threading.Lock()

    @staticmethod
    def _credentials() -> Credentials:
        service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        service_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
        if service_json:
            return Credentials.from_service_account_info(
                json.loads(service_json),
                scopes=WRITE_SCOPES,
            )
        if service_file:
            return Credentials.from_service_account_file(
                service_file,
                scopes=WRITE_SCOPES,
            )
        raise ValueError("Google service account credentials not configured")

    def _get_worksheet(self):
        if self._worksheet is not None:
            return self._worksheet

        client = gspread.authorize(self._credentials())
        spreadsheet = (
            client.open_by_key(self.sheet_id)
            if self.sheet_id
            else client.open(self.sheet_name)
        )
        try:
            worksheet = spreadsheet.worksheet(self.worksheet_name)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=self.worksheet_name,
                rows=1000,
                cols=len(HEADERS),
            )
        if not worksheet.row_values(1):
            worksheet.append_row(HEADERS, value_input_option="RAW")
        self._worksheet = worksheet
        return worksheet

    def record(self, event: AccessEvent) -> None:
        occurred_at = event.occurred_at.astimezone(timezone.utc)
        with self._lock:
            worksheet = self._get_worksheet()
            worksheet.append_row(
                [
                    occurred_at.isoformat(),
                    occurred_at.astimezone(self.timezone).isoformat(),
                    event.event_type,
                    event.session_id,
                    event.path,
                    event.ip_address,
                ],
                value_input_option="RAW",
            )

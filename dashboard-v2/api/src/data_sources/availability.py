"""Read-only Google Sheets source for the latest availability snapshot."""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime, timezone

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from src.data_sources.google_sheets import DataSourceUnavailable, Snapshot


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class AvailabilityRepository:
    def __init__(self, ttl_seconds: int = 900, initial_load_timeout_seconds: int = 12):
        self.ttl_seconds = ttl_seconds
        self.initial_load_timeout_seconds = initial_load_timeout_seconds
        self._snapshot: Snapshot | None = None
        self._monotonic = 0.0
        self._lock = threading.Lock()
        self._refreshing = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="availability-load")
        self._future = None

    def _load(self) -> Snapshot:
        raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        service_file = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        if raw:
            credentials = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
        elif service_file:
            credentials = Credentials.from_service_account_file(service_file, scopes=SCOPES)
        else:
            raise DataSourceUnavailable("Google service account credentials not configured")
        sheet = gspread.authorize(credentials).open(os.getenv("GOOGLE_SHEET_NAME", "Mob Price Monitor"))
        rows = pd.DataFrame(sheet.worksheet("drz_availability_current").get_all_records())
        required = {
            "run_id", "crawled_at", "venture", "brand_name", "product_id",
            "daraz_sku", "short_item_eng_name", "color", "category",
            "url_daraz", "availability_status", "status_reason",
            "l90_product_transaction_flag",
        }
        if rows.empty or not required.issubset(rows.columns):
            raise DataSourceUnavailable("Availability snapshot is missing or incomplete")
        rows["availability_status"] = rows["availability_status"].astype(str).str.strip().str.lower()
        rows["crawled_at"] = pd.to_datetime(rows["crawled_at"], errors="coerce", utc=True)
        return Snapshot(rows, datetime.now(timezone.utc), stale=False)

    def _refresh(self) -> None:
        try:
            snapshot = self._load()
            with self._lock:
                self._snapshot = snapshot
                self._monotonic = time.monotonic()
        finally:
            with self._lock:
                self._refreshing = False

    def get(self) -> Snapshot:
        with self._lock:
            fresh = self._snapshot is not None and time.monotonic() - self._monotonic < self.ttl_seconds
            snapshot = self._snapshot
        if fresh:
            return snapshot
        if snapshot is not None:
            with self._lock:
                if not self._refreshing:
                    self._refreshing = True
                    threading.Thread(target=self._refresh, daemon=True).start()
            return Snapshot(snapshot.data, snapshot.generated_at, stale=True)
        if self._future is None or (self._future.done() and self._future.exception() is not None):
            self._future = self._executor.submit(self._load)
        try:
            loaded = self._future.result(timeout=self.initial_load_timeout_seconds)
        except FutureTimeoutError as exc:
            raise DataSourceUnavailable("Availability data source timed out") from exc
        with self._lock:
            self._snapshot = loaded
            self._monotonic = time.monotonic()
        self._future = None
        return loaded

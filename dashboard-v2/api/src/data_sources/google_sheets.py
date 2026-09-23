"""Read-only Google Sheets adapter with stale-while-revalidate caching."""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from src.domain.pricing import (
    enrich_with_sku_master,
    prepare_price_daily_df,
)


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class DataSourceUnavailable(RuntimeError):
    pass


@dataclass
class Snapshot:
    data: pd.DataFrame
    generated_at: datetime
    stale: bool = False


class GoogleSheetsRepository:
    """
    Google Sheets repository using stale-while-revalidate caching.

    Behaviour:
    1. First request:
       No snapshot exists, so load Google Sheets synchronously.

    2. Fresh snapshot:
       Return cached data immediately.

    3. Expired snapshot:
       Return existing data immediately and refresh Google Sheets
       in a background thread.

    4. Refresh failure:
       Keep serving the last successful snapshot.
    """

    def __init__(self, ttl_seconds: int = 900, initial_load_timeout_seconds: int = 12):
        self.ttl_seconds = ttl_seconds
        self.initial_load_timeout_seconds = initial_load_timeout_seconds

        self._snapshot: Snapshot | None = None
        self._monotonic = 0.0

        self._lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._refreshing = False
        self._load_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="google-sheets-initial-load",
        )
        self._load_future: Future[Snapshot] | None = None

    def _is_fresh(self) -> bool:
        return (
            self._snapshot is not None
            and time.monotonic() - self._monotonic < self.ttl_seconds
        )

    def _load_from_google(self) -> Snapshot:
        service_json = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_JSON"
        )
        service_file = os.environ.get(
            "GOOGLE_SERVICE_ACCOUNT_FILE"
        )

        # Render production mode
        if service_json:
            credentials = Credentials.from_service_account_info(
                json.loads(service_json),
                scopes=SCOPES,
            )

        # Local development mode
        elif service_file:
            credentials = Credentials.from_service_account_file(
                service_file,
                scopes=SCOPES,
            )

        else:
            raise ValueError(
                "Google service account credentials not configured"
            )

        sheet = (
            gspread
            .authorize(credentials)
            .open(
                os.getenv(
                    "GOOGLE_SHEET_NAME",
                    "Mob Price Monitor",
                )
            )
        )

        prices = pd.DataFrame(
            sheet
            .worksheet("price_daily")
            .get_all_records()
        )

        try:
            master = pd.DataFrame(
                sheet
                .worksheet("sku_master")
                .get_all_records()
            )
        except Exception:
            master = pd.DataFrame()

        data = (
            enrich_with_sku_master(
                prepare_price_daily_df(prices),
                master,
            )
            if not prices.empty
            else prices
        )

        required_columns = {
            "crawl_date",
            "country",
            "brand",
            "model",
            "memory",
            "platform",
        }
        if data.empty or not required_columns.issubset(data.columns):
            raise DataSourceUnavailable("Google Sheet contains no usable pricing data")

        return Snapshot(
            data=data,
            generated_at=datetime.now(timezone.utc),
            stale=False,
        )

    def _load_initial_snapshot(self) -> Snapshot:
        if self._load_future is None or (
            self._load_future.done() and self._load_future.exception() is not None
        ):
            self._load_future = self._load_executor.submit(self._load_from_google)

        try:
            snapshot = self._load_future.result(
                timeout=self.initial_load_timeout_seconds
            )
        except FutureTimeoutError as exc:
            raise DataSourceUnavailable(
                "Pricing data source timed out during initial load."
            ) from exc

        self._load_future = None
        return snapshot

    def _background_refresh(self) -> None:
        try:
            new_snapshot = self._load_from_google()

            with self._lock:
                self._snapshot = new_snapshot
                self._monotonic = time.monotonic()

        except Exception as exc:
            print("===== GOOGLE SHEET BACKGROUND REFRESH ERROR =====")
            print(type(exc))
            print(repr(exc))
            print("================================================")

        finally:
            with self._refresh_lock:
                self._refreshing = False

    def _start_background_refresh(self) -> None:
        with self._refresh_lock:
            if self._refreshing:
                return

            self._refreshing = True

        thread = threading.Thread(
            target=self._background_refresh,
            name="google-sheets-refresh",
            daemon=True,
        )
        thread.start()

    def get(self) -> Snapshot:
        # Fast path: cached snapshot is still fresh.
        if self._is_fresh():
            return self._snapshot

        # Stale-while-revalidate:
        # If we already have usable data, never block the user while
        # refreshing Google Sheets.
        if self._snapshot is not None:
            stale_snapshot = Snapshot(
                data=self._snapshot.data,
                generated_at=self._snapshot.generated_at,
                stale=True,
            )

            self._start_background_refresh()

            return stale_snapshot

        # Cold start:
        # There is no usable snapshot yet, so the first request must
        # load Google Sheets synchronously.
        with self._lock:
            # Another request may have completed the initial load
            # while this request was waiting for the lock.
            if self._snapshot is not None:
                return self._snapshot

            try:
                self._snapshot = self._load_initial_snapshot()
                self._monotonic = time.monotonic()

            except Exception as exc:
                print("===== GOOGLE SHEET ERROR =====")
                print(type(exc))
                print(repr(exc))
                print("==============================")

                raise DataSourceUnavailable(
                    "Pricing data is temporarily unavailable."
                ) from exc

            return self._snapshot

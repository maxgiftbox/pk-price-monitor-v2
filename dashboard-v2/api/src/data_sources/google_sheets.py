"""Read-only Google Sheets adapter with a five-minute, stale-if-error cache."""
from __future__ import annotations

import json
import os
import threading
import time
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
    def __init__(self, ttl_seconds: int = 300):
        self.ttl_seconds = ttl_seconds
        self._snapshot: Snapshot | None = None
        self._monotonic = 0
        self._lock = threading.Lock()

    def get(self) -> Snapshot:
        now = datetime.now(timezone.utc)

        if (
            self._snapshot
            and time.monotonic() - self._monotonic < self.ttl_seconds
        ):
            return self._snapshot

        with self._lock:
            if (
                self._snapshot
                and time.monotonic() - self._monotonic < self.ttl_seconds
            ):
                return self._snapshot

            try:
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

                self._snapshot = Snapshot(
                    data=data,
                    generated_at=now,
                    stale=False,
                )

                self._monotonic = time.monotonic()

            except Exception as exc:
                print("===== GOOGLE SHEET ERROR =====")
                print(type(exc))
                print(repr(exc))
                print("==============================")

                if self._snapshot:
                    self._snapshot = Snapshot(
                        self._snapshot.data,
                        self._snapshot.generated_at,
                        True,
                    )
                else:
                    raise DataSourceUnavailable(
                        "Pricing data is temporarily unavailable."
                    ) from exc

            return self._snapshot

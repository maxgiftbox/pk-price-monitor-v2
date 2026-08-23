"""Full Daraz PK/BD crawler for the fixed self-hosted GitHub runner."""

import csv
import os
import random
import time
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Tuple

from playwright.sync_api import sync_playwright

from scraper import (
    PRICE_DAILY_COLUMNS,
    PRICE_DAILY_TAB,
    SHEET_NAME,
    SKU_MASTER_TAB,
    build_price_daily_row,
    ensure_price_daily_header,
    get_gspread_client,
    google_sheets_retry,
    parse_daraz,
)

DEBUG_DIR = "debug_daraz_selfhosted"
SUMMARY_PATH = "output/daraz_selfhosted_run_summary.csv"
DAILY_KEY_COLUMNS = ("crawl_date", "platform", "country", "brand", "model", "memory")
CAPTCHA_MARKERS = ("captcha", "verify you are human", "unusual traffic", "robot check")
THROTTLE_SECONDS = float(os.getenv("DARAZ_THROTTLE_SECONDS", "4"))
MAX_BACKOFF_SECONDS = float(os.getenv("DARAZ_MAX_BACKOFF_SECONDS", "120"))
CAPTCHA_BREAKER_THRESHOLD = int(os.getenv("DARAZ_CAPTCHA_BREAKER_THRESHOLD", "3"))
CAPTCHA_COOLDOWN_SECONDS = float(os.getenv("DARAZ_CAPTCHA_COOLDOWN_SECONDS", "300"))


def normalized_key(row: Dict[str, Any]) -> Tuple[str, ...]:
    """Return the case-insensitive daily identity used for Daraz upserts."""
    return tuple(str(row.get(column, "")).strip().casefold() for column in DAILY_KEY_COLUMNS)


def _row_values(row: Dict[str, Any]) -> List[Any]:
    return [row.get(column, "") for column in PRICE_DAILY_COLUMNS]


def upsert_daraz_rows(worksheet: Any, rows: Iterable[Dict[str, Any]]) -> Tuple[int, int]:
    """Update matching daily Daraz rows or append them without changing the schema."""
    records = google_sheets_retry(worksheet.get_all_records)
    existing = {normalized_key(record): index for index, record in enumerate(records, start=2)}
    updated = appended = 0

    for row in rows:
        key = normalized_key(row)
        row_number = existing.get(key)
        if row_number is not None:
            google_sheets_retry(
                worksheet.update,
                f"A{row_number}:N{row_number}",
                [_row_values(row)],
                value_input_option="RAW",
            )
            updated += 1
        else:
            google_sheets_retry(
                worksheet.append_row,
                _row_values(row),
                value_input_option="RAW",
            )
            # Track the newly appended row so duplicate keys within this run update it.
            existing[key] = len(records) + appended + 2
            appended += 1
    return updated, appended


def classify_result(result: Dict[str, Any]) -> str:
    if result.get("product_price"):
        return "success"
    error = str(result.get("error_message", "")).casefold()
    if any(marker in error for marker in CAPTCHA_MARKERS):
        return "captcha"
    if "timeout" in error:
        return "timeout"
    if "not parsed" in error or "parsing" in error:
        return "parse_failure"
    return "other_error"


def write_summary(summary: Dict[Tuple[str, str], Dict[str, int]]) -> None:
    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    fields = ["country", "brand", "total", "success", "captcha", "parse_failure", "timeout", "success_rate"]
    with open(SUMMARY_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (country, brand), counts in sorted(summary.items()):
            total = counts["total"]
            writer.writerow({
                "country": country,
                "brand": brand,
                **{name: counts[name] for name in fields[2:7]},
                "success_rate": f"{(counts['success'] / total * 100) if total else 0:.2f}%",
            })


def print_summary(rows: List[Dict[str, Any]], statuses: List[str], summary: Dict[Tuple[str, str], Dict[str, int]]) -> None:
    totals = defaultdict(int)
    country_totals = defaultdict(int)
    country_success = defaultdict(int)
    for row, status in zip(rows, statuses):
        totals[status] += 1
        country = str(row.get("country", "")).strip().upper()
        country_totals[country] += 1
        country_success[country] += status == "success"
    total = len(rows)
    rate = lambda part, whole: (part / whole * 100) if whole else 0

    print("\nDARAZ SELF-HOSTED RUN SUMMARY")
    print(f"Total Daraz SKUs: {total}")
    print(f"PK total: {country_totals['PK']}")
    print(f"BD total: {country_totals['BD']}")
    print(f"Successful: {totals['success']}")
    print(f"CAPTCHA: {totals['captcha']}")
    print(f"Parse failures: {totals['parse_failure']}")
    print(f"Timeouts: {totals['timeout']}")
    print(f"Other errors: {totals['other_error']}")
    print(f"Overall success rate: {rate(totals['success'], total):.2f}%")
    print(f"CAPTCHA rate: {rate(totals['captcha'], total):.2f}%")
    print(f"PK success rate: {rate(country_success['PK'], country_totals['PK']):.2f}%")
    print(f"BD success rate: {rate(country_success['BD'], country_totals['BD']):.2f}%")
    print("Brand-level summary:")
    print("country / brand / total / success / captcha / failure")
    for (country, brand), counts in sorted(summary.items()):
        failure = counts["parse_failure"] + counts["timeout"] + counts["other_error"]
        print(f"{country} / {brand} / {counts['total']} / {counts['success']} / {counts['captcha']} / {failure}")


def main() -> None:
    os.makedirs(DEBUG_DIR, exist_ok=True)
    client = get_gspread_client()
    spreadsheet = google_sheets_retry(client.open, SHEET_NAME)
    sku_ws = google_sheets_retry(spreadsheet.worksheet, SKU_MASTER_TAB)
    price_ws = google_sheets_retry(spreadsheet.worksheet, PRICE_DAILY_TAB)
    ensure_price_daily_header(price_ws)

    records = google_sheets_retry(sku_ws.get_all_records)
    rows = [row for row in records if str(row.get("status", "")).strip().casefold() == "active"
            and str(row.get("platform", "")).strip().casefold() == "daraz"
            and str(row.get("country", "")).strip().upper() in {"PK", "BD"}]
    print(f"Loaded {len(rows)} active Daraz PK/BD SKU(s) from {SKU_MASTER_TAB}.")

    output_rows: List[Dict[str, Any]] = []
    statuses: List[str] = []
    summary: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    consecutive_captchas = 0
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        for index, row in enumerate(rows):
            url = str(row.get("product_url", "")).strip()
            if url:
                result = parse_daraz(context, url, debug_identity=row, debug_dir=DEBUG_DIR)
            else:
                result = {"error_message": "Missing product_url", "stock_status": "unknown"}
            status = classify_result(result)
            output_rows.append(build_price_daily_row(row, result))
            statuses.append(status)
            key = (str(row.get("country", "")).strip().upper(), str(row.get("brand", "")).strip())
            summary[key]["total"] += 1
            summary[key][status] += 1

            if status == "captcha":
                consecutive_captchas += 1
                backoff = min(2 ** consecutive_captchas, MAX_BACKOFF_SECONDS)
                print(f"[DARAZ] CAPTCHA detected; backing off {backoff:.0f}s (no bypass attempted).")
                time.sleep(backoff)
                if consecutive_captchas >= CAPTCHA_BREAKER_THRESHOLD:
                    print(f"[DARAZ] Circuit breaker open; cooling down {CAPTCHA_COOLDOWN_SECONDS:.0f}s.")
                    time.sleep(CAPTCHA_COOLDOWN_SECONDS)
                    consecutive_captchas = 0
            else:
                consecutive_captchas = 0
            if index + 1 < len(rows):
                time.sleep(THROTTLE_SECONDS + random.uniform(0, 1.5))
        browser.close()

    updated, appended = upsert_daraz_rows(price_ws, output_rows)
    print(f"Daraz daily upsert complete: {updated} updated, {appended} appended.")
    write_summary(summary)
    print_summary(rows, statuses, summary)


if __name__ == "__main__":
    main()

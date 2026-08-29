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
CHECKPOINT_SIZE = 20
THROTTLE_SECONDS = float(os.getenv("DARAZ_THROTTLE_SECONDS", "4"))
MAX_BACKOFF_SECONDS = float(os.getenv("DARAZ_MAX_BACKOFF_SECONDS", "120"))
CAPTCHA_BREAKER_THRESHOLD = int(os.getenv("DARAZ_CAPTCHA_BREAKER_THRESHOLD", "3"))
CAPTCHA_COOLDOWN_SECONDS = float(os.getenv("DARAZ_CAPTCHA_COOLDOWN_SECONDS", "300"))
NETWORK_MAX_ATTEMPTS = 3
NETWORK_RETRY_DELAYS = (5, 10)
TRANSIENT_NETWORK_MARKERS = (
    "err_internet_disconnected",
    "err_connection_reset",
    "err_connection_closed",
    "err_network_changed",
    "err_timed_out",
    "err_name_not_resolved",
    "err_dns",
    "temporary failure in name resolution",
    "timeout while loading page",
    "target page, context or browser has been closed",
    "navigation failed",
)


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
            # Retry the complete lookup-and-write unit, rather than append_row alone.
            # If an append reached Sheets but its response was lost, the next lookup
            # finds the daily key and updates it instead of creating a duplicate.
            append_attempted = False

            def append_if_missing() -> Tuple[bool, int]:
                nonlocal append_attempted
                current_records = worksheet.get_all_records()
                current = {
                    normalized_key(record): index
                    for index, record in enumerate(current_records, start=2)
                }
                current_row_number = current.get(key)
                if current_row_number is not None:
                    worksheet.update(
                        f"A{current_row_number}:N{current_row_number}",
                        [_row_values(row)],
                        value_input_option="RAW",
                    )
                    return append_attempted, current_row_number
                append_attempted = True
                worksheet.append_row(_row_values(row), value_input_option="RAW")
                return True, len(current_records) + 2

            was_appended, row_number = google_sheets_retry(append_if_missing)
            # Track the newly appended row so duplicate keys within this run update it.
            existing[key] = row_number
            if was_appended:
                appended += 1
            else:
                updated += 1
    return updated, appended


def classify_result(result: Dict[str, Any]) -> str:
    if result.get("product_price"):
        return "success"
    error = str(result.get("error_message", "")).casefold()
    if "pdp unavailable / 404" in error:
        return "unavailable"
    if any(marker in error for marker in CAPTCHA_MARKERS):
        return "captcha"
    if "timeout" in error:
        return "timeout_failure"
    if "network failure after" in error:
        return "network_failure"
    if "not parsed" in error or "parsing" in error:
        return "parse_failure"
    return "other_error"


def _network_reason(result: Dict[str, Any]) -> str:
    error = str(result.get("error_message", ""))
    folded = error.casefold()
    for marker in TRANSIENT_NETWORK_MARKERS:
        if marker in folded:
            return marker.upper().removeprefix("NET::")
    return ""


def crawl_daraz_with_retries(
    context: Any,
    url: str,
    row: Dict[str, Any],
    recover_context: Any = None,
) -> Tuple[Dict[str, Any], Any]:
    """Crawl one SKU with bounded network retries and one fresh parse retry."""
    network_failures = 0
    parse_retry_used = False
    while True:
        result = parse_daraz(context, url, debug_identity=row, debug_dir=DEBUG_DIR)
        reason = _network_reason(result)
        if reason:
            network_failures += 1
            if network_failures >= NETWORK_MAX_ATTEMPTS:
                category = (
                    "Timeout"
                    if "TIMEOUT" in reason or "TIMED_OUT" in reason
                    else "Network failure"
                )
                print(
                    f"[NETWORK FAILED] country={row.get('country', '')} model={row.get('model', '')} "
                    f"attempts={NETWORK_MAX_ATTEMPTS} reason={reason}"
                )
                result["error_message"] = f"{category} after {NETWORK_MAX_ATTEMPTS} attempts"
                return result, context

            next_attempt = network_failures + 1
            print(
                f"[NETWORK RETRY] country={row.get('country', '')} model={row.get('model', '')} "
                f"attempt={next_attempt}/{NETWORK_MAX_ATTEMPTS} reason={reason}"
            )
            if recover_context is not None:
                context = recover_context(context)
            delay = NETWORK_RETRY_DELAYS[network_failures - 1]
            print(f"[NETWORK RETRY] waiting={delay}s")
            time.sleep(delay)
            continue

        if network_failures:
            print(
                f"[NETWORK RECOVERED] country={row.get('country', '')} model={row.get('model', '')} "
                f"attempt={network_failures + 1}"
            )
        if result.get("error_message") == "Product price not parsed" and not parse_retry_used:
            parse_retry_used = True
            time.sleep(random.uniform(3, 6))
            continue
        return result, context


def write_summary(summary: Dict[Tuple[str, str], Dict[str, int]]) -> None:
    os.makedirs(os.path.dirname(SUMMARY_PATH), exist_ok=True)
    count_fields = [
        "total",
        "success",
        "unavailable",
        "captcha",
        "parse_failure",
        "network_failure",
        "timeout_failure",
        "other_error",
    ]
    fields = ["country", "brand", *count_fields, "success_rate"]
    with open(SUMMARY_PATH, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (country, brand), counts in sorted(summary.items()):
            total = counts["total"]
            writer.writerow({
                "country": country,
                "brand": brand,
                **{name: counts[name] for name in count_fields},
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
    print(f"PDP unavailable / 404: {totals['unavailable']}")
    print(f"CAPTCHA: {totals['captcha']}")
    print(f"Parse failures: {totals['parse_failure']}")
    print(f"Network failures: {totals['network_failure']}")
    print(f"Timeout failures: {totals['timeout_failure']}")
    print(f"Other errors: {totals['other_error']}")
    print(f"Overall success rate: {rate(totals['success'], total):.2f}%")
    print(f"CAPTCHA rate: {rate(totals['captcha'], total):.2f}%")
    print(f"PK success rate: {rate(country_success['PK'], country_totals['PK']):.2f}%")
    print(f"BD success rate: {rate(country_success['BD'], country_totals['BD']):.2f}%")
    print("Brand-level summary:")
    print("country / brand / total / success / captcha / failure")
    for (country, brand), counts in sorted(summary.items()):
        failure = sum(
            counts[name]
            for name in (
                "unavailable",
                "parse_failure",
                "network_failure",
                "timeout_failure",
                "other_error",
            )
        )
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

    current_batch: List[Dict[str, Any]] = []
    statuses: List[str] = []
    summary: Dict[Tuple[str, str], Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    consecutive_captchas = 0
    total_batches = successful_batches = failed_batches = 0
    total_records_checkpointed = total_updated = total_appended = 0
    checkpoint_write_failed = False

    def write_checkpoint() -> None:
        nonlocal total_batches, successful_batches, failed_batches
        nonlocal total_records_checkpointed, total_updated, total_appended
        nonlocal checkpoint_write_failed
        total_batches += 1
        batch_number = total_batches
        record_count = len(current_batch)
        print(f"[CHECKPOINT] Writing batch {batch_number} | records={record_count}")
        try:
            updated, appended = upsert_daraz_rows(price_ws, current_batch)
        except Exception as error:
            failed_batches += 1
            checkpoint_write_failed = True
            print(f"[CHECKPOINT ERROR] batch={batch_number} records={record_count} reason={error}")
            raise
        successful_batches += 1
        total_records_checkpointed += record_count
        total_updated += updated
        total_appended += appended
        print(f"[CHECKPOINT] Batch {batch_number} complete | updated={updated} | appended={appended}")
        # Retain the batch until its upsert succeeds so a failed write is never discarded.
        current_batch.clear()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()

            def recover_context(current_context: Any) -> Any:
                """Keep a usable context, replacing it only when Playwright reports it closed."""
                try:
                    probe = current_context.new_page()
                    probe.close()
                    return current_context
                except Exception:  # noqa: BLE001 - Playwright has several closed-target errors
                    try:
                        current_context.close()
                    except Exception:  # noqa: BLE001
                        pass
                    return browser.new_context()

            try:
                for index, row in enumerate(rows):
                    url = str(row.get("product_url", "")).strip()
                    if url:
                        result, context = crawl_daraz_with_retries(context, url, row, recover_context)
                    else:
                        result = {"error_message": "Missing product_url", "stock_status": "unknown"}
                    status = classify_result(result)
                    current_batch.append(build_price_daily_row(row, result))
                    statuses.append(status)
                    key = (str(row.get("country", "")).strip().upper(), str(row.get("brand", "")).strip())
                    summary[key]["total"] += 1
                    summary[key][status] += 1

                    if len(current_batch) >= CHECKPOINT_SIZE:
                        write_checkpoint()

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
            finally:
                if current_batch and not checkpoint_write_failed:
                    write_checkpoint()
                browser.close()
    finally:
        print("\nCHECKPOINT WRITE SUMMARY")
        print(f"Total batches: {total_batches}")
        print(f"Successful batches: {successful_batches}")
        print(f"Failed batches: {failed_batches}")
        print(f"Total records checkpointed: {total_records_checkpointed}")

    print(f"Daraz daily upsert complete: {total_updated} updated, {total_appended} appended.")
    write_summary(summary)
    print_summary(rows, statuses, summary)


if __name__ == "__main__":
    main()

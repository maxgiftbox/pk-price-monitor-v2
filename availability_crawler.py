"""Full Daraz variant availability snapshot crawler for manual GitHub runs."""

from __future__ import annotations

import os
import random
import re
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from playwright.sync_api import sync_playwright

from daraz_selfhosted import crawl_daraz_with_retries
from scraper import SHEET_NAME, get_gspread_client, google_sheets_retry


SOURCE_TAB = "drz_sku_virants"
CURRENT_TAB = "drz_availability_current"
STAGING_TAB = "drz_availability_staging"
RUN_LOG_TAB = "availability_run_log"
DEBUG_DIR = "debug_availability"
THROTTLE_SECONDS = float(os.getenv("AVAILABILITY_THROTTLE_SECONDS", "4"))

AVAILABILITY_COLUMNS = [
    "run_id",
    "crawled_at",
    "venture",
    "brand_name",
    "product_id",
    "daraz_sku",
    "short_item_eng_name",
    "memory",
    "color",
    "category",
    "url_daraz",
    "availability_status",
    "status_reason",
    "selected_sku_verified",
    "l90_gis",
    "l90_gmv",
    "l90_product_transaction_flag",
]

RUN_LOG_COLUMNS = [
    "run_id",
    "started_at",
    "completed_at",
    "status",
    "total_variants",
    "available",
    "unavailable",
    "unknown",
    "notes",
]


def extract_memory(product_name: Any) -> str:
    """Extract the final storage-capacity token without inventing RAM."""
    matches = re.findall(r"(?i)\b(\d+(?:\.\d+)?\s*(?:TB|GB))\b", str(product_name or ""))
    return re.sub(r"\s+", "", matches[-1]).upper() if matches else ""


def classify_availability(result: Dict[str, Any]) -> tuple[str, str]:
    error = str(result.get("error_message", "")).strip()
    folded = error.casefold()
    stock = str(result.get("stock_status", "")).strip().casefold()
    if "pdp unavailable / 404" in folded:
        return "unavailable", "pdp_unavailable"
    if stock == "out_of_stock":
        return "unavailable", "out_of_stock"
    if stock == "active":
        return "available", "purchase_action_available"
    if "captcha" in folded:
        return "unknown", "captcha"
    if "timeout" in folded:
        return "unknown", "timeout"
    if "network failure" in folded:
        return "unknown", "network_failure"
    if "price not parsed" in folded:
        return "unknown", "parse_failure"
    return "unknown", "unverified"


def sku_verified(row: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """Verify that the final Daraz URL still identifies the requested seller SKU."""
    final_url = str(result.get("final_url", ""))
    seller_sku = str(row.get("daraz_sku", "")).rsplit("-", 1)[-1]
    return bool(final_url and seller_sku and re.search(rf"(?:-|/)s?{re.escape(seller_sku)}(?:\D|$)", final_url))


def build_row(source: Dict[str, Any], result: Dict[str, Any], run_id: str, crawled_at: str) -> Dict[str, Any]:
    status, reason = classify_availability(result)
    verified = sku_verified(source, result) if status != "unknown" else False
    if status in {"available", "unavailable"} and reason != "pdp_unavailable" and not verified:
        status, reason = "unknown", "variant_not_verified"
    return {
        "run_id": run_id,
        "crawled_at": crawled_at,
        "venture": str(source.get("venture", "")).strip().upper(),
        "brand_name": str(source.get("brand_name", "")).strip(),
        "product_id": str(source.get("product_id", "")).strip(),
        "daraz_sku": str(source.get("daraz_sku", "")).strip(),
        "short_item_eng_name": str(source.get("short_item_eng_name", "")).strip(),
        "memory": extract_memory(source.get("short_item_eng_name", "")),
        "color": str(source.get("color", "")).strip() or "Not specified",
        "category": str(source.get("Category", "")).strip(),
        "url_daraz": str(source.get("url_daraz", "")).strip(),
        "availability_status": status,
        "status_reason": reason,
        "selected_sku_verified": verified,
        "l90_gis": source.get("L90 GIS", ""),
        "l90_gmv": source.get("L90 GMV", ""),
        "l90_product_transaction_flag": str(source.get("L90 Product Transaction Flag", "")).strip(),
    }


def ensure_worksheet(spreadsheet: Any, title: str, rows: int, cols: int) -> Any:
    try:
        worksheet = google_sheets_retry(spreadsheet.worksheet, title)
        if worksheet.row_count < rows or worksheet.col_count < cols:
            google_sheets_retry(worksheet.resize, rows=max(rows, worksheet.row_count), cols=max(cols, worksheet.col_count))
        return worksheet
    except Exception as exc:
        if "WorksheetNotFound" not in type(exc).__name__:
            raise
        return google_sheets_retry(spreadsheet.add_worksheet, title=title, rows=rows, cols=cols)


def replace_snapshot(worksheet: Any, rows: Iterable[Dict[str, Any]]) -> None:
    values = [AVAILABILITY_COLUMNS]
    values.extend([[row.get(column, "") for column in AVAILABILITY_COLUMNS] for row in rows])
    google_sheets_retry(worksheet.clear)
    google_sheets_retry(worksheet.update, values=values, range_name="A1", value_input_option="RAW")


def append_run_log(worksheet: Any, values: Dict[str, Any]) -> None:
    existing = google_sheets_retry(worksheet.get_all_values)
    if not existing:
        google_sheets_retry(worksheet.append_row, RUN_LOG_COLUMNS, value_input_option="RAW")
    google_sheets_retry(
        worksheet.append_row,
        [values.get(column, "") for column in RUN_LOG_COLUMNS],
        value_input_option="RAW",
    )


def main() -> None:
    started = datetime.now(timezone.utc)
    run_id = f"{started:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
    client = get_gspread_client()
    spreadsheet = google_sheets_retry(client.open, SHEET_NAME)
    source_ws = google_sheets_retry(spreadsheet.worksheet, SOURCE_TAB)
    source_rows = google_sheets_retry(source_ws.get_all_records)
    source_rows = [row for row in source_rows if str(row.get("daraz_sku", "")).strip() and str(row.get("url_daraz", "")).strip()]
    if not source_rows:
        raise RuntimeError(f"{SOURCE_TAB} contains no usable SKU rows")
    if len({str(row["daraz_sku"]).strip() for row in source_rows}) != len(source_rows):
        raise RuntimeError(f"{SOURCE_TAB} contains duplicate daraz_sku values")

    staging = ensure_worksheet(spreadsheet, STAGING_TAB, len(source_rows) + 10, len(AVAILABILITY_COLUMNS))
    current = ensure_worksheet(spreadsheet, CURRENT_TAB, len(source_rows) + 10, len(AVAILABILITY_COLUMNS))
    run_log = ensure_worksheet(spreadsheet, RUN_LOG_TAB, 1000, len(RUN_LOG_COLUMNS))
    results: List[Dict[str, Any]] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()

            def recover_context(current_context: Any) -> Any:
                try:
                    probe = current_context.new_page()
                    probe.close()
                    return current_context
                except Exception:
                    try:
                        current_context.close()
                    except Exception:
                        pass
                    return browser.new_context()

            try:
                for index, source in enumerate(source_rows, start=1):
                    result, context = crawl_daraz_with_retries(
                        context,
                        str(source["url_daraz"]).strip(),
                        source,
                        recover_context,
                    )
                    crawled_at = datetime.now(timezone.utc).isoformat()
                    row = build_row(source, result, run_id, crawled_at)
                    results.append(row)
                    print(f"[{index}/{len(source_rows)}] {row['venture']} {row['daraz_sku']} {row['availability_status']}")
                    if index < len(source_rows):
                        time.sleep(THROTTLE_SECONDS + random.uniform(0, 1.5))
            finally:
                browser.close()

        if len(results) != len(source_rows):
            raise RuntimeError("Availability crawl did not produce a complete snapshot")
        replace_snapshot(staging, results)
        replace_snapshot(current, results)
        counts = Counter(row["availability_status"] for row in results)
        append_run_log(run_log, {
            "run_id": run_id,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "success",
            "total_variants": len(results),
            "available": counts["available"],
            "unavailable": counts["unavailable"],
            "unknown": counts["unknown"],
            "notes": "Full snapshot published",
        })
    except Exception as exc:
        append_run_log(run_log, {
            "run_id": run_id,
            "started_at": started.isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed",
            "total_variants": len(source_rows),
            "available": "",
            "unavailable": "",
            "unknown": "",
            "notes": str(exc)[:500],
        })
        raise


if __name__ == "__main__":
    main()

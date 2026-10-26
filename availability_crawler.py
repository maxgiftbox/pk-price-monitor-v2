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

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from scraper import SHEET_NAME, get_gspread_client, google_sheets_retry


SOURCE_TAB = "drz_sku_virants"
CURRENT_TAB = "drz_availability_current"
STAGING_TAB = "drz_availability_staging"
RUN_LOG_TAB = "availability_run_log"
DEBUG_DIR = "debug_availability"
THROTTLE_SECONDS = float(os.getenv("AVAILABILITY_THROTTLE_SECONDS", "4"))
NETWORK_MAX_ATTEMPTS = 3
NETWORK_RETRY_DELAYS = (5, 10)

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


def classify_purchase_signals(signals: Dict[str, Any]) -> tuple[str, str]:
    """Map PDP purchase controls to Availability without relying on price parsing."""
    if signals.get("purchase_action_enabled"):
        return "active", "purchase_action_enabled"
    if signals.get("out_of_stock_visible"):
        return "out_of_stock", "out_of_stock_visible"
    if signals.get("wishlist_visible") and not signals.get("purchase_action_enabled"):
        return "out_of_stock", "wishlist_only"
    if signals.get("purchase_action_visible"):
        return "out_of_stock", "purchase_action_disabled"
    return "unknown", "purchase_state_not_found"


def inspect_purchase_controls(page: Any) -> Dict[str, Any]:
    """Inspect visible PDP actions and distinguish enabled purchasing from wishlist-only."""
    return page.evaluate(
        r"""
        () => {
            const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const visible = (element) => {
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' &&
                    Number(style.opacity || 1) > 0 && rect.width > 0 && rect.height > 0;
            };
            const enabled = (element) => {
                const classes = normalize(element.className);
                const style = window.getComputedStyle(element);
                return !element.disabled && element.getAttribute('aria-disabled') !== 'true' &&
                    !/(^|\s)(disabled|is-disabled)(\s|$)/.test(classes) &&
                    style.pointerEvents !== 'none';
            };
            const controls = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'))
                .filter(visible)
                .map((element) => ({
                    text: normalize(element.innerText || element.value || element.getAttribute('aria-label')),
                    enabled: enabled(element),
                }));
            const purchase = controls.filter(({ text }) => /(^|\b)(buy now|add to cart)(\b|$)/.test(text));
            const wishlist = controls.some(({ text }) => /add to wishlist|wishlist/.test(text));
            const body = normalize(document.body && document.body.innerText);
            return {
                purchase_action_visible: purchase.length > 0,
                purchase_action_enabled: purchase.some(({ enabled: isEnabled }) => isEnabled),
                wishlist_visible: wishlist,
                out_of_stock_visible: /\bout of stock\b|\bsold out\b|this item is no longer available/.test(body),
                purchase_action_labels: purchase.map(({ text }) => text).slice(0, 5),
            };
        }
        """
    )


def crawl_daraz_availability(
    context: Any,
    url: str,
    row: Dict[str, Any],
    recover_context: Any = None,
) -> tuple[Dict[str, Any], Any]:
    """Crawl one SKU using PDP purchase controls, independently from Pricing parsing."""
    for attempt in range(1, NETWORK_MAX_ATTEMPTS + 1):
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            body_text = page.locator("body").inner_text(timeout=10000)
            folded = body_text.casefold()
            final_url = page.url

            if any(marker in folded for marker in ("captcha", "verify you are human", "unusual traffic", "robot check")):
                return {
                    "stock_status": "unknown",
                    "final_url": final_url,
                    "error_message": "CAPTCHA detected; crawl not bypassed",
                }, context

            title = page.title().casefold()
            unavailable_page = (
                (response is not None and response.status == 404)
                or "we seem to have lost this page" in folded
                or "we're sorry, an error has occurred" in folded
                or "we’re sorry, an error has occurred" in folded
                or "error" in title
            )
            if unavailable_page:
                return {
                    "stock_status": "out_of_stock",
                    "final_url": final_url,
                    "error_message": "Daraz PDP unavailable / 404",
                }, context

            signals: Dict[str, Any] = {}
            for _ in range(8):
                signals = inspect_purchase_controls(page)
                if any(
                    signals.get(key)
                    for key in (
                        "purchase_action_visible",
                        "wishlist_visible",
                        "out_of_stock_visible",
                    )
                ):
                    break
                page.wait_for_timeout(1000)
            stock_status, signal_reason = classify_purchase_signals(signals)
            return {
                "stock_status": stock_status,
                "final_url": final_url,
                "availability_signal": signal_reason,
                "purchase_action_labels": signals.get("purchase_action_labels", []),
            }, context
        except PlaywrightTimeoutError:
            error_message = "Timeout while loading availability controls"
        except Exception as exc:  # noqa: BLE001
            error_message = f"Navigation failed: {exc}"
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

        if attempt == NETWORK_MAX_ATTEMPTS:
            return {
                "stock_status": "unknown",
                "error_message": f"Network failure after {NETWORK_MAX_ATTEMPTS} attempts: {error_message}",
            }, context
        if recover_context is not None:
            context = recover_context(context)
        time.sleep(NETWORK_RETRY_DELAYS[attempt - 1])

    raise AssertionError("unreachable")


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
                    result, context = crawl_daraz_availability(
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

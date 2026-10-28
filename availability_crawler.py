"""Full Daraz variant availability snapshot crawler for manual GitHub runs."""

from __future__ import annotations

import atexit
import multiprocessing
import os
import random
import re
import time
import uuid
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from scraper import SHEET_NAME, get_gspread_client, google_sheets_retry


SOURCE_TAB = "drz_sku_virants"
CURRENT_TAB = "drz_availability_current"
STAGING_TAB = "drz_availability_staging"
RUN_LOG_TAB = "availability_run_log"
DEBUG_DIR = "debug_availability"
THROTTLE_SECONDS = float(os.getenv("AVAILABILITY_THROTTLE_SECONDS", "4"))
FALLBACK_MAX_WORKERS = max(1, min(4, int(os.getenv("AVAILABILITY_FALLBACK_WORKERS", "3"))))
NETWORK_MAX_ATTEMPTS = 3
NETWORK_RETRY_DELAYS = (5, 10)
PDP_READY_SELECTOR = "#module_add_to_cart"
BLOCKED_RESOURCE_TYPES = {"image", "font", "media"}

_fallback_playwright: Any = None
_fallback_browser: Any = None
_fallback_context: Any = None

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
    signal_reason = str(result.get("availability_signal", "")).strip()
    if "pdp unavailable / 404" in folded:
        return "unavailable", "pdp_unavailable"
    if stock == "out_of_stock":
        return "unavailable", signal_reason or "out_of_stock"
    if stock == "active":
        return "available", signal_reason or "purchase_action_available"
    if "captcha" in folded:
        return "unknown", "captcha"
    if "timeout" in folded:
        return "unknown", "timeout"
    if "network failure" in folded:
        return "unknown", "network_failure"
    if "price not parsed" in folded:
        return "unknown", "parse_failure"
    return "unknown", signal_reason or "unverified"


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


def seller_sku_id(row: Dict[str, Any]) -> str:
    return str(row.get("daraz_sku", "")).strip().rsplit("-", 1)[-1]


def product_group_key(row: Dict[str, Any]) -> Tuple[str, str]:
    venture = str(row.get("venture", "")).strip().upper()
    product_id = str(row.get("product_id", "")).strip()
    if not product_id:
        product_id = str(row.get("daraz_sku", "")).strip().split("_", 1)[0]
    return venture, product_id


def group_source_rows(rows: Iterable[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(product_group_key(row), []).append(row)
    return list(groups.values())


def classify_sku_info(info: Dict[str, Any]) -> tuple[str, str]:
    """Classify one finalized Daraz skuInfos entry."""
    quantity = info.get("quantity") or {}
    limit = quantity.get("limit") or {}
    maximum = limit.get("max")
    quantity_text = str(quantity.get("text", "")).casefold()
    operation = info.get("operation") or {}
    operations = info.get("operations") or []
    operation_types = {
        str(item.get("type", "")).casefold()
        for item in [operation, *operations]
        if isinstance(item, dict)
    }
    operation_text = " ".join(
        str(item.get("text", ""))
        for item in [operation, *operations]
        if isinstance(item, dict)
    ).casefold()

    if maximum == 0 or "out of stock" in quantity_text or "sold out" in quantity_text:
        return "out_of_stock", "sku_quantity_unavailable"
    if "wishlist" in operation_types or "wishlist" in operation_text:
        return "out_of_stock", "sku_wishlist_only"
    if isinstance(maximum, (int, float)) and maximum > 0:
        return "active", "sku_quantity_available"
    if operation and not operation.get("disable") and str(operation.get("type", "")).casefold() == "default":
        return "active", "sku_purchase_operation_available"
    return "unknown", "sku_state_not_found"


def inspect_purchase_controls(page: Any) -> Dict[str, Any]:
    """Inspect visible PDP actions and distinguish enabled purchasing from wishlist-only."""
    return page.evaluate(
        r"""
        () => {
            const normalize = (value) => (value || '').replace(/\s+/g, ' ').trim().toLowerCase();
            const scope = document.querySelector('#module_add_to_cart');
            if (!scope) {
                return {
                    purchase_action_visible: false,
                    purchase_action_enabled: false,
                    wishlist_visible: false,
                    out_of_stock_visible: false,
                    purchase_action_labels: [],
                };
            }
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
            const controls = Array.from(scope.querySelectorAll('button, a, [role="button"], input[type="button"], input[type="submit"]'))
                .filter(visible)
                .map((element) => ({
                    text: normalize(element.innerText || element.value || element.getAttribute('aria-label')),
                    enabled: enabled(element),
                }));
            const purchase = controls.filter(({ text }) => /(^|\b)(buy now|add to cart)(\b|$)/.test(text));
            const wishlist = controls.some(({ text }) => /add to wishlist|wishlist/.test(text));
            const body = normalize(scope.innerText);
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


def inspect_product_sku_data(page: Any) -> Dict[str, Any]:
    """Return the finalized, minimal per-SKU state already used by the rendered PDP."""
    return page.evaluate(
        r"""
        () => {
            const fields = window.__moduleData__?.data?.root?.fields || {};
            const primary = fields.primaryKey || {};
            const infos = fields.skuInfos || {};
            const normalized = {};
            for (const [key, value] of Object.entries(infos)) {
                if (key === '0' || !value || typeof value !== 'object') continue;
                normalized[String(value.skuId || key)] = {
                    skuId: String(value.skuId || key),
                    quantity: value.quantity || {},
                    operation: value.operation || {},
                    operations: value.operations || [],
                };
            }
            return {
                primarySkuId: String(primary.skuId || primary.defaultSkuId || ''),
                loadedSkuIds: (primary.loadedSkuIds || []).map(String),
                skuInfos: normalized,
            };
        }
        """
    )


def product_results_from_payload(
    payload: Dict[str, Any],
    signals: Dict[str, Any],
    final_url: str,
) -> Dict[str, Dict[str, Any]]:
    primary_sku = str(payload.get("primarySkuId", ""))
    loaded_skus = {str(sku_id) for sku_id in (payload.get("loadedSkuIds") or [])}
    results: Dict[str, Dict[str, Any]] = {}
    for sku_id, info in (payload.get("skuInfos") or {}).items():
        sku_id = str(sku_id)
        stock_status, signal_reason = classify_sku_info(info)
        requires_fallback = False
        if sku_id == primary_sku:
            dom_status, dom_reason = classify_purchase_signals(signals)
            if (
                sku_id in loaded_skus
                and dom_status != "unknown"
                and stock_status != "unknown"
                and dom_status != stock_status
            ):
                stock_status, signal_reason = "unknown", f"state_conflict:{signal_reason}:{dom_reason}"
                requires_fallback = True
            elif dom_status != "unknown":
                stock_status, signal_reason = dom_status, dom_reason
            elif sku_id not in loaded_skus:
                stock_status, signal_reason = "unknown", "sku_not_loaded"
                requires_fallback = True
            elif signal_reason == "sku_quantity_unavailable":
                # Daraz may report max=0 for a SKU that is still purchasable on
                # its own PDP. Treat the batch quantity as a lead, not proof.
                requires_fallback = True
            elif stock_status == "unknown":
                requires_fallback = True
        elif sku_id not in loaded_skus:
            stock_status, signal_reason = "unknown", "sku_not_loaded"
            requires_fallback = True
        elif signal_reason == "sku_quantity_unavailable":
            # A sibling SKU must be opened directly before it can be published
            # as unavailable; only the target PDP controls are authoritative.
            requires_fallback = True
        elif stock_status == "unknown":
            requires_fallback = True

        results[sku_id] = {
            "stock_status": stock_status,
            "final_url": final_url,
            "availability_signal": signal_reason,
            "verified_sku_id": sku_id,
            "purchase_action_labels": signals.get("purchase_action_labels", []) if sku_id == primary_sku else [],
            "requires_fallback": requires_fallback,
        }
    return results


def result_requires_fallback(result: Optional[Dict[str, Any]]) -> bool:
    return result is None or bool(result.get("requires_fallback"))


def resolve_single_sku_result(
    result: Optional[Dict[str, Any]],
    signals: Dict[str, Any],
    final_url: str,
) -> Dict[str, Any]:
    """Resolve a SKU-specific PDP from its visible controls when batch data is incomplete."""
    dom_status, dom_reason = classify_purchase_signals(signals)
    if dom_status != "unknown":
        return {
            "stock_status": dom_status,
            "final_url": final_url,
            "availability_signal": dom_reason,
            "purchase_action_labels": signals.get("purchase_action_labels", []),
            "requires_fallback": False,
        }
    unresolved = dict(result or {})
    unresolved.update({
        "stock_status": "unknown",
        "final_url": final_url,
        "availability_signal": unresolved.get("availability_signal") or "sku_state_not_found",
        "error_message": "Single-SKU PDP did not expose a decisive purchase state",
        "requires_fallback": False,
    })
    return unresolved


def _unknown_results(rows: Iterable[Dict[str, Any]], error_message: str, final_url: str = "") -> Dict[str, Dict[str, Any]]:
    return {
        seller_sku_id(row): {
            "stock_status": "unknown",
            "final_url": final_url,
            "verified_sku_id": seller_sku_id(row),
            "error_message": error_message,
        }
        for row in rows
    }


def crawl_daraz_product(
    context: Any,
    rows: List[Dict[str, Any]],
    recover_context: Any = None,
) -> tuple[Dict[str, Dict[str, Any]], Any]:
    """Open one PDP and return finalized states for all source SKUs in the Product."""
    representative = rows[0]
    url = str(representative["url_daraz"]).strip()
    source_skus = {seller_sku_id(row) for row in rows}
    for attempt in range(1, NETWORK_MAX_ATTEMPTS + 1):
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            final_url = page.url
            body_text = page.locator("body").inner_text(timeout=10000)
            folded = body_text.casefold()
            if any(marker in folded for marker in ("captcha", "verify you are human", "unusual traffic", "robot check")):
                return _unknown_results(rows, "CAPTCHA detected; crawl not bypassed", final_url), context

            title = page.title().casefold()
            unavailable_page = (
                (response is not None and response.status == 404)
                or "we seem to have lost this page" in folded
                or "we're sorry, an error has occurred" in folded
                or "we’re sorry, an error has occurred" in folded
                or "error" in title
            )
            if unavailable_page:
                if len(rows) == 1:
                    sku_id = seller_sku_id(rows[0])
                    return {
                        sku_id: {
                            "stock_status": "out_of_stock",
                            "final_url": final_url,
                            "verified_sku_id": sku_id,
                            "error_message": "Daraz PDP unavailable / 404",
                        }
                    }, context
                return {}, context

            page.locator(PDP_READY_SELECTOR).wait_for(state="visible", timeout=10000)
            signals = inspect_purchase_controls(page)
            payload = inspect_product_sku_data(page)
            results = product_results_from_payload(payload, signals, final_url)
            matched = {sku: result for sku, result in results.items() if sku in source_skus}
            if len(rows) == 1:
                sku_id = seller_sku_id(rows[0])
                single_result = matched.get(sku_id)
                if result_requires_fallback(single_result):
                    single_result = resolve_single_sku_result(single_result, signals, final_url)
                return {sku_id: single_result}, context
            if matched:
                return matched, context
            error_message = "Rendered PDP did not expose any requested seller SKU"
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
            return _unknown_results(
                rows,
                f"Network failure after {NETWORK_MAX_ATTEMPTS} attempts: {error_message}",
            ), context
        if recover_context is not None:
            context = recover_context(context)
        time.sleep(NETWORK_RETRY_DELAYS[attempt - 1])

    raise AssertionError("unreachable")


def crawl_daraz_availability(
    context: Any,
    url: str,
    row: Dict[str, Any],
    recover_context: Any = None,
) -> tuple[Dict[str, Any], Any]:
    """Fallback crawl for one SKU when it is absent from its Product payload."""
    row = dict(row)
    row["url_daraz"] = url
    results, context = crawl_daraz_product(context, [row], recover_context)
    return results.get(seller_sku_id(row), {
        "stock_status": "unknown",
        "error_message": "Requested seller SKU was not present in rendered PDP data",
    }), context


def sku_verified(row: Dict[str, Any], result: Dict[str, Any]) -> bool:
    """Verify that the final Daraz URL still identifies the requested seller SKU."""
    expected_sku = seller_sku_id(row)
    verified_sku = str(result.get("verified_sku_id", ""))
    if expected_sku and verified_sku:
        return expected_sku == verified_sku
    final_url = str(result.get("final_url", ""))
    return bool(final_url and expected_sku and re.search(rf"(?:-|/)s?{re.escape(expected_sku)}(?:\D|$)", final_url))


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


def create_browser_context(browser: Any) -> Any:
    context = browser.new_context()
    context.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES
        else route.continue_(),
    )
    return context


def fallback_worker_count(total_rows: int, configured_workers: int = FALLBACK_MAX_WORKERS) -> int:
    """Bound fallback concurrency so a manual run cannot overload Daraz or the runner."""
    if total_rows <= 0:
        return 0
    return min(total_rows, max(1, min(4, configured_workers)))


def _close_fallback_worker() -> None:
    global _fallback_playwright, _fallback_browser, _fallback_context
    for resource in (_fallback_context, _fallback_browser):
        try:
            if resource is not None:
                resource.close()
        except Exception:
            pass
    try:
        if _fallback_playwright is not None:
            _fallback_playwright.stop()
    except Exception:
        pass
    _fallback_context = None
    _fallback_browser = None
    _fallback_playwright = None


def _init_fallback_worker() -> None:
    """Give each process its own Playwright driver, Chromium, and browser context."""
    global _fallback_playwright, _fallback_browser, _fallback_context
    _fallback_playwright = sync_playwright().start()
    _fallback_browser = _fallback_playwright.chromium.launch(headless=True)
    _fallback_context = create_browser_context(_fallback_browser)
    atexit.register(_close_fallback_worker)


def _recover_fallback_context(current_context: Any) -> Any:
    global _fallback_context
    try:
        probe = current_context.new_page()
        probe.close()
        return current_context
    except Exception:
        try:
            current_context.close()
        except Exception:
            pass
        _fallback_context = create_browser_context(_fallback_browser)
        return _fallback_context


def _crawl_fallback_worker(source: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Crawl one target SKU inside an isolated, persistent worker browser."""
    global _fallback_context
    sku = str(source["daraz_sku"]).strip()
    try:
        time.sleep(THROTTLE_SECONDS + random.uniform(0, 1.5))
        result, _fallback_context = crawl_daraz_availability(
            _fallback_context,
            str(source["url_daraz"]).strip(),
            source,
            _recover_fallback_context,
        )
        return sku, result
    except Exception as exc:  # noqa: BLE001
        return sku, {
            "stock_status": "unknown",
            "verified_sku_id": seller_sku_id(source),
            "error_message": f"Parallel fallback worker failed: {exc}",
        }


def run_parallel_fallbacks(source_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Resolve target-SKU fallbacks with bounded, process-isolated concurrency."""
    workers = fallback_worker_count(len(source_rows))
    if workers == 0:
        return {}
    print(f"[Fallback] queued={len(source_rows)} workers={workers}")
    results: Dict[str, Dict[str, Any]] = {}
    spawn_context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=workers,
        mp_context=spawn_context,
        initializer=_init_fallback_worker,
    ) as executor:
        future_to_sku = {
            executor.submit(_crawl_fallback_worker, source): str(source["daraz_sku"]).strip()
            for source in source_rows
        }
        total = len(future_to_sku)
        for completed, future in enumerate(as_completed(future_to_sku), start=1):
            expected_sku = future_to_sku[future]
            try:
                sku, result = future.result()
            except Exception as exc:  # noqa: BLE001
                sku, result = expected_sku, {
                    "stock_status": "unknown",
                    "error_message": f"Parallel fallback process failed: {exc}",
                }
            results[sku] = result
            if completed % 25 == 0 or completed == total:
                counts = Counter(classify_availability(value)[0] for value in results.values())
                print(
                    f"[Fallback {completed}/{total}] available={counts['available']} "
                    f"unavailable={counts['unavailable']} unknown={counts['unknown']}"
                )
    return results


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
        results_by_sku: Dict[str, Dict[str, Any]] = {}
        fallback_sources: List[Dict[str, Any]] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = create_browser_context(browser)

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
                    return create_browser_context(browser)

            try:
                source_groups = group_source_rows(source_rows)
                for group_index, source_group in enumerate(source_groups, start=1):
                    product_results, context = crawl_daraz_product(
                        context,
                        source_group,
                        recover_context,
                    )
                    for source in source_group:
                        sku_id = seller_sku_id(source)
                        result = product_results.get(sku_id)
                        if result_requires_fallback(result):
                            fallback_sources.append(source)
                        results_by_sku[str(source["daraz_sku"]).strip()] = result or {
                            "stock_status": "unknown",
                            "availability_signal": "sku_state_not_found",
                            "requires_fallback": True,
                        }

                    statuses = Counter(
                        classify_availability(
                            results_by_sku.get(str(source["daraz_sku"]).strip(), {})
                        )[0]
                        for source in source_group
                    )
                    venture, product_id = product_group_key(source_group[0])
                    pending = sum(
                        result_requires_fallback(
                            results_by_sku.get(str(source["daraz_sku"]).strip())
                        )
                        for source in source_group
                    )
                    print(
                        f"[Product {group_index}/{len(source_groups)}] {venture} {product_id} "
                        f"variants={len(source_group)} available={statuses['available']} "
                        f"unavailable={statuses['unavailable']} unknown={statuses['unknown']} "
                        f"fallback={pending}"
                    )
                    if group_index < len(source_groups):
                        time.sleep(THROTTLE_SECONDS + random.uniform(0, 1.5))

            finally:
                browser.close()

        results_by_sku.update(run_parallel_fallbacks(fallback_sources))
        crawled_at = datetime.now(timezone.utc).isoformat()
        results = [
            build_row(
                source,
                results_by_sku.get(str(source["daraz_sku"]).strip(), {
                    "stock_status": "unknown",
                    "error_message": "No crawl result produced for source SKU",
                }),
                run_id,
                crawled_at,
            )
            for source in source_rows
        ]

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

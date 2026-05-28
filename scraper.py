import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import gspread
import pandas as pd
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

SHEET_NAME = "Mob Price Monitor"
SKU_MASTER_TAB = "sku_master"
PRICE_DAILY_TAB = "price_daily"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
PRICE_DAILY_COLUMNS = [
    "crawl_date",
    "platform",
    "brand",
    "model",
    "memory",
    "original_price",
    "product_price",
    "stock_status",
    "product_url",
    "crawl_time",
    "error_message",
]


def get_gspread_client() -> gspread.Client:
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set.")

    try:
        service_account_info = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc

    credentials = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    return gspread.authorize(credentials)


def clean_price(value: Optional[str]) -> str:
    if not value:
        return ""
    return " ".join(value.replace("\xa0", " ").split())


def extract_price_data(page_html: str) -> Dict[str, str]:
    soup = BeautifulSoup(page_html, "html.parser")

    product_price = ""
    original_price = ""
    stock_status = ""

    current_selectors = [
        "p.price",
        "span.price",
        "[data-testid='product-price']",
        ".price-box .price",
    ]
    original_selectors = [
        "p.actual-price",
        "span.actual-price",
        ".price-box .actual-price",
        "del",
    ]
    stock_selectors = [
        ".stock-status",
        ".availability",
        "[data-testid='stock-status']",
        ".product-status",
    ]

    for selector in current_selectors:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            product_price = clean_price(node.get_text(" ", strip=True))
            break

    for selector in original_selectors:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            original_price = clean_price(node.get_text(" ", strip=True))
            break

    for selector in stock_selectors:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            stock_status = clean_price(node.get_text(" ", strip=True))
            break

    return {
        "product_price": product_price,
        "original_price": original_price,
        "stock_status": stock_status,
    }


def normalize_memory(text: str) -> str:
    value = (text or "").lower()
    value = value.replace("＋", "+")
    numbers = re.findall(r"\d+", value)
    if len(numbers) >= 2:
        return f"{numbers[0]}/{numbers[1]}"
    compact = re.sub(r"\s+", "", value)
    return compact


def sanitize_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[\\/]+", "_", (value or "").strip())
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", cleaned)
    cleaned = cleaned.strip("._-")
    return cleaned or fallback


def save_debug_artifacts(page: Any, screenshot_path: Optional[str] = None, html_path: Optional[str] = None) -> None:
    try:
        if screenshot_path:
            page.screenshot(path=screenshot_path, full_page=True)
            print(f"[DEBUG][PriceOye] Saved screenshot: {screenshot_path}")
    except Exception as exc:
        print(f"[DEBUG][PriceOye] Failed to save screenshot {screenshot_path}: {exc}")

    try:
        if html_path:
            with open(html_path, "w", encoding="utf-8") as handle:
                handle.write(page.content())
            print(f"[DEBUG][PriceOye] Saved HTML: {html_path}")
    except Exception as exc:
        print(f"[DEBUG][PriceOye] Failed to save HTML {html_path}: {exc}")


def collect_memory_click_candidates(page: Any) -> List[Dict[str, Any]]:
    script = """
    () => {
        const selectors = [
            'button',
            '[role="button"]',
            'label',
            'li',
            'a',
            'span',
            'div'
        ];
        const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
        const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            if (!style) return false;
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };
        const clickableNodeNames = new Set(['A', 'BUTTON', 'LABEL', 'INPUT', 'OPTION']);
        const output = [];
        for (const el of nodes) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (!text) continue;
            const role = (el.getAttribute('role') || '').toLowerCase();
            const tabIndex = Number(el.getAttribute('tabindex') || '');
            const isClickable = clickableNodeNames.has(el.tagName) || role === 'button' || role === 'option' || !Number.isNaN(tabIndex);
            if (!isClickable) continue;
            output.push({
                tag: el.tagName.toLowerCase(),
                text,
                class_name: el.className || '',
                aria_label: el.getAttribute('aria-label') || ''
            });
        }
        return output;
    }
    """
    data = page.evaluate(script)
    if not isinstance(data, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cleaned.append(
            {
                "tag": clean_price(str(item.get("tag", ""))),
                "text": clean_price(str(item.get("text", ""))),
                "class_name": clean_price(str(item.get("class_name", ""))),
                "aria_label": clean_price(str(item.get("aria_label", ""))),
            }
        )
    return cleaned


def extract_prices_near_memory(text: str, memory: str) -> Dict[str, str]:
    if not text or not memory:
        return {}

    normalized_memory = normalize_memory(memory)
    if not normalized_memory or "/" not in normalized_memory:
        return {}

    ram, rom = normalized_memory.split("/", 1)
    memory_patterns = [
        rf"\b{ram}\s*/\s*{rom}\b",
        rf"\b{ram}\s*gb\s*\+\s*{rom}\s*gb\b",
        rf"\b{ram}\s*gb\s*ram\s*{rom}\s*gb\s*rom\b",
        rf"\b{ram}\s*gb\s*/\s*{rom}\s*gb\b",
    ]

    price_pattern = re.compile(r"Rs\.?\s*[\d,]+", re.I)
    compiled_patterns = [re.compile(p, re.I) for p in memory_patterns]

    best: Dict[str, str] = {}
    for pattern in compiled_patterns:
        for match in pattern.finditer(text):
            window_start = max(0, match.start() - 220)
            window_end = min(len(text), match.end() + 220)
            snippet = text[window_start:window_end]
            prices = [clean_price(p) for p in price_pattern.findall(snippet)]
            if not prices:
                continue
            best = {
                "product_price": prices[0],
                "original_price": prices[1] if len(prices) > 1 else "",
            }
            return best
    return best


def extract_variant_map_from_scripts(html_or_scripts: str) -> Dict[str, Dict[str, str]]:
    variant_map: Dict[str, Dict[str, str]] = {}
    if not html_or_scripts:
        return variant_map

    soup = BeautifulSoup(html_or_scripts, "html.parser")
    script_texts = [s.get_text(" ", strip=False) for s in soup.find_all("script")]
    if not script_texts:
        script_texts = [html_or_scripts]
    source_text = "\n".join(script_texts + [html_or_scripts])

    memory_token = r"(4\s*/\s*64|4\s*/\s*128|6\s*/\s*128|8\s*/\s*128|8\s*/\s*256|12\s*/\s*256|12\s*/\s*512|16\s*/\s*512|\d+\s*gb\s*\+\s*\d+\s*gb|\d+\s*gb\s*ram\s*\d+\s*gb\s*rom|\d+\s*gb\s*/\s*\d+\s*gb)"
    pair_pattern = re.compile(
        rf"(?P<memory>{memory_token}).{{0,220}}?(?P<price>Rs\.?\s*[\d,]+)(?:.{{0,120}}?(?P<orig>Rs\.?\s*[\d,]+))?(?:.{{0,220}}?(?P<url>https?://[^\s\"'<>]+))?",
        re.I | re.S,
    )

    for match in pair_pattern.finditer(source_text):
        mem = normalize_memory(match.group("memory"))
        if not mem:
            continue
        if mem in variant_map and variant_map[mem].get("product_price"):
            continue
        variant_map[mem] = {
            "product_price": clean_price(match.group("price") or ""),
            "original_price": clean_price(match.group("orig") or ""),
            "url": clean_price(match.group("url") or ""),
        }

    return variant_map


def get_visible_texts_for_selector(page: Any, selector: str) -> List[str]:
    script = """
    (selector) => {
        const nodes = Array.from(document.querySelectorAll(selector));
        const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            if (!style) return false;
            if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        };

        const output = [];
        for (const el of nodes) {
            if (!isVisible(el)) continue;
            const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
            if (text) output.push(text);
        }
        return output;
    }
    """
    values = page.evaluate(script, selector)
    if not isinstance(values, list):
        return []
    return [clean_price(str(v)) for v in values if clean_price(str(v))]


def get_memory_debug_matches(text: str) -> List[Dict[str, str]]:
    pattern = re.compile(r"(4\s*/\s*64|4\s*/\s*128|6\s*/\s*128|8\s*/\s*128|8\s*/\s*256|12\s*/\s*256|12\s*/\s*512)", re.I)
    matches: List[Dict[str, str]] = []
    for match in pattern.finditer(text):
        start = max(0, match.start() - 150)
        end = min(len(text), match.end() + 150)
        snippet = clean_price(text[start:end])
        matches.append(
            {
                "match": clean_price(match.group(0)),
                "snippet": snippet,
            }
        )
    return matches


def parse_memory_variants(page: Any) -> List[Tuple[str, str]]:
    """Returns [(memory_text, linked_price_text), ...] found on the page."""
    variants: List[Tuple[str, str]] = []
    memory_pattern = re.compile(r"\b\d+\s*/\s*\d+\b")
    # Gather from likely interactive controls and text containers.
    candidate_selectors = [
        "button",
        "[role='button']",
        "label",
        "li",
        "a",
        "span",
        "div",
    ]

    for selector in candidate_selectors:
        locator = page.locator(selector)
        count = min(locator.count(), 250)
        for i in range(count):
            text = clean_price(locator.nth(i).inner_text())
            memory_match = memory_pattern.search(text)
            if not memory_match:
                continue
            memory = clean_price(memory_match.group(0))
            price_match = re.search(r"Rs\.?\s?[\d,]+", text)
            linked_price = clean_price(price_match.group(0)) if price_match else ""
            pair = (memory, linked_price)
            if pair not in variants:
                variants.append(pair)

    return variants


def crawl_priceoye_page(
    browser_context: Any,
    product_url: str,
    memory: str = "",
    force_debug_artifacts: bool = False,
) -> Dict[str, str]:
    page = browser_context.new_page()
    try:
        os.makedirs("debug_screenshots", exist_ok=True)
        page.goto(product_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        body_text = page.locator("body").inner_text()
        html = page.content()
        scripts_text = page.evaluate(
            """() => Array.from(document.querySelectorAll('script'))
                .map((s) => s.textContent || '')
                .join('\\n')"""
        )
        body_text_lower = body_text.lower()

        normalized_requested_memory = normalize_memory(memory)
        current_url = page.url
        visible_button_texts = get_visible_texts_for_selector(page, "button, [role='button']")
        visible_link_texts = get_visible_texts_for_selector(page, "a")
        memory_debug_matches = get_memory_debug_matches(body_text)

        print(f"[DEBUG][PriceOye] Crawling URL (input): {product_url}")
        print(f"[DEBUG][PriceOye] Current page URL: {current_url}")
        print(f"[DEBUG][PriceOye] Requested memory from sku_master: {memory or '(blank)'}")
        print(f"[DEBUG][PriceOye] Visible body text (first 5000 chars):\n{body_text[:5000]}")
        print(f"[DEBUG][PriceOye] All visible button texts ({len(visible_button_texts)}): {visible_button_texts}")
        print(f"[DEBUG][PriceOye] All visible link texts ({len(visible_link_texts)}): {visible_link_texts}")
        print(
            "[DEBUG][PriceOye] Memory-pattern visible snippets: "
            f"{[m.get('match', '') for m in memory_debug_matches]}"
        )
        for idx, item in enumerate(memory_debug_matches, start=1):
            print(
                "[DEBUG][PriceOye] Memory match context "
                f"#{idx} [{item.get('match', '')}] (~300 chars): {item.get('snippet', '')}"
            )

        print(f"[DEBUG][PriceOye] requested memory: {memory or '(blank)'}")
        print(f"[DEBUG][PriceOye] normalized requested memory: {normalized_requested_memory or '(blank)'}")

        parsed_data = extract_price_data(html)
        base_product_price = parsed_data.get("product_price", "")
        base_original_price = parsed_data.get("original_price", "")
        fallback_used = False
        error_message = ""
        safe_model = sanitize_filename(product_url.rstrip("/").split("/")[-1], "unknown_model")
        safe_memory = sanitize_filename(memory or "default", "default_memory")
        debug_prefix = os.path.join("debug_screenshots", f"{safe_model}_{safe_memory}")

        if force_debug_artifacts:
            save_debug_artifacts(page, screenshot_path=f"{debug_prefix}_before.png")

        if normalized_requested_memory:
            candidates = collect_memory_click_candidates(page)
            print(f"[DEBUG][PriceOye] Candidate clickable memory elements ({len(candidates)}):")
            for idx, candidate in enumerate(candidates, start=1):
                print(
                    "[DEBUG][PriceOye] candidate "
                    f"#{idx} tag={candidate.get('tag', '')} "
                    f"text={candidate.get('text', '')} "
                    f"class={candidate.get('class_name', '')} "
                    f"aria-label={candidate.get('aria_label', '')}"
                )

            matched_candidate: Optional[Dict[str, Any]] = None
            for candidate in candidates:
                if normalize_memory(candidate.get("text", "")) == normalized_requested_memory:
                    matched_candidate = candidate
                    break

            if matched_candidate:
                clicked_text = matched_candidate.get("text", "")
                selector = (
                    f"{matched_candidate.get('tag', '')}"
                    f"{'.' + '.'.join([c for c in matched_candidate.get('class_name', '').split() if c]) if matched_candidate.get('class_name', '') else ''}"
                )
                clicked = False

                if selector:
                    locator = page.locator(selector).filter(has_text=clicked_text).first
                    if locator.count() > 0:
                        locator.click(timeout=5000)
                        clicked = True

                if not clicked:
                    locator = page.locator("*").filter(has_text=clicked_text).first
                    if locator.count() > 0:
                        locator.click(timeout=5000)
                        clicked = True

                page.wait_for_timeout(3000)
                if force_debug_artifacts:
                    save_debug_artifacts(
                        page,
                        screenshot_path=f"{debug_prefix}_after.png",
                        html_path=f"{debug_prefix}.html",
                    )
                refreshed_html = page.content()
                refreshed_data = extract_price_data(refreshed_html)
                price_after_click = refreshed_data.get("product_price", "")
                original_after_click = refreshed_data.get("original_price", "")

                if (
                    price_after_click == base_product_price
                    and original_after_click == base_original_price
                    and clicked
                ):
                    if selector:
                        js_locator = page.locator(selector).filter(has_text=clicked_text).first
                    else:
                        js_locator = page.locator("*").filter(has_text=clicked_text).first
                    if js_locator.count() > 0:
                        js_locator.evaluate("el => el.click()")
                        page.wait_for_timeout(3000)
                        refreshed_html = page.content()
                        refreshed_data = extract_price_data(refreshed_html)
                        price_after_click = refreshed_data.get("product_price", "")
                        original_after_click = refreshed_data.get("original_price", "")

                print(
                    "[DEBUG][PriceOye] Click result: "
                    f"requested memory={memory}, "
                    f"clicked element text={clicked_text}, "
                    f"price before click={base_product_price}, "
                    f"price after click={price_after_click}"
                )

                parsed_data["product_price"] = price_after_click or base_product_price
                parsed_data["original_price"] = original_after_click or base_original_price

                if price_after_click == base_product_price and original_after_click == base_original_price:
                    error_message = f"Matched memory {memory} but price did not change"
            else:
                fallback_used = True
                error_message = f"Memory clickable element not found for {memory}; fallback default price used"

        stock_status = "unknown"
        matched_keyword = ""
        out_of_stock_keywords = ["out of stock", "sold out", "unavailable"]
        active_keywords = ["add to cart", "buy now", "available", "in stock"]

        for keyword in out_of_stock_keywords:
            if keyword in body_text_lower:
                stock_status = "out_of_stock"
                matched_keyword = keyword
                break

        if stock_status == "unknown":
            for keyword in active_keywords:
                if keyword in body_text_lower:
                    stock_status = "active"
                    matched_keyword = keyword
                    break

        parsed_data["stock_status"] = stock_status
        print(f"[DEBUG][PriceOye] Stock status matched keyword: {matched_keyword or 'none'}")

        regex_matches = re.findall(r"Rs\.?\s?([\d,]+)", body_text)
        normalized_matches = [f"Rs {m}" for m in regex_matches]
        print(f"[DEBUG][PriceOye] Regex matched prices: {normalized_matches}")

        if normalized_matches and not parsed_data.get("product_price"):
            parsed_data["product_price"] = normalized_matches[0]
        if len(normalized_matches) > 1 and not parsed_data.get("original_price"):
            parsed_data["original_price"] = normalized_matches[1]

        if error_message:
            parsed_data["error_message"] = error_message

        print(f"[DEBUG][PriceOye] fallback_used: {'yes' if fallback_used else 'no'}")
        print(f"[DEBUG][PriceOye] final product_price: {parsed_data.get('product_price', '')}")
        print(f"[DEBUG][PriceOye] final original_price: {parsed_data.get('original_price', '')}")
        print(f"[DEBUG][PriceOye] final stock_status: {parsed_data.get('stock_status', '')}")
        print(
            "[DEBUG][PriceOye] Parsed prices summary: "
            f"product_price={parsed_data.get('product_price', '')}, "
            f"original_price={parsed_data.get('original_price', '')}"
        )
        print(f"[DEBUG][PriceOye] Final stock_status: {parsed_data.get('stock_status', '')}")

        if (
            not parsed_data.get("product_price")
            and not parsed_data.get("original_price")
            and not parsed_data.get("stock_status")
        ):
            with open("debug_output.txt", "w", encoding="utf-8") as debug_file:
                debug_file.write(body_text)
            print("[DEBUG][PriceOye] Parsing failed. Saved full body text to debug_output.txt")

        return parsed_data
    except PlaywrightTimeoutError:
        return {
            "product_price": "",
            "original_price": "",
            "stock_status": "unknown",
            "error_message": "Timeout while loading page",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "product_price": "",
            "original_price": "",
            "stock_status": "unknown",
            "error_message": f"Crawl failed: {exc}",
        }
    finally:
        if force_debug_artifacts:
            safe_model = sanitize_filename(product_url.rstrip("/").split("/")[-1], "unknown_model")
            safe_memory = sanitize_filename(memory or "default", "default_memory")
            debug_prefix = os.path.join("debug_screenshots", f"{safe_model}_{safe_memory}")
            save_debug_artifacts(
                page,
                screenshot_path=f"{debug_prefix}_after.png",
                html_path=f"{debug_prefix}.html",
            )
        page.close()


def build_price_daily_row(base: Dict[str, str], crawl_result: Dict[str, str]) -> Dict[str, str]:
    now_utc = datetime.now(timezone.utc)
    row = {
        "crawl_date": now_utc.date().isoformat(),
        "platform": str(base.get("platform", "")).strip(),
        "brand": str(base.get("brand", "")).strip(),
        "model": str(base.get("model", "")).strip(),
        "memory": str(base.get("memory", "")).strip(),
        "original_price": crawl_result.get("original_price", ""),
        "product_price": crawl_result.get("product_price", ""),
        "stock_status": crawl_result.get("stock_status", ""),
        "product_url": str(base.get("product_url", "")).strip(),
        "crawl_time": now_utc.isoformat(timespec="seconds"),
        "error_message": crawl_result.get("error_message", ""),
    }
    return row


def ensure_price_daily_header(worksheet: gspread.Worksheet) -> None:
    existing_header = worksheet.row_values(1)
    if existing_header != PRICE_DAILY_COLUMNS:
        worksheet.update("A1:K1", [PRICE_DAILY_COLUMNS])


def main() -> None:
    os.makedirs("debug_screenshots", exist_ok=True)
    print(f"[DEBUG][PriceOye] Debug directory ready: {os.path.abspath('debug_screenshots')}")

    client = get_gspread_client()
    sheet = client.open(SHEET_NAME)

    sku_ws = sheet.worksheet(SKU_MASTER_TAB)
    price_ws = sheet.worksheet(PRICE_DAILY_TAB)

    ensure_price_daily_header(price_ws)

    sku_records = sku_ws.get_all_records()
    if not sku_records:
        print("No SKU rows found in sku_master.")
        return

    active_rows = [
        row for row in sku_records if str(row.get("status", "")).strip().lower() == "active"
    ]

    if not active_rows:
        print("No active rows found in sku_master.")
        return

    output_rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        crawled_sku_count = 0

        for row in active_rows:
            product_url = str(row.get("product_url", "")).strip()
            platform = str(row.get("platform", "")).strip().lower()

            crawl_result: Dict[str, str]
            if not product_url:
                crawl_result = {
                    "product_price": "",
                    "original_price": "",
                    "stock_status": "unknown",
                    "error_message": "Missing product_url",
                }
            elif platform != "priceoye":
                crawl_result = {
                    "product_price": "",
                    "original_price": "",
                    "stock_status": "unknown",
                    "error_message": f"Unsupported platform: {platform}",
                }
            else:
                memory = str(row.get("memory", "")).strip()
                crawled_sku_count += 1
                force_debug_artifacts = crawled_sku_count <= 5
                crawl_result = crawl_priceoye_page(
                    context,
                    product_url,
                    memory=memory,
                    force_debug_artifacts=force_debug_artifacts,
                )
                if (
                    not crawl_result.get("product_price")
                    and not crawl_result.get("original_price")
                    and not crawl_result.get("stock_status")
                    and not crawl_result.get("error_message")
                ):
                    crawl_result["error_message"] = "Price parsing failed"

            output_rows.append(build_price_daily_row(row, crawl_result))

        browser.close()

    df = pd.DataFrame(output_rows, columns=PRICE_DAILY_COLUMNS).fillna("")
    if not df.empty:
        price_ws.append_rows(df.values.tolist(), value_input_option="RAW")
    print(f"Appended {len(df)} row(s) to {PRICE_DAILY_TAB}.")


if __name__ == "__main__":
    main()

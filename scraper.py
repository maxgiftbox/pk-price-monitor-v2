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
    "country",
    "brand",
    "model",
    "memory",
    "original_price",
    "product_price",
    "stock_status",
    "voucher_amount",
    "effective_price",
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




def parse_price_to_int(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return value

    cleaned = str(value).replace(" ", " ").replace("\xa0", " ")
    cleaned = re.sub(r"(?i)(rs|tk|bdt)\.?", "", cleaned)
    cleaned = cleaned.replace("৳", "")
    cleaned = cleaned.replace(",", "")
    cleaned = re.sub(r"\s+", "", cleaned)

    if not cleaned:
        return ""

    if not cleaned.isdigit():
        return ""

    try:
        return int(cleaned)
    except ValueError:
        return ""


def parse_tk_bdt_price_to_int(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return value

    text = str(value).replace("\xa0", " ")
    text = re.sub(r"(?i)(tk|bdt)\.?\s*", "", text)
    text = text.replace("৳", "")
    text = text.replace(",", "")
    text = re.sub(r"\s+", "", text)
    if not text or not text.isdigit():
        return ""
    try:
        return int(text)
    except ValueError:
        return ""

PICKABOO_PRICE_PATTERN = re.compile(r"(?i)(?:৳|tk|bdt)\s*([\d,]+)|\b(\d{1,3}(?:,\d{3})+)\b")
PICKABOO_OFFER_CONTEXT_PATTERN = re.compile(
    r"(?i)(available offer|checkout discount|voucher|coupon|promo|cashback|save|discount)"
)


def first_tk_bdt_price_to_int(text: str) -> Any:
    for match in PICKABOO_PRICE_PATTERN.finditer(text or ""):
        parsed = parse_tk_bdt_price_to_int(match.group(1) or match.group(2))
        if isinstance(parsed, int) and parsed > 0:
            return parsed
    return ""


def extract_pickaboo_product_price(page: Any, body_text: str) -> Any:
    candidate_texts = page.evaluate(
        r"""
        () => {
            const selectors = [
                '.product-price',
                '.product_price',
                '.special-price',
                '.final-price',
                '.price-box .price',
                '.product-info-main .price',
                '.product-details .price',
                '.pdp-price',
                '[class*=\"product\"][class*=\"price\"]',
                '[class*=\"price\"]'
            ];
            const nodes = Array.from(document.querySelectorAll(selectors.join(',')));
            const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };
            return nodes
                .filter(isVisible)
                .map((el) => {
                    const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                    const context = (el.closest('section, article, div')?.innerText || text)
                        .replace(/\s+/g, ' ')
                        .trim();
                    return { text, context };
                })
                .filter((item) => item.text);
        }
        """
    )
    if isinstance(candidate_texts, list):
        for item in candidate_texts:
            if not isinstance(item, dict):
                continue
            text = clean_price(str(item.get("text", "")))
            context = clean_price(str(item.get("context", "")))
            if not text:
                continue
            if PICKABOO_OFFER_CONTEXT_PATTERN.search(context) and not re.search(
                r"(?i)(regular price|special price|sale price|current price)", context
            ):
                continue
            parsed = first_tk_bdt_price_to_int(text)
            if isinstance(parsed, int):
                return parsed

    for line in [clean_price(line) for line in (body_text or "").splitlines()]:
        if not line or PICKABOO_OFFER_CONTEXT_PATTERN.search(line):
            continue
        parsed = first_tk_bdt_price_to_int(line)
        if isinstance(parsed, int):
            return parsed

    return ""


def extract_pickaboo_original_price(page: Any, product_price: Any) -> Any:
    original_texts = page.evaluate(
        r"""
        () => Array.from(document.querySelectorAll('del, s, .old-price, .regular-price'))
            .filter((el) => {
                const style = window.getComputedStyle(el);
                if (!style) return false;
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            })
            .map((el) => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim())
            .filter(Boolean)
        """
    )
    if isinstance(original_texts, list):
        for text in original_texts:
            parsed = first_tk_bdt_price_to_int(str(text))
            if isinstance(parsed, int) and parsed > 0:
                return parsed
    return product_price if isinstance(product_price, int) else ""


def extract_pickaboo_voucher_amount(text: str) -> int:
    if not re.search(r"(?i)(available offer|checkout discount)", text or ""):
        return 0

    patterns = [
        re.compile(r"(?i)(?:৳|tk|bdt)\s*([\d,]+)\s*(?:checkout discount|discount)"),
        re.compile(r"(?i)(?:checkout discount|discount)\D{0,40}(?:৳|tk|bdt)?\s*([\d,]+)"),
    ]
    for pattern in patterns:
        match = pattern.search(text or "")
        if not match:
            continue
        parsed = parse_tk_bdt_price_to_int(match.group(1))
        if isinstance(parsed, int) and parsed > 0:
            return parsed
    return 0

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
    ram, storage = parse_memory_to_ram_storage(text)
    if ram and storage:
        return f"{ram}/{storage}"
    value = (text or "").lower()
    compact = re.sub(r"\s+", "", value)
    return compact




def parse_memory_to_ram_storage(text: str) -> Tuple[Optional[str], Optional[str]]:
    value = (text or "").lower().replace("＋", "+")
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        return (None, None)

    nums = [int(n) for n in re.findall(r"\d+", value)]
    if len(nums) < 2:
        return (None, None)

    # PriceOye-like format: "256GB - 8GB RAM" => storage first then RAM.
    if "ram" in value and "-" in value:
        left_part, right_part = value.split("-", 1)
        left_nums = [int(n) for n in re.findall(r"\d+", left_part)]
        right_nums = [int(n) for n in re.findall(r"\d+", right_part)]
        if left_nums and right_nums:
            storage = str(left_nums[0])
            ram = str(right_nums[0])
            return (ram, storage)

    # sku_master format and related variants: "8/256", "8GB/256GB", "8GB + 256GB" => RAM first then storage.
    ram = str(nums[0])
    storage = str(nums[1])
    return (ram, storage)



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




def extract_prices_from_body_text_top(body_text: str) -> Tuple[str, str, List[str]]:
    if not body_text:
        return "", "", []

    # Prefer the top product section first.
    top_window = body_text[:4500]
    price_pattern = re.compile(r"Rs\.?\s*[\d,]+", re.I)
    matches = [clean_price(m) for m in price_pattern.findall(top_window)]

    if len(matches) < 2:
        full_matches = [clean_price(m) for m in price_pattern.findall(body_text)]
        if len(full_matches) > len(matches):
            matches = full_matches

    product_price = matches[0] if matches else ""
    original_price = ""
    if len(matches) > 1:
        unique_prices = []
        for item in matches:
            if item not in unique_prices:
                unique_prices.append(item)
        if len(unique_prices) > 1:
            original_price = unique_prices[1]
        else:
            original_price = matches[1]

    return product_price, original_price, matches


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
) -> Dict[str, str]:
    page = browser_context.new_page()
    try:
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
        requested_ram, requested_storage = parse_memory_to_ram_storage(memory)

        parsed_data = extract_price_data(html)
        base_product_price = parsed_data.get("product_price", "")
        base_original_price = parsed_data.get("original_price", "")
        error_message = ""
        selected_button_text_after_click = ""

        if normalized_requested_memory:
            candidates = collect_memory_click_candidates(page)

            matched_candidate: Optional[Dict[str, Any]] = None
            for candidate in candidates:
                candidate_text = candidate.get("text", "")
                candidate_ram, candidate_storage = parse_memory_to_ram_storage(candidate_text)
                if (
                    requested_ram
                    and requested_storage
                    and candidate_ram == requested_ram
                    and candidate_storage == requested_storage
                ):
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
                refreshed_body_text = page.locator("body").inner_text()
                selected_button_texts = collect_memory_click_candidates(page)
                selected_button_text_after_click = ""
                for item in selected_button_texts:
                    classes = (item.get("class_name", "") or "").lower()
                    if any(flag in classes for flag in ["active", "selected", "current", "checked"]):
                        selected_button_text_after_click = item.get("text", "")
                        break
                refreshed_html = page.content()
                refreshed_data = extract_price_data(refreshed_html)
                body_product_price, body_original_price, _ = extract_prices_from_body_text_top(refreshed_body_text)
                price_after_click = body_product_price or refreshed_data.get("product_price", "")
                original_after_click = body_original_price or refreshed_data.get("original_price", "")

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
                        refreshed_body_text = page.locator("body").inner_text()
                        refreshed_html = page.content()
                        refreshed_data = extract_price_data(refreshed_html)
                        body_product_price, body_original_price, _ = extract_prices_from_body_text_top(refreshed_body_text)
                        price_after_click = body_product_price or refreshed_data.get("product_price", "")
                        original_after_click = body_original_price or refreshed_data.get("original_price", "")


                parsed_data["product_price"] = price_after_click or base_product_price
                parsed_data["original_price"] = original_after_click or base_original_price
                if requested_ram and requested_storage:
                    selected_ram, selected_storage = parse_memory_to_ram_storage(selected_button_text_after_click)
                    if (
                        selected_button_text_after_click
                        and (selected_ram != requested_ram or selected_storage != requested_storage)
                    ):
                        error_message = "Selected memory validation uncertain"
                    elif not selected_button_text_after_click:
                        error_message = "Selected memory validation uncertain"

                if (
                    price_after_click == base_product_price
                    and original_after_click == base_original_price
                    and not error_message
                ):
                    error_message = f"Matched memory {memory} but price did not change"
            else:
                error_message = f"Memory clickable element not found for {memory}; fallback default price used"

        stock_status = "unknown"
        out_of_stock_keywords = ["out of stock", "sold out", "unavailable"]
        active_keywords = ["add to cart", "buy now", "available", "in stock"]

        for keyword in out_of_stock_keywords:
            if keyword in body_text_lower:
                stock_status = "out_of_stock"
                break

        if stock_status == "unknown":
            for keyword in active_keywords:
                if keyword in body_text_lower:
                    stock_status = "active"
                    break

        parsed_data["stock_status"] = stock_status

        fallback_product_from_body, fallback_original_from_body, _ = extract_prices_from_body_text_top(body_text)

        if fallback_product_from_body and not parsed_data.get("product_price"):
            parsed_data["product_price"] = fallback_product_from_body
        if fallback_original_from_body and not parsed_data.get("original_price"):
            parsed_data["original_price"] = fallback_original_from_body

        if error_message:
            parsed_data["error_message"] = error_message

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
        page.close()


def crawl_pickaboo_page(browser_context: Any, product_url: str) -> Dict[str, Any]:
    page = browser_context.new_page()
    try:
        page.goto(product_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        raw_body_text = page.locator("body").inner_text()
        body_text = clean_price(raw_body_text)

        attr_values = page.evaluate(
            """() => Array.from(document.querySelectorAll('img'))
                .flatMap((img) => [img.getAttribute('alt') || '', img.getAttribute('title') || ''])
                .filter(Boolean)
            """
        )
        attr_text = clean_price(" ".join([str(v) for v in attr_values])) if isinstance(attr_values, list) else ""
        combined_text = clean_price(f"{body_text} {attr_text}")

        product_price = extract_pickaboo_product_price(page, raw_body_text)
        voucher_amount = extract_pickaboo_voucher_amount(combined_text)

        stock_status = "unknown"
        if re.search(r"(?i)(out of stock|sold out)", body_text):
            stock_status = "out_of_stock"
        elif re.search(r"(?i)(add to cart|buy now)", body_text):
            stock_status = "active"

        if not isinstance(product_price, int):
            return {
                "product_price": "",
                "original_price": "",
                "stock_status": stock_status,
                "voucher_amount": voucher_amount,
                "effective_price": "",
                "error_message": "Product price not parsed",
            }

        original_price = extract_pickaboo_original_price(page, product_price)
        if not isinstance(original_price, int):
            original_price = product_price

        effective_price = max(product_price - voucher_amount, 0)

        # TODO: Add OCR-based PDP banner parsing for voucher extraction from embedded images.
        return {
            "product_price": product_price,
            "original_price": original_price,
            "stock_status": stock_status,
            "voucher_amount": voucher_amount,
            "effective_price": effective_price,
        }
    except PlaywrightTimeoutError:
        return {
            "product_price": "",
            "original_price": "",
            "stock_status": "unknown",
            "voucher_amount": "",
            "effective_price": "",
            "error_message": "Timeout while loading page",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "product_price": "",
            "original_price": "",
            "stock_status": "unknown",
            "voucher_amount": "",
            "effective_price": "",
            "error_message": f"Crawl failed: {exc}",
        }
    finally:
        page.close()

def build_price_daily_row(base: Dict[str, str], crawl_result: Dict[str, Any]) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    platform = str(base.get("platform", "")).strip().lower()

    product_price = parse_price_to_int(crawl_result.get("product_price", ""))
    product_price_valid = isinstance(product_price, int) and product_price > 0
    if not product_price_valid:
        product_price = ""

    original_price = parse_price_to_int(crawl_result.get("original_price", ""))
    if not isinstance(original_price, int):
        original_price = product_price if product_price_valid else ""
    elif original_price == 0 and product_price_valid:
        original_price = product_price

    voucher_amount = parse_price_to_int(crawl_result.get("voucher_amount", ""))
    if not isinstance(voucher_amount, int):
        voucher_amount = 0

    if platform == "priceoye":
        voucher_amount = 0

    effective_price: Any = ""
    if product_price_valid:
        effective_price = max(product_price - voucher_amount, 0)
    error_message = str(crawl_result.get("error_message", "")).strip()
    if not product_price_valid and not error_message:
        error_message = "Product price not parsed"


    row = {
        "crawl_date": now_utc.date().isoformat(),
        "platform": str(base.get("platform", "")).strip(),
        "country": str(base.get("country", "")).strip(),
        "brand": str(base.get("brand", "")).strip(),
        "model": str(base.get("model", "")).strip(),
        "memory": str(base.get("memory", "")).strip(),
        "original_price": original_price,
        "product_price": product_price,
        "stock_status": crawl_result.get("stock_status", ""),
        "voucher_amount": voucher_amount,
        "effective_price": effective_price,
        "product_url": str(base.get("product_url", "")).strip(),
        "crawl_time": now_utc.isoformat(timespec="seconds"),
        "error_message": error_message,
    }
    return row


def ensure_price_daily_header(worksheet: gspread.Worksheet) -> None:
    existing_header = worksheet.row_values(1)
    if existing_header != PRICE_DAILY_COLUMNS:
        worksheet.update("A1:N1", [PRICE_DAILY_COLUMNS])


def main() -> None:
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
        for row in active_rows:
            product_url = str(row.get("product_url", "")).strip()
            platform = str(row.get("platform", "")).strip().lower()

            crawl_result: Dict[str, str]
            if not product_url:
                crawl_result = {
                    "product_price": "",
                    "original_price": "",
                    "stock_status": "unknown",
                    "voucher_amount": "",
                    "effective_price": "",
                    "error_message": "Missing product_url",
                }
            elif platform == "priceoye":
                memory = str(row.get("memory", "")).strip()
                crawl_result = crawl_priceoye_page(
                    context,
                    product_url,
                    memory=memory,
                )
            elif platform == "pickaboo":
                crawl_result = crawl_pickaboo_page(context, product_url)
            else:
                crawl_result = {
                    "product_price": "",
                    "original_price": "",
                    "stock_status": "unknown",
                    "voucher_amount": "",
                    "effective_price": "",
                    "error_message": f"Unsupported platform: {platform}",
                }

            if (
                not crawl_result.get("product_price")
                and not crawl_result.get("original_price")
                and not crawl_result.get("stock_status")
                and not crawl_result.get("error_message")
            ):
                crawl_result["error_message"] = "Price parsing failed"

            output_row = build_price_daily_row(row, crawl_result)
            print(
                f"[SKU] platform={output_row.get('platform', '')} | country={output_row.get('country', '')} | "
                f"brand={output_row.get('brand', '')} | model={output_row.get('model', '')} | "
                f"memory={output_row.get('memory', '')} | product_price={output_row.get('product_price', '')} | "
                f"original_price={output_row.get('original_price', '')} | "
                f"voucher_amount={output_row.get('voucher_amount', '')} | "
                f"effective_price={output_row.get('effective_price', '')} | "
                f"stock_status={output_row.get('stock_status', '')} | "
                f"error_message={output_row.get('error_message', '')}"
            )
            output_rows.append(output_row)

        browser.close()

    df = pd.DataFrame(output_rows, columns=PRICE_DAILY_COLUMNS).fillna("")
    if not df.empty:
        price_ws.append_rows(df.values.tolist(), value_input_option="RAW")
    print(f"Appended {len(df)} row(s) to {PRICE_DAILY_TAB}.")


if __name__ == "__main__":
    main()

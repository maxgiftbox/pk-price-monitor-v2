import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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


def crawl_priceoye_page(browser_context: Any, product_url: str) -> Dict[str, str]:
    page = browser_context.new_page()
    try:
        page.goto(product_url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)

        body_text = page.locator("body").inner_text()
        body_text_lower = body_text.lower()
        print(f"[DEBUG][PriceOye] Crawling URL: {product_url}")
        print(f"[DEBUG][PriceOye] Body text (first 3000 chars):\n{body_text[:3000]}")

        html = page.content()
        parsed_data = extract_price_data(html)

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

        print(f"[DEBUG][PriceOye] Final parsed product_price: {parsed_data.get('product_price', '')}")
        print(f"[DEBUG][PriceOye] Final parsed original_price: {parsed_data.get('original_price', '')}")
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
                crawl_result = crawl_priceoye_page(context, product_url)
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

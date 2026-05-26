# Mob Price Monitor

A Python project that crawls mobile prices from active SKUs in Google Sheets and provides a Streamlit dashboard for analysis.

## Google Sheet Structure

Sheet name: **Mob Price Monitor**

### `sku_master` columns
- `platform`
- `brand`
- `model`
- `memory`
- `product_url`
- `status`

### `price_daily` columns
- `crawl_date`
- `platform`
- `brand`
- `model`
- `memory`
- `original_price`
- `product_price`
- `stock_status`
- `product_url`
- `crawl_time`
- `error_message`

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Install Playwright Chromium:
   ```bash
   playwright install chromium
   ```
4. Set Google service account JSON in environment variable:
   ```bash
   export GOOGLE_SERVICE_ACCOUNT_JSON='{"type":"service_account", ... }'
   ```

## Run Scraper

```bash
python scraper.py
```

The scraper:
- Authenticates with Google Sheets using `GOOGLE_SERVICE_ACCOUNT_JSON`
- Reads `sku_master`
- Processes only rows where `status=active`
- Crawls PriceOye URLs in headless Chromium
- Appends rows into `price_daily`
- Writes errors into `error_message` when parsing/crawling fails

## Run Dashboard

```bash
streamlit run app.py
```

Features:
- Filters by platform, brand, model, memory, and date range
- Latest price table
- Price trend chart
- CSV download for filtered data

## GitHub Actions

Workflow file: `.github/workflows/crawl.yml`

- Name: **Crawl Price Data**
- Triggers: `push`, `workflow_dispatch`
- Python: `3.11`
- Installs dependencies and Playwright Chromium
- Runs `python scraper.py` with `GOOGLE_SERVICE_ACCOUNT_JSON` from GitHub Secrets

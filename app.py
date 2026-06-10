import html
import json
import os
import re
from datetime import date, datetime
import gspread
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from google.oauth2.service_account import Credentials

SHEET_NAME = "Mob Price Monitor"
PRICE_DAILY_TAB = "price_daily"
SKU_MASTER_TAB = "sku_master"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
PRICE_COLUMNS = ["original_price", "product_price", "voucher_amount", "effective_price"]
SKU_COLUMNS = ["country", "brand", "model", "memory"]
DASHBOARD_SKU_IDENTITY_COLUMNS = [
    "join_date",
    "__platform_key",
    "join_country",
    "join_brand",
    "join_model",
    "join_memory",
]
DASHBOARD_MATCH_IDENTITY_COLUMNS = [
    "join_date",
    "join_country",
    "join_brand",
    "join_model",
    "join_memory",
]
GAP_SKU_IDENTITY_COLUMNS = ["crawl_date", "Country", "Brand", "SKU", "Memory"]
SKU_MASTER_PRIMARY_JOIN_COLUMNS = [
    "norm_platform",
    "norm_country",
    "norm_brand",
    "norm_model",
    "norm_memory",
]
SKU_MASTER_FALLBACK_JOIN_COLUMNS = ["norm_platform", "norm_country", "normalized_url"]
SKU_MASTER_MODEL_FALLBACK_JOIN_COLUMNS = [
    "norm_platform",
    "norm_country",
    "norm_brand",
    "norm_model",
]
SKU_MASTER_STANDARD_COLUMNS = ["standard_model", "standard_memory"]
COMPETITOR_PLATFORMS = ["PriceOye", "Pickaboo"]
DARAZ_PLATFORM = "Daraz"
TABLE_COLUMNS = [
    "crawl_time",
    "country",
    "brand",
    "model",
    "memory",
    "Daraz Effective Price",
    "Daraz Stock Status",
    "Competitor Platform",
    "Competitor Effective Price",
    "LC Stock Status",
]
GAP_COLUMNS = [
    "crawl_time",
    "country",
    "brand",
    "model",
    "memory",
    "Daraz Effective Price",
    "Daraz Stock Status",
    "Competitor Platform",
    "Competitor Effective Price",
    "LC Stock Status",
    "Gap Amount",
    "Gap %",
    "Alert",
]
RAW_GAP_COLUMNS = [
    "crawl_date",
    "Country",
    "Brand",
    "SKU",
    "Memory",
    "Daraz Price",
    "Daraz Stock Status",
    "Competitor Platform",
    "Competitor Price",
    "LC Stock Status",
    "Gap Amount",
    "Gap %",
    "Alert",
]
INTERNAL_GAP_URL_COLUMNS = ["daraz_product_url", "competitor_product_url"]
INTERNAL_TABLE_COLUMNS = ["product_url", "daraz_product_url", "competitor_product_url"]
TABLE_HEADER_LABELS = {
    "crawl_time": "Date",
    "crawl_date": "Date",
    "Daraz Effective Price": "Drz Price",
    "Daraz Price": "Drz Price",
    "Daraz Stock Status": "Stock",
    "Competitor Platform": "LC",
    "Competitor Effective Price": "LC Price",
    "Competitor Price": "LC Price",
    "LC Stock Status": "LC Stock",
    "Gap Amount": "Gap",
}
LINKABLE_PLATFORM_COLUMNS = {"Competitor Platform", "LC"}
PLATFORM_DISPLAY_NAMES = {
    "daraz": "daraz",
    "priceoye": "priceoye",
    "pickaboo": "pickaboo",
}
PLATFORM_COLORS = {
    "daraz": "#9b7bff",
    "priceoye": "#5b8def",
    "pickaboo": "#34c7a0",
}
PAGE_SIZE = 100
SECTION_ANCHORS = {
    "Latest Price Table": "price-table",
    "Price Gap Analysis": "gap-analysis",
    "Price Trend Chart": "trend-chart",
}

ALERT_FILTERS = {
    "Red": {"key": "gap_alert_filter_red", "label": "🔴 Red"},
    "Orange": {"key": "gap_alert_filter_orange", "label": "🟠 Orange"},
    "Green": {"key": "gap_alert_filter_green", "label": "🟢 Green"},
}


def get_config_value(name: str) -> str:
    """Read a configuration value from Streamlit secrets or the environment."""
    value = ""
    if hasattr(st, "secrets"):
        try:
            value = str(st.secrets.get(name, "") or "").strip()
        except Exception:  # noqa: BLE001 - missing local Streamlit secrets should fall back to env vars.
            value = ""
    return value or os.getenv(name, "").strip()


@st.cache_resource
def get_sheet_client() -> gspread.Client:
    raw_json = get_config_value("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw_json:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set.")

    service_account_info = json.loads(raw_json)
    credentials = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
    return gspread.authorize(credentials)


@st.cache_data(ttl=300)
def load_price_data() -> pd.DataFrame:
    client = get_sheet_client()
    sheet = client.open(SHEET_NAME)
    worksheet = sheet.worksheet(PRICE_DAILY_TAB)
    records = worksheet.get_all_records()
    df = pd.DataFrame(records)

    if df.empty:
        return df

    df = prepare_price_daily_df(df)
    sku_master_df = load_sku_master_df(sheet)
    return enrich_with_sku_master(df, sku_master_df)



def normalize_url(url: object) -> str:
    """Normalize product URLs for sku_master enrichment joins only."""
    if pd.isna(url):
        return ""

    normalized = str(url).strip().casefold()
    if not normalized:
        return ""

    normalized = normalized.split("?", 1)[0].split("#", 1)[0].strip()
    normalized = re.sub(r"^https?://", "", normalized)
    normalized = re.sub(r"^www\.", "", normalized)
    normalized = normalized.rstrip("/")
    return normalized


def normalize_url_series(series: pd.Series) -> pd.Series:
    return series.apply(normalize_url)


def normalize_mapping_text(value: object) -> str:
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value).strip()).casefold()


def normalize_mapping_text_series(series: pd.Series) -> pd.Series:
    return series.apply(normalize_mapping_text)


def add_standard_mapping_fields(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    if "product_url" in working.columns:
        working["normalized_url"] = normalize_url_series(working["product_url"])
    elif "normalized_url" not in working.columns:
        working["normalized_url"] = ""

    for source_col, normalized_col in [
        ("platform", "norm_platform"),
        ("country", "norm_country"),
        ("brand", "norm_brand"),
        ("model", "norm_model"),
    ]:
        source = working[source_col] if source_col in working.columns else pd.Series("", index=working.index)
        working[normalized_col] = normalize_mapping_text_series(source)

    memory_source = working["memory"] if "memory" in working.columns else pd.Series("", index=working.index)
    working["norm_memory"] = normalize_mapping_text_series(normalize_memory_series(memory_source))
    return working

def prepare_price_daily_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    for col in PRICE_COLUMNS:
        if col in df.columns:
            df[col] = to_numeric_price(df[col])

    for col in ["platform", "country", "brand", "model", "memory", "product_url", "stock_status"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

    df = add_standard_mapping_fields(df)

    if "crawl_date" in df.columns:
        df["crawl_date"] = pd.to_datetime(df["crawl_date"], errors="coerce").dt.date

    if "crawl_date" in df.columns and "crawl_time" in df.columns:
        combined_crawl_time = df["crawl_date"].astype(str) + " " + df["crawl_time"].astype(str)
        df["crawl_datetime"] = pd.to_datetime(combined_crawl_time, errors="coerce")
        df["crawl_datetime"] = df["crawl_datetime"].fillna(
            pd.to_datetime(df["crawl_time"], errors="coerce")
        )
    elif "crawl_time" in df.columns:
        df["crawl_datetime"] = pd.to_datetime(df["crawl_time"], errors="coerce")
    elif "crawl_date" in df.columns:
        df["crawl_datetime"] = pd.to_datetime(df["crawl_date"], errors="coerce")
    else:
        df["crawl_datetime"] = pd.NaT

    return df


def load_sku_master_df(sheet: object) -> pd.DataFrame:
    try:
        worksheet = sheet.worksheet(SKU_MASTER_TAB)
        records = worksheet.get_all_records()
    except Exception:  # noqa: BLE001 - missing sku_master should not block the dashboard.
        return pd.DataFrame()

    sku_master_df = pd.DataFrame(records)
    if sku_master_df.empty:
        return sku_master_df

    sku_master_df.columns = [str(col).strip() for col in sku_master_df.columns]
    sku_master_text_columns = set(
        ["platform", "country", "brand", "model", "memory", "product_url"]
        + SKU_MASTER_PRIMARY_JOIN_COLUMNS
        + SKU_MASTER_FALLBACK_JOIN_COLUMNS
        + SKU_MASTER_MODEL_FALLBACK_JOIN_COLUMNS
        + SKU_MASTER_STANDARD_COLUMNS
    )
    for col in sku_master_text_columns:
        if col in sku_master_df.columns:
            sku_master_df[col] = sku_master_df[col].fillna("").astype(str).str.strip()

    sku_master_df = add_standard_mapping_fields(sku_master_df)

    return sku_master_df


def enrich_with_sku_master(df: pd.DataFrame, sku_master_df: pd.DataFrame) -> pd.DataFrame:
    enriched = add_standard_mapping_fields(df)
    enriched["raw_model"] = (
        enriched["model"].fillna("").astype(str).str.strip()
        if "model" in enriched.columns
        else pd.Series("", index=enriched.index)
    )
    enriched["raw_memory"] = (
        enriched["memory"].fillna("").astype(str).str.strip()
        if "memory" in enriched.columns
        else pd.Series("", index=enriched.index)
    )
    enriched["standard_model"] = ""
    enriched["standard_memory"] = ""

    if not sku_master_df.empty:
        sku_master_df = add_standard_mapping_fields(sku_master_df)
        enriched = apply_sku_master_match(
            enriched,
            sku_master_df,
            SKU_MASTER_PRIMARY_JOIN_COLUMNS,
        )

        rows_missing_primary_match = missing_standard_mask(enriched)
        if rows_missing_primary_match.any():
            url_unique_sku_master_df = filter_unique_sku_master_matches(
                sku_master_df,
                SKU_MASTER_FALLBACK_JOIN_COLUMNS,
            )
            fallback_matches = apply_sku_master_match(
                enriched.loc[rows_missing_primary_match],
                url_unique_sku_master_df,
                SKU_MASTER_FALLBACK_JOIN_COLUMNS,
            )
            enriched.loc[rows_missing_primary_match, SKU_MASTER_STANDARD_COLUMNS] = fallback_matches[
                SKU_MASTER_STANDARD_COLUMNS
            ].to_numpy()

    enriched["dashboard_model"] = coalesce_text(enriched["standard_model"], enriched["raw_model"])
    enriched["dashboard_memory"] = normalize_memory_series(
        coalesce_text(enriched["standard_memory"], enriched["raw_memory"])
    )
    enriched["model"] = enriched["dashboard_model"]
    enriched["memory"] = enriched["dashboard_memory"]
    return enriched


def filter_unique_sku_master_matches(
    sku_master_df: pd.DataFrame,
    join_keys: list[str],
) -> pd.DataFrame:
    if not join_keys or not set(join_keys).issubset(sku_master_df.columns):
        return sku_master_df.iloc[0:0].copy()

    working = sku_master_df.copy()
    normalized_key_cols = add_normalized_join_keys(working, join_keys)
    valid_key_mask = working[normalized_key_cols].ne("").all(axis=1)
    if not valid_key_mask.any():
        return working.iloc[0:0].drop(columns=normalized_key_cols, errors="ignore")

    valid_working = working.loc[valid_key_mask].copy()
    key_row_counts = valid_working.groupby(
        normalized_key_cols,
        dropna=False,
    )[normalized_key_cols[0]].transform("size")
    unique_matches = valid_working.loc[key_row_counts.eq(1)].copy()
    return unique_matches.drop(columns=normalized_key_cols, errors="ignore")


def apply_sku_master_match(
    df: pd.DataFrame,
    sku_master_df: pd.DataFrame,
    join_keys: list[str],
) -> pd.DataFrame:
    required_sku_master_cols = set(join_keys + SKU_MASTER_STANDARD_COLUMNS)
    if not join_keys or not required_sku_master_cols.issubset(sku_master_df.columns):
        return df
    if not set(join_keys).issubset(df.columns):
        return df

    left = df.copy()
    right = sku_master_df[join_keys + SKU_MASTER_STANDARD_COLUMNS].copy()
    left_key_cols = add_normalized_join_keys(left, join_keys)
    right_key_cols = add_normalized_join_keys(right, join_keys)
    right = right[right[right_key_cols].ne("").all(axis=1)]
    right = right.drop_duplicates(right_key_cols, keep="first")

    if right.empty:
        return left.drop(columns=left_key_cols, errors="ignore")

    merged = left.merge(
        right[right_key_cols + SKU_MASTER_STANDARD_COLUMNS],
        left_on=left_key_cols,
        right_on=right_key_cols,
        how="left",
        suffixes=("", "_sku_master"),
    )

    for col in SKU_MASTER_STANDARD_COLUMNS:
        matched_col = f"{col}_sku_master"
        if matched_col in merged.columns:
            merged[col] = coalesce_text(merged[matched_col], merged[col])
            merged = merged.drop(columns=[matched_col])

    return merged.drop(columns=left_key_cols + right_key_cols, errors="ignore")



def apply_unique_model_sku_master_match(
    df: pd.DataFrame,
    sku_master_df: pd.DataFrame,
) -> pd.DataFrame:
    join_keys = SKU_MASTER_MODEL_FALLBACK_JOIN_COLUMNS
    required_sku_master_cols = set(join_keys + ["norm_memory"] + SKU_MASTER_STANDARD_COLUMNS)
    if not required_sku_master_cols.issubset(sku_master_df.columns):
        return df
    if not set(join_keys + ["norm_memory"]).issubset(df.columns):
        return df

    left = df.copy()
    right = sku_master_df[list(required_sku_master_cols)].copy()
    right = right[right[join_keys].ne("").all(axis=1)]
    right = right[right["standard_model"].fillna("").astype(str).str.strip().ne("")]
    if right.empty:
        return left

    unique_models = []
    for keys, group in right.groupby(join_keys, dropna=False):
        standard_models = unique_nonblank(group["standard_model"])
        if len(standard_models) != 1:
            continue

        standard_memories = unique_nonblank(group["standard_memory"])
        row = dict(zip(join_keys, keys if isinstance(keys, tuple) else (keys,)))
        row["standard_model_model_fallback"] = standard_models[0]
        row["standard_memory_unique_model_fallback"] = (
            standard_memories[0] if len(standard_memories) == 1 else ""
        )
        unique_models.append(row)

    if not unique_models:
        return left

    unique_model_df = pd.DataFrame(unique_models)
    matched = left.merge(unique_model_df, on=join_keys, how="left")
    matched["standard_model"] = coalesce_text(
        matched["standard_model_model_fallback"], matched["standard_model"]
    )

    memory_match_cols = join_keys + ["norm_memory"]
    memory_matches = right[right["norm_memory"].fillna("").astype(str).str.strip().ne("")].copy()
    memory_matches = memory_matches[memory_matches["standard_memory"].fillna("").astype(str).str.strip().ne("")]
    exact_memory_matches = []
    for keys, group in memory_matches.groupby(memory_match_cols, dropna=False):
        standard_memories = unique_nonblank(group["standard_memory"])
        if len(standard_memories) != 1:
            continue
        row = dict(zip(memory_match_cols, keys if isinstance(keys, tuple) else (keys,)))
        row["standard_memory_memory_fallback"] = standard_memories[0]
        exact_memory_matches.append(row)

    if exact_memory_matches:
        matched = matched.merge(pd.DataFrame(exact_memory_matches), on=memory_match_cols, how="left")
    else:
        matched["standard_memory_memory_fallback"] = ""

    matched["standard_memory"] = coalesce_text(
        matched["standard_memory_memory_fallback"], matched["standard_memory"]
    )
    matched["standard_memory"] = coalesce_text(
        matched["standard_memory_unique_model_fallback"], matched["standard_memory"]
    )
    return matched.drop(
        columns=[
            "standard_model_model_fallback",
            "standard_memory_memory_fallback",
            "standard_memory_unique_model_fallback",
        ],
        errors="ignore",
    )


def unique_nonblank(series: pd.Series) -> list[str]:
    values = series.fillna("").astype(str).str.strip()
    return sorted(values[values.ne("")].unique().tolist())

def add_normalized_join_keys(df: pd.DataFrame, join_keys: list[str]) -> list[str]:
    normalized_key_cols = []
    for key in join_keys:
        normalized_col = f"__join_{key}"
        source = df[key]
        if key == "memory":
            source = normalize_memory_series(source)
        df[normalized_col] = source.fillna("").astype(str).str.strip().str.casefold()
        normalized_key_cols.append(normalized_col)
    return normalized_key_cols


def normalize_memory(value: object) -> str:
    if pd.isna(value):
        return ""

    memory = str(value).strip()
    if not memory:
        return ""
    if memory.casefold() in {"n/a", "na", "none", "null"}:
        return "N/A"

    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(tb|gb)?", memory, flags=re.IGNORECASE)
    if not matches:
        return memory

    normalized_parts = []
    for number_text, unit in matches:
        number = float(number_text)
        if unit.casefold() == "tb":
            number *= 1024
        if number.is_integer():
            normalized_parts.append(str(int(number)))
        else:
            normalized_parts.append(str(number).rstrip("0").rstrip("."))

    return "/".join(normalized_parts)


def normalize_memory_series(series: pd.Series) -> pd.Series:
    return series.apply(normalize_memory)


def missing_standard_mask(df: pd.DataFrame) -> pd.Series:
    return df["standard_model"].fillna("").astype(str).str.strip().eq("") | df[
        "standard_memory"
    ].fillna("").astype(str).str.strip().eq("")


def is_unique_sku_master_key(sku_master_df: pd.DataFrame, join_keys: list[str]) -> bool:
    if not join_keys or not set(join_keys).issubset(sku_master_df.columns):
        return False

    normalized = sku_master_df.copy()
    normalized_key_cols = add_normalized_join_keys(normalized, join_keys)
    normalized = normalized[normalized[normalized_key_cols].ne("").all(axis=1)]
    return not normalized.duplicated(normalized_key_cols, keep=False).any()


def normalize_join_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.lower()


def add_dashboard_join_fields(df: pd.DataFrame) -> pd.DataFrame:
    working = df.copy()
    if "crawl_date" in working.columns:
        working["join_date"] = pd.to_datetime(working["crawl_date"], errors="coerce").dt.date
    else:
        working["join_date"] = pd.NaT

    for source_col, join_col in [
        ("country", "join_country"),
        ("brand", "join_brand"),
    ]:
        working[join_col] = (
            normalize_join_text(working[source_col]) if source_col in working.columns else ""
        )

    model_source = working.get(
        "dashboard_model",
        working.get("model", pd.Series("", index=working.index)),
    )
    memory_source = working.get(
        "dashboard_memory",
        working.get("memory", pd.Series("", index=working.index)),
    )
    working["dashboard_model"] = model_source.fillna("").astype(str).str.strip()
    working["dashboard_memory"] = normalize_memory_series(memory_source)
    working["model"] = working["dashboard_model"]
    working["memory"] = working["dashboard_memory"]
    working["join_model"] = normalize_join_text(working["dashboard_model"])
    working["join_memory"] = normalize_join_text(working["dashboard_memory"])
    return working


def coalesce_text(primary: pd.Series, fallback: pd.Series) -> pd.Series:
    primary_text = primary.fillna("").astype(str).str.strip()
    fallback_text = fallback.fillna("").astype(str).str.strip()
    return primary_text.where(primary_text.ne(""), fallback_text)


def to_numeric_price(series: pd.Series) -> pd.Series:
    cleaned = (
        series.fillna("")
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.replace(r"[^0-9.\-]", "", regex=True)
        .replace("", pd.NA)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def format_date(value: object) -> object:
    try:
        if pd.isna(value):
            return value
        if isinstance(value, date):
            return value.strftime("%Y-%m-%d")
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            return value
        return parsed.strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001 - display formatting should never crash the dashboard.
        return value


def format_price(value: object) -> object:
    try:
        if pd.isna(value):
            return value
        numeric_value = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric_value):
            return value
        return f"{numeric_value:,.0f}"
    except Exception:  # noqa: BLE001 - display formatting should never crash the dashboard.
        return value


def format_gap_pct(value: object) -> object:
    try:
        if pd.isna(value):
            return value
        numeric_value = pd.to_numeric(value, errors="coerce")
        if pd.isna(numeric_value):
            return value
        return f"{numeric_value * 100:.2f}%"
    except Exception:  # noqa: BLE001 - display formatting should never crash the dashboard.
        return value


def normalized_platform(value: object) -> str:
    if pd.isna(value):
        return ""
    platform_key = str(value).strip().casefold()
    return PLATFORM_DISPLAY_NAMES.get(platform_key, platform_key)


def platform_toggle_label(platform: str) -> str:
    return {
        "daraz": "Daraz",
        "priceoye": "Priceoye",
        "pickaboo": "Pickaboo",
    }.get(platform, platform.title())


def render_platform_toggles(available_platforms: list[str]) -> list[str]:
    state_key = "trend_chart_platforms"
    stored_platforms = st.session_state.get(state_key, available_platforms)
    if not isinstance(stored_platforms, list):
        stored_platforms = available_platforms

    selected_platforms = [platform for platform in available_platforms if platform in stored_platforms]
    if not selected_platforms:
        selected_platforms = available_platforms.copy()
    st.session_state[state_key] = selected_platforms

    st.markdown("<div class='platform-toggle-control'></div>", unsafe_allow_html=True)
    toggle_cols = st.columns(len(available_platforms))
    for platform, col in zip(available_platforms, toggle_cols, strict=False):
        active_class = " active" if platform in selected_platforms else ""
        col.markdown(f"<div class='platform-toggle-btn{active_class}'></div>", unsafe_allow_html=True)
        if col.button(
            platform_toggle_label(platform),
            key=f"trend_platform_toggle_{platform}",
            use_container_width=True,
        ):
            updated_platforms = st.session_state[state_key].copy()
            if platform in updated_platforms:
                if len(updated_platforms) > 1:
                    updated_platforms.remove(platform)
            else:
                updated_platforms.append(platform)
                updated_platforms = [item for item in available_platforms if item in updated_platforms]
            st.session_state[state_key] = updated_platforms
            st.rerun()

    return st.session_state[state_key]


def require_password() -> bool:
    password = get_config_value("STREAMLIT_DASHBOARD_PASSWORD")
    if not password:
        st.warning(
            "STREAMLIT_DASHBOARD_PASSWORD is not set in Streamlit secrets or the environment. "
            "Dashboard access is open."
        )
        return True

    if st.session_state.get("authenticated"):
        return True

    st.markdown("### Private dashboard")
    entered_password = st.text_input("Password", type="password")
    if st.button("Unlock", type="primary"):
        if entered_password == password:
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Incorrect password.")

    return False


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --pm-ink: #182033;
            --pm-heading: #0f172a;
            --pm-muted: #667085;
            --pm-soft: #eef4ff;
            --pm-card: rgba(255, 255, 255, 0.92);
            --pm-card-solid: #ffffff;
            --pm-sidebar: rgba(255, 255, 255, 0.62);
            --pm-border: rgba(148, 163, 184, 0.16);
            --pm-table-header: #f4f7fb;
            --pm-table-header-text: #5c6678;
            --pm-blue: #5b8def;
            --pm-purple: #9b7bff;
            --pm-green: #34c7a0;
            --pm-shadow: 0 28px 80px rgba(91, 119, 190, 0.18);
            --pm-card-shadow: 0 18px 45px rgba(79, 96, 140, 0.11);
            --pm-card-shadow-hover: 0 24px 70px rgba(79, 96, 140, 0.16);
            --pm-radius: 24px;
            font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", sans-serif;
        }

        #MainMenu, header[data-testid="stHeader"], footer, [data-testid="stToolbar"] {
            visibility: hidden;
            height: 0;
        }

        html, body, .stApp, [data-testid="stAppViewContainer"] {
            min-height: 100%;
            font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Segoe UI", sans-serif;
        }

        html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewContainer"] > .main {
            overflow-y: auto;
            overflow-x: visible;
        }

        .stApp {
            color: var(--pm-ink);
            background:
                radial-gradient(circle at 4% 8%, rgba(208, 228, 255, 0.95) 0, rgba(208, 228, 255, 0.38) 27%, transparent 48%),
                radial-gradient(circle at 88% 4%, rgba(222, 210, 255, 0.85) 0, rgba(222, 210, 255, 0.34) 29%, transparent 50%),
                radial-gradient(circle at 72% 88%, rgba(198, 244, 233, 0.70) 0, rgba(198, 244, 233, 0.26) 28%, transparent 50%),
                linear-gradient(135deg, #fbfdff 0%, #f4f8ff 36%, #f9f5ff 72%, #ffffff 100%);
        }

        [data-testid="stAppViewContainer"] > .main {
            position: relative;
        }

        .main .block-container {
            max-width: 100%;
            padding-left: 32px;
            padding-right: 32px;
            padding-top: 20px;
            padding-bottom: 32px;
        }

        .block-container {
            min-height: auto;
            margin: 0 auto;
            border: 0;
            background: transparent;
            box-shadow: none;
        }

        .main [data-testid="stVerticalBlock"] {
            gap: 0.75rem;
        }

        h1, h2, h3, p { font-family: inherit; }
        h1, h2, h3 { color: var(--pm-heading); letter-spacing: -0.045em; }
        h2, h3, .stSubheader { font-weight: 760; }
        hr { display: none; }

        section[data-testid="stSidebar"] {
            width: 292px !important;
            background: transparent;
            padding: 0 0 14px 14px;
            overflow-y: auto;
        }

        section[data-testid="stSidebar"] > div {
            margin: 0;
            padding: 10px 14px 16px;
            width: 268px;
            min-height: calc(100vh - 24px);
            border-radius: 32px;
            border: 1px solid rgba(255, 255, 255, 0.72);
            background:
                linear-gradient(180deg, rgba(255, 255, 255, 0.76), rgba(255, 255, 255, 0.50)),
                radial-gradient(circle at 24% 0%, rgba(157, 188, 255, 0.30), transparent 42%),
                radial-gradient(circle at 92% 18%, rgba(180, 152, 255, 0.22), transparent 38%);
            box-shadow: 0 24px 70px rgba(91, 119, 190, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(30px) saturate(1.35);
            -webkit-backdrop-filter: blur(30px) saturate(1.35);
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
            padding-top: 0;
            overflow-y: auto;
        }
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span {
            color: #344054 !important;
        }

        .pm-sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.8rem;
            margin: 0 0 24px;
            padding: 0 0.25rem;
        }
        .pm-logo-orb {
            width: 38px;
            height: 38px;
            border-radius: 14px;
            background: linear-gradient(135deg, #64a7ff 0%, #8d7bff 58%, #c8b6ff 100%);
            box-shadow: 0 14px 32px rgba(111, 124, 255, 0.32), inset 0 1px 10px rgba(255, 255, 255, 0.58);
        }
        .pm-brand-title { font-size: 1.05rem; font-weight: 780; letter-spacing: -0.035em; color: #111827; }
        .sidebar-nav {
            display: flex;
            flex-direction: column;
            gap: 10px;
            margin: 0 0 20px 0;
        }
        .sidebar-nav-item {
            display: block;
            padding: 10px 18px;
            border-radius: 28px;
            text-decoration: none;
            font-weight: 700;
            color: #5f6b80;
            transition: all 0.2s ease;
        }
        .sidebar-nav-item:hover {
            background: rgba(255, 255, 255, 0.72);
            color: #172033;
            box-shadow: 0 16px 40px rgba(111, 143, 190, 0.18);
        }
        .pm-filter-title { color: #344054; font-size: 0.76rem; font-weight: 800; letter-spacing: 0.13em; text-transform: uppercase; margin: 20px 0 0.2rem; }
        .pm-filter-caption { color: #7a8699; font-size: 0.8rem; line-height: 1.4; margin-bottom: 0.7rem; }
        section[data-testid="stSidebar"] .stButton { margin-bottom: 20px; }
        section[data-testid="stSidebar"] .stButton button { min-height: 40px; }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:has(.stMultiSelect),
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:has(.stDateInput) {
            margin: 0.42rem 0;
            padding: 0.62rem 0.68rem 0.72rem;
            border: 0;
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.58);
            box-shadow: 0 10px 26px rgba(91, 119, 190, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.82);
        }
        /* Selector styling is intentionally handled in the final CSS block at the end of this style tag. */

        .platform-toggle-control {
            margin: 8px 0 20px 0;
        }

        [data-testid="stHorizontalBlock"]:has(.platform-toggle-control) {
            gap: 10px !important;
            align-items: center !important;
            margin: 8px 0 20px 0 !important;
        }

        [data-testid="stHorizontalBlock"]:has(.platform-toggle-control) [data-testid="column"] {
            flex: 0 0 auto !important;
            min-width: 112px !important;
        }

        [data-testid="column"]:has(.platform-toggle-btn) .stButton button {
            border-radius: 999px !important;
            padding: 10px 18px !important;
            min-height: 44px !important;
            font-weight: 700 !important;
            border: 1px solid rgba(148,163,184,0.28) !important;
            background: #ffffff !important;
            color: #1f2937 !important;
            box-shadow: 0 10px 26px rgba(111,143,190,0.10) !important;
        }

        [data-testid="column"]:has(.platform-toggle-btn.active) .stButton button {
            background: #eef2f7 !important;
            border-color: rgba(148,163,184,0.42) !important;
            color: #1f2937 !important;
            font-weight: 800 !important;
        }

        [data-testid="stSelectbox"] div[data-baseweb="select"]:has([aria-disabled="true"]),
        [data-testid="stSelectbox"] div[data-baseweb="select"]:has(input:disabled),
        [data-testid="stMultiSelect"] div[data-baseweb="select"]:has([aria-disabled="true"]),
        [data-testid="stMultiSelect"] div[data-baseweb="select"]:has(input:disabled) {
            opacity: 0.62;
        }
        div[data-baseweb="popover"] div[data-baseweb="menu"],
        div[data-baseweb="popover"] ul[role="listbox"],
        div[data-baseweb="popover"] [role="listbox"] {
            background: #FFFFFF !important;
            color: #111827 !important;
            border-radius: 16px !important;
            border: 1px solid #E5E7EB !important;
            box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12) !important;
            overflow: hidden !important;
        }
        div[data-baseweb="popover"] [role="listbox"] *,
        div[data-baseweb="popover"] div[data-baseweb="menu"] * {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
        }
        div[data-baseweb="popover"] [role="option"],
        div[data-baseweb="popover"] li[role="option"] {
            color: #111827 !important;
            background: #FFFFFF !important;
            font-weight: 600 !important;
        }
        div[data-baseweb="popover"] [role="option"]:hover,
        div[data-baseweb="popover"] li[role="option"]:hover,
        div[data-baseweb="popover"] [role="option"][aria-selected="true"] {
            background: #EEF2FF !important;
            color: #111827 !important;
        }

        section[data-testid="stSidebar"] .stDateInput [data-baseweb="input"],
        section[data-testid="stSidebar"] .stDateInput [data-baseweb="input"] > div,
        section[data-testid="stSidebar"] .stDateInput input {
            background: #FFFFFF !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            border-color: #DDD6FE !important;
            border-radius: 16px !important;
        }
        div[data-baseweb="popover"]:has([data-baseweb="calendar"]),
        div[data-baseweb="popover"]:has([role="grid"]) {
            background: transparent !important;
            box-shadow: none !important;
        }
        div[data-baseweb="popover"] [data-baseweb="calendar"],
        div[data-baseweb="popover"] [data-baseweb="calendar"] > div,
        div[data-baseweb="popover"] div:has(> [role="grid"]) {
            background: #FFFFFF !important;
            color: #111827 !important;
            border: 1px solid #E5E7EB !important;
            border-radius: 20px !important;
            box-shadow: 0 18px 48px rgba(15, 23, 42, 0.12) !important;
            overflow: hidden !important;
        }
        div[data-baseweb="popover"] [data-baseweb="calendar"] *,
        div[data-baseweb="popover"] [role="grid"] *,
        div[data-baseweb="popover"] [role="dialog"]:has([role="grid"]) * {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
        }
        div[data-baseweb="popover"] [data-baseweb="calendar"] header,
        div[data-baseweb="popover"] [data-baseweb="calendar"] [data-baseweb="calendar-header"],
        div[data-baseweb="popover"] [role="dialog"]:has([role="grid"]) header {
            background: #F8FAFC !important;
            color: #374151 !important;
            -webkit-text-fill-color: #374151 !important;
            border-bottom: 1px solid #E5E7EB !important;
        }
        div[data-baseweb="popover"] [role="columnheader"],
        div[data-baseweb="popover"] [role="grid"] abbr,
        div[data-baseweb="popover"] [role="grid"] th {
            color: #6B7280 !important;
            -webkit-text-fill-color: #6B7280 !important;
            background: #FFFFFF !important;
        }
        div[data-baseweb="popover"] [role="gridcell"],
        div[data-baseweb="popover"] [role="gridcell"] button,
        div[data-baseweb="popover"] [role="grid"] td,
        div[data-baseweb="popover"] [role="grid"] button {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            background: transparent !important;
            border-radius: 999px !important;
        }
        div[data-baseweb="popover"] [role="gridcell"]:hover,
        div[data-baseweb="popover"] [role="gridcell"] button:hover,
        div[data-baseweb="popover"] [role="grid"] td:hover,
        div[data-baseweb="popover"] [role="grid"] button:hover {
            background: #EEF2FF !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
        }
        div[data-baseweb="popover"] [role="gridcell"][aria-selected="true"],
        div[data-baseweb="popover"] [role="gridcell"][aria-selected="true"] button,
        div[data-baseweb="popover"] [role="grid"] [aria-selected="true"],
        div[data-baseweb="popover"] [role="grid"] [aria-pressed="true"] {
            background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            border-radius: 999px !important;
        }
        div[data-baseweb="popover"] [data-baseweb="calendar"] input,
        div[data-baseweb="popover"] [data-baseweb="calendar"] [data-baseweb="input"],
        div[data-baseweb="popover"] [role="dialog"]:has([role="grid"]) input {
            background: #FFFFFF !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            border: 1px solid #DDD6FE !important;
            border-radius: 16px !important;
        }

        .pm-topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1.25rem;
            margin-bottom: 24px;
        }
        .pm-search-pill {
            width: min(520px, 100%);
            min-height: 48px;
            display: flex;
            align-items: center;
            gap: 0.78rem;
            padding: 0 1.12rem;
            border-radius: 999px;
            border: 1px solid rgba(255, 255, 255, 0.82);
            background: rgba(255, 255, 255, 0.70);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.85), 0 12px 30px rgba(91, 119, 190, 0.10);
            color: #7a8699;
            font-size: 0.94rem;
            font-weight: 550;
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
        }
        .pm-top-icons { display: flex; gap: 0.72rem; }
        .pm-icon-button {
            width: 46px;
            height: 46px;
            display: grid;
            place-items: center;
            border-radius: 16px;
            border: 1px solid rgba(255, 255, 255, 0.82);
            background: rgba(255, 255, 255, 0.72);
            box-shadow: 0 14px 30px rgba(91, 119, 190, 0.12), inset 0 1px 0 rgba(255,255,255,0.86);
            color: #344054;
            font-size: 1.03rem;
        }

        .pm-hero {
            margin: 0 0 24px;
            padding: 0;
        }
        .pm-eyebrow { display: none; }
        .pm-title {
            color: #0f172a;
            font-size: clamp(3rem, 5.3vw, 5.6rem);
            font-weight: 820;
            letter-spacing: -0.085em;
            line-height: 0.9;
            margin: 0;
        }
        .pm-subtitle {
            color: #667085;
            font-size: clamp(1rem, 1.55vw, 1.22rem);
            font-weight: 520;
            margin-top: 24px;
        }
        .pm-overview { display: none; }
        .pm-hero-panel { display: none; }

        .pm-section-label {
            color: #667085;
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.14em;
            margin: 0 0 16px;
            text-transform: uppercase;
        }

        .metric-card,
        div[data-testid="stMetric"] {
            min-height: 136px;
            padding: 1.25rem 1.18rem 1.08rem;
            border: 0;
            border-radius: var(--pm-radius);
            background:
                linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(250, 252, 255, 0.92)),
                radial-gradient(circle at 0% 0%, rgba(91, 141, 239, 0.11), transparent 48%);
            box-shadow: var(--pm-card-shadow);
            backdrop-filter: blur(18px) saturate(1.16);
            -webkit-backdrop-filter: blur(18px) saturate(1.16);
        }
        div[data-testid="stMetricLabel"],
        div[data-testid="stMetricLabel"] p,
        div[data-testid="stMetricLabel"] span {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            letter-spacing: 0.01em;
            opacity: 1 !important;
        }
        div[data-testid="stMetricValue"] {
            color: #111827;
            font-weight: 800;
            letter-spacing: -0.055em;
        }

        .pm-card,
        .metric-card,
        .table-card,
        .chart-card {
            margin: 32px 0 0;
            padding: 1.35rem;
            border: 0;
            border-radius: var(--pm-radius);
            background: var(--pm-card);
            box-shadow: var(--pm-card-shadow);
            backdrop-filter: blur(18px) saturate(1.12);
            -webkit-backdrop-filter: blur(18px) saturate(1.12);
        }
        .pm-card h2, .pm-card h3 { margin-top: 0; color: #111827; letter-spacing: -0.04em; }
        .pm-section-heading {
            color: #111827;
            font-size: 1.45rem;
            font-weight: 780;
            letter-spacing: -0.04em;
            line-height: 1.2;
            margin: 32px 0 16px;
        }

        .pm-pagination-summary {
            color: #6b7280;
            font-size: 14px;
            font-weight: 500;
            margin: 14px 0 10px;
            padding-top: 0;
            text-align: center;
            white-space: nowrap;
        }
        .pm-page-indicator {
            color: #374151;
            font-size: 0.88rem;
            font-weight: 700;
            line-height: 46px;
            padding-top: 0;
            text-align: center;
            white-space: nowrap;
        }
        .pm-table-card,
        .table-card {
            border-radius: 24px;
            background: #ffffff;
            box-shadow: 0 18px 48px rgba(79, 96, 140, 0.10);
        }
        .pm-chart-card,
        .chart-card {
            background: rgba(255, 255, 255, 0.86);
            border-radius: 24px;
            padding: 28px 30px;
            box-shadow: 0 24px 70px rgba(111, 143, 190, 0.16);
            backdrop-filter: blur(18px);
            -webkit-backdrop-filter: blur(18px);
            border: 1px solid rgba(255, 255, 255, 0.72);
        }

        .pm-table-scroll,
        [data-testid="stDataFrame"] {
            width: 100%;
            max-height: 720px;
            overflow-x: auto;
            overflow-y: auto;
            border-radius: 24px;
            border: 0;
            box-shadow: 0 10px 30px rgba(79, 96, 140, 0.08);
            background: #ffffff;
        }
        .pm-dashboard-table {
            width: 100%;
            min-width: 860px;
            border-collapse: separate;
            border-spacing: 0;
            background: #ffffff;
            color: #1f2937;
            font-size: 0.88rem;
            line-height: 1.5;
        }
        .pm-dashboard-table thead th {
            position: sticky;
            top: 0;
            z-index: 10;
            padding: 0.86rem 1rem;
            border-right: 0;
            border-bottom: 1px solid rgba(92, 102, 120, 0.08);
            background: #f4f7fb;
            color: #5c6678;
            font-weight: 700;
            text-align: left;
            white-space: nowrap;
        }
        .pm-dashboard-table thead th:first-child { border-top-left-radius: 18px; }
        .pm-dashboard-table thead th:last-child { border-top-right-radius: 18px; }
        .pm-dashboard-table tbody td {
            padding: 0.86rem 1rem;
            border-right: 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.10);
            background: #ffffff;
            color: #1f2937;
            vertical-align: top;
        }
        .pm-dashboard-table tbody tr:nth-child(even) td {
            background: #fbfcff;
        }
        .pm-dashboard-table tbody tr:hover td {
            background: #f7faff;
        }
        .pm-dashboard-table tbody tr:last-child td {
            border-bottom: 0;
        }
        .pm-alert-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 4.25rem;
            padding: 0.22rem 0.62rem;
            border-radius: 999px;
            color: #ffffff;
            font-size: 0.76rem;
            font-weight: 760;
            line-height: 1.35;
            box-shadow: 0 8px 18px rgba(79, 96, 140, 0.14);
        }
        .pm-alert-badge.is-red { background: #f04463; }
        .pm-alert-badge.is-orange { background: #f59e0b; }
        .pm-alert-badge.is-green { background: #22c55e; }

        [data-testid="stDataFrame"] div[role="grid"],
        [data-testid="stDataFrame"] [role="table"] {
            background: #ffffff !important;
            color: #1f2937 !important;
        }
        [data-testid="stDataFrame"] [role="columnheader"],
        [data-testid="stDataFrame"] [data-testid="stDataFrameResizable"] {
            border-right: 0 !important;
            border-bottom: 1px solid rgba(92, 102, 120, 0.08) !important;
            background: #f4f7fb !important;
            color: #5c6678 !important;
            font-weight: 700 !important;
        }
        [data-testid="stDataFrame"] [role="gridcell"],
        [data-testid="stDataFrame"] [role="cell"] {
            border-right: 0 !important;
            border-bottom: 1px solid rgba(148, 163, 184, 0.10) !important;
            background: #ffffff !important;
            color: #1f2937 !important;
        }
        [data-testid="stDataFrame"] [role="row"]:nth-child(even) [role="gridcell"],
        [data-testid="stDataFrame"] [role="row"]:nth-child(even) [role="cell"] {
            background: #fbfcff !important;
        }
        [data-testid="stDataFrame"] [role="row"]:hover,
        [data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"],
        [data-testid="stDataFrame"] [role="row"]:hover [role="cell"] {
            background: #f7faff !important;
        }

        .stPlotlyChart {
            padding: 1.45rem 1.65rem;
            border-radius: 24px;
            border: 0;
            background: #ffffff;
            box-shadow: 0 24px 70px rgba(111, 143, 190, 0.16);
            overflow: hidden;
        }
        .stPlotlyChart .hoverlayer .hovertext {
            filter: drop-shadow(0 14px 30px rgba(79, 96, 140, 0.18));
        }
        .stDownloadButton button, .stButton button {
            border: 0;
            border-radius: 16px;
            background: linear-gradient(135deg, #5b8def, #9b7bff);
            color: #ffffff;
            box-shadow: 0 14px 30px rgba(91, 141, 239, 0.26);
            font-weight: 720;
        }
        .stDownloadButton button:hover, .stButton button:hover {
            box-shadow: var(--pm-card-shadow-hover);
            transform: translateY(-1px);
        }

        @media (max-width: 980px) {
            .main .block-container { padding-left: 16px; padding-right: 16px; padding-top: 20px; }
            section[data-testid="stSidebar"] { width: 19rem !important; padding-left: 0.8rem; }
            section[data-testid="stSidebar"] > div { width: 17.8rem; border-radius: 26px; }
            .pm-topbar { align-items: flex-start; flex-direction: column; }
            .pm-title { font-size: clamp(2.4rem, 14vw, 3.6rem); }
            .pm-card, .table-card, .chart-card { padding: 1.15rem; border-radius: 22px; }
        }

        /* Final selector fixes: scoped to explicit wrappers/markers so older Streamlit/BaseWeb styles cannot win. */
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper),
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper),
        [data-testid="column"]:has(.selector-fix-wrapper),
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) {
            overflow: visible !important;
        }

        .selector-fix-wrapper {
            display: none !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-testid="stSelectbox"],
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-testid="stMultiSelect"],
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-testid="stSelectbox"],
        [data-testid="column"]:has(.selector-fix-wrapper) [data-testid="stSelectbox"],
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-testid="stMultiSelect"] {
            width: 100% !important;
            max-width: 100% !important;
            overflow: visible !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"],
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"],
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"],
        .selector-fix-wrapper [data-baseweb="select"] {
            width: 100% !important;
            max-width: 100% !important;
            min-width: 0 !important;
            border: 0 !important;
            background: transparent !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            overflow: visible !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] > div,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] > div,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] > div,
        .selector-fix-wrapper [data-baseweb="select"] > div {
            width: 100% !important;
            max-width: 100% !important;
            min-height: 46px !important;
            height: auto !important;
            background: #ffffff !important;
            background-color: #ffffff !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            border: 1px solid rgba(148, 163, 184, 0.36) !important;
            border-radius: 16px !important;
            box-shadow: 0 8px 22px rgba(111, 143, 190, 0.10) !important;
            padding: 8px 38px 8px 12px !important;
            overflow: visible !important;
            opacity: 1 !important;
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] > div {
            min-height: 54px !important;
            padding: 8px 34px 8px 10px !important;
            flex-wrap: wrap !important;
            align-items: center !important;
            gap: 4px !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] span,
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] input,
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] div,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] span,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] input,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] div,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] span,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] input,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] div,
        .selector-fix-wrapper [data-baseweb="select"] span,
        .selector-fix-wrapper [data-baseweb="select"] input,
        .selector-fix-wrapper [data-baseweb="select"] div {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            font-weight: 700 !important;
            opacity: 1 !important;
            line-height: 1.35 !important;
            text-shadow: none !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] input,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] input,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] input,
        .selector-fix-wrapper [data-baseweb="select"] input {
            min-width: 130px !important;
            caret-color: #111827 !important;
        }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] input {
            min-width: 150px !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] input::placeholder,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] input::placeholder,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] input::placeholder,
        .selector-fix-wrapper [data-baseweb="select"] input::placeholder {
            color: #64748b !important;
            -webkit-text-fill-color: #64748b !important;
            font-weight: 700 !important;
            opacity: 1 !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"],
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"],
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="tag"],
        .selector-fix-wrapper [data-baseweb="tag"] {
            max-width: 214px !important;
            min-width: 0 !important;
            margin: 2px 4px 2px 0 !important;
            padding: 5px 8px !important;
            background: #f3f4f6 !important;
            background-color: #f3f4f6 !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            border: 1px solid rgba(148, 163, 184, 0.28) !important;
            border-radius: 10px !important;
            box-shadow: none !important;
            overflow: hidden !important;
            opacity: 1 !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] span,
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] div,
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] p,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] span,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] div,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] p,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="tag"] span,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="tag"] div,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="tag"] p,
        .selector-fix-wrapper [data-baseweb="tag"] span,
        .selector-fix-wrapper [data-baseweb="tag"] div,
        .selector-fix-wrapper [data-baseweb="tag"] p {
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            font-weight: 800 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
            line-height: 1.2 !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] svg,
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] svg,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] svg,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="tag"] svg,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] svg,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="tag"] svg,
        .selector-fix-wrapper [data-baseweb="select"] svg,
        .selector-fix-wrapper [data-baseweb="tag"] svg {
            color: #64748b !important;
            fill: #64748b !important;
        }

        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] *::before,
        [data-testid="stVerticalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] *::after,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] *::before,
        [data-testid="stHorizontalBlock"]:has(.selector-fix-wrapper) [data-baseweb="select"] *::after,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] *::before,
        [data-testid="column"]:has(.selector-fix-wrapper) [data-baseweb="select"] *::after,
        .selector-fix-wrapper [data-baseweb="select"] *::before,
        .selector-fix-wrapper [data-baseweb="select"] *::after {
            content: none !important;
            display: none !important;
            background: none !important;
            box-shadow: none !important;
        }

        /* Hide sidebar placeholder only */
        .sidebar-filter-wrapper input::placeholder,
        .sidebar-filter-wrapper [data-baseweb="select"] input::placeholder,
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) input::placeholder,
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="select"] input::placeholder {
            color: transparent !important;
            -webkit-text-fill-color: transparent !important;
            opacity: 0 !important;
        }

        .pm-alert-filter-row {
            margin: -2px 0 16px;
        }
        [class*="gap_alert_filter_"] .stButton button,
        [class*="gap-alert-filter-"] .stButton button {
            min-height: 42px !important;
            padding: 0.42rem 1.05rem !important;
            border-radius: 999px !important;
            border: 1px solid #d1d5db !important;
            background: #ffffff !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            font-weight: 700 !important;
            box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06) !important;
            white-space: nowrap !important;
        }
        [class*="gap_alert_filter_"] .stButton button:hover,
        [class*="gap-alert-filter-"] .stButton button:hover {
            border-color: #9ca3af !important;
            box-shadow: 0 10px 22px rgba(15, 23, 42, 0.10) !important;
        }
        [class*="gap_alert_filter_red_is_selected"] .stButton button,
        [class*="gap-alert-filter-red-is-selected"] .stButton button {
            background: #dc2626 !important;
            border-color: #dc2626 !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-weight: 800 !important;
        }
        [class*="gap_alert_filter_orange_is_selected"] .stButton button,
        [class*="gap-alert-filter-orange-is-selected"] .stButton button {
            background: #f97316 !important;
            border-color: #f97316 !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-weight: 800 !important;
        }
        [class*="gap_alert_filter_green_is_selected"] .stButton button,
        [class*="gap-alert-filter-green-is-selected"] .stButton button {
            background: #16a34a !important;
            border-color: #16a34a !important;
            color: #ffffff !important;
            -webkit-text-fill-color: #ffffff !important;
            font-weight: 800 !important;
        }

        /* Keep pagination controls centered as one compact flex group below tables. */
        [data-testid="stHorizontalBlock"]:has(.pagination-controls-fix),
        [class*="pagination_controls_fix"] [data-testid="stHorizontalBlock"],
        [class*="pagination-controls-fix"] [data-testid="stHorizontalBlock"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 32px !important;
            overflow: visible !important;
        }
        [data-testid="stHorizontalBlock"]:has(.pagination-controls-fix) > [data-testid="stVerticalBlock"],
        [class*="pagination_controls_fix"] [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"],
        [class*="pagination-controls-fix"] [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"] {
            flex: 0 0 auto !important;
            width: auto !important;
            min-width: fit-content !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            overflow: visible !important;
        }
        [data-testid="stHorizontalBlock"]:has(.pagination-controls-fix) .stButton,
        [class*="pagination_controls_fix"] .stButton,
        [class*="pagination-controls-fix"] .stButton {
            width: auto !important;
            margin: 0 !important;
        }
        [data-testid="stHorizontalBlock"]:has(.pagination-controls-fix) .stButton button,
        [class*="pagination_controls_fix"] .stButton button,
        [class*="pagination-controls-fix"] .stButton button {
            min-height: 46px !important;
            margin: 0 !important;
            white-space: nowrap !important;
        }

        /* Sidebar filters: blank empty state, visible arrow, light-gray readable selected tags. */
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="select"] input {
            min-width: 1px !important;
            width: 1px !important;
        }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="select"] input::placeholder,
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="select"] [class*="placeholder"],
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="select"] div[aria-label="Choose options"] {
            color: transparent !important;
            -webkit-text-fill-color: transparent !important;
            opacity: 0 !important;
        }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="select"] svg {
            color: #64748b !important;
            fill: #64748b !important;
            opacity: 1 !important;
            visibility: visible !important;
        }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="tag"] {
            max-width: 184px !important;
            background: #f3f4f6 !important;
            background-color: #f3f4f6 !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            border-color: rgba(148, 163, 184, 0.30) !important;
        }
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="tag"] span,
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="tag"] div,
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]:has(.sidebar-filter-wrapper) [data-baseweb="tag"] p {
            max-width: 150px !important;
            color: #111827 !important;
            -webkit-text-fill-color: #111827 !important;
            font-weight: 800 !important;
            white-space: nowrap !important;
            overflow: hidden !important;
            text-overflow: ellipsis !important;
        }


        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_chrome() -> None:
    st.sidebar.markdown(
        """
        <div class="pm-sidebar-brand">
            <span class="pm-logo-orb"></span>
            <span class="pm-brand-title">Mob Monitor</span>
        </div>
        <div class="sidebar-nav">
            <a href="#price-table" class="sidebar-nav-item">Price Table</a>
            <a href="#gap-analysis" class="sidebar-nav-item">Gap Analysis</a>
            <a href="#trend-chart" class="sidebar-nav-item">Trend Chart</a>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_header() -> None:
    st.markdown(
        f"""
        <div class="pm-hero">
            <div class="pm-hero-copy">
                <div class="pm-title">Overview</div>
                <div class="pm-subtitle">Daraz vs Competitor Pricing Intelligence — Latest Market Snapshot</div>
                <div class="pm-overview">Overview generated on {date.today().strftime("%B %d, %Y")}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_refresh_control() -> None:
    if st.sidebar.button("🔄 Refresh Data"):
        st.session_state["last_refreshed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.cache_data.clear()
        st.rerun()

    if st.session_state.get("last_refreshed_at"):
        st.sidebar.caption(f"Last refreshed: {st.session_state['last_refreshed_at']}")


def available_columns(columns: list[str], df: pd.DataFrame) -> list[str]:
    return [col for col in columns if col in df.columns]


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    st.sidebar.markdown(
        """
        <div class="pm-filter-title">Filters</div>
        <div class="pm-filter-caption">Refine the pricing intelligence view</div>
        """,
        unsafe_allow_html=True,
    )

    filter_specs = [
        ("country", "Country"),
        ("brand", "Brand"),
        ("model", "SKU"),
        ("memory", "Memory"),
    ]

    for col, label in filter_specs:
        if col in filtered.columns:
            options = sorted([x for x in filtered[col].dropna().unique().tolist() if str(x).strip()])
            st.sidebar.markdown(
                f"<div class='selector-fix-wrapper sidebar-filter-wrapper sidebar-selector-fix sidebar-selector-{col}'></div>",
                unsafe_allow_html=True,
            )
            selected = st.sidebar.multiselect(label, options=options, placeholder=" ")
            if selected:
                filtered = filtered[filtered[col].isin(selected)]

    if "crawl_date" in filtered.columns and not filtered["crawl_date"].dropna().empty:
        min_date = filtered["crawl_date"].dropna().min()
        max_date = filtered["crawl_date"].dropna().max()
        date_range = st.sidebar.date_input("Date Range", value=(min_date, max_date))
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            filtered = filtered[
                (filtered["crawl_date"] >= start_date) & (filtered["crawl_date"] <= end_date)
            ]

    return filtered


def latest_price_table(gap_df: pd.DataFrame) -> pd.DataFrame:
    if gap_df.empty:
        return pd.DataFrame(columns=TABLE_COLUMNS + INTERNAL_TABLE_COLUMNS)

    required = {
        "crawl_date",
        "Country",
        "Brand",
        "SKU",
        "Memory",
        "Daraz Price",
        "Competitor Platform",
        "Competitor Price",
    }
    if not required.issubset(gap_df.columns):
        return pd.DataFrame(columns=TABLE_COLUMNS + INTERNAL_TABLE_COLUMNS)

    display = pd.DataFrame(index=gap_df.index)
    display["crawl_time"] = gap_df["crawl_date"].apply(format_date)
    display["country"] = gap_df["Country"]
    display["brand"] = gap_df["Brand"]
    display["model"] = gap_df["SKU"]
    display["memory"] = gap_df["Memory"]
    display["Daraz Effective Price"] = gap_df["Daraz Price"].apply(format_price).fillna("")
    display["Daraz Stock Status"] = (
        gap_df["Daraz Stock Status"] if "Daraz Stock Status" in gap_df.columns else ""
    )
    display["Competitor Platform"] = gap_df["Competitor Platform"]
    display["Competitor Effective Price"] = gap_df["Competitor Price"].apply(format_price).fillna("")
    display["LC Stock Status"] = gap_df["LC Stock Status"] if "LC Stock Status" in gap_df.columns else ""
    display["product_url"] = gap_df.get("competitor_product_url", pd.Series("", index=gap_df.index))
    display["daraz_product_url"] = gap_df.get("daraz_product_url", pd.Series("", index=gap_df.index))
    display["competitor_product_url"] = gap_df.get(
        "competitor_product_url", pd.Series("", index=gap_df.index)
    )

    sort_display_cols = available_columns(
        ["crawl_time", "country", "brand", "model", "memory", "Competitor Platform"], display
    )
    if sort_display_cols:
        display = display.sort_values(
            sort_display_cols, ascending=[False] + [True] * (len(sort_display_cols) - 1)
        )
    return display[available_columns(TABLE_COLUMNS + INTERNAL_TABLE_COLUMNS, display)]


def latest_platform_rows(
    df: pd.DataFrame,
    group_cols: list[str],
    selected_cols: list[str],
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=selected_cols)

    existing_selected_cols = available_columns(selected_cols, df)
    sort_cols = available_columns(["crawl_datetime"], df)
    sorted_df = df[existing_selected_cols].copy()
    if sort_cols:
        sorted_df = sorted_df.sort_values(
            sort_cols,
            ascending=[False] * len(sort_cols),
            na_position="last",
        )

    existing_group_cols = available_columns(group_cols, sorted_df)
    if not existing_group_cols:
        return sorted_df
    return sorted_df.drop_duplicates(existing_group_cols, keep="first")


def calculate_gap_table(df: pd.DataFrame) -> pd.DataFrame:
    required = {"crawl_date", "country", "brand", "model", "memory", "platform", "effective_price"}
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame(columns=RAW_GAP_COLUMNS)

    working = add_dashboard_join_fields(df)
    if working.empty:
        return pd.DataFrame(columns=RAW_GAP_COLUMNS)

    working["__platform_key"] = working["platform"].apply(normalized_platform)
    join_cols = available_columns(DASHBOARD_MATCH_IDENTITY_COLUMNS, working)
    sku_cols = available_columns(DASHBOARD_SKU_IDENTITY_COLUMNS, working)
    display_key_cols = ["country", "brand", "model", "memory"]
    competitor_keys = [platform.casefold() for platform in COMPETITOR_PLATFORMS]
    selected_cols = join_cols + display_key_cols + ["__platform_key", "effective_price"]
    selected_cols += available_columns(["crawl_datetime", "crawl_date", "product_url", "stock_status"], working)

    # Price availability is the only row-level filter used for dashboard matching.
    # Stock status is display-only and must not exclude active, out_of_stock,
    # unknown, or blank Daraz/competitor rows from the matched tables.
    priced_rows = working[working["effective_price"].notna()]

    daraz = latest_platform_rows(
        priced_rows[priced_rows["__platform_key"] == DARAZ_PLATFORM.casefold()],
        sku_cols,
        selected_cols,
    ).rename(
        columns={
            "effective_price": "Daraz Price",
            "product_url": "daraz_product_url",
            "stock_status": "Daraz Stock Status",
            "crawl_datetime": "daraz_crawl_datetime",
            "crawl_date": "daraz_crawl_date",
        }
    )

    competitors = latest_platform_rows(
        priced_rows[priced_rows["__platform_key"].isin(competitor_keys)],
        sku_cols,
        selected_cols,
    ).rename(
        columns={
            "__platform_key": "Competitor Platform",
            "effective_price": "Competitor Price",
            "product_url": "competitor_product_url",
            "stock_status": "LC Stock Status",
            "crawl_datetime": "competitor_crawl_datetime",
            "crawl_date": "competitor_crawl_date",
        }
    )

    if daraz.empty:
        return pd.DataFrame(columns=RAW_GAP_COLUMNS)

    if competitors.empty:
        gap = daraz.copy()
        gap["Competitor Platform"] = ""
        gap["Competitor Price"] = pd.NA
        gap["LC Stock Status"] = ""
        gap["competitor_product_url"] = ""
        gap["competitor_crawl_datetime"] = pd.NaT
        gap["competitor_crawl_date"] = pd.NaT
    else:
        gap = daraz.merge(competitors, on=join_cols, how="left", suffixes=("", "_competitor"))
    if gap.empty:
        return pd.DataFrame(columns=RAW_GAP_COLUMNS)

    gap["crawl_date"] = gap.get(
        "daraz_crawl_date", gap.get("join_date", pd.Series(pd.NaT, index=gap.index))
    )
    gap["crawl_datetime"] = gap.get(
        "daraz_crawl_datetime", pd.Series(pd.NaT, index=gap.index)
    )
    gap["Daraz Stock Status"] = gap.get("Daraz Stock Status", pd.Series("", index=gap.index)).fillna("")
    gap["LC Stock Status"] = gap.get("LC Stock Status", pd.Series("", index=gap.index)).fillna("")
    gap["Competitor Platform"] = gap["Competitor Platform"].fillna("")
    gap["competitor_product_url"] = gap["competitor_product_url"].fillna("")
    gap["Gap Amount"] = gap["Daraz Price"] - gap["Competitor Price"]
    gap["Gap %"] = gap["Gap Amount"] / gap["Daraz Price"]
    gap["Alert"] = gap["Gap %"].apply(alert_level).where(gap["Competitor Price"].notna(), "")
    gap["__alert_sort"] = gap["Alert"].map({"Red": 0, "Orange": 1, "Green": 2}).fillna(3)

    latest_sort_cols = available_columns(["crawl_date", "crawl_datetime"], gap)
    if latest_sort_cols:
        gap = gap.sort_values(
            latest_sort_cols,
            ascending=[False] * len(latest_sort_cols),
            na_position="last",
        )
        latest_gap_key_cols = available_columns(
            DASHBOARD_MATCH_IDENTITY_COLUMNS + ["Competitor Platform"], gap
        )
        gap = gap.groupby(latest_gap_key_cols, dropna=False).head(1)

    gap = gap.sort_values(["__alert_sort", "Gap %"], ascending=[True, False], na_position="last")
    gap = gap.rename(
        columns={
            "country": "Country",
            "brand": "Brand",
            "model": "SKU",
            "memory": "Memory",
        }
    )
    return gap[available_columns(RAW_GAP_COLUMNS + INTERNAL_GAP_URL_COLUMNS, gap)]


def alert_level(gap_pct: float) -> str:
    if pd.isna(gap_pct):
        return "Green"
    if gap_pct >= 0.05:
        return "Red"
    if gap_pct > 0:
        return "Orange"
    return "Green"


def format_gap_table(gap_df: pd.DataFrame) -> pd.DataFrame:
    if gap_df.empty:
        return pd.DataFrame(columns=GAP_COLUMNS)

    try:
        formatted = pd.DataFrame(index=gap_df.index)
        formatted["crawl_time"] = (
            gap_df["crawl_date"].apply(format_date) if "crawl_date" in gap_df.columns else ""
        )
        formatted["country"] = gap_df["Country"] if "Country" in gap_df.columns else ""
        formatted["brand"] = gap_df["Brand"] if "Brand" in gap_df.columns else ""
        formatted["model"] = gap_df["SKU"] if "SKU" in gap_df.columns else ""
        formatted["memory"] = gap_df["Memory"] if "Memory" in gap_df.columns else ""
        formatted["Daraz Effective Price"] = (
            gap_df["Daraz Price"].apply(format_price) if "Daraz Price" in gap_df.columns else ""
        )
        formatted["Daraz Stock Status"] = (
            gap_df["Daraz Stock Status"] if "Daraz Stock Status" in gap_df.columns else ""
        )
        formatted["Competitor Platform"] = (
            gap_df["Competitor Platform"] if "Competitor Platform" in gap_df.columns else ""
        )
        formatted["Competitor Effective Price"] = (
            gap_df["Competitor Price"].apply(format_price)
            if "Competitor Price" in gap_df.columns
            else ""
        )
        formatted["LC Stock Status"] = (
            gap_df["LC Stock Status"] if "LC Stock Status" in gap_df.columns else ""
        )
        formatted["Gap Amount"] = (
            gap_df["Gap Amount"].apply(format_price) if "Gap Amount" in gap_df.columns else ""
        )
        formatted["Gap %"] = gap_df["Gap %"].apply(format_gap_pct) if "Gap %" in gap_df.columns else ""
        formatted["Alert"] = gap_df["Alert"] if "Alert" in gap_df.columns else ""
        formatted["product_url"] = gap_df.get("competitor_product_url", pd.Series("", index=gap_df.index))
        formatted["daraz_product_url"] = gap_df.get("daraz_product_url", pd.Series("", index=gap_df.index))
        formatted["competitor_product_url"] = gap_df.get(
            "competitor_product_url", pd.Series("", index=gap_df.index)
        )
        return formatted[available_columns(GAP_COLUMNS + INTERNAL_TABLE_COLUMNS, formatted)]
    except Exception:  # noqa: BLE001 - display formatting should never crash the dashboard.
        return gap_df[available_columns(GAP_COLUMNS + INTERNAL_TABLE_COLUMNS, gap_df)]


def render_kpis(gap_df: pd.DataFrame) -> None:
    sku_cols = available_columns(GAP_SKU_IDENTITY_COLUMNS, gap_df)
    daraz_prices = numeric_gap_price(gap_df, "Daraz Price")
    competitor_prices = numeric_gap_price(gap_df, "Competitor Price")

    total_skus = count_distinct_gap_skus(gap_df, sku_cols)
    daraz_skus = count_distinct_gap_skus(gap_df, sku_cols, daraz_prices.notna())
    lc_skus = count_distinct_gap_skus(gap_df, sku_cols, competitor_prices.notna())
    daraz_win_skus = count_distinct_gap_skus(
        gap_df,
        sku_cols,
        daraz_prices.notna() & competitor_prices.notna() & (daraz_prices < competitor_prices),
    )
    daraz_loss_skus = count_distinct_gap_skus(
        gap_df,
        sku_cols,
        daraz_prices.notna() & competitor_prices.notna() & (daraz_prices > competitor_prices),
    )

    metrics = [
        ("Total SKU", f"{total_skus:,}"),
        ("Drz SKU", f"{daraz_skus:,}"),
        ("LC SKU", f"{lc_skus:,}"),
        ("Drz Wins", f"{daraz_win_skus:,}"),
        ("Drz Losses", f"{daraz_loss_skus:,}"),
    ]
    label_style = (
        "color:#0F172A !important; "
        "opacity:1 !important; "
        "font-size:13px !important; "
        "font-weight:800 !important; "
        "letter-spacing:0.8px !important; "
        "text-transform:uppercase !important; "
        "margin-bottom:18px !important; "
        "display:block !important;"
    )
    value_style = (
        "color:#111827; "
        "font-size:2.25rem; "
        "font-weight:800; "
        "letter-spacing:-0.055em; "
        "line-height:1;"
    )
    card_style = "margin:0 !important;"
    cols = st.columns(5)

    for col, (label, value) in zip(cols, metrics, strict=False):
        col.markdown(
            f"""
            <div class="metric-card" style="{card_style}">
                <div class="kpi-label" style="{label_style}">{html.escape(label)}</div>
                <div class="kpi-value" style="{value_style}">{html.escape(value)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def numeric_gap_price(gap_df: pd.DataFrame, column: str) -> pd.Series:
    if column not in gap_df.columns:
        return pd.Series(pd.NA, index=gap_df.index, dtype="Float64")
    return pd.to_numeric(gap_df[column], errors="coerce")


def count_distinct_gap_skus(
    gap_df: pd.DataFrame, sku_cols: list[str], mask: pd.Series | None = None
) -> int:
    if gap_df.empty:
        return 0

    selected = gap_df.loc[mask] if mask is not None else gap_df
    if selected.empty:
        return 0
    return selected.drop_duplicates(sku_cols).shape[0] if sku_cols else len(selected)


def chart_platform_label(platform: object) -> str:
    platform_key = str(platform).strip().casefold()
    return {
        "daraz": "Daraz",
        "priceoye": "PriceOye",
        "pickaboo": "Pickaboo",
    }.get(platform_key, str(platform).strip().title())


def chart_legend_sku_label(sku: object, brand: object = "") -> str:
    sku_label = str(sku).strip()
    brand_label = "" if pd.isna(brand) else str(brand).strip()
    if brand_label and sku_label.casefold().startswith(f"{brand_label.casefold()} "):
        return sku_label[len(brand_label) :].strip()
    return sku_label


def render_gap_chart(filtered: pd.DataFrame) -> None:
    st.markdown("<a id='trend-chart'></a>", unsafe_allow_html=True)
    st.markdown("<h2 class='pm-section-heading'>Price Trend Chart</h2>", unsafe_allow_html=True)

    has_standard_sku = "standard_model_memory" in filtered.columns
    has_fallback_sku = {"model", "memory"}.issubset(filtered.columns)
    required = {"crawl_date", "effective_price"}
    if not required.issubset(filtered.columns) or not (has_standard_sku or has_fallback_sku):
        st.info(
            "Trend chart requires crawl_date, effective_price, and SKU columns "
            "(standard_model_memory or model and memory)."
        )
        return

    trend_df = filtered.copy()
    trend_df["crawl_date"] = pd.to_datetime(trend_df["crawl_date"], errors="coerce").dt.date
    trend_df["effective_price"] = pd.to_numeric(trend_df["effective_price"], errors="coerce")
    trend_df = trend_df.dropna(subset=["crawl_date", "effective_price"])

    if trend_df.empty:
        st.info("No numeric price data available for the selected filters.")
        return

    sku_key = "standard_model_memory" if has_standard_sku else "sku_display"
    if has_standard_sku:
        trend_df[sku_key] = trend_df[sku_key].fillna("").astype(str).str.strip()
    else:
        trend_df[sku_key] = (
            trend_df["model"].fillna("").astype(str).str.strip()
            + " "
            + trend_df["memory"].fillna("").astype(str).str.strip()
        ).str.strip()

    trend_df[sku_key] = trend_df[sku_key].where(
        trend_df[sku_key].ne(""),
        "Unknown SKU",
    )

    if "platform" not in trend_df.columns:
        st.info("Trend chart requires platform data to compare prices by platform.")
        return

    trend_df["platform_display"] = trend_df["platform"].apply(normalized_platform)
    platform_order = ["daraz", "priceoye", "pickaboo"]
    available_platforms = [
        platform
        for platform in platform_order
        if platform in set(trend_df["platform_display"].dropna().astype(str))
    ]

    if not available_platforms:
        st.info("No Daraz, PriceOye, or Pickaboo price data available for the selected filters.")
        return

    st.markdown("<div class='pm-filter-caption'>Platform</div>", unsafe_allow_html=True)
    selected_platforms = render_platform_toggles(available_platforms)

    chart_df = trend_df[trend_df["platform_display"].isin(selected_platforms)].copy()
    brand_series = (
        chart_df["brand"] if "brand" in chart_df.columns else pd.Series("", index=chart_df.index)
    )
    chart_df["legend_sku"] = [
        chart_legend_sku_label(sku, brand)
        for sku, brand in zip(chart_df[sku_key], brand_series, strict=False)
    ]
    chart_df = (
        chart_df
        .sort_values(["crawl_date", "platform_display", sku_key])
        .groupby(["crawl_date", "platform_display", sku_key], as_index=False)
        .agg({"effective_price": "last", "legend_sku": "last"})
    )
    chart_df["series_key"] = (
        chart_df["platform_display"].astype(str) + "|" + chart_df[sku_key].astype(str)
    )

    if chart_df.empty:
        st.info("No price trend data available for the selected chart platforms.")
        return

    min_price = chart_df["effective_price"].min()
    max_price = chart_df["effective_price"].max()

    if min_price == max_price:
        y_min = max(0, min_price * 0.9)
        y_max = max_price * 1.1
    else:
        y_min = max(0, min_price * 0.95)
        y_max = max_price * 1.05

    if y_max <= y_min:
        y_max = y_min + 1

    unique_dates = sorted(chart_df["crawl_date"].dropna().unique())
    xaxis_options = {
        "tickmode": "array",
        "tickvals": unique_dates,
        "ticktext": [date.strftime("%d-%b") for date in unique_dates],
    }

    fig = go.Figure()
    series_palette = [
        "#2563eb",  # blue
        "#f97316",  # orange
        "#10b981",  # emerald
        "#8b5cf6",  # purple
        "#ec4899",  # pink
        "#06b6d4",  # cyan
        "#84cc16",  # lime
        "#f59e0b",  # amber
        "#ef4444",  # red
        "#14b8a6",  # teal
    ]
    series_keys = sorted(chart_df["series_key"].dropna().astype(str).unique())
    series_color_map = {
        key: series_palette[index % len(series_palette)]
        for index, key in enumerate(series_keys)
    }
    platform_dash_map = {
        "daraz": "solid",
        "priceoye": "dash",
        "pickaboo": "dot",
    }

    for (platform_name, sku_name), group in chart_df.groupby(["platform_display", sku_key]):
        group = group.sort_values("crawl_date")
        platform_name = str(platform_name)
        sku_name = str(sku_name)
        series_key = f"{platform_name}|{sku_name}"
        legend_sku = str(group["legend_sku"].iloc[-1]) if "legend_sku" in group else sku_name
        legend_name = f"{chart_platform_label(platform_name)} | {legend_sku}"

        fig.add_trace(
            go.Scatter(
                x=group["crawl_date"],
                y=group["effective_price"],
                mode="lines+markers",
                name=legend_name,
                line=dict(
                    color=series_color_map.get(series_key, "#64748b"),
                    dash=platform_dash_map.get(platform_name, "solid"),
                    shape="spline",
                    width=3,
                    smoothing=1.25,
                ),
                marker=dict(
                    size=8,
                    symbol="circle",
                    line=dict(width=1.5, color="#ffffff"),
                ),
                customdata=list(
                    zip(
                        group["platform_display"].apply(chart_platform_label),
                        group["legend_sku"],
                        strict=False,
                    )
                ),
                hovertemplate=(
                    "<b>Platform:</b> %{customdata[0]}<br>"
                    "<b>SKU:</b> %{customdata[1]}<br>"
                    "<b>Date:</b> %{x|%d-%b}<br>"
                    "<b>Price:</b> %{y:,.0f}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        height=520,
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        hovermode="closest",
        margin=dict(l=70, r=40, t=50, b=85),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.08,
            xanchor="left",
            x=0,
            bgcolor="rgba(255,255,255,0)",
            font=dict(size=13, color="#111827"),
            title=dict(text="Platform | SKU", font=dict(size=13, color="#111827")),
        ),
        font=dict(
            family="Inter, -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
            color="#111827",
        ),
        hoverlabel=dict(
            bgcolor="#ffffff",
            bordercolor="rgba(17,24,39,0.10)",
            font=dict(color="#111827", size=13),
            align="left",
        ),
    )

    fig.update_xaxes(
        tickformat="%d-%b",
        showgrid=True,
        gridcolor="rgba(148,163,184,0.22)",
        zeroline=False,
        showline=False,
        ticks="",
        color="#111827",
        title=dict(
            text="<b>Date</b>",
            font=dict(size=16, color="#1f2937", family="Inter, sans-serif"),
            standoff=18,
        ),
        tickfont=dict(size=13, color="#334155"),
        **xaxis_options,
    )

    fig.update_yaxes(
        title=dict(
            text="<b>Price</b>",
            font=dict(size=16, color="#1f2937", family="Inter, sans-serif"),
            standoff=14,
        ),
        range=[y_min, y_max],
        showgrid=True,
        gridcolor="rgba(148,163,184,0.22)",
        zeroline=False,
        showline=False,
        ticks="",
        color="#111827",
        tickfont=dict(size=13, color="#334155"),
        tickformat=",",
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": False,
            "responsive": True,
        },
    )


def render_data_section(title: str, df: pd.DataFrame, columns: list[str] | None = None) -> None:
    if anchor_id := SECTION_ANCHORS.get(title):
        st.markdown(f"<a id='{anchor_id}'></a>", unsafe_allow_html=True)
    st.markdown(f"<h2 class='pm-section-heading'>{html.escape(title)}</h2>", unsafe_allow_html=True)
    visible_columns = available_columns(columns, df) if columns else visible_table_columns(df)
    display_columns = visible_columns + [
        column for column in INTERNAL_TABLE_COLUMNS if column in df.columns and column not in visible_columns
    ]
    display_df = df[display_columns] if display_columns else df
    page_df, pagination_state = paginate_table(title, display_df)
    st.markdown(
        render_dashboard_table(page_df, visible_columns, title),
        unsafe_allow_html=True,
    )
    render_table_pagination_controls(pagination_state)


def render_gap_analysis_section(gap_df: pd.DataFrame) -> pd.DataFrame:
    title = "Price Gap Analysis"
    if anchor_id := SECTION_ANCHORS.get(title):
        st.markdown(f"<a id='{anchor_id}'></a>", unsafe_allow_html=True)
    st.markdown(f"<h2 class='pm-section-heading'>{html.escape(title)}</h2>", unsafe_allow_html=True)
    render_gap_alert_filters()

    display_gap_df = prepare_gap_analysis_display(gap_df)
    visible_columns = available_columns(GAP_COLUMNS, display_gap_df)
    display_columns = visible_columns + [
        column
        for column in INTERNAL_TABLE_COLUMNS
        if column in display_gap_df.columns and column not in visible_columns
    ]
    display_df = display_gap_df[display_columns] if display_columns else display_gap_df
    page_df, pagination_state = paginate_table(title, display_df)
    st.markdown(
        render_dashboard_table(page_df, visible_columns, title),
        unsafe_allow_html=True,
    )
    render_table_pagination_controls(pagination_state)
    return display_gap_df


def prepare_gap_analysis_display(gap_df: pd.DataFrame) -> pd.DataFrame:
    sorted_gap_df = gap_df.copy()
    if "crawl_date" in sorted_gap_df.columns:
        sorted_gap_df["crawl_date"] = pd.to_datetime(sorted_gap_df["crawl_date"], errors="coerce")
        sorted_gap_df = sorted_gap_df.sort_values("crawl_date", ascending=True)

    selected_alerts = selected_gap_alert_filters()
    if selected_alerts and len(selected_alerts) < len(ALERT_FILTERS) and "Alert" in sorted_gap_df.columns:
        sorted_gap_df = sorted_gap_df[sorted_gap_df["Alert"].isin(selected_alerts)]

    return format_gap_table(sorted_gap_df)


def render_gap_alert_filters() -> None:
    initialize_gap_alert_filters()
    st.markdown("<div class='pm-alert-filter-row'></div>", unsafe_allow_html=True)
    columns = st.columns([0.12, 0.15, 0.13, 0.60], gap="small")
    for column, alert_name in zip(columns[:3], ALERT_FILTERS, strict=False):
        filter_config = ALERT_FILTERS[alert_name]
        is_selected = bool(st.session_state.get(filter_config["key"], True))
        selected_class = "is_selected" if is_selected else "is_unselected"
        container_key = f"{filter_config['key']}_{selected_class}"
        with column.container(key=container_key):
            st.button(
                filter_config["label"],
                key=f"{filter_config['key']}_button",
                on_click=toggle_gap_alert_filter,
                args=(filter_config["key"],),
                use_container_width=True,
            )


def initialize_gap_alert_filters() -> None:
    for filter_config in ALERT_FILTERS.values():
        st.session_state.setdefault(filter_config["key"], True)


def selected_gap_alert_filters() -> list[str]:
    initialize_gap_alert_filters()
    return [
        alert_name
        for alert_name, filter_config in ALERT_FILTERS.items()
        if st.session_state.get(filter_config["key"], True)
    ]


def toggle_gap_alert_filter(filter_key: str) -> None:
    st.session_state[filter_key] = not bool(st.session_state.get(filter_key, True))
    st.session_state["table_price_gap_analysis_page"] = 1


def paginate_table(title: str, df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int | str]]:
    section_key = section_state_key(title)
    page_key = f"{section_key}_page"
    page_size = PAGE_SIZE

    if page_key not in st.session_state:
        st.session_state[page_key] = 1

    total_rows = len(df)
    total_pages = max((total_rows + page_size - 1) // page_size, 1)
    st.session_state[page_key] = min(max(int(st.session_state[page_key]), 1), total_pages)

    current_page = min(max(int(st.session_state[page_key]), 1), total_pages)
    start_index = (current_page - 1) * page_size
    end_index = min(start_index + page_size, total_rows)
    pagination_state = {
        "section_key": section_key,
        "page_key": page_key,
        "current_page": current_page,
        "total_pages": total_pages,
        "total_rows": total_rows,
        "start_index": start_index,
        "end_index": end_index,
    }
    return df.iloc[start_index:end_index], pagination_state


def render_table_pagination_controls(pagination_state: dict[str, int | str]) -> None:
    section_key = str(pagination_state["section_key"])
    page_key = str(pagination_state["page_key"])
    current_page = int(pagination_state["current_page"])
    total_pages = int(pagination_state["total_pages"])
    total_rows = int(pagination_state["total_rows"])
    start_index = int(pagination_state["start_index"])
    end_index = int(pagination_state["end_index"])

    if total_rows:
        showing_text = f"Showing {start_index + 1}–{end_index} of {total_rows} rows"
    else:
        showing_text = "Showing 0–0 of 0 rows"

    st.markdown(
        f"<div class='pm-pagination-summary'>{showing_text}</div>",
        unsafe_allow_html=True,
    )

    with st.container(
        horizontal=True,
        horizontal_alignment="center",
        vertical_alignment="center",
        gap="medium",
        key=f"{section_key}_pagination_controls_fix",
    ):
        st.button(
            "Previous",
            key=f"{section_key}_previous_page",
            disabled=current_page <= 1,
            on_click=change_table_page,
            args=(page_key, total_pages, -1),
        )
        st.markdown(
            f"<div class='pagination-controls-fix pm-page-indicator'>Page {current_page} / {total_pages}</div>",
            unsafe_allow_html=True,
        )
        st.button(
            "Next",
            key=f"{section_key}_next_page",
            disabled=current_page >= total_pages,
            on_click=change_table_page,
            args=(page_key, total_pages, 1),
        )


def change_table_page(page_key: str, total_pages: int, delta: int) -> None:
    current_page = int(st.session_state.get(page_key, 1))
    st.session_state[page_key] = min(max(current_page + delta, 1), total_pages)


def section_state_key(title: str) -> str:
    normalized = "".join(char.casefold() if char.isalnum() else "_" for char in title)
    normalized = "_".join(part for part in normalized.split("_") if part)
    return f"table_{normalized or 'section'}"


def visible_table_columns(df: pd.DataFrame) -> list[str]:
    return [column for column in df.columns if column not in INTERNAL_TABLE_COLUMNS]


def render_dashboard_table(
    df: pd.DataFrame,
    visible_columns: list[str] | None = None,
    title: str | None = None,
    sort_column: str | None = None,
    sort_direction: str | None = None,
) -> str:
    visible_columns = visible_columns or visible_table_columns(df)
    header_cells = "".join(
        f"<th>{html.escape(display_header_label(column))}</th>" for column in visible_columns
    )
    table_head = f"<thead><tr>{header_cells}</tr></thead>" if header_cells else ""

    if df.empty:
        empty_message = html.escape("No rows to display")
        colspan = max(len(visible_columns), 1)
        return (
            "<div class='pm-table-scroll'>"
            "<table class='pm-dashboard-table'>"
            f"{table_head}<tbody><tr><td colspan='{colspan}'>{empty_message}</td></tr></tbody>"
            "</table>"
            "</div>"
        )

    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for column in visible_columns:
            value = row.get(column, "")
            cell_html = format_table_cell(column, value, row)
            cells.append(f"<td>{cell_html}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    return (
        "<div class='pm-table-scroll'>"
        "<table class='pm-dashboard-table'>"
        f"{table_head}<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
        "</div>"
    )


def display_header_label(column: str) -> str:
    if column in TABLE_HEADER_LABELS:
        return TABLE_HEADER_LABELS[column]

    words = str(column).replace("_", " ").split()
    return " ".join(word[:1].upper() + word[1:] for word in words)


def format_table_cell(column: str, value: object, row: pd.Series | None = None) -> str:
    if pd.isna(value):
        return ""

    value_text = str(value)
    if column == "Alert":
        badge_class = {
            "Red": "is-red",
            "Orange": "is-orange",
            "Green": "is-green",
        }.get(value_text)
        if badge_class:
            escaped_value = html.escape(value_text)
            return f"<span class='pm-alert-badge {badge_class}'>{escaped_value}</span>"

    if column == "model" and row is not None:
        linked_value = linked_platform_cell(value_text, row.get("daraz_product_url", ""))
        if linked_value:
            return linked_value

    if column in LINKABLE_PLATFORM_COLUMNS and row is not None:
        linked_value = linked_platform_cell(value_text, row.get("product_url", ""))
        if linked_value:
            return linked_value

    return html.escape(value_text)


def linked_platform_cell(value_text: str, url: object) -> str:
    if not value_text:
        return ""
    if pd.isna(url):
        return ""

    url_text = str(url).strip()
    if not url_text or not url_text.casefold().startswith(("http://", "https://")):
        return ""

    escaped_value = html.escape(value_text)
    escaped_url = html.escape(url_text, quote=True)
    return f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">{escaped_value}</a>'


def render_downloads(latest_df: pd.DataFrame, gap_df: pd.DataFrame) -> None:
    st.markdown("<h2 class='pm-section-heading'>Download</h2>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    col1.download_button(
        label="Download latest price table CSV",
        data=latest_df.to_csv(index=False).encode("utf-8"),
        file_name="latest_price_table.csv",
        mime="text/csv",
        use_container_width=True,
    )
    col2.download_button(
        label="Download price gap analysis CSV",
        data=gap_df.to_csv(index=False).encode("utf-8"),
        file_name="price_gap_analysis.csv",
        mime="text/csv",
        use_container_width=True,
    )


def main() -> None:
    st.set_page_config(page_title="Mob Price Monitor", layout="wide", page_icon="📱")
    inject_styles()

    render_sidebar_chrome()
    render_dashboard_header()

    if not require_password():
        st.stop()

    render_refresh_control()

    try:
        df = load_price_data()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load Google Sheet data: {exc}")
        st.stop()

    if df.empty:
        st.info("No rows found in price_daily.")
        st.stop()

    filtered = apply_filters(df)
    gap_df = calculate_gap_table(filtered)
    latest_df = latest_price_table(gap_df)
    render_kpis(gap_df)

    formatted_gap_df = render_gap_analysis_section(gap_df)
    render_data_section("Latest Price Table", latest_df, TABLE_COLUMNS)
    render_gap_chart(filtered)

    render_downloads(latest_df, formatted_gap_df)


if __name__ == "__main__":
    main()

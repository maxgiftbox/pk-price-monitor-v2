import json
import os
from datetime import date
import gspread
import pandas as pd
import plotly.express as px
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
SKU_MASTER_PRODUCT_URL_JOIN_COLUMNS = ["platform", "country", "product_url"]
SKU_MASTER_FALLBACK_JOIN_COLUMNS = ["platform", "country", "brand", "model", "memory"]
SKU_MASTER_JOIN_COLUMNS = list(
    dict.fromkeys(SKU_MASTER_PRODUCT_URL_JOIN_COLUMNS + SKU_MASTER_FALLBACK_JOIN_COLUMNS)
)
SKU_MASTER_STANDARD_COLUMNS = ["standard_model", "standard_memory"]
COMPETITOR_PLATFORMS = ["PriceOye", "Pickaboo"]
DARAZ_PLATFORM = "Daraz"
OUT_OF_STOCK_STATUSES = {"out_of_stock", "unavailable"}
TABLE_COLUMNS = [
    "crawl_time",
    "country",
    "brand",
    "model",
    "memory",
    "Daraz Effective Price",
    "Competitor Platform",
    "Competitor Effective Price",
    "product_url",
]
GAP_COLUMNS = [
    "crawl_time",
    "country",
    "brand",
    "model",
    "memory",
    "Daraz Effective Price",
    "Competitor Platform",
    "Competitor Effective Price",
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
    "Competitor Platform",
    "Competitor Price",
    "Gap Amount",
    "Gap %",
    "Alert",
]
INTERNAL_GAP_URL_COLUMNS = ["daraz_product_url", "competitor_product_url"]
PLATFORM_DISPLAY_NAMES = {
    "daraz": "daraz",
    "priceoye": "priceoye",
    "pickaboo": "pickaboo",
}
PLATFORM_COLORS = {
    "daraz": "#f85606",
    "priceoye": "#0a84ff",
    "pickaboo": "#34c759",
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


def prepare_price_daily_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(col).strip() for col in df.columns]

    for col in PRICE_COLUMNS:
        if col in df.columns:
            df[col] = to_numeric_price(df[col])

    for col in ["platform", "country", "brand", "model", "memory", "product_url", "stock_status"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str).str.strip()

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
    for col in set(SKU_MASTER_JOIN_COLUMNS + SKU_MASTER_STANDARD_COLUMNS):
        if col in sku_master_df.columns:
            sku_master_df[col] = sku_master_df[col].fillna("").astype(str).str.strip()

    return sku_master_df


def enrich_with_sku_master(df: pd.DataFrame, sku_master_df: pd.DataFrame) -> pd.DataFrame:
    enriched = df.copy()
    enriched["raw_model"] = enriched["model"] if "model" in enriched.columns else ""
    enriched["raw_memory"] = enriched["memory"] if "memory" in enriched.columns else ""
    enriched["standard_model"] = ""
    enriched["standard_memory"] = ""

    if not sku_master_df.empty:
        enriched = apply_sku_master_match(
            enriched,
            sku_master_df,
            SKU_MASTER_PRODUCT_URL_JOIN_COLUMNS,
        )

        unmatched_mask = missing_standard_mask(enriched)
        if unmatched_mask.any():
            fallback_matches = apply_sku_master_match(
                enriched.loc[unmatched_mask].copy(),
                sku_master_df,
                SKU_MASTER_FALLBACK_JOIN_COLUMNS,
            )
            for col in SKU_MASTER_STANDARD_COLUMNS:
                enriched.loc[unmatched_mask, col] = coalesce_text(
                    enriched.loc[unmatched_mask, col].reset_index(drop=True),
                    fallback_matches[col].reset_index(drop=True),
                ).values

    enriched["dashboard_model"] = coalesce_text(enriched["standard_model"], enriched["raw_model"])
    enriched["dashboard_memory"] = coalesce_text(enriched["standard_memory"], enriched["raw_memory"])
    enriched["model"] = enriched["dashboard_model"]
    enriched["memory"] = enriched["dashboard_memory"]
    return enriched


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


def add_normalized_join_keys(df: pd.DataFrame, join_keys: list[str]) -> list[str]:
    normalized_key_cols = []
    for key in join_keys:
        normalized_col = f"__join_{key}"
        df[normalized_col] = df[key].fillna("").astype(str).str.strip().str.casefold()
        normalized_key_cols.append(normalized_col)
    return normalized_key_cols


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

    model_source = coalesce_text(
        working["standard_model"], working["model"]
    ) if "standard_model" in working.columns and "model" in working.columns else working.get(
        "standard_model", working.get("model", pd.Series("", index=working.index))
    )
    memory_source = coalesce_text(
        working["standard_memory"], working["memory"]
    ) if "standard_memory" in working.columns and "memory" in working.columns else working.get(
        "standard_memory", working.get("memory", pd.Series("", index=working.index))
    )
    working["join_model"] = normalize_join_text(model_source)
    working["join_memory"] = normalize_join_text(memory_source)
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
            --pm-ink: #111715;
            --pm-muted: #6f7c80;
            --pm-soft: #e6eef2;
            --pm-card: rgba(255, 255, 255, 0.88);
            --pm-border: rgba(255, 255, 255, 0.62);
            --pm-sidebar: rgba(12, 25, 23, 0.82);
            --pm-shadow: 0 34px 90px rgba(5, 18, 17, 0.28);
            --pm-card-shadow: 0 22px 54px rgba(20, 38, 42, 0.12);
            --pm-radius: 22px;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        #MainMenu, header[data-testid="stHeader"], footer, [data-testid="stToolbar"] {
            visibility: hidden;
            height: 0;
        }

        html, body, .stApp, [data-testid="stAppViewContainer"] {
            min-height: 100vh;
            font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        }

        .stApp {
            color: var(--pm-ink);
            background:
                radial-gradient(circle at 15% 12%, rgba(134, 162, 151, 0.50), transparent 28%),
                radial-gradient(circle at 76% 6%, rgba(215, 225, 228, 0.34), transparent 24%),
                radial-gradient(circle at 86% 82%, rgba(14, 55, 48, 0.70), transparent 32%),
                linear-gradient(135deg, #101a18 0%, #34443f 42%, #9aa7aa 100%);
            background-attachment: fixed;
        }

        .stApp::before {
            content: "";
            position: fixed;
            inset: 0;
            pointer-events: none;
            background:
                radial-gradient(circle at 50% 45%, rgba(238, 246, 248, 0.18), transparent 48%),
                linear-gradient(120deg, rgba(255, 255, 255, 0.13), rgba(255, 255, 255, 0.02));
            backdrop-filter: blur(4px);
            -webkit-backdrop-filter: blur(4px);
            z-index: 0;
        }

        [data-testid="stAppViewContainer"] > .main {
            position: relative;
            z-index: 1;
        }

        .block-container {
            max-width: 1400px;
            min-height: calc(100vh - 3.2rem);
            padding: 2.05rem 2.25rem 2.65rem;
            margin: 1.55rem auto;
            border: 1px solid rgba(255, 255, 255, 0.58);
            border-radius: 28px;
            background:
                linear-gradient(145deg, rgba(230, 238, 242, 0.72), rgba(236, 242, 244, 0.60)),
                radial-gradient(circle at 18% 0%, rgba(255, 255, 255, 0.55), transparent 34%);
            box-shadow: var(--pm-shadow);
            backdrop-filter: blur(24px) saturate(1.22);
            -webkit-backdrop-filter: blur(24px) saturate(1.22);
        }

        h1, h2, h3, p { font-family: inherit; }
        h1, h2, h3 { color: var(--pm-ink); letter-spacing: -0.045em; }
        h2, h3, .stSubheader { font-weight: 780; }
        hr { display: none; }

        section[data-testid="stSidebar"] {
            width: 240px !important;
            background: transparent;
            padding: 1.55rem 0 1.55rem 1.35rem;
        }

        section[data-testid="stSidebar"] > div {
            margin: 0;
            padding: 1.45rem 1rem 1.2rem;
            width: 240px;
            min-height: calc(100vh - 3.1rem);
            border-radius: 28px 22px 22px 28px;
            border: 1px solid rgba(255, 255, 255, 0.15);
            background:
                linear-gradient(180deg, rgba(25, 40, 37, 0.88), rgba(9, 19, 17, 0.80)),
                radial-gradient(circle at 28% 0%, rgba(95, 132, 120, 0.35), transparent 38%);
            box-shadow: 18px 30px 72px rgba(0, 0, 0, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.12);
            backdrop-filter: blur(24px) saturate(1.25);
            -webkit-backdrop-filter: blur(24px) saturate(1.25);
        }

        section[data-testid="stSidebar"] [data-testid="stSidebarContent"] { padding-top: 0; }
        section[data-testid="stSidebar"] h1,
        section[data-testid="stSidebar"] h2,
        section[data-testid="stSidebar"] h3,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] span {
            color: rgba(245, 249, 248, 0.88) !important;
        }

        .pm-sidebar-brand {
            display: flex;
            align-items: center;
            gap: 0.72rem;
            margin: 0.05rem 0 1.55rem;
            padding: 0 0.15rem;
        }
        .pm-logo-orb {
            width: 34px;
            height: 34px;
            border-radius: 50%;
            background: linear-gradient(135deg, #72d0ff 0%, #4a7dff 54%, #8ec7ff 100%);
            box-shadow: 0 10px 28px rgba(67, 139, 255, 0.42), inset 0 1px 10px rgba(255, 255, 255, 0.50);
        }
        .pm-brand-title { font-size: 1.03rem; font-weight: 800; letter-spacing: -0.03em; color: #f8fbfb; }
        .pm-sidebar-menu { display: grid; gap: 0.48rem; margin-bottom: 1.55rem; }
        .pm-menu-item {
            border-radius: 16px;
            padding: 0.78rem 0.88rem;
            color: rgba(233, 238, 237, 0.72);
            font-size: 0.91rem;
            font-weight: 680;
            letter-spacing: -0.01em;
        }
        .pm-menu-item.is-active {
            color: #ffffff;
            border: 1px solid rgba(255, 255, 255, 0.25);
            background: linear-gradient(135deg, rgba(255, 255, 255, 0.17), rgba(255, 255, 255, 0.07));
            box-shadow: 0 12px 30px rgba(169, 213, 199, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.16);
        }
        .pm-filter-title { color: rgba(241, 246, 246, 0.94); font-size: 0.78rem; font-weight: 820; letter-spacing: 0.12em; text-transform: uppercase; margin: 0.25rem 0 0.2rem; }
        .pm-filter-caption { color: rgba(221, 229, 228, 0.58); font-size: 0.78rem; line-height: 1.35; margin-bottom: 0.8rem; }

        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:has(.stMultiSelect),
        section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] > div:has(.stDateInput) {
            margin: 0.52rem 0;
            padding: 0.74rem 0.72rem 0.82rem;
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 18px;
            background: linear-gradient(145deg, rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.035));
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 12px 28px rgba(0, 0, 0, 0.12);
        }
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div,
        section[data-testid="stSidebar"] [data-baseweb="input"] {
            min-height: 40px;
            border-color: rgba(255, 255, 255, 0.14) !important;
            border-radius: 14px !important;
            background-color: rgba(4, 12, 10, 0.42) !important;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
            color: rgba(255, 255, 255, 0.94) !important;
        }

        .pm-topbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1.25rem;
            margin-bottom: 1.72rem;
        }
        .pm-search-pill {
            width: min(460px, 100%);
            min-height: 46px;
            display: flex;
            align-items: center;
            gap: 0.72rem;
            padding: 0 1.05rem;
            border-radius: 999px;
            border: 1px solid rgba(255, 255, 255, 0.76);
            background: rgba(255, 255, 255, 0.48);
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.65), 0 12px 28px rgba(32, 52, 56, 0.07);
            color: #829096;
            font-size: 0.94rem;
            font-weight: 560;
        }
        .pm-top-icons { display: flex; gap: 0.72rem; }
        .pm-icon-button {
            width: 44px;
            height: 44px;
            display: grid;
            place-items: center;
            border-radius: 50%;
            border: 1px solid rgba(255, 255, 255, 0.75);
            background: rgba(255, 255, 255, 0.56);
            box-shadow: 0 14px 30px rgba(26, 49, 55, 0.10), inset 0 1px 0 rgba(255,255,255,0.75);
            color: #22332f;
            font-size: 1.05rem;
        }

        .pm-hero {
            margin: 0 0 1.55rem;
            padding: 0.35rem 0 0;
        }
        .pm-eyebrow { display: none; }
        .pm-title {
            color: #101513;
            font-size: clamp(3rem, 5.1vw, 5.15rem);
            font-weight: 850;
            letter-spacing: -0.085em;
            line-height: 0.9;
            margin: 0;
        }
        .pm-subtitle {
            color: #68777c;
            font-size: clamp(1rem, 1.55vw, 1.22rem);
            font-weight: 540;
            margin-top: 0.85rem;
        }
        .pm-overview { display: none; }
        .pm-hero-panel { display: none; }

        .pm-section-label {
            color: #415651;
            font-size: 0.78rem;
            font-weight: 820;
            letter-spacing: 0.13em;
            margin: 0.2rem 0 0.85rem;
            text-transform: uppercase;
        }

        div[data-testid="stMetric"] {
            min-height: 126px;
            padding: 1.15rem 1.08rem 1rem;
            border: 1px solid rgba(13, 28, 27, 0.055);
            border-radius: 22px;
            background: linear-gradient(145deg, rgba(255, 255, 255, 0.99), rgba(247, 250, 251, 0.93));
            box-shadow: var(--pm-card-shadow);
            backdrop-filter: blur(14px);
            -webkit-backdrop-filter: blur(14px);
        }
        div[data-testid="stMetric"]::before {
            content: "Live";
            float: right;
            border-radius: 999px;
            padding: 0.18rem 0.46rem;
            background: rgba(50, 89, 75, 0.08);
            color: #5d716a;
            font-size: 0.64rem;
            font-weight: 800;
            letter-spacing: 0.04em;
        }
        div[data-testid="stMetricLabel"] p {
            color: var(--pm-muted);
            font-size: 0.76rem;
            font-weight: 760;
            letter-spacing: 0.01em;
        }
        div[data-testid="stMetricValue"] {
            color: #121817;
            font-weight: 850;
            letter-spacing: -0.05em;
        }

        .pm-card {
            margin: 1.75rem 0 0;
            padding: 1.5rem;
            border: 1px solid rgba(17, 35, 34, 0.065);
            border-radius: 22px;
            background: rgba(255, 255, 255, 0.88);
            box-shadow: var(--pm-card-shadow);
            backdrop-filter: blur(14px) saturate(1.12);
            -webkit-backdrop-filter: blur(14px) saturate(1.12);
        }
        .pm-card h2, .pm-card h3 { margin-top: 0; color: #17201d; letter-spacing: -0.04em; }

        [data-testid="stDataFrame"] {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(18, 31, 32, 0.07);
            box-shadow: 0 12px 30px rgba(24, 42, 45, 0.075);
            background: #ffffff;
        }
        [data-testid="stDataFrame"] div[role="grid"] { background: #ffffff; color: #202827; }
        [data-testid="stDataFrame"] [role="columnheader"] {
            background: #f1f4f5 !important;
            color: #33413f !important;
            font-weight: 760 !important;
        }
        [data-testid="stDataFrame"] [role="row"] { border-bottom-color: rgba(20, 34, 36, 0.06) !important; }

        .stPlotlyChart {
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid rgba(20, 34, 36, 0.05);
            background: rgba(255, 255, 255, 0.65);
        }
        .stDownloadButton button, .stButton button {
            border: 1px solid rgba(255, 255, 255, 0.48);
            border-radius: 16px;
            background: linear-gradient(135deg, #304a43, #14201d);
            color: #ffffff;
            box-shadow: 0 12px 28px rgba(11, 31, 26, 0.18);
        }

        @media (max-width: 980px) {
            .block-container { padding: 1.35rem 1rem 2rem; margin-top: 0.5rem; border-radius: 22px; }
            section[data-testid="stSidebar"] { width: 19rem !important; padding-left: 0.8rem; }
            .pm-topbar { align-items: flex-start; flex-direction: column; }
            .pm-title { font-size: clamp(2.4rem, 14vw, 3.6rem); }
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
        <div class="pm-sidebar-menu">
            <div class="pm-menu-item is-active">Dashboard</div>
            <div class="pm-menu-item">Price Table</div>
            <div class="pm-menu-item">Gap Analysis</div>
            <div class="pm-menu-item">Trend Chart</div>
            <div class="pm-menu-item">Settings</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dashboard_header() -> None:
    st.markdown(
        f"""
        <div class="pm-topbar">
            <div class="pm-search-pill">⌕ <span>Search country, brand, SKU...</span></div>
            <div class="pm-top-icons">
                <div class="pm-icon-button">◔</div>
                <div class="pm-icon-button">⚙</div>
                <div class="pm-icon-button">●</div>
            </div>
        </div>
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
            selected = st.sidebar.multiselect(label, options=options)
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
        return pd.DataFrame(columns=TABLE_COLUMNS)

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
        return pd.DataFrame(columns=TABLE_COLUMNS)

    display = pd.DataFrame(index=gap_df.index)
    display["crawl_time"] = gap_df["crawl_date"].apply(format_date)
    display["country"] = gap_df["Country"]
    display["brand"] = gap_df["Brand"]
    display["model"] = gap_df["SKU"]
    display["memory"] = gap_df["Memory"]
    display["Daraz Effective Price"] = gap_df["Daraz Price"].apply(format_price).fillna("")
    display["Competitor Platform"] = gap_df["Competitor Platform"]
    display["Competitor Effective Price"] = gap_df["Competitor Price"].apply(format_price).fillna("")
    display["product_url"] = coalesce_text(
        gap_df.get("competitor_product_url", pd.Series("", index=gap_df.index)),
        gap_df.get("daraz_product_url", pd.Series("", index=gap_df.index)),
    )

    sort_display_cols = available_columns(
        ["crawl_time", "country", "brand", "model", "memory", "Competitor Platform"], display
    )
    if sort_display_cols:
        display = display.sort_values(
            sort_display_cols, ascending=[False] + [True] * (len(sort_display_cols) - 1)
        )
    return display[TABLE_COLUMNS]

def latest_platform_rows(
    df: pd.DataFrame,
    group_cols: list[str],
    selected_cols: list[str],
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=selected_cols)

    existing_selected_cols = available_columns(selected_cols, df)
    sort_cols = available_columns(["crawl_datetime"], df) + ["effective_price"]
    sorted_df = df[existing_selected_cols].copy()
    if sort_cols:
        sorted_df = sorted_df.sort_values(
            sort_cols,
            ascending=[False if col == "crawl_datetime" else True for col in sort_cols],
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

    working = add_dashboard_join_fields(df.dropna(subset=["effective_price"]))
    if working.empty:
        return pd.DataFrame(columns=RAW_GAP_COLUMNS)

    working["__platform_key"] = working["platform"].apply(normalized_platform)
    join_cols = ["join_date", "join_country", "join_brand", "join_model", "join_memory"]
    display_key_cols = ["country", "brand", "model", "memory"]
    competitor_keys = [platform.casefold() for platform in COMPETITOR_PLATFORMS]
    selected_cols = join_cols + display_key_cols + ["__platform_key", "effective_price"]
    selected_cols += available_columns(["crawl_datetime", "crawl_date", "product_url"], working)

    daraz = latest_platform_rows(
        working[working["__platform_key"] == DARAZ_PLATFORM.casefold()],
        join_cols + ["__platform_key"],
        selected_cols,
    ).rename(
        columns={
            "effective_price": "Daraz Price",
            "product_url": "daraz_product_url",
            "crawl_datetime": "daraz_crawl_datetime",
            "crawl_date": "daraz_crawl_date",
        }
    )

    competitors = latest_platform_rows(
        working[working["__platform_key"].isin(competitor_keys)],
        join_cols + ["__platform_key"],
        selected_cols,
    ).rename(
        columns={
            "__platform_key": "Competitor Platform",
            "effective_price": "Competitor Price",
            "product_url": "competitor_product_url",
            "crawl_datetime": "competitor_crawl_datetime",
            "crawl_date": "competitor_crawl_date",
        }
    )

    if competitors.empty or daraz.empty:
        return pd.DataFrame(columns=RAW_GAP_COLUMNS)

    gap = daraz.merge(competitors, on=join_cols, how="inner", suffixes=("", "_competitor"))
    if gap.empty:
        return pd.DataFrame(columns=RAW_GAP_COLUMNS)

    gap["crawl_date"] = gap.get(
        "daraz_crawl_date", gap.get("join_date", pd.Series(pd.NaT, index=gap.index))
    )
    gap["crawl_datetime"] = gap.get(
        "daraz_crawl_datetime", pd.Series(pd.NaT, index=gap.index)
    )
    gap["Gap Amount"] = gap["Daraz Price"] - gap["Competitor Price"]
    gap["Gap %"] = gap["Gap Amount"] / gap["Daraz Price"]
    gap["Alert"] = gap["Gap %"].apply(alert_level)
    gap["__alert_sort"] = gap["Alert"].map({"Red": 0, "Orange": 1, "Green": 2}).fillna(3)

    latest_sort_cols = available_columns(["crawl_date", "crawl_datetime"], gap)
    if latest_sort_cols:
        gap = gap.sort_values(
            latest_sort_cols,
            ascending=[False] * len(latest_sort_cols),
            na_position="last",
        )
        gap = gap.groupby(join_cols + ["Competitor Platform"], dropna=False).head(1)

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
        formatted["Competitor Platform"] = (
            gap_df["Competitor Platform"] if "Competitor Platform" in gap_df.columns else ""
        )
        formatted["Competitor Effective Price"] = (
            gap_df["Competitor Price"].apply(format_price)
            if "Competitor Price" in gap_df.columns
            else ""
        )
        formatted["Gap Amount"] = (
            gap_df["Gap Amount"].apply(format_price) if "Gap Amount" in gap_df.columns else ""
        )
        formatted["Gap %"] = gap_df["Gap %"].apply(format_gap_pct) if "Gap %" in gap_df.columns else ""
        formatted["Alert"] = gap_df["Alert"] if "Alert" in gap_df.columns else ""
        return formatted[available_columns(GAP_COLUMNS, formatted)]
    except Exception:  # noqa: BLE001 - display formatting should never crash the dashboard.
        return gap_df[available_columns(GAP_COLUMNS, gap_df)]


def render_kpis(latest_df: pd.DataFrame, gap_df: pd.DataFrame) -> None:
    sku_cols = available_columns(SKU_COLUMNS, latest_df)
    active_latest = latest_df.copy()
    if "stock_status" in active_latest.columns:
        active_latest = active_latest[~active_latest["stock_status"].str.casefold().isin(OUT_OF_STOCK_STATUSES)]

    latest_crawl = "—"
    if "crawl_datetime" in latest_df.columns and not latest_df["crawl_datetime"].dropna().empty:
        latest_crawl = latest_df["crawl_datetime"].max().strftime("%Y-%m-%d %H:%M")
    elif "crawl_date" in latest_df.columns and not latest_df["crawl_date"].dropna().empty:
        latest_value = latest_df["crawl_date"].max()
        latest_crawl = latest_value.isoformat() if isinstance(latest_value, date) else str(latest_value)
    elif "crawl_time" in latest_df.columns and not latest_df["crawl_time"].dropna().empty:
        latest_crawl = str(latest_df["crawl_time"].max())

    total_active_skus = active_latest.drop_duplicates(sku_cols).shape[0] if sku_cols else len(active_latest)
    if "Daraz Effective Price" in latest_df.columns:
        daraz_skus = latest_df.dropna(subset=["Daraz Effective Price"]).drop_duplicates(sku_cols).shape[0]
    else:
        daraz_skus = count_platform_skus(latest_df, [DARAZ_PLATFORM])
    if "Competitor Platform" in latest_df.columns:
        competitor_rows = latest_df[latest_df["Competitor Platform"].fillna("").astype(str).str.strip().ne("")]
        competitor_skus = competitor_rows.drop_duplicates(sku_cols).shape[0] if sku_cols else len(competitor_rows)
    else:
        competitor_skus = count_platform_skus(latest_df, COMPETITOR_PLATFORMS)
    red_alerts = int((gap_df.get("Alert", pd.Series(dtype=str)) == "Red").sum())
    average_gap = gap_df["Gap %"].mean() * 100 if "Gap %" in gap_df.columns and not gap_df.empty else 0

    cols = st.columns(6)
    st.markdown("<div class='pm-section-label'>Overview</div>", unsafe_allow_html=True)

    metrics = [
        ("Latest crawl time", latest_crawl),
        ("Total active SKUs", f"{total_active_skus:,}"),
        ("Daraz SKUs", f"{daraz_skus:,}"),
        ("Competitor SKUs", f"{competitor_skus:,}"),
        ("Red alerts", f"{red_alerts:,}"),
        ("Avg gap", f"{average_gap:.2f}%"),
    ]
    for col, (label, value) in zip(cols, metrics, strict=False):
        col.metric(label, value)


def count_platform_skus(df: pd.DataFrame, platforms: list[str]) -> int:
    if df.empty or "platform" not in df.columns:
        return 0
    sku_cols = available_columns(SKU_COLUMNS, df)
    platform_values = [platform.casefold() for platform in platforms]
    selected = df[df["platform"].str.casefold().isin(platform_values)]
    return selected.drop_duplicates(sku_cols).shape[0] if sku_cols else len(selected)


def render_gap_chart(filtered: pd.DataFrame) -> None:
    st.markdown("<div class='pm-card'>", unsafe_allow_html=True)
    st.subheader("Price Trend Chart")

    required = {"crawl_date", "effective_price", "platform"}
    if not required.issubset(filtered.columns):
        st.info("Trend chart requires crawl_date, effective_price, and platform columns.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    chart_df = filtered.dropna(subset=["crawl_date", "effective_price"]).copy()
    if chart_df.empty:
        st.info("No numeric price data available for the selected filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    chart_df["crawl_date_display"] = chart_df["crawl_date"].apply(format_date)
    chart_df["platform_display"] = chart_df["platform"].apply(normalized_platform)

    fig = px.line(
        chart_df.sort_values("crawl_date"),
        x="crawl_date_display",
        y="effective_price",
        color="platform_display",
        color_discrete_map=PLATFORM_COLORS,
        markers=True,
        hover_data=available_columns(["country", "brand", "model", "memory", "stock_status"], chart_df),
        labels={
            "crawl_date_display": "crawl_date",
            "effective_price": "effective_price",
            "platform_display": "platform",
        },
        template="plotly_white",
    )
    fig.update_layout(
        plot_bgcolor="rgba(255, 255, 255, 0.52)",
        paper_bgcolor="rgba(255, 255, 255, 0)",
        font_color="#111111",
        legend_title_text="Platform",
        margin=dict(l=10, r=10, t=20, b=10),
    )
    st.plotly_chart(fig, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_data_section(title: str, df: pd.DataFrame, columns: list[str] | None = None) -> None:
    st.markdown("<div class='pm-card'>", unsafe_allow_html=True)
    st.subheader(title)
    display_df = df[available_columns(columns, df)] if columns else df
    dataframe_to_render = display_df

    if "Alert" in display_df.columns:
        try:
            dataframe_to_render = display_df.style.map(style_alert_level, subset=["Alert"])
        except Exception as exc:  # noqa: BLE001 - styling should not block dashboard data rendering.
            st.warning(f"{title} styling could not be applied; showing the table without styling. {exc}")

    try:
        st.dataframe(dataframe_to_render, use_container_width=True, hide_index=True)
    except Exception as exc:  # noqa: BLE001 - styling should never block the table itself.
        if dataframe_to_render is not display_df:
            st.warning(f"{title} styled rendering failed; showing the table without styling. {exc}")
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            raise
    st.markdown("</div>", unsafe_allow_html=True)


def style_alert_level(value: object) -> str:
    colors = {
        "Red": "background-color: #c1121f; color: #ffffff; font-weight: 700;",
        "Orange": "background-color: #f77f00; color: #ffffff; font-weight: 700;",
        "Green": "background-color: #2d6a4f; color: #ffffff; font-weight: 700;",
    }
    return colors.get(str(value), "")


def render_downloads(latest_df: pd.DataFrame, gap_df: pd.DataFrame) -> None:
    st.markdown("<div class='pm-card'>", unsafe_allow_html=True)
    st.subheader("Download")
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
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="Mob Price Monitor", layout="wide", page_icon="📱")
    inject_styles()

    render_sidebar_chrome()
    render_dashboard_header()

    if not require_password():
        st.stop()

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
    formatted_gap_df = format_gap_table(gap_df)

    st.markdown("---")
    render_kpis(latest_df, gap_df)

    render_data_section("Latest Price Table", latest_df, TABLE_COLUMNS)
    render_data_section("Price Gap Analysis", formatted_gap_df, GAP_COLUMNS)
    render_gap_chart(filtered)

    alert_df = (
        formatted_gap_df[formatted_gap_df["Alert"].isin(["Red", "Orange"])]
        if "Alert" in formatted_gap_df.columns
        else formatted_gap_df
    )
    render_data_section("Alert Section — Red and Orange", alert_df, GAP_COLUMNS)

    out_of_stock_df = latest_df.copy()
    if "stock_status" in out_of_stock_df.columns:
        out_of_stock_df = out_of_stock_df[
            out_of_stock_df["stock_status"].str.casefold().isin(OUT_OF_STOCK_STATUSES)
        ]
    else:
        out_of_stock_df = out_of_stock_df.iloc[0:0]
    render_data_section("Out of Stock Section", out_of_stock_df, TABLE_COLUMNS)

    render_downloads(latest_df, formatted_gap_df)


if __name__ == "__main__":
    main()

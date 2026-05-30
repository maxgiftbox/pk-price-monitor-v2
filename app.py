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
SKU_MASTER_JOIN_COLUMNS = [
    "platform",
    "country",
    "brand",
    "model",
    "memory",
    "product_url",
]
SKU_MASTER_STANDARD_COLUMNS = ["standard_model", "standard_memory"]
COMPETITOR_PLATFORMS = ["PriceOye", "Pickaboo"]
DARAZ_PLATFORM = "Daraz"
OUT_OF_STOCK_STATUSES = {"out_of_stock", "unavailable"}
TABLE_COLUMNS = [
    "country",
    "brand",
    "model",
    "memory",
    "platform",
    "original_price",
    "product_price",
    "voucher_amount",
    "effective_price",
    "stock_status",
    "product_url",
    "crawl_time",
]
GAP_COLUMNS = [
    "country",
    "brand",
    "model",
    "memory",
    "daraz_effective_price",
    "lowest_competitor_platform",
    "lowest_competitor_price",
    "price_gap",
    "gap_pct",
    "alert_level",
]


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
        enriched = apply_sku_master_match(enriched, sku_master_df, ["product_url"])
        unmatched_mask = missing_standard_mask(enriched)
        if unmatched_mask.any():
            fallback_keys = [col for col in SKU_MASTER_JOIN_COLUMNS if col in enriched.columns]
            if fallback_keys and set(fallback_keys).issubset(sku_master_df.columns):
                fallback_matches = apply_sku_master_match(
                    enriched.loc[unmatched_mask].copy(),
                    sku_master_df,
                    fallback_keys,
                )
                for col in SKU_MASTER_STANDARD_COLUMNS:
                    enriched.loc[unmatched_mask, col] = coalesce_text(
                        fallback_matches[col].reset_index(drop=True),
                        enriched.loc[unmatched_mask, col].reset_index(drop=True),
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
        :root { --radius: 22px; }
        .stApp { background: #f5f5f7; color: #111111; }
        h1, h2, h3 { letter-spacing: -0.04em; color: #111111; }
        section[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e5e5e7; }
        div[data-testid="stMetric"] {
            background: #ffffff;
            border: 1px solid #e5e5e7;
            border-radius: var(--radius);
            padding: 18px 18px 14px 18px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.04);
        }
        div[data-testid="stMetricLabel"] p { color: #6e6e73; font-size: 0.86rem; }
        div[data-testid="stMetricValue"] { color: #111111; }
        .pm-card {
            background: #ffffff;
            border: 1px solid #e5e5e7;
            border-radius: var(--radius);
            padding: 22px;
            margin: 10px 0 22px 0;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.04);
        }
        .pm-eyebrow { color: #6e6e73; font-size: 0.85rem; letter-spacing: 0.08em; text-transform: uppercase; }
        .pm-title { font-size: 2.8rem; font-weight: 760; letter-spacing: -0.07em; margin-bottom: 0; }
        .pm-subtitle { color: #6e6e73; font-size: 1.05rem; margin-top: 4px; }
        .tag-red, .tag-brown, .tag-green {
            border-radius: 999px;
            color: #ffffff;
            display: inline-block;
            font-size: 0.78rem;
            font-weight: 700;
            padding: 4px 10px;
        }
        .tag-red { background: #c1121f; }
        .tag-brown { background: #8b5e34; }
        .tag-green { background: #2d6a4f; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def available_columns(columns: list[str], df: pd.DataFrame) -> list[str]:
    return [col for col in columns if col in df.columns]


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    st.sidebar.header("Filters")

    filter_specs = [
        ("country", "Country"),
        ("brand", "Brand"),
        ("model", "Model / SKU"),
        ("memory", "Memory"),
        ("platform", "Platform"),
        ("stock_status", "Stock Status"),
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


def latest_price_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sort_col = "crawl_datetime" if "crawl_datetime" in df.columns else None
    working = df.copy()
    if sort_col:
        working = working.sort_values(sort_col)

    group_cols = available_columns(["country", "platform", "brand", "model", "memory", "product_url"], working)
    if group_cols and sort_col:
        working = working.groupby(group_cols, dropna=False).tail(1)

    if sort_col:
        working = working.sort_values(sort_col, ascending=False, na_position="last")

    return working


def calculate_gap_table(df: pd.DataFrame) -> pd.DataFrame:
    required = set(SKU_COLUMNS + ["platform", "effective_price"])
    if df.empty or not required.issubset(df.columns):
        return pd.DataFrame(columns=GAP_COLUMNS)

    group_cols = SKU_COLUMNS + (["crawl_date"] if "crawl_date" in df.columns else [])
    working = df.dropna(subset=["effective_price"]).copy()
    if working.empty:
        return pd.DataFrame(columns=GAP_COLUMNS)

    daraz = (
        working[working["platform"].str.casefold() == DARAZ_PLATFORM.casefold()]
        .groupby(group_cols, dropna=False, as_index=False)["effective_price"]
        .min()
        .rename(columns={"effective_price": "daraz_effective_price"})
    )

    competitor_mask = working["platform"].str.casefold().isin(
        [platform.casefold() for platform in COMPETITOR_PLATFORMS]
    )
    competitors = working[competitor_mask].copy()
    if competitors.empty or daraz.empty:
        return pd.DataFrame(columns=GAP_COLUMNS)

    competitors = competitors.sort_values(group_cols + ["effective_price"], na_position="last")
    competitors = competitors.groupby(group_cols, dropna=False).head(1)
    competitors = competitors.rename(
        columns={
            "platform": "lowest_competitor_platform",
            "effective_price": "lowest_competitor_price",
        }
    )[group_cols + ["lowest_competitor_platform", "lowest_competitor_price"]]

    gap = daraz.merge(competitors, on=group_cols, how="inner")
    gap["price_gap"] = gap["daraz_effective_price"] - gap["lowest_competitor_price"]
    gap["gap_pct"] = gap["price_gap"] / gap["daraz_effective_price"]
    gap["alert_level"] = gap["gap_pct"].apply(alert_level)

    if "crawl_date" in gap.columns:
        gap = gap.sort_values(["crawl_date", "gap_pct"], ascending=[False, False])
        gap = gap.groupby(SKU_COLUMNS, dropna=False).head(1)

    return gap[available_columns(GAP_COLUMNS, gap)]


def alert_level(gap_pct: float) -> str:
    if pd.isna(gap_pct):
        return "Green"
    if gap_pct > 0.05:
        return "Red"
    if gap_pct >= 0.01:
        return "Brown"
    return "Green"


def format_gap_table(gap_df: pd.DataFrame) -> pd.DataFrame:
    formatted = gap_df.copy()
    for col in ["daraz_effective_price", "lowest_competitor_price", "price_gap"]:
        if col in formatted.columns:
            formatted[col] = formatted[col].round(2)
    if "gap_pct" in formatted.columns:
        formatted["gap_pct"] = (formatted["gap_pct"] * 100).round(2)
    return formatted


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

    total_active_skus = active_latest.drop_duplicates(sku_cols).shape[0] if sku_cols else len(active_latest)
    daraz_skus = count_platform_skus(latest_df, [DARAZ_PLATFORM])
    competitor_skus = count_platform_skus(latest_df, COMPETITOR_PLATFORMS)
    red_alerts = int((gap_df.get("alert_level", pd.Series(dtype=str)) == "Red").sum())
    average_gap = gap_df["gap_pct"].mean() * 100 if "gap_pct" in gap_df.columns and not gap_df.empty else 0

    cols = st.columns(6)
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

    fig = px.line(
        chart_df.sort_values("crawl_date"),
        x="crawl_date",
        y="effective_price",
        color="platform",
        markers=True,
        hover_data=available_columns(["country", "brand", "model", "memory", "stock_status"], chart_df),
        template="plotly_white",
    )
    fig.update_layout(
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
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
    if "alert_level" in display_df.columns:
        st.dataframe(
            display_df.style.applymap(style_alert_level, subset=["alert_level"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    st.markdown("</div>", unsafe_allow_html=True)


def style_alert_level(value: object) -> str:
    colors = {
        "Red": "background-color: #c1121f; color: #ffffff; font-weight: 700;",
        "Brown": "background-color: #8b5e34; color: #ffffff; font-weight: 700;",
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
        label="Download gap table CSV",
        data=gap_df.to_csv(index=False).encode("utf-8"),
        file_name="daraz_competitor_gap_table.csv",
        mime="text/csv",
        use_container_width=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    st.set_page_config(page_title="Mob Price Monitor", layout="wide", page_icon="📱")
    inject_styles()

    st.markdown("<div class='pm-eyebrow'>Mob Price Monitor</div>", unsafe_allow_html=True)
    st.markdown("<div class='pm-title'>Price Monitor</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='pm-subtitle'>SKU-level Daraz vs PriceOye / Pickaboo pricing intelligence.</div>",
        unsafe_allow_html=True,
    )

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
    latest_df = latest_price_table(filtered)
    gap_df = calculate_gap_table(filtered)
    formatted_gap_df = format_gap_table(gap_df)

    st.markdown("---")
    render_kpis(latest_df, gap_df)

    render_data_section("Latest Price Table", latest_df, TABLE_COLUMNS)
    render_data_section("Daraz vs Competitor Gap Table", formatted_gap_df, GAP_COLUMNS)
    render_gap_chart(filtered)

    alert_df = (
        formatted_gap_df[formatted_gap_df["alert_level"].isin(["Red", "Brown"])]
        if "alert_level" in formatted_gap_df.columns
        else formatted_gap_df
    )
    if "gap_pct" in alert_df.columns:
        alert_df = alert_df.sort_values("gap_pct", ascending=False)
    render_data_section("Alert Section — Red and Brown", alert_df, GAP_COLUMNS)

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

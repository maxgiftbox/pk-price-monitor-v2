import json
import os

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SHEET_NAME = "Mob Price Monitor"
PRICE_DAILY_TAB = "price_daily"
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@st.cache_resource
def get_sheet_client() -> gspread.Client:
    raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
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

    if "crawl_date" in df.columns:
        df["crawl_date"] = pd.to_datetime(df["crawl_date"], errors="coerce").dt.date

    for col in ["platform", "brand", "model", "memory", "product_url", "stock_status"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()

    st.sidebar.header("Filters")

    for col in ["platform", "brand", "model", "memory"]:
        if col in filtered.columns:
            options = sorted([x for x in filtered[col].dropna().unique().tolist() if x])
            selected = st.sidebar.multiselect(f"{col.title()}", options=options)
            if selected:
                filtered = filtered[filtered[col].isin(selected)]

    if "crawl_date" in filtered.columns and not filtered["crawl_date"].dropna().empty:
        min_date = filtered["crawl_date"].min()
        max_date = filtered["crawl_date"].max()
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

    sort_cols = [c for c in ["crawl_date", "crawl_time"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols)

    group_cols = [c for c in ["platform", "brand", "model", "memory", "product_url"] if c in df.columns]
    if not group_cols:
        return df

    latest_idx = df.groupby(group_cols, dropna=False).tail(1).index
    return df.loc[latest_idx].sort_values(sort_cols, ascending=False)


def main() -> None:
    st.set_page_config(page_title="Mob Price Monitor", layout="wide")
    st.title("Mob Price Monitor Dashboard")

    try:
        df = load_price_data()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to load Google Sheet data: {exc}")
        st.stop()

    if df.empty:
        st.info("No rows found in price_daily.")
        st.stop()

    filtered = apply_filters(df)

    st.subheader("Latest Prices")
    latest_df = latest_price_table(filtered)
    st.dataframe(latest_df, use_container_width=True)

    st.subheader("Price Trend")
    chart_df = filtered.copy()
    if "crawl_date" in chart_df.columns and "product_price" in chart_df.columns:
        chart_df["crawl_date"] = pd.to_datetime(chart_df["crawl_date"], errors="coerce")
        chart_df["product_price_num"] = (
            chart_df["product_price"].astype(str).str.replace(r"[^0-9.]", "", regex=True)
        )
        chart_df["product_price_num"] = pd.to_numeric(chart_df["product_price_num"], errors="coerce")
        chart_df = chart_df.dropna(subset=["crawl_date", "product_price_num"])

        if not chart_df.empty:
            st.line_chart(
                chart_df,
                x="crawl_date",
                y="product_price_num",
                color="model" if "model" in chart_df.columns else None,
            )
        else:
            st.info("No numeric price data available for trend chart.")

    st.subheader("Download Data")
    csv_data = filtered.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="Download filtered CSV",
        data=csv_data,
        file_name="price_daily_filtered.csv",
        mime="text/csv",
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Materialize auditable daily Social Rating V1.0 rows in Google Sheets."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import gspread
import pandas as pd
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dashboard-v2" / "api"))
from src.data_sources.social_intelligence import SocialIntelligenceRepository  # noqa: E402
from src.services.social_intelligence import _filter, _rating_day  # noqa: E402


TAB = "social_brand_ratings_daily"
FIELDS = [
    "rating_date", "country", "brand", "window_days", "platform_scope", "monitor_scope",
    "voice_posts", "earned_mentions", "total_views", "total_likes", "median_likes_per_post",
    "activity_score", "reach_score", "engagement_score", "earned_score", "social_rating",
    "country_rank", "rank_change", "score_change", "views_coverage", "engagement_coverage",
    "confidence_level", "calculated_at", "scoring_version",
]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.readonly"]


def client() -> gspread.Client:
    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    if raw:
        credentials = Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    elif path:
        credentials = Credentials.from_service_account_file(path, scopes=SCOPES)
    else:
        raise RuntimeError("Google credentials are not configured")
    return gspread.authorize(credentials)


def spreadsheet(gc: gspread.Client) -> gspread.Spreadsheet:
    sheet_id = os.getenv("SOCIAL_INTELLIGENCE_GOOGLE_SHEET_ID") or os.getenv("GOOGLE_SHEET_ID")
    return gc.open_by_key(sheet_id) if sheet_id else gc.open(os.getenv("GOOGLE_SHEET_NAME", "Mob Price Monitor"))


def rows_for(data: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, windows: list[int]) -> list[dict]:
    generated = datetime.now(timezone.utc).isoformat()
    result: list[dict] = []
    for country in sorted(data["country"].dropna().astype(str).unique()):
        country_frame = _filter(data, {"country": [country]})
        prior: dict[tuple[int, str], dict] = {}
        for window in windows:
            for day in pd.date_range(start, end, freq="D", tz="UTC"):
                for item in _rating_day(country_frame, day, window):
                    previous = prior.get((window, item["brand"]))
                    result.append({
                        "rating_date": item["date"], "country": country, "brand": item["brand"], "window_days": window,
                        "platform_scope": "All", "monitor_scope": "All", "voice_posts": item["voicePosts"],
                        "earned_mentions": item["earnedMentions"], "total_views": item["totalViews"], "total_likes": item["totalLikes"],
                        "median_likes_per_post": item["medianLikesPerPost"] if item["medianLikesPerPost"] is not None else "",
                        "activity_score": item["activityScore"], "reach_score": item["reachScore"] if item["reachScore"] is not None else "",
                        "engagement_score": item["engagementScore"], "earned_score": item["earnedScore"], "social_rating": item["socialRating"],
                        "country_rank": item["rank"], "rank_change": previous["rank"] - item["rank"] if previous else 0,
                        "score_change": round(item["socialRating"] - previous["socialRating"], 1) if previous else 0,
                        "views_coverage": item["viewsCoverage"], "engagement_coverage": item["engagementCoverage"],
                        "confidence_level": item["confidenceLevel"], "calculated_at": generated, "scoring_version": "1.0",
                    })
                    prior[(window, item["brand"])] = item
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--windows", default="7,14,30")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT.parent / ".env")
    book = spreadsheet(client())
    master = pd.DataFrame(book.worksheet(os.getenv("SOCIAL_INTELLIGENCE_WORKSHEET", "social_intelligence_master")).get_all_records())
    data = SocialIntelligenceRepository._prepare(master)
    dated = data["published_at"].dropna()
    start = pd.Timestamp(args.start_date, tz="UTC") if args.start_date else dated.min().normalize()
    end = pd.Timestamp(args.end_date, tz="UTC") if args.end_date else dated.max().normalize()
    records = rows_for(data, start, end, [int(value) for value in args.windows.split(",")])
    if args.dry_run:
        print(json.dumps({"rows": len(records), "start": start.date().isoformat(), "end": end.date().isoformat()}, indent=2))
        return
    try:
        worksheet = book.worksheet(TAB)
        headers = worksheet.row_values(1)
        if headers != FIELDS:
            raise RuntimeError(f"{TAB} headers do not match Rating V1.0 contract")
        existing = worksheet.get_all_records()
    except gspread.WorksheetNotFound:
        worksheet = book.add_worksheet(title=TAB, rows=max(1000, len(records) + 50), cols=len(FIELDS))
        worksheet.append_row(FIELDS, value_input_option="RAW")
        existing = []
    key = lambda row: (str(row.get("rating_date", "")), str(row.get("country", "")), str(row.get("brand", "")), str(row.get("window_days", "")), str(row.get("platform_scope", "")), str(row.get("monitor_scope", "")))
    existing_keys = {key(row) for row in existing}
    new_rows = [row for row in records if key(row) not in existing_keys]
    if new_rows:
        worksheet.append_rows([[row.get(field, "") for field in FIELDS] for row in new_rows], value_input_option="RAW")
    print(json.dumps({"calculated": len(records), "appended": len(new_rows), "worksheet": TAB, "start": start.date().isoformat(), "end": end.date().isoformat()}, indent=2))


if __name__ == "__main__":
    main()

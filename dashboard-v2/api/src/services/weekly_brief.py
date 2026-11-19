from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
import html
import re
from typing import Any

import pandas as pd

COUNTRY_NAMES = {"PK": "Pakistan", "BD": "Bangladesh"}
BRAND_PARENT = {"redmi": "xiaomi", "poco": "xiaomi"}
BRAND_NAMES = {"samsung": "Samsung", "xiaomi": "Xiaomi", "oppo": "OPPO", "tecno": "TECNO", "vivo": "vivo", "realme": "realme", "honor": "HONOR", "infinix": "Infinix", "nubia": "Nubia", "itel": "itel", "apple": "Apple", "oneplus": "OnePlus", "motorola": "Motorola"}
TOPIC_PATTERNS = [
    ("Original / genuine", r"original|genuine|authentic|sealed|pin pack|intact"),
    ("Delivery", r"deliver|fast|late|on time"), ("Packaging", r"pack"),
    ("Price / value", r"price|value|cheap|discount|voucher"), ("Warranty", r"warrant"),
    ("Gifts", r"gift|free"), ("Battery / charging", r"battery|charg"),
    ("Repeated \"good product\" text", r"(?:good products?\s*){2,}"),
]
EXCLUDED_MARKET_CATEGORIES = {"mobile", "electronics", "brand / marketing"}


def normalize_brands(value: Any) -> list[str]:
    result: list[str] = []
    for part in str(value or "").split(";"):
        key = BRAND_PARENT.get(part.strip().casefold(), part.strip().casefold())
        if key and key not in {"nan", "none", "other", "all brand", "all brands"} and key not in result:
            result.append(key)
    return result


def brand_name(key: str) -> str:
    return BRAND_NAMES.get(key, key[:1].upper() + key[1:])


def _first_sentence(value: Any, limit: int = 180) -> str:
    text = html.unescape(re.sub(r"\s+", " ", str(value or "")).strip())
    if not text:
        return ""
    protected = text
    for abbreviation in ("Rs.", "No.", "vs.", "Mr.", "Dr."):
        protected = protected.replace(abbreviation, abbreviation.replace(".", "<DOT>"))
    match = re.search(r"[.!?](?:\s|$)", protected)
    sentence = protected[:match.end()].replace("<DOT>", ".") if match else text
    return sentence if len(sentence) <= limit else sentence[:limit - 1].rstrip() + "…"


def _week(iso: str | None, available_dates: pd.Series) -> tuple[str, date, date]:
    if iso:
        match = re.fullmatch(r"(\d{4})-W(\d{2})", iso)
        if not match:
            raise ValueError("week must use YYYY-Www format")
        start = date.fromisocalendar(int(match.group(1)), int(match.group(2)), 1)
        return iso, start, start + timedelta(days=6)
    today = date.today()
    last_sunday = today - timedelta(days=today.weekday() + 1)
    valid = pd.to_datetime(available_dates, errors="coerce", utc=True).dropna()
    if not valid.empty:
        latest = valid.max().date()
        last_sunday = min(last_sunday, latest + timedelta(days=6 - latest.weekday()))
    start = last_sunday - timedelta(days=6)
    year, number, _ = start.isocalendar()
    return f"{year}-W{number:02d}", start, last_sunday


def _range(frame: pd.DataFrame, column: str, start: date, end: date) -> pd.DataFrame:
    values = pd.to_datetime(frame[column], errors="coerce", utc=True).dt.date
    return frame[(values >= start) & (values <= end)].copy()


def _variation(cur: int, prev: int) -> str:
    if prev == 0:
        return "from none last week" if cur else "held at 0"
    ratio = cur / prev
    if ratio >= 2.5: return "tripled"
    if ratio >= 1.8: return "doubled"
    if ratio <= .55: return "halved"
    if abs(cur - prev) < 3 and abs(ratio - 1) < .2: return ""
    return f"up from {prev}" if cur > prev else f"down from {prev}"


def _family(sku: str, brand: str) -> str:
    value = re.sub(r"\s+(?:\d+/\d+|\d+GB)$", "", sku, flags=re.IGNORECASE).strip()
    return re.sub(rf"^{re.escape(brand_name(brand))}\s+", "", value, flags=re.IGNORECASE)


def _consumer_rows(data: pd.DataFrame, country: str) -> pd.DataFrame:
    frame = data[data["venture"].astype(str).str.upper() == country].copy()
    if "review_status" in frame:
        frame = frame[frame["review_status"].astype(str).str.casefold() == "approved"]
    frame["brief_brand"] = frame["brand"].map(normalize_brands)
    frame = frame.explode("brief_brand")
    return frame[frame["brief_brand"].notna() & frame["brief_brand"].ne("")]


def _social_rows(data: pd.DataFrame, country: str) -> pd.DataFrame:
    frame = data[data["country"].astype(str).str.upper() == country].copy()
    if "quality_status" in frame:
        frame = frame[frame["quality_status"].astype(str).str.casefold() == "dashboard_ready"]
    frame["brief_brands"] = frame["brand"].map(normalize_brands)
    return frame


def _topic_counts(frame: pd.DataFrame) -> dict[str, int]:
    text = frame["review_content"].fillna("").astype(str)
    return {label: int(text.str.contains(pattern, case=False, regex=True).sum()) for label, pattern in TOPIC_PATTERNS}


def _daily(frame: pd.DataFrame, start: date) -> list[dict[str, Any]]:
    counts = Counter(pd.to_datetime(frame["created_at"], errors="coerce").dt.date.dropna())
    average = len(frame) / 7
    return [{"date": (start + timedelta(days=i)).isoformat(), "count": counts[start + timedelta(days=i)], "peak": bool(counts[start + timedelta(days=i)] >= average * 1.5 and counts[start + timedelta(days=i)] > 0)} for i in range(7)]


def _peak_text(daily: list[dict[str, Any]]) -> str:
    peaks = [item for item in daily if item["peak"]]
    if len(peaks) == 1:
        return f"Peak on {pd.Timestamp(peaks[0]['date']).strftime('%-d %b')} ({peaks[0]['count']})"
    if len(peaks) == 2:
        first, second = peaks
        a, b = pd.Timestamp(first["date"]), pd.Timestamp(second["date"])
        if (b - a).days == 1:
            return f"Peak on {a.strftime('%-d')}–{b.strftime('%-d %b')} ({first['count']} and {second['count']} a day)"
        return f"Two peaks: {a.strftime('%-d %b')} ({first['count']}) and {b.strftime('%-d %b')} ({second['count']})"
    return ""


def _brand_payloads(consumer: pd.DataFrame, cur_reviews: pd.DataFrame, prev_reviews: pd.DataFrame, cur_social: pd.DataFrame, prev_social: pd.DataFrame, start: date, country: str, total_reviews: int, total_posts: int) -> list[dict[str, Any]]:
    cur_expanded = cur_social.explode("brief_brands").rename(columns={"brief_brands": "brief_brand"})
    prev_expanded = prev_social.explode("brief_brands").rename(columns={"brief_brands": "brief_brand"})
    keys = set(cur_reviews["brief_brand"].dropna()) | set(prev_reviews["brief_brand"].dropna()) | set(cur_expanded["brief_brand"].dropna()) | set(prev_expanded["brief_brand"].dropna())
    payloads: list[dict[str, Any]] = []
    for key in keys:
        cr, pr = cur_reviews[cur_reviews["brief_brand"] == key], prev_reviews[prev_reviews["brief_brand"] == key]
        cs, ps = cur_expanded[cur_expanded["brief_brand"] == key], prev_expanded[prev_expanded["brief_brand"] == key]
        rated = cr[cr["rating_valid"]]
        negative = rated[rated["rating"].isin([1, 2, 3])].sort_values(["rating", "created_at"])
        likes = pd.to_numeric(cs["likes"], errors="coerce").fillna(0)
        total_likes, top_likes = int(likes.sum()), int(likes.max()) if not likes.empty else 0
        top_posts = [{"summary": _first_sentence(row.content_summary or row.title), "platform": row.platform, "date": pd.Timestamp(row.published_at).date().isoformat(), "likes": int(row.brief_likes), "url": row.source_url} for row in cs.assign(brief_likes=likes).sort_values(["brief_likes", "published_at"], ascending=[False, False]).head(3).itertuples()]
        negatives = [{"rating": int(row.rating), "sku": row.product_name, "text": row.review_content} for row in negative.itertuples()]
        sku_cur, sku_prev = Counter(cr["product_name"].fillna("").astype(str)), Counter(pr["product_name"].fillna("").astype(str))
        earlier = consumer[(consumer["brief_brand"] == key) & (pd.to_datetime(consumer["created_at"], errors="coerce").dt.date < start)]
        history = Counter(earlier["product_name"].fillna("").astype(str))
        sku_stats = [{"sku": sku, "cur": count, "prev": sku_prev[sku], "history": history[sku]} for sku, count in sku_cur.most_common() if sku]
        families: Counter[str] = Counter()
        for sku, count in sku_cur.items(): families[_family(sku, key)] += count
        family, family_count = families.most_common(1)[0] if families else ("", 0)
        payloads.append({"key": key, "name": brand_name(key), "reviews": len(cr), "reviews_prev": len(pr), "review_share": round(len(cr) / total_reviews, 4) if total_reviews else 0, "avg_rating": round(float(rated["rating"].mean()), 2) if not rated.empty else None, "negative": len(negative), "posts": len(cs), "posts_prev": len(ps), "post_share": round(len(cs) / total_posts, 4) if total_posts else 0, "likes": total_likes, "top_post_likes": top_likes, "viral_flag": bool(top_likes >= 10000 and total_likes and top_likes / total_likes >= .5), "own_posts": int(cs["account_type"].astype(str).str.casefold().eq("brand").sum()), "non_phone_reviews": int(cr["type"].astype(str).str.casefold().ne("phone").sum()) if "type" in cr else 0, "top_posts": top_posts, "negative_reviews": negatives, "sku_stats": sku_stats, "family": family, "family_count": family_count, "highlight": "", "shown": bool(len(cr) >= 2 or len(cs) >= 8)})
    payloads.sort(key=lambda item: (-item["reviews"], -item["posts"], item["name"].casefold()))
    eligible = [item for item in payloads if item["reviews"] >= 3 and item["avg_rating"] is not None]
    lowest = min((item["avg_rating"] for item in eligible), default=None)
    for item in payloads:
        sentences: list[str] = []
        first = [sku for sku in item["sku_stats"] if sku["history"] == 0]
        returned = [sku for sku in item["sku_stats"] if sku["prev"] == 0 and sku["cur"] >= 5 and sku["history"] > 0]
        if first: sentences.append(f"{first[0]['sku']} got its first reviews ({first[0]['cur']}).")
        if returned: sentences.append(f"{returned[0]['sku']} has {returned[0]['cur']} reviews, from none last week.")
        if not sentences and item["family_count"] >= 5 and item["reviews"] and item["family_count"] / item["reviews"] >= .4: sentences.append(f"{item['family']} has {item['family_count']} of the {item['reviews']} reviews.")
        if len(sentences) < 2 and item["reviews"] and item["non_phone_reviews"] / item["reviews"] >= .5:
            sentences.append("Accessories drive reviews: " + ", ".join(f"{sku['sku']} ({sku['cur']})" for sku in item["sku_stats"][:2]) + ".")
        if len(sentences) < 2 and item["negative_reviews"]:
            review = item["negative_reviews"][0]; quote = re.sub(r"\s+", " ", review["text"]).strip()[:60]
            sentences.append(f"{item['negative']} negative review{'s' if item['negative'] != 1 else ''}: {review['sku']} {review['rating']}★, \"{quote}\".")
        if len(sentences) < 2 and lowest is not None and item["avg_rating"] == lowest and lowest < 4.5: sentences.append("Lowest rating this week.")
        if len(sentences) < 2 and item["viral_flag"] and item["top_posts"]:
            post = item["top_posts"][0]; sentences.append(f"One {post['platform']} post on {pd.Timestamp(post['date']).strftime('%-d %b')} shows {item['top_post_likes']:,} likes.")
        variation = _variation(item["posts"], item["posts_prev"])
        if len(sentences) < 2 and variation in {"tripled", "doubled", "halved"}: sentences.append(f"Posting {variation} ({item['posts']}, from {item['posts_prev']}).")
        elif len(sentences) < 2 and item["posts"] and item["posts_prev"] == 0: sentences.append("Back on social after no posts last week.")
        if len(sentences) < 2 and item["reviews"] >= 10 and item["own_posts"] == 0: sentences.append(f"No posts of its own captured in {COUNTRY_NAMES[country]}.")
        if len(sentences) < 2 and item["posts"] >= 8 and item["reviews"] == 0: sentences.append("No Daraz reviews this week.")
        item["highlight"] = " ".join(sentences[:2]) or "No notable change this week."
    return payloads


def _market(frame: pd.DataFrame) -> list[dict[str, Any]]:
    filtered = frame[~frame["category"].astype(str).str.casefold().isin(EXCLUDED_MARKET_CATEGORIES) & ~frame["account_type"].astype(str).str.casefold().eq("brand")].copy()
    filtered["dedupe"] = filtered["title"].fillna("").astype(str).str[:30].str.casefold()
    filtered = filtered.sort_values("published_at").drop_duplicates("dedupe").head(6)
    return [{"category": row.category, "account": row.account_name, "date": pd.Timestamp(row.published_at).date().isoformat(), "summary": _first_sentence(row.content_summary or row.title), "url": row.source_url} for row in filtered.itertuples()]


def _topline(totals: dict[str, Any], daily: list[dict[str, Any]], brands: list[dict[str, Any]], market: list[dict[str, Any]], display_mode: str) -> list[dict[str, str]]:
    cur, prev = totals["reviews"], totals["reviews_prev"]; variation = _variation(cur, prev)
    if variation == "doubled": headline = f"Review volume doubled: {cur} reviews, up from {prev}."
    else:
        verb = "rose to" if cur > prev else "fell to" if cur < prev else "held at"
        headline = f"Reviews {verb} {cur}" + (f", {variation}." if variation else ".")
    rating = "–" if totals["avg_rating"] is None else f"{totals['avg_rating']:.2f}"
    peak = _peak_text(daily)
    result = [{"source": "on_daraz", "headline": headline, "detail": f"{peak + '. ' if peak else ''}Average rating {rating}, {totals['negative']} negative review{'s' if totals['negative'] != 1 else ''}."}]
    leader = next((item for item in brands if item["reviews"] >= 10), None)
    if leader:
        lead = f"{round(leader['review_share'] * 100)}% of reviews" if display_mode == "share" else f"{leader['reviews']} reviews"
        family = f", led by the {leader['family']} with {leader['family_count']}" if leader["family_count"] >= 5 and leader["family_count"] / leader["reviews"] >= .4 else ""
        result.append({"source": "on_daraz", "headline": f"{leader['name']} leads with {lead}{family}.", "detail": ""})
    returned = [(item, sku) for item in brands for sku in item["sku_stats"] if sku["prev"] == 0 and sku["cur"] >= 5]
    if returned:
        selected = sorted(returned, key=lambda pair: (pair[1]["history"] > 0, -pair[1]["cur"]))[:4]
        result.append({"source": "on_daraz", "headline": f"{len(selected)} models had no reviews last week and now have: " + ", ".join(f"{sku['sku']} ({sku['cur']})" for _item, sku in selected) + ".", "detail": ""})
    social_leader = max(brands, key=lambda item: item["posts"], default=None)
    if totals["posts"] >= 10 and social_leader and social_leader["posts"]:
        detail = ""
        if social_leader["viral_flag"] and social_leader["top_posts"]:
            post = social_leader["top_posts"][0]; detail = f"One {post['platform']} post on {pd.Timestamp(post['date']).strftime('%-d %b')} shows {social_leader['top_post_likes']:,} likes."
        comparison = _variation(social_leader["posts"], social_leader["posts_prev"])
        result.append({"source": "off_platform", "headline": f"{social_leader['name']} was the most active brand: {social_leader['posts']} posts" + (f", {comparison}." if comparison else "."), "detail": detail})
    if market: result.append({"source": "market", "headline": market[0]["summary"], "detail": f"{len(market)} market and policy items this week."})
    return result[:5]


def _coverage(label: str, frame: pd.DataFrame, column: str, end: date) -> dict[str, Any]:
    dates = pd.to_datetime(frame[column], errors="coerce", utc=True).dropna()
    latest = dates.max().date() if not dates.empty else None
    lag = max((end - latest).days, 0) if latest else None
    return {
        "label": label,
        "through": min(latest, end).isoformat() if latest else None,
        "count": len(frame),
        "status": "Current" if lag == 0 else f"{lag} days behind" if lag is not None else "No data",
        "current": lag == 0,
    }


def _movers(brands: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [
        {
            "key": item["key"],
            "name": item["name"],
            "current": item["posts"],
            "previous": item["posts_prev"],
            "delta": item["posts"] - item["posts_prev"],
            "material": abs(item["posts"] - item["posts_prev"]) >= 8,
        }
        for item in brands
        if item["posts"] or item["posts_prev"]
    ]
    return sorted(rows, key=lambda item: (-abs(item["delta"]), item["name"].casefold()))[:10]


def _executive_items(brands: list[dict[str, Any]], country_name: str) -> list[dict[str, str]]:
    used: set[str] = set()
    result: list[dict[str, str]] = []

    risk_candidates = [item for item in brands if item["negative_reviews"]]
    if risk_candidates:
        brand = sorted(risk_candidates, key=lambda item: (-item["negative"], item["avg_rating"] or 9))[0]
        review = brand["negative_reviews"][0]
        quote = re.sub(r"\s+", " ", str(review["text"] or "")).strip()[:90]
        result.append({
            "key": brand["key"], "label": "RISK", "source": "Reviews",
            "title": f"{brand['name']} recorded {brand['negative']} negative review{'s' if brand['negative'] != 1 else ''} this week.",
            "detail": f"Lowest evidence: {review['sku']} · {review['rating']}★" + (f" · “{quote}”" if quote else ""),
            "what_changed": f"{brand['reviews']} reviews this week versus {brand['reviews_prev']} last week; average rating {brand['avg_rating']:.2f}.",
            "evidence": f"{brand['negative']} negative review{'s' if brand['negative'] != 1 else ''}; lowest cited item is {review['sku']} at {review['rating']}★.",
            "next_step": "Review the cited buyer feedback and confirm whether the issue repeats by SKU.",
        })
        used.add(brand["key"])

    growth = sorted(
        brands,
        key=lambda item: -((item["reviews"] - item["reviews_prev"]) + (item["posts"] - item["posts_prev"])),
    )
    opportunity = next((item for item in growth if item["key"] not in used and (item["reviews"] > item["reviews_prev"] or item["posts"] > item["posts_prev"])), growth[0] if growth else None)
    if opportunity:
        result.append({
            "key": opportunity["key"], "label": "OPPORTUNITY", "source": "Social + Reviews",
            "title": f"{opportunity['name']} showed the strongest cross-channel activity gain.",
            "detail": f"Reviews {opportunity['reviews_prev']} → {opportunity['reviews']}; social posts {opportunity['posts_prev']} → {opportunity['posts']}.",
            "what_changed": f"Review activity changed by {opportunity['reviews'] - opportunity['reviews_prev']:+d} and social activity by {opportunity['posts'] - opportunity['posts_prev']:+d} week on week.",
            "evidence": opportunity["highlight"],
            "next_step": "Check the highlighted model or campaign against its Daraz listing, price and stock.",
        })
        used.add(opportunity["key"])

    watch_candidates = sorted(
        [item for item in brands if item["key"] not in used and item["posts"] >= 8 and item["reviews"] == 0],
        key=lambda item: -item["posts"],
    )
    if not watch_candidates:
        watch_candidates = sorted(
            [item for item in brands if item["key"] not in used],
            key=lambda item: (item["posts"] - item["posts_prev"], -item["top_post_likes"]),
        )
    if watch_candidates:
        brand = watch_candidates[0]
        if brand["posts"] >= 8 and brand["reviews"] == 0:
            title = f"{brand['name']} generated {brand['posts']} social posts but no Daraz reviews."
            next_step = "Compare the active campaign with Daraz assortment and listing readiness."
        else:
            title = f"{brand['name']} social activity moved from {brand['posts_prev']} to {brand['posts']} posts."
            next_step = "Keep this brand on the next weekly check and confirm whether the direction repeats."
        result.append({
            "key": brand["key"], "label": "WATCH", "source": "Social",
            "title": title,
            "detail": f"{brand['likes']:,} likes captured across {brand['posts']} posts in {country_name}.",
            "what_changed": f"Social posts changed by {brand['posts'] - brand['posts_prev']:+d} versus last week.",
            "evidence": brand["highlight"],
            "next_step": next_step,
        })
    return result[:3]


def build_weekly_brief(consumer_data: pd.DataFrame, social_data: pd.DataFrame, country: str = "PK", week: str | None = None) -> dict[str, Any]:
    selected = country.upper() if country.upper() in COUNTRY_NAMES else "PK"
    consumer, social = _consumer_rows(consumer_data, selected), _social_rows(social_data, selected)
    iso, start, end = _week(week, pd.concat([consumer["created_at"], social["published_at"]]))
    prev_start, prev_end = start - timedelta(days=7), end - timedelta(days=7)
    cur_reviews, prev_reviews = _range(consumer, "created_at", start, end), _range(consumer, "created_at", prev_start, prev_end)
    cur_social, prev_social = _range(social, "published_at", start, end), _range(social, "published_at", prev_start, prev_end)
    rated = cur_reviews[cur_reviews["rating_valid"]]
    totals = {"reviews": len(cur_reviews), "reviews_prev": len(prev_reviews), "avg_rating": round(float(rated["rating"].mean()), 2) if not rated.empty else None, "negative": int(rated["rating"].isin([1, 2, 3]).sum()), "posts": len(cur_social), "posts_prev": len(prev_social)}
    daily = _daily(cur_reviews, start)
    brands = _brand_payloads(consumer, cur_reviews, prev_reviews, cur_social, prev_social, start, selected, totals["reviews"], totals["posts"])
    market = _market(cur_social)
    cur_topics, prev_topics = _topic_counts(cur_reviews), _topic_counts(prev_reviews)
    topics = [{"label": label, "cur": cur_topics[label], "prev": prev_topics[label], "emphasis": bool(cur_topics[label] >= 3 and cur_topics[label] >= prev_topics[label] * 2)} for label, _ in TOPIC_PATTERNS if cur_topics[label] or prev_topics[label]]
    repeated = [item for item in topics if item["label"].startswith("Repeated")]
    topics = sorted([item for item in topics if not item["label"].startswith("Repeated")], key=lambda item: (-item["cur"], item["label"]))[:6] + repeated
    display_mode = "share" if totals["reviews"] >= 100 else "count"
    executive = _executive_items(brands, COUNTRY_NAMES[selected])
    return {"country": selected, "country_name": COUNTRY_NAMES[selected], "week": {"iso": iso, "start": start.isoformat(), "end": end.isoformat()}, "prev_week": {"start": prev_start.isoformat(), "end": prev_end.isoformat()}, "available_weeks": [{"iso": f"{(start - timedelta(days=7 * i)).isocalendar().year}-W{(start - timedelta(days=7 * i)).isocalendar().week:02d}"} for i in range(8)], "totals": totals, "coverage": [_coverage("Social", cur_social, "published_at", end), _coverage("Reviews", cur_reviews, "created_at", end)], "executive": executive, "priorities": executive, "movers": _movers(brands), "topline": _topline(totals, daily, brands, market, display_mode), "daily_reviews": daily, "topics": topics, "brands": brands, "market": market, "display_mode": display_mode}

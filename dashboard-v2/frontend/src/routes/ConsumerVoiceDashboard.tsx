import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Area, AreaChart, CartesianGrid, Cell, Legend, Pie, PieChart, PolarAngleAxis,
  PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { consumerVoiceApi } from "../lib/api";

const COLORS = ["#fb7185", "#fb923c", "#facc15", "#38bdf8", "#34d399"];
const sentimentLabel = { all: "All reviews", positive: "Positive", neutral: "Neutral", negative: "Negative" } as const;

function Stars({ rating }: { rating: number | null }) {
  if (!rating) return <span className="text-xs font-semibold text-slate-400">Not rated</span>;
  return <span aria-label={`${rating} stars`} className="tracking-[.12em] text-amber-400">{"★★★★★".slice(0, rating)}<span className="text-slate-200">{"★★★★★".slice(rating)}</span></span>;
}

function MetricCard({ label, value, note, accent }: { label: string; value: string; note: string; accent: string }) {
  return <div className="metric-card"><div className={`metric-accent ${accent}`} /><p>{label}</p><strong>{value}</strong><span>{note}</span></div>;
}

export function ConsumerVoiceDashboard() {
  const filters = useQuery({ queryKey: ["consumer-voice-filters"], queryFn: consumerVoiceApi.filters });
  const [venture, setVenture] = useState("");
  const [brand, setBrand] = useState("");
  const [productId, setProductId] = useState("");
  const [sentiment, setSentiment] = useState<keyof typeof sentimentLabel>("all");
  const [sort, setSort] = useState("recent");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const params = useMemo(() => {
    const next = new URLSearchParams();
    if (venture) next.append("venture", venture);
    if (brand) next.append("brand", brand);
    if (productId) next.append("productId", productId);
    if (sentiment !== "all") next.set("sentiment", sentiment);
    next.set("sort", sort);
    if (dateFrom) next.set("dateFrom", dateFrom);
    if (dateTo) next.set("dateTo", dateTo);
    return next;
  }, [venture, brand, productId, sentiment, sort, dateFrom, dateTo]);

  const dashboard = useQuery({
    queryKey: ["consumer-voice-dashboard", params.toString()],
    queryFn: () => consumerVoiceApi.dashboard(params),
  });
  const data = dashboard.data;
  const options = filters.data?.options;
  const products = options?.products.filter((product) => !brand || product.brand === brand) ?? [];
  const totalStars = data?.stars.reduce((sum, row) => sum + row.count, 0) ?? 0;

  if (dashboard.isError && !dashboard.data) return <div className="error-panel"><p>Consumer Voice data is temporarily unavailable.</p><button onClick={() => { filters.refetch(); dashboard.refetch(); }}>Retry</button></div>;

  return <div className="consumer-page">
    {(filters.isError || dashboard.isError) && <div className="refresh-warning"><span>{dashboard.isError && dashboard.data ? "Could not refresh Consumer Voice data. Showing the last successful result." : "Filter options could not be refreshed."}</span><button onClick={() => { filters.refetch(); dashboard.refetch(); }}>Retry</button></div>}
    <section className="consumer-hero">
      <div>
        <div className="eyebrow">Consumer Voice Intelligence</div>
        <h1>Turn every review into a decision signal.</h1>
        <p>Track product experience, catch emerging issues and hear the customer language behind the score.</p>
      </div>
      <div className="hero-pulse"><span>Live review pulse</span><strong>{data?.metrics.reviewCount ?? "—"}</strong><small>matching reviews</small></div>
    </section>

    <section className="filter-panel">
      <label>Venture<select value={venture} onChange={(event) => setVenture(event.target.value)}><option value="">All ventures</option>{options?.ventures.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>Brand<select value={brand} onChange={(event) => { setBrand(event.target.value); setProductId(""); }}><option value="">All brands</option>{options?.brands.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label className="product-filter">Product<select value={productId} onChange={(event) => setProductId(event.target.value)}><option value="">All products</option>{products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>From<input type="date" min={options?.dateRange.min ?? undefined} max={options?.dateRange.max ?? undefined} value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} /></label>
      <label>To<input type="date" min={options?.dateRange.min ?? undefined} max={options?.dateRange.max ?? undefined} value={dateTo} onChange={(event) => setDateTo(event.target.value)} /></label>
      <button onClick={() => { setVenture(""); setBrand(""); setProductId(""); setDateFrom(""); setDateTo(""); }}>Reset</button>
    </section>

    {dashboard.isLoading ? <div className="loading-panel">Reading customer signals…</div> : <>
      <section className="metric-grid">
        <MetricCard label="Overall rating" value={data?.metrics.averageRating?.toFixed(2) ?? "—"} note={`${data?.metrics.ratedReviewCount ?? 0} rated reviews`} accent="accent-violet" />
        <MetricCard label="Positive review rate" value={data?.metrics.positiveRate != null ? `${Math.round(data.metrics.positiveRate * 100)}%` : "—"} note="4 and 5 star share" accent="accent-emerald" />
        <MetricCard label="Review volume" value={(data?.metrics.reviewCount ?? 0).toLocaleString()} note={`${data?.metrics.imageReviewCount ?? 0} reviews with images`} accent="accent-sky" />
      </section>

      <section className="analytics-grid">
        <article className="panel radar-panel"><header><div><span>Experience dimensions</span><h2>Where the experience bends</h2></div><span className="panel-note">Score out of 5</span></header>
          <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><RadarChart data={data?.dimensions}><PolarGrid stroke="#dbe3ef" /><PolarAngleAxis dataKey="dimension" tick={{ fill: "#475569", fontSize: 12 }} /><Radar dataKey="score" stroke="#7c3aed" fill="#8b5cf6" fillOpacity={0.24} strokeWidth={2} /><Tooltip /></RadarChart></ResponsiveContainer></div>
        </article>
        <article className="panel star-panel"><header><div><span>Reputation structure</span><h2>Star distribution</h2></div><span className="panel-note">{totalStars} rated</span></header>
          <div className="star-layout"><div className="donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={data?.stars} dataKey="count" nameKey="rating" innerRadius={58} outerRadius={84} paddingAngle={2}>{data?.stars.map((entry, index) => <Cell key={entry.rating} fill={COLORS[index]} />)}</Pie><Tooltip formatter={(value, name) => [`${value} reviews`, `${name} star`]} /></PieChart></ResponsiveContainer><div><strong>{data?.metrics.averageRating?.toFixed(1) ?? "—"}</strong><span>average</span></div></div>
          <div className="star-bars">{[...(data?.stars ?? [])].reverse().map((row) => <div key={row.rating}><span>{row.rating} ★</span><i><b style={{ width: totalStars ? `${(row.count / totalStars) * 100}%` : "0%", background: COLORS[row.rating - 1] }} /></i><strong>{row.count}</strong></div>)}</div></div>
        </article>
      </section>

      <section className="signals-grid">
        <article className="panel tag-panel"><header><div><span>Customer language</span><h2>What customers talk about</h2></div></header>
          <div className="tag-cloud">{data?.tags.length ? data.tags.map((tag) => <span key={tag.label} className={`tag tag-${tag.sentiment}`} style={{ fontSize: `${Math.min(20, 12 + tag.count * 0.8)}px` }}>{tag.label}<b>{tag.count}</b></span>) : <p className="empty">No recurring tags in this selection.</p>}</div>
        </article>
        <article className="panel alert-panel"><header><div><span>Action queue</span><h2>Exceptions that need attention</h2></div><span className="alert-count">{data?.alerts.length ?? 0}</span></header>
          <div className="alert-list">{data?.alerts.length ? data.alerts.map((alert, index) => <div className="alert-row" key={`${alert.productId}-${index}`}><div className="alert-icon">!</div><div><div className="alert-meta"><span>{alert.venture}</span><span>{alert.rating ? `${alert.rating} ★` : "Unrated"}</span><span>{alert.date}</span></div><h3>{alert.productName}</h3><p>{alert.review}</p><div className="reason-list">{alert.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div></div></div>) : <p className="empty">No exceptions detected.</p>}</div>
        </article>
      </section>

      <section className="review-section">
        <header><div><span>Review explorer</span><h2>Read the customer voice</h2></div><div className="review-controls"><div className="segments">{Object.entries(sentimentLabel).map(([key, label]) => <button key={key} className={sentiment === key ? "active" : ""} onClick={() => setSentiment(key as keyof typeof sentimentLabel)}>{label}</button>)}</div><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="recent">Most recent</option><option value="helpful">Most helpful</option></select></div></header>
        <div className="review-grid">{data?.reviews.map((review) => <article className="review-card" key={review.id}>{review.images.length > 0 && <div className="review-images">{review.images.map((image, index) => <img key={image} src={image} alt={`${review.productName} customer photo ${index + 1}`} loading="lazy" />)}</div>}<div className="review-body"><div className="review-top"><Stars rating={review.rating} /><span>{review.date}</span></div><h3>{review.productName}</h3><p>{review.review}</p><div className="review-tags">{review.tags.map((tag) => <span key={tag}>{tag}</span>)}</div><footer><span>{review.venture} · {review.brand}</span><span>Helpful {review.upvotes}</span></footer></div></article>)}</div>
        {!data?.reviews.length && <p className="empty">No reviews match the selected filters.</p>}
      </section>
    </>}
  </div>;
}

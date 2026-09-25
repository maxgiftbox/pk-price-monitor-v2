import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, PolarAngleAxis, PolarGrid, Radar, RadarChart, ResponsiveContainer, Tooltip } from "recharts";

import { consumerVoiceApi } from "../lib/api";
import type { ConsumerVoiceFilters } from "../types/consumerVoice";

const COLORS = ["#fb7185", "#fb923c", "#facc15", "#38bdf8", "#34d399"];
const sentimentLabel = { all: "All", positive: "Positive", neutral: "Neutral", negative: "Negative" } as const;
type FilterState = { venture: string; brand: string; productId: string; dateFrom: string; dateTo: string };
const emptyFilter = (): FilterState => ({ venture: "", brand: "", productId: "", dateFrom: "", dateTo: "" });

function buildParams(filter: FilterState, section: string, extras?: Record<string, string>) {
  const params = new URLSearchParams({ section, ...extras });
  if (filter.venture) params.set("venture", filter.venture);
  if (filter.brand) params.set("brand", filter.brand);
  if (filter.productId) params.set("productId", filter.productId);
  if (filter.dateFrom) params.set("dateFrom", filter.dateFrom);
  if (filter.dateTo) params.set("dateTo", filter.dateTo);
  return params;
}

function Stars({ rating }: { rating: number | null }) {
  if (!rating) return <span className="not-rated">Not rated</span>;
  return <span aria-label={`${rating} stars`} className="stars">{"★★★★★".slice(0, rating)}<span>{"★★★★★".slice(rating)}</span></span>;
}

function MetricCard({ label, value, note, accent }: { label: string; value: string; note: string; accent: string }) {
  return <div className="metric-card"><div className={`metric-accent ${accent}`} /><p>{label}</p><strong>{value}</strong><span>{note}</span></div>;
}

function LocalFilters({ label, value, onChange, options }: {
  label: string;
  value: FilterState;
  onChange: (value: FilterState) => void;
  options?: ConsumerVoiceFilters["options"];
}) {
  const products = options?.products.filter((product) => !value.brand || product.brand === value.brand) ?? [];
  const activeCount = Object.values(value).filter(Boolean).length;
  return <details className="module-filter">
    <summary>Filters{activeCount > 0 && <b>{activeCount}</b>}</summary>
    <div className="module-filter-popover" aria-label={`${label} filters`}>
      <label>Venture<select value={value.venture} onChange={(event) => onChange({ ...value, venture: event.target.value })}><option value="">All ventures</option>{options?.ventures.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label>Brand<select value={value.brand} onChange={(event) => onChange({ ...value, brand: event.target.value, productId: "" })}><option value="">All brands</option>{options?.brands.map((item) => <option key={item}>{item}</option>)}</select></label>
      <label className="product-filter">Product<select value={value.productId} onChange={(event) => onChange({ ...value, productId: event.target.value })}><option value="">All products</option>{products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>From<input type="date" min={options?.dateRange.min ?? undefined} max={options?.dateRange.max ?? undefined} value={value.dateFrom} onChange={(event) => onChange({ ...value, dateFrom: event.target.value })} /></label>
      <label>To<input type="date" min={options?.dateRange.min ?? undefined} max={options?.dateRange.max ?? undefined} value={value.dateTo} onChange={(event) => onChange({ ...value, dateTo: event.target.value })} /></label>
      <button onClick={() => onChange(emptyFilter())}>Reset</button>
    </div>
  </details>;
}

function SectionHeader({ eyebrow, title, count, filter }: { eyebrow: string; title: string; count?: number; filter: React.ReactNode }) {
  return <header className="section-heading"><div><span>{eyebrow}</span><h2>{title}</h2>{count != null && <small>{count} matching reviews</small>}</div>{filter}</header>;
}

export function ConsumerVoiceDashboard() {
  const filters = useQuery({ queryKey: ["consumer-voice-filters"], queryFn: consumerVoiceApi.filters });
  const [overviewFilter, setOverviewFilter] = useState<FilterState>(emptyFilter);
  const [signalsFilter, setSignalsFilter] = useState<FilterState>(emptyFilter);
  const [reviewsFilter, setReviewsFilter] = useState<FilterState>(emptyFilter);
  const [sentiment, setSentiment] = useState<keyof typeof sentimentLabel>("all");
  const [sort, setSort] = useState("recent");

  const overviewParams = useMemo(() => buildParams(overviewFilter, "overview"), [overviewFilter]);
  const signalsParams = useMemo(() => buildParams(signalsFilter, "signals"), [signalsFilter]);
  const reviewsParams = useMemo(() => buildParams(reviewsFilter, "reviews", { sentiment, sort, limit: "24" }), [reviewsFilter, sentiment, sort]);
  const overview = useQuery({ queryKey: ["consumer-voice-overview", overviewParams.toString()], queryFn: () => consumerVoiceApi.dashboard(overviewParams) });
  const signals = useQuery({ queryKey: ["consumer-voice-signals", signalsParams.toString()], queryFn: () => consumerVoiceApi.dashboard(signalsParams) });
  const reviews = useQuery({ queryKey: ["consumer-voice-reviews", reviewsParams.toString()], queryFn: () => consumerVoiceApi.dashboard(reviewsParams) });

  const options = filters.data?.options;
  const overviewData = overview.data;
  const signalsData = signals.data;
  const reviewData = reviews.data;
  const totalStars = overviewData?.stars?.reduce((sum, row) => sum + row.count, 0) ?? 0;
  const allQueries = [overview, signals, reviews];
  const hasFatalError = allQueries.some((query) => query.isError && !query.data);
  const hasRefreshError = filters.isError || allQueries.some((query) => query.isError && query.data);

  if (hasFatalError) return <div className="error-panel"><p>Consumer Voice data is temporarily unavailable.</p><button onClick={() => { filters.refetch(); overview.refetch(); signals.refetch(); reviews.refetch(); }}>Retry</button></div>;

  return <div className="consumer-page compact-consumer-page">
    {hasRefreshError && <div className="refresh-warning"><span>Could not refresh all Consumer Voice modules. Showing the last successful result where available.</span><button onClick={() => { filters.refetch(); overview.refetch(); signals.refetch(); reviews.refetch(); }}>Retry</button></div>}
    <div className="page-intro"><div><span>Consumer Voice Intelligence</span><h1>Customer experience at a glance</h1></div><p>Each section has independent filters.</p></div>

    <section className="dashboard-module overview-module">
      <SectionHeader eyebrow="Business overview" title="Ratings and experience health" count={overviewData?.meta?.filteredCount} filter={<LocalFilters label="Business overview" value={overviewFilter} onChange={setOverviewFilter} options={options} />} />
      {overview.isLoading ? <div className="module-loading">Loading overview…</div> : <>
        <div className="metric-grid compact-metrics">
          <MetricCard label="Overall rating" value={overviewData?.metrics?.averageRating?.toFixed(2) ?? "—"} note={`${overviewData?.metrics?.ratedReviewCount ?? 0} rated`} accent="accent-violet" />
          <MetricCard label="Positive rate" value={overviewData?.metrics?.positiveRate != null ? `${Math.round(overviewData.metrics.positiveRate * 100)}%` : "—"} note="4–5 star share" accent="accent-emerald" />
          <MetricCard label="Review volume" value={(overviewData?.metrics?.reviewCount ?? 0).toLocaleString()} note={`${overviewData?.metrics?.imageReviewCount ?? 0} with images`} accent="accent-sky" />
        </div>
        <div className="analytics-grid compact-analytics">
          <article className="panel radar-panel"><header><div><span>Experience dimensions</span><h3>Product, seller and logistics</h3></div><span className="panel-note">/ 5</span></header>
            <div className="chart-wrap"><ResponsiveContainer width="100%" height="100%"><RadarChart data={overviewData?.dimensions}><PolarGrid stroke="#dbe3ef" /><PolarAngleAxis dataKey="dimension" tick={{ fill: "#475569", fontSize: 11 }} /><Radar dataKey="score" stroke="#7c3aed" fill="#8b5cf6" fillOpacity={0.24} strokeWidth={2} /><Tooltip /></RadarChart></ResponsiveContainer></div>
          </article>
          <article className="panel star-panel"><header><div><span>Rating mix</span><h3>Star distribution</h3></div><span className="panel-note">{totalStars} rated</span></header>
            <div className="star-layout"><div className="donut"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={overviewData?.stars} dataKey="count" nameKey="rating" innerRadius={48} outerRadius={68} paddingAngle={2}>{overviewData?.stars?.map((entry, index) => <Cell key={entry.rating} fill={COLORS[index]} />)}</Pie><Tooltip formatter={(value, name) => [`${value} reviews`, `${name} star`]} /></PieChart></ResponsiveContainer><div><strong>{overviewData?.metrics?.averageRating?.toFixed(1) ?? "—"}</strong><span>average</span></div></div>
            <div className="star-bars">{[...(overviewData?.stars ?? [])].reverse().map((row) => <div key={row.rating}><span>{row.rating} ★</span><i><b style={{ width: totalStars ? `${(row.count / totalStars) * 100}%` : "0%", background: COLORS[row.rating - 1] }} /></i><strong>{row.count}</strong></div>)}</div></div>
          </article>
        </div>
      </>}
    </section>

    <section className="dashboard-module signals-module">
      <SectionHeader eyebrow="Customer signals" title="Topics and exceptions" count={signalsData?.meta?.filteredCount} filter={<LocalFilters label="Customer signals" value={signalsFilter} onChange={setSignalsFilter} options={options} />} />
      {signals.isLoading ? <div className="module-loading">Loading signals…</div> : <div className="signals-grid compact-signals">
        <article className="panel tag-panel"><header><div><span>Customer language</span><h3>Top topics</h3></div></header>
          <div className="tag-cloud">{signalsData?.tags?.length ? signalsData.tags.slice(0, 12).map((tag) => <span key={tag.label} className={`tag tag-${tag.sentiment}`} style={{ fontSize: `${Math.min(16, 11 + tag.count * 0.45)}px` }}>{tag.label}<b>{tag.count}</b></span>) : <p className="empty">No recurring tags.</p>}</div>
        </article>
        <article className="panel alert-panel"><header><div><span>Action queue</span><h3>Exceptions</h3></div><span className="alert-count">{signalsData?.alerts?.length ?? 0}</span></header>
          <div className="alert-list">{signalsData?.alerts?.length ? signalsData.alerts.slice(0, 6).map((alert, index) => <div className="alert-row" key={`${alert.productId}-${index}`}><div className="alert-icon">!</div><div><div className="alert-meta"><span>{alert.venture}</span><span>{alert.rating ? `${alert.rating} ★` : "Unrated"}</span><span>{alert.date}</span></div><h3>{alert.productName}</h3><p>{alert.review}</p><div className="reason-list">{alert.reasons.slice(0, 3).map((reason) => <span key={reason}>{reason}</span>)}</div></div></div>) : <p className="empty">No exceptions detected.</p>}</div>
        </article>
      </div>}
    </section>

    <section className="dashboard-module review-section compact-review-section">
      <SectionHeader eyebrow="Review explorer" title="Read the customer voice" count={reviewData?.meta?.filteredCount} filter={<LocalFilters label="Review explorer" value={reviewsFilter} onChange={setReviewsFilter} options={options} />} />
      <div className="review-toolbar"><div className="segments">{Object.entries(sentimentLabel).map(([key, label]) => <button key={key} className={sentiment === key ? "active" : ""} onClick={() => setSentiment(key as keyof typeof sentimentLabel)}>{label}</button>)}</div><select value={sort} onChange={(event) => setSort(event.target.value)}><option value="recent">Most recent</option><option value="helpful">Most helpful</option></select></div>
      {reviews.isLoading ? <div className="module-loading">Loading reviews…</div> : <div className="review-grid">{reviewData?.reviews?.map((review) => <article className="review-card" key={review.id}>{review.images.length > 0 && <div className="review-images">{review.images.map((image, index) => <img key={image} src={image} alt={`${review.productName} customer photo ${index + 1}`} loading="lazy" />)}</div>}<div className="review-body"><div className="review-top"><Stars rating={review.rating} /><span>{review.date}</span></div><h3 title={review.productName}>{review.productName}</h3><p>{review.review || "No written review"}</p><div className="review-tags">{review.tags.slice(0, 2).map((tag) => <span key={tag}>{tag}</span>)}</div><footer><span>{review.venture} · {review.brand}</span><span>Helpful {review.upvotes}</span></footer></div></article>)}</div>}
      {!reviews.isLoading && !reviewData?.reviews?.length && <p className="empty">No reviews match the selected filters.</p>}
    </section>
  </div>;
}

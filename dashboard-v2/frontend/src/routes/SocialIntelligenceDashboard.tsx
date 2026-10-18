import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { resolveApiAssetUrl, socialIntelligenceApi } from "../lib/api";
import type { SocialRatingPoint, SocialRecord } from "../types/socialIntelligence";

type FeedFilter = { query: string; country: string; platform: string; monitorType: string; brand: string; accountType: string; mediaType: string; dateFrom: string; dateTo: string; sort: string };
type RatingFilter = { period: string; country: string; platform: string; monitorType: string };
type RankingFilter = { period: string; country: string; metric: "views" | "likes" };
type CloudFilter = { period: string; country: string };
const emptyFeed = (): FeedFilter => ({ query: "", country: "", platform: "", monitorType: "", brand: "", accountType: "", mediaType: "", dateFrom: "", dateTo: "", sort: "recent" });

function periodStart(days: string) { const date = new Date(); date.setUTCDate(date.getUTCDate() - Math.max(0, Number(days) - 1)); return date.toISOString().slice(0, 10); }
function buildParams(values: Record<string, string>, extras: Record<string, string> = {}) { const params = new URLSearchParams(extras); Object.entries(values).forEach(([key, value]) => { if (value && key !== "period" && key !== "metric") params.set(key, value); }); if (values.period) params.set("dateFrom", periodStart(values.period)); return params; }
function number(value: number | null | undefined) { return value == null ? "—" : Intl.NumberFormat("en", { notation: value >= 10000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(value); }
function engagement(record: SocialRecord, metric: "views" | "likes") { return record.viewsStatus === "not_applicable" ? "N/A" : number(record[metric]); }
function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: { value: string; label: string }[] }) { return <label>{label}<select value={value} onChange={(event) => onChange(event.target.value)}>{options.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>; }

const BRAND_COLORS = ["#7c3aed", "#0f766e", "#ea580c", "#2563eb", "#db2777", "#ca8a04", "#0891b2", "#64748b", "#16a34a", "#9333ea"];
const BRAND_MARKS: Record<string, string> = { TECNO: "T", Samsung: "S", XIAOMI: "mi", Xiaomi: "mi", OPPO: "O", vivo: "v", Infinix: "X", realme: "R", HONOR: "H", Honor: "H", Itel: "i", itel: "i", Nubia: "N", nubia: "N", Apple: "A" };

function formatChartDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`);
  return `${date.getUTCDate()} ${date.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}`;
}

function spreadBrandLabels(items: { brand: string; score: number; color: string }[]) {
  const sorted = [...items].sort((a, b) => b.score - a.score);
  const minimumGap = sorted.length > 7 ? 9 : 11;
  const positions = sorted.map((item) => Math.max(3, Math.min(97, 100 - item.score)));
  for (let index = 1; index < positions.length; index += 1) positions[index] = Math.max(positions[index], positions[index - 1] + minimumGap);
  const overflow = Math.max(0, (positions.at(-1) ?? 97) - 97);
  if (overflow) for (let index = 0; index < positions.length; index += 1) positions[index] -= overflow;
  for (let index = positions.length - 2; index >= 0; index -= 1) positions[index] = Math.min(positions[index], positions[index + 1] - minimumGap);
  return sorted.map((item, index) => ({ ...item, position: Math.max(3, positions[index]) }));
}

function BrandRatingChart({ points, brands, dates }: { points: SocialRatingPoint[]; brands: string[]; dates: string[] }) {
  const data = dates.map((date) => {
    const row: Record<string, string | number | undefined> = { date };
    points.filter((point) => point.date === date).forEach((point) => { row[`${point.brand}Rank`] = point.rank; row[`${point.brand}Score`] = point.socialRating; });
    return row;
  });
  const latestByBrand = brands.map((brand, index) => {
    const latestPoint = points.filter((point) => point.brand === brand).sort((a, b) => a.date.localeCompare(b.date)).at(-1);
    return latestPoint ? { brand, score: latestPoint.socialRating, color: BRAND_COLORS[index % BRAND_COLORS.length] } : null;
  }).filter((item): item is { brand: string; score: number; color: string } => Boolean(item));
  const brandLabels = spreadBrandLabels(latestByBrand);
  return <div className="rating-chart-layout">
    <div className="rating-chart"><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 18, right: 8, bottom: 4, left: 0 }}>
      <CartesianGrid stroke="#eef1f6" vertical={true} horizontal={true} />
      <XAxis dataKey="date" tickFormatter={formatChartDate} tick={{ fill: "#7b8799", fontSize: 9, fontWeight: 700 }} axisLine={false} tickLine={false} />
      <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} width={30} tick={{ fill: "#94a3b8", fontSize: 8, fontWeight: 700 }} axisLine={false} tickLine={false} />
      <Tooltip content={({ active, payload, label }) => { if (!active || !payload?.length) return null; return <div className="rating-tooltip"><strong>{new Date(`${label}T00:00:00Z`).toLocaleDateString("en-US", { dateStyle: "medium", timeZone: "UTC" })}</strong>{payload.map((entry) => { const brand = String(entry.dataKey).replace(/Score$/, ""); const point = points.find((item) => item.date === label && item.brand === brand); return point ? <div key={brand}><i style={{ background: entry.color }} /><b>{brand}</b><span>{point.socialRating}/100 · rank #{point.rank}</span><small>{point.voicePosts} posts · {point.earnedMentions} mentions · {number(point.totalLikes)} likes · {point.confidenceLevel} confidence</small></div> : null; })}</div>; }} />
      {brands.map((brand, index) => <Line key={brand} type="linear" dataKey={`${brand}Score`} name={brand} connectNulls stroke={BRAND_COLORS[index % BRAND_COLORS.length]} strokeWidth={2.5} activeDot={{ r: 5, strokeWidth: 2 }} dot={{ r: 3.25, fill: "white", strokeWidth: 2.25 }} />)}
    </LineChart></ResponsiveContainer></div>
    <aside className="rating-brand-axis" aria-label="Brands">{brandLabels.map((item) => <span key={item.brand} style={{ top: `${item.position}%`, color: item.color }} title={item.brand}><i style={{ background: item.color }}>{BRAND_MARKS[item.brand] ?? item.brand.slice(0, 1).toUpperCase()}</i><b>{item.brand}</b></span>)}</aside>
  </div>;
}

function SignalCard({ record, onOpen }: { record: SocialRecord; onOpen: () => void }) {
  return <article className="social-signal-card" onClick={onOpen}>{record.mediaUrl && <div className="social-card-media"><img src={resolveApiAssetUrl(record.mediaUrl)} alt="" loading="lazy" onError={(event) => { event.currentTarget.parentElement!.style.display = "none"; }} /></div>}<div className="social-card-body"><div className="social-badges"><span>{record.country}</span><span className={`platform-${record.platform.toLowerCase()}`}>{record.platform}</span><span className={`monitor-${record.monitorType}`}>{record.monitorType === "trend_discovery" ? "Trend" : "Watchlist"}</span>{record.accountType && <span>{record.accountType}</span>}</div><h3>{record.title}</h3><p>{record.contentSummary || record.content}</p>{record.whyItMatters && <div className="social-why"><b>Why it matters</b>{record.whyItMatters}</div>}<footer><span>{record.accountName || record.brand} · {record.publishedAt ? new Date(record.publishedAt).toLocaleDateString() : "Date unavailable"}</span><span>Views {engagement(record, "views")} · Likes {engagement(record, "likes")}</span></footer></div></article>;
}

export function SocialIntelligenceDashboard() {
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>({ period: "7", country: "BD", platform: "", monitorType: "" });
  const [rankingFilter, setRankingFilter] = useState<RankingFilter>({ period: "7", country: "", metric: "views" });
  const [cloudFilter, setCloudFilter] = useState<CloudFilter>({ period: "7", country: "" });
  const [feedFilter, setFeedFilter] = useState<FeedFilter>(emptyFeed);
  const [selected, setSelected] = useState<SocialRecord | null>(null);
  const filters = useQuery({ queryKey: ["social-intelligence-filters"], queryFn: socialIntelligenceApi.filters });
  const ratingParams = useMemo(() => { const params = new URLSearchParams({ periodDays: ratingFilter.period, topN: "6" }); if (ratingFilter.country) params.set("country", ratingFilter.country); if (ratingFilter.platform) params.set("platform", ratingFilter.platform); if (ratingFilter.monitorType) params.set("monitorType", ratingFilter.monitorType); return params; }, [ratingFilter]);
  const rankingParams = useMemo(() => buildParams(rankingFilter as unknown as Record<string, string>, { limit: "5", sort: rankingFilter.metric }), [rankingFilter]);
  const cloudParams = useMemo(() => buildParams(cloudFilter as unknown as Record<string, string>, { limit: "1" }), [cloudFilter]);
  const feedParams = useMemo(() => buildParams(feedFilter as unknown as Record<string, string>, { limit: "40", sort: feedFilter.sort }), [feedFilter]);
  const ratings = useQuery({ queryKey: ["social-ratings", ratingParams.toString()], queryFn: () => socialIntelligenceApi.ratings(ratingParams) });
  const ranking = useQuery({ queryKey: ["social-ranking", rankingParams.toString()], queryFn: () => socialIntelligenceApi.dashboard(rankingParams) });
  const cloud = useQuery({ queryKey: ["social-cloud", cloudParams.toString()], queryFn: () => socialIntelligenceApi.dashboard(cloudParams) });
  const feed = useQuery({ queryKey: ["social-feed", feedParams.toString()], queryFn: () => socialIntelligenceApi.dashboard(feedParams) });
  const options = filters.data?.options;
  const countries = [{ value: "", label: "All countries" }, ...(options?.countries ?? []).map((value) => ({ value, label: value }))];
  const periods = [{ value: "1", label: "Past 1 day" }, { value: "7", label: "Past 7 days" }, { value: "14", label: "Past 14 days" }, { value: "30", label: "Past 30 days" }];
  const refreshed = feed.data?.meta.cacheGeneratedAt ? new Date(feed.data.meta.cacheGeneratedAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : null;
  const fatal = [ratings, ranking, cloud, feed].some((query) => query.isError && !query.data);
  if (fatal) return <div className="error-panel"><p>Social Voice data is temporarily unavailable.</p><button onClick={() => { ratings.refetch(); ranking.refetch(); cloud.refetch(); feed.refetch(); }}>Retry</button></div>;
  const updateFeed = (key: keyof FeedFilter, value: string) => setFeedFilter((current) => ({ ...current, [key]: value }));
  const keywords = cloud.data?.keywordCloud ?? [];
  const featuredKeywords = keywords.slice(0, 3);
  const supportingKeywords = keywords.slice(3);
  const maxKeyword = Math.max(1, ...keywords.map((item) => item.count));

  return <div className="social-page">
    <div className="social-page-intro"><div><span>Social Voice</span><h1>Market signals and brand activity</h1></div><p>{feed.data?.meta.stale ? `Using local pipeline snapshot${refreshed ? ` · ${refreshed}` : ""}` : `Data Synced${refreshed ? ` - ${refreshed}` : ""}`}</p></div>
    <section className="social-overview-module social-rating-module"><header><div><span>Brand social ratings</span><strong>Competitive momentum by market</strong></div><div className="social-mini-filters"><Select label="Period" value={ratingFilter.period} onChange={(period) => setRatingFilter({ ...ratingFilter, period })} options={periods.filter((item) => item.value !== "1")} /><Select label="Country" value={ratingFilter.country} onChange={(country) => setRatingFilter({ ...ratingFilter, country })} options={countries.filter((item) => item.value)} /><Select label="Platform" value={ratingFilter.platform} onChange={(platform) => setRatingFilter({ ...ratingFilter, platform })} options={[{ value: "", label: "All platforms" }, ...(options?.platforms ?? []).map((value) => ({ value, label: value }))]} /><Select label="Monitor" value={ratingFilter.monitorType} onChange={(monitorType) => setRatingFilter({ ...ratingFilter, monitorType })} options={[{ value: "", label: "All sources" }, ...(options?.monitorTypes ?? []).map((value) => ({ value, label: value === "trend_discovery" ? "Trend" : "Watchlist" }))]} /></div></header>{ratings.isLoading ? <div className="module-loading">Calculating brand ratings…</div> : ratings.data?.series.length ? <BrandRatingChart points={ratings.data.series} brands={ratings.data.brands} dates={ratings.data.dates} /> : <p className="empty">Not enough verified brand data for this selection.</p>}<footer className="rating-methodology"><span>Rating V1.0</span><span>Activity 25%</span><span>Reach 20%</span><span>Engagement 30%</span><span>Earned mentions 25%</span><i title="Views are excluded and weights rebalanced when verified reach data is unavailable.">How it works ⓘ</i></footer></section>
    <section className="social-discovery-grid">
      <article className="social-ranking-module"><header><div><span>Top ranking</span><h2>Most popular content</h2></div><div className="social-inline-controls"><select value={rankingFilter.period} onChange={(e) => setRankingFilter({ ...rankingFilter, period: e.target.value })}>{periods.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><select value={rankingFilter.country} onChange={(e) => setRankingFilter({ ...rankingFilter, country: e.target.value })}>{countries.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><select value={rankingFilter.metric} onChange={(e) => setRankingFilter({ ...rankingFilter, metric: e.target.value as "views" | "likes" })}><option value="views">By views</option><option value="likes">By likes</option></select></div></header><div className="social-ranking-list">{ranking.data?.records.map((record, index) => <button key={record.recordId} onClick={() => setSelected(record)}><b>{index + 1}</b>{record.mediaUrl ? <img src={resolveApiAssetUrl(record.mediaUrl)} alt="" /> : <i>{record.platform}</i>}<span><strong>{record.title}</strong><small>{record.country} · {record.platform} · {record.accountName}</small></span><em>{engagement(record, rankingFilter.metric)}<small>{rankingFilter.metric}</small></em></button>)}</div></article>
      <article className="social-cloud-module"><header><div><span>Hot topics</span><h2>What the market is talking about</h2></div><div className="social-inline-controls"><select value={cloudFilter.period} onChange={(e) => setCloudFilter({ ...cloudFilter, period: e.target.value })}>{periods.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><select value={cloudFilter.country} onChange={(e) => setCloudFilter({ ...cloudFilter, country: e.target.value })}>{countries.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></div></header><div className="social-topic-leaders">{featuredKeywords.map((item, index) => <div key={item.label}><small>#{index + 1} theme</small><strong>{item.label}</strong><span>{item.count} signals</span></div>)}</div><div className="social-word-cloud">{supportingKeywords.map((item, index) => <span key={item.label} className={`word-tone-${index % 5}`} style={{ fontSize: `${11 + (item.count / maxKeyword) * 11}px` }} title={`${item.count} signals`}>{item.label}<i>{item.count}</i></span>)}</div>{!keywords.length && <p className="empty">No discussion themes found for this period.</p>}</article>
    </section>
    <section className="social-feed-module"><header><div><span>Latest intelligence</span><h2>Verified content feed</h2><small>{feed.data?.meta.filteredCount ?? 0} matching records</small></div><button className="social-reset" onClick={() => setFeedFilter(emptyFeed())}>Reset filters</button></header><div className="social-filter-grid"><label className="social-search">Search<input value={feedFilter.query} onChange={(e) => updateFeed("query", e.target.value)} placeholder="Title, content or account" /></label>{([ ["monitorType", "Monitor type", options?.monitorTypes], ["country", "Country", options?.countries], ["brand", "Brand", options?.brands], ["platform", "Platform", options?.platforms], ["accountType", "Account type", options?.accountTypes], ["mediaType", "Media type", options?.mediaTypes] ] as [keyof FeedFilter, string, string[] | undefined][]).map(([key, label, items]) => <label key={key}>{label}<select value={feedFilter[key]} onChange={(e) => updateFeed(key, e.target.value)}><option value="">All</option>{items?.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>)}<label>From<input type="date" value={feedFilter.dateFrom} min={options?.dateRange.min ?? undefined} max={options?.dateRange.max ?? undefined} onChange={(e) => updateFeed("dateFrom", e.target.value)} /></label><label>To<input type="date" value={feedFilter.dateTo} min={options?.dateRange.min ?? undefined} max={options?.dateRange.max ?? undefined} onChange={(e) => updateFeed("dateTo", e.target.value)} /></label><label>Sort<select value={feedFilter.sort} onChange={(e) => updateFeed("sort", e.target.value)}><option value="recent">Most recent</option><option value="views">Most viewed</option><option value="likes">Most liked</option></select></label></div>{feed.isLoading ? <div className="module-loading">Loading intelligence…</div> : <div className="social-signal-grid">{feed.data?.records.map((record) => <SignalCard key={record.recordId} record={record} onOpen={() => setSelected(record)} />)}</div>}{!feed.isLoading && !feed.data?.records.length && <p className="empty">No intelligence matches the selected filters.</p>}</section>
    {selected && <div className="social-drawer-backdrop" onClick={() => setSelected(null)}><aside className="social-drawer" onClick={(event) => event.stopPropagation()}><button onClick={() => setSelected(null)}>×</button>{selected.mediaUrl && <img src={resolveApiAssetUrl(selected.mediaUrl)} alt="" />}<div className="social-badges"><span>{selected.country}</span><span>{selected.platform}</span><span>{selected.monitorType}</span></div><h2>{selected.title}</h2><p className="social-full-content">{selected.content}</p><h3>Why it matters</h3><p>{selected.whyItMatters}</p><div className="social-impact-list">{selected.businessImpact.map((item) => <span key={item}>{item}</span>)}</div><a href={selected.sourceUrl} target="_blank" rel="noreferrer">Open original post ↗</a></aside></div>}
  </div>;
}

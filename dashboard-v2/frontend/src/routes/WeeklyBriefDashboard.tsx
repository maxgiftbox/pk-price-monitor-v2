import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import { weeklyBriefApi } from '../lib/api';
import type { BriefExecutiveItem, WeeklyBrandBrief, WeeklyBrief } from '../types/weeklyBrief';

const number = new Intl.NumberFormat('en-US');
const dayMonth = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

function dateLabel(value: string) {
  return dayMonth.format(new Date(`${value}T00:00:00Z`));
}

function rangeLabel(start: string, end: string, year = false) {
  const a = new Date(`${start}T00:00:00Z`);
  const b = new Date(`${end}T00:00:00Z`);
  return `${a.getUTCDate()} – ${b.getUTCDate()} ${b.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })}${year ? ` ${b.getUTCFullYear()}` : ''}`;
}

function Skeleton() {
  return <div className="weekly-exec exec-skeleton"><div /><div /><div className="exec-skeleton-grid"><div /><div /></div><div /></div>;
}

function DataCoverage({ data }: { data: WeeklyBrief }) {
  return <section className="exec-coverage">
    <strong>DATA COVERAGE</strong>
    {data.coverage.map(item => <div key={item.label}>
      <b>{item.label}</b> · {item.through ? `through ${dateLabel(item.through)}` : 'no dated records'} · {number.format(item.count)} {item.label === 'Social' ? 'signals' : 'reviews'}
      <span className={item.current ? 'current' : 'behind'}>{item.status}</span>
    </div>)}
    <div className="coverage-scope">Pricing, availability and product data are not yet connected to this brief.</div>
  </section>;
}

function ExecutiveSummary({ items }: { items: BriefExecutiveItem[] }) {
  return <section className="exec-card exec-summary">
    <div className="exec-eyebrow">THE WEEK IN THREE LINES</div>
    {items.map(item => <article key={`${item.label}-${item.key}`}>
      <span className={`exec-badge ${item.label.toLowerCase()}`}>{item.label}</span>
      <div><h2>{item.title}</h2><p>{item.detail} <a href={`#brand-${item.key}`}>See evidence</a></p></div>
      <small>{item.source}</small>
    </article>)}
  </section>;
}

function Movers({ data }: { data: WeeklyBrief }) {
  const scale = Math.max(1, ...data.movers.map(item => Math.abs(item.delta)));
  return <section className="exec-card exec-movers">
    <div className="exec-eyebrow">MOVERS</div>
    <h2>Social activity, change vs last week</h2>
    <p className="exec-subtitle">Sorted by absolute change in captured posts. Stronger colour marks a change of at least 8 posts.</p>
    <div className="mover-list">{data.movers.map(item => <div className={item.material ? 'material' : ''} key={item.key}>
      <strong>{item.name}</strong>
      <span className="mover-track"><i className="negative"><em style={{ width: `${item.delta < 0 ? Math.abs(item.delta) / scale * 100 : 0}%` }} /></i><i className="positive"><em style={{ width: `${item.delta > 0 ? item.delta / scale * 100 : 0}%` }} /></i></span>
      <b>{item.delta > 0 ? '+' : ''}{item.delta}</b>
    </div>)}</div>
    <footer>Current and previous counts are visible in the Brand Scoreboard below.</footer>
  </section>;
}

function PriorityCards({ items }: { items: BriefExecutiveItem[] }) {
  return <div className="priority-stack">{items.map((item, index) => <article className="exec-card priority-card" key={`${item.label}-${item.key}`}>
    <header><h3>{index + 1} · {item.title}</h3><span className={`exec-badge ${item.label.toLowerCase()}`}>{item.label}</span></header>
    <div className="priority-columns">
      <div><strong>WHAT CHANGED</strong><p>{item.what_changed}</p></div>
      <div><strong>EVIDENCE</strong><p>{item.evidence}</p><a href={`#brand-${item.key}`}>Open brand evidence</a></div>
      <div><strong>NEXT STEP</strong><p>{item.next_step}</p></div>
    </div>
  </article>)}</div>;
}

function BrandEvidence({ item }: { item: WeeklyBrandBrief }) {
  return <div className="exec-evidence">
    <div><h4>Top social posts</h4>{item.top_posts.length ? item.top_posts.map(post => <a key={`${post.url}-${post.date}`} href={post.url} target="_blank" rel="noreferrer"><b>{post.summary || 'Untitled post'}</b><span>{post.platform} · {dateLabel(post.date)} · {number.format(post.likes)} likes</span></a>) : <p>No social posts captured.</p>}</div>
    <div><h4>Negative reviews</h4>{item.negative_reviews.length ? item.negative_reviews.map((review, index) => <article key={`${review.sku}-${index}`}><b>{review.rating}★ · {review.sku}</b><p>{review.text || 'No written review.'}</p></article>) : <p>No negative reviews captured.</p>}</div>
  </div>;
}

function Scoreboard({ data }: { data: WeeklyBrief }) {
  const brands = data.brands.filter(item => item.reviews || item.posts);
  return <section className="exec-card scoreboard">
    <header><div><div className="exec-eyebrow">BRAND SCOREBOARD</div><h2>One row per brand, on Daraz and off platform</h2></div><small>Sorted by Daraz reviews · previous week in brackets · expand a row for evidence</small></header>
    <div className="scoreboard-scroll"><table>
      <thead><tr><th rowSpan={2}>Brand</th><th className="daraz" colSpan={3}>ON DARAZ</th><th className="social" colSpan={2}>OFF PLATFORM</th><th rowSpan={2}>This week</th></tr><tr><th className="daraz">Reviews</th><th className="daraz">Rating</th><th className="daraz">Negative</th><th className="social">Posts</th><th className="social">Likes</th></tr></thead>
      <tbody>{brands.map(item => <tr id={`brand-${item.key}`} key={item.key}><td colSpan={7}><details><summary>
        <strong>{item.name}</strong><span>{item.reviews} ({item.reviews_prev})</span><span>{item.avg_rating == null ? '–' : item.avg_rating.toFixed(2)}</span><span>{item.reviews ? item.negative : '–'}</span><span>{item.posts} ({item.posts_prev})</span><span>{item.posts ? number.format(item.likes) : '–'}</span><span>{item.highlight}</span>
      </summary><BrandEvidence item={item} /></details></td></tr>)}</tbody>
    </table></div>
  </section>;
}

function DailyReviews({ data }: { data: WeeklyBrief }) {
  const max = Math.max(1, ...data.daily_reviews.map(item => item.count));
  const peaks = data.daily_reviews.filter(item => item.peak);
  const subtitle = peaks.length === 1 ? `Peak on ${dateLabel(peaks[0].date)}` : peaks.length === 2 ? `Two peaks, ${new Date(`${peaks[0].date}T00:00:00Z`).getUTCDate()} and ${dateLabel(peaks[1].date)}` : 'Reviews by day';
  return <section className="exec-card daily-card"><div className="exec-eyebrow">DAILY REVIEWS</div><h2>{subtitle}</h2><div className="daily-bars">{data.daily_reviews.map(item => <div className={item.peak ? 'peak' : ''} key={item.date}><b>{item.count}</b><i style={{ height: `${Math.max(2, item.count / max * 100)}%` }} /><small>{new Date(`${item.date}T00:00:00Z`).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', timeZone: 'UTC' })}</small></div>)}</div></section>;
}

function Topics({ data }: { data: WeeklyBrief }) {
  return <section className="exec-card topics-card"><div className="exec-eyebrow">WHAT BUYERS MENTIONED</div><h2>Reviews mentioning each topic</h2>{data.topics.length ? <table><thead><tr><th>Topic</th><th>This week</th><th>Last week</th></tr></thead><tbody>{data.topics.map(item => <tr className={`${item.emphasis ? 'emphasis ' : ''}${item.label.startsWith('Repeated') ? 'quality' : ''}`} key={item.label}><td>{item.label}</td><td>{item.cur}</td><td>{item.prev}</td></tr>)}</tbody></table> : <p className="exec-empty">No tracked topics appeared this week or last week.</p>}<footer>Keyword match on review text. Read as direction, not exact counts.</footer></section>;
}

function Market({ data }: { data: WeeklyBrief }) {
  return <section className="exec-card market-card"><header><div><div className="exec-eyebrow">MARKET AND POLICY</div><h2>{data.market.length ? 'News that is not about one brand' : `No market or policy news captured for ${data.country_name}`}</h2></div></header>{data.market.length ? <div className="market-grid">{data.market.map((item, index) => <a key={`${item.url}-${index}`} href={item.url} target="_blank" rel="noreferrer"><small>{item.category} · {item.account} · {dateLabel(item.date)}</small><strong>{item.summary}</strong></a>)}</div> : <p className="exec-empty">All {data.totals.posts} posts are brand or product content.</p>}</section>;
}

function copyText(data: WeeklyBrief) {
  const lines = [
    `EL Weekly Brief · ${data.country_name} · ${data.week.iso.replace(/^\d{4}-/, '')} (${rangeLabel(data.week.start, data.week.end, true)})`,
    '', 'The week in three lines',
    ...data.executive.map(item => `- [${item.label}] ${item.title} ${item.detail}`),
    '', 'Priority checks',
    ...data.priorities.map((item, index) => `${index + 1}. ${item.next_step}`),
    '', 'Brand scoreboard',
    ...data.brands.filter(item => item.reviews || item.posts).map(item => `- ${item.name}: ${item.reviews} reviews (${item.reviews_prev}), ${item.posts} posts (${item.posts_prev}). ${item.highlight}`),
  ];
  return navigator.clipboard.writeText(lines.join('\n'));
}

export function WeeklyBriefDashboard() {
  const [search, setSearch] = useSearchParams();
  const [copied, setCopied] = useState(false);
  const country = search.get('country') || 'PK';
  const week = search.get('week') || '';
  const params = useMemo(() => { const value = new URLSearchParams({ country }); if (week) value.set('week', week); return value; }, [country, week]);
  const query = useQuery({ queryKey: ['weekly-brief-executive', params.toString()], queryFn: () => weeklyBriefApi.get(params) });
  const data = query.data;
  const update = (key: string, value: string) => { const next = new URLSearchParams(search); next.set(key, value); setSearch(next); };
  if (query.isError) return <div className="error-panel"><p>Weekly Brief is temporarily unavailable.</p><button onClick={() => query.refetch()}>Retry</button></div>;
  if (!data) return <Skeleton />;

  const weekIndex = data.available_weeks.findIndex(item => item.iso === data.week.iso);
  const olderWeek = data.available_weeks[weekIndex + 1]?.iso;
  const newerWeek = weekIndex > 0 ? data.available_weeks[weekIndex - 1]?.iso : undefined;
  return <div className="weekly-exec">
    <header className="exec-header"><div><div className="exec-eyebrow">WEEKLY BRIEF · WEEK {data.week.iso.split('W')[1]}</div><h1>{data.country_name} · {rangeLabel(data.week.start, data.week.end, true)}</h1><p>Compared with {rangeLabel(data.prev_week.start, data.prev_week.end)}</p></div><div className="exec-controls"><div className="exec-country"><button className={country === 'PK' ? 'active' : ''} onClick={() => update('country', 'PK')}>Pakistan</button><button className={country === 'BD' ? 'active' : ''} onClick={() => update('country', 'BD')}>Bangladesh</button></div><div className="exec-week"><button disabled={!olderWeek} onClick={() => olderWeek && update('week', olderWeek)}>‹</button><span>{olderWeek?.replace(/^\d{4}-/, '') || '–'} · <b>{data.week.iso.replace(/^\d{4}-/, '')}</b> · {newerWeek?.replace(/^\d{4}-/, '') || '–'}</span><button disabled={!newerWeek} onClick={() => newerWeek && update('week', newerWeek)}>›</button></div><button className="exec-copy" onClick={async () => { await copyText(data); setCopied(true); window.setTimeout(() => setCopied(false), 1600); }}>{copied ? 'Copied' : 'Copy as text'}</button></div></header>
    <DataCoverage data={data} />
    <ExecutiveSummary items={data.executive} />
    <div className="exec-priority-layout"><Movers data={data} /><PriorityCards items={data.priorities} /></div>
    <Scoreboard data={data} />
    <div className="exec-supporting"><DailyReviews data={data} /><Topics data={data} /></div>
    <Market data={data} />
  </div>;
}

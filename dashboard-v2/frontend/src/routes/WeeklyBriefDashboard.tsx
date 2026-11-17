import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';

import { weeklyBriefApi } from '../lib/api';
import type { BriefSource, WeeklyBrandBrief, WeeklyBrief } from '../types/weeklyBrief';

const number = new Intl.NumberFormat('en-US');
const dayMonth = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', timeZone: 'UTC' });

function dateLabel(value: string) { return dayMonth.format(new Date(`${value}T00:00:00Z`)); }
function rangeLabel(start: string, end: string, year = false) {
  const a = new Date(`${start}T00:00:00Z`), b = new Date(`${end}T00:00:00Z`);
  const startDay = a.getUTCDate();
  return `${startDay} – ${b.getUTCDate()} ${b.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })}${year ? ` ${b.getUTCFullYear()}` : ''}`;
}

function Skeleton() {
  return <div className="weekly-v2 skeleton-page"><div className="sk sk-head" /><div className="sk sk-wide" /><div className="sk-grid"><div className="sk"/><div className="sk"/></div><div className="sk sk-wide"/></div>;
}

function SourceTag({ source }: { source: BriefSource }) {
  const label = source === 'on_daraz' ? 'ON DARAZ' : source === 'off_platform' ? 'OFF PLATFORM' : 'MARKET';
  return <span className={`brief-source ${source}`}>{label}</span>;
}

function ComparisonBars({ data }: { data: WeeklyBrief }) {
  const brands = data.brands.filter(item => item.reviews || item.posts).slice(0, 10);
  const maxReviews = Math.max(1, ...brands.map(item => item.reviews));
  const maxPosts = Math.max(1, ...brands.map(item => item.posts));
  return <section className="v2-card comparison-card">
    <header><div><span>ON DARAZ VS OFF PLATFORM</span><h2>Who sells on Daraz, and who is talking outside it</h2></div></header>
    <div className="comparison-legend"><i className="daraz"/> {data.display_mode === 'share' ? 'Share of Daraz reviews' : 'Daraz reviews'} <i className="off"/> {data.display_mode === 'share' ? 'Share of social posts' : 'Social posts'}</div>
    <div className="comparison-rows">{brands.map(item => {
      const darazValue = data.display_mode === 'share' ? `${Math.round(item.review_share * 100)}%` : item.reviews;
      const socialValue = data.display_mode === 'share' ? `${Math.round(item.post_share * 100)}%` : item.posts;
      return <div className="comparison-row" key={item.key}><strong>{item.name}</strong><div><i className="daraz" style={{width:`max(1px,${item.reviews / maxReviews * 100}%)`}}/><i className="off" style={{width:`max(1px,${item.posts / maxPosts * 100}%)`}}/></div><span>{darazValue} · {socialValue}</span></div>;
    })}</div>
    {data.display_mode === 'count' && <p className="count-note">Shown as counts, not shares, because the week has fewer than 100 reviews.</p>}
    <footer>Review count is used as a stand-in for Daraz sales until order data is connected.</footer>
  </section>;
}

function DailyReviews({ data }: { data: WeeklyBrief }) {
  const max = Math.max(1, ...data.daily_reviews.map(item => item.count));
  const peaks = data.daily_reviews.filter(item => item.peak);
  const subtitle = peaks.length === 1 ? `Peak on ${dateLabel(peaks[0].date)}` : peaks.length === 2 ? `Two peaks, ${new Date(`${peaks[0].date}T00:00:00Z`).getUTCDate()} and ${dateLabel(peaks[1].date)}` : 'Reviews by day';
  return <section className="v2-card daily-card"><header><div><span>DAILY REVIEWS</span><h2>{subtitle}</h2></div></header><div className="daily-bars">{data.daily_reviews.map(item => <div className={item.peak ? 'peak' : ''} key={item.date}><b>{item.count}</b><i style={{height:`${Math.max(2,item.count / max * 100)}%`}}/><small>{new Date(`${item.date}T00:00:00Z`).toLocaleString('en-GB',{weekday:'short',day:'numeric',timeZone:'UTC'})}</small></div>)}</div></section>;
}

function Topics({ data }: { data: WeeklyBrief }) {
  return <section className="v2-card topics-card"><header><div><span>WHAT BUYERS MENTIONED</span><h2>Reviews mentioning each topic</h2></div></header>{data.topics.length ? <table><thead><tr><th>Topic</th><th>This week</th><th>Last week</th></tr></thead><tbody>{data.topics.map(item => <tr className={`${item.emphasis ? 'emphasis ' : ''}${item.label.startsWith('Repeated') ? 'quality' : ''}`} key={item.label}><td>{item.label}</td><td>{item.cur}</td><td>{item.prev}</td></tr>)}</tbody></table> : <p className="v2-empty">No tracked topics appeared in review text this week or last week.</p>}<footer>Keyword match on review text. Read as direction, not exact counts.</footer></section>;
}

function BrandEvidence({ item }: { item: WeeklyBrandBrief }) {
  if (!item.top_posts.length && !item.negative_reviews.length) return <p className="v2-empty evidence-empty">No post or negative-review evidence captured for this brand.</p>;
  return <div className="brand-evidence">
    <div><h4>Top social posts</h4>{item.top_posts.length ? item.top_posts.map(post => <a key={`${post.url}-${post.date}`} href={post.url} target="_blank" rel="noreferrer"><strong>{post.summary || 'Untitled post'}</strong><span>{post.platform} · {dateLabel(post.date)} · {number.format(post.likes)} likes</span></a>) : <p>No social posts captured.</p>}</div>
    <div><h4>Negative reviews</h4>{item.negative_reviews.length ? item.negative_reviews.map((review,index) => <article key={`${review.sku}-${index}`}><strong>{review.rating}★ · {review.sku}</strong><p>{review.text || 'No written review.'}</p></article>) : <p>No negative reviews captured.</p>}</div>
  </div>;
}

function BrandTable({ data }: { data: WeeklyBrief }) {
  const shown = data.brands.filter(item => item.shown);
  const hidden = data.brands.filter(item => !item.shown && (item.reviews || item.posts));
  return <section className="v2-card brand-table-card"><header><div><span>BRAND HIGHLIGHTS</span><h2>One line per brand</h2></div><small>Sorted by Daraz reviews · last week in brackets</small></header><div className="v2-table-scroll"><table className="brand-table"><thead><tr><th rowSpan={2}>Brand</th><th className="daraz-head" colSpan={3}>ON DARAZ</th><th className="off-head" colSpan={2}>OFF PLATFORM</th><th rowSpan={2}>Highlight</th></tr><tr><th className="daraz-head">Reviews</th><th className="daraz-head">Rating</th><th className="daraz-head">Negative</th><th className="off-head">Posts</th><th className="off-head">Likes</th></tr></thead><tbody>{shown.map(item => <tr className="brand-main-row" key={item.key}><td colSpan={7}><details><summary><span className="brand-name">{item.name}</span><span>{item.reviews} ({item.reviews_prev})</span><span>{item.avg_rating == null ? '–' : item.avg_rating.toFixed(2)}</span><span>{item.reviews ? item.negative : '–'}</span><span>{item.posts} ({item.posts_prev})</span><span>{item.posts ? number.format(item.likes) : '–'}</span><span className="brand-highlight">{item.highlight}</span></summary><BrandEvidence item={item}/></details></td></tr>)}</tbody></table></div>{hidden.length > 0 && <p className="not-shown">Not shown: {hidden.map(item => `${item.name} (${item.reviews} review${item.reviews === 1 ? '' : 's'}, ${item.posts} posts)`).join('. ')}.</p>}</section>;
}

function Market({ data }: { data: WeeklyBrief }) {
  return <section className="v2-card market-card"><header><div><span>MARKET AND POLICY</span><h2>{data.market.length ? 'News that is not about one brand' : `No market or policy news captured for ${data.country_name} this week`}</h2></div></header>{data.market.length ? <div className="market-grid">{data.market.map((item,index) => <a key={`${item.url}-${index}`} href={item.url} target="_blank" rel="noreferrer"><small>{item.category} · {item.account} · {dateLabel(item.date)}</small><strong>{item.summary}</strong></a>)}</div> : <p className="v2-empty">All {data.totals.posts} posts are brand or product content.</p>}</section>;
}

function copyText(data: WeeklyBrief) {
  const lines = [`EL Weekly Brief · ${data.country_name} · ${data.week.iso.replace(/^\d{4}-/,'')} (${rangeLabel(data.week.start,data.week.end,true)})`, '', 'What happened', ...data.topline.map(item => `- [${item.source === 'on_daraz' ? 'On Daraz' : item.source === 'off_platform' ? 'Off platform' : 'Market'}] ${item.headline} ${item.detail}`.trim()), '', 'Brand highlights', ...data.brands.filter(item => item.shown).map(item => `- ${item.name}: ${item.reviews} reviews (${item.reviews_prev}), ${item.posts} posts (${item.posts_prev}). ${item.highlight}`)];
  return navigator.clipboard.writeText(lines.join('\n'));
}

export function WeeklyBriefDashboard() {
  const [search, setSearch] = useSearchParams();
  const [copied, setCopied] = useState(false);
  const country = search.get('country') || 'PK';
  const week = search.get('week') || '';
  const params = useMemo(() => { const p = new URLSearchParams({country}); if (week) p.set('week',week); return p; }, [country,week]);
  const query = useQuery({ queryKey:['weekly-brief-v2',params.toString()], queryFn:()=>weeklyBriefApi.get(params) });
  const data = query.data;
  const update = (key:string,value:string) => { const next = new URLSearchParams(search); next.set(key,value); setSearch(next); };
  if (query.isError) return <div className="error-panel"><p>Weekly Brief is temporarily unavailable.</p><button onClick={()=>query.refetch()}>Retry</button></div>;
  if (!data) return <Skeleton/>;
  const weekIndex = data.available_weeks.findIndex(item => item.iso === data.week.iso);
  const olderWeek = data.available_weeks[weekIndex + 1]?.iso;
  const newerWeek = weekIndex > 0 ? data.available_weeks[weekIndex - 1]?.iso : undefined;
  return <div className="weekly-v2">
    <header className="v2-header"><div><span>WEEKLY BRIEF · WEEK {data.week.iso.split('W')[1]}</span><h1>{data.country_name} · {rangeLabel(data.week.start,data.week.end,true)}</h1><p>Compared with {rangeLabel(data.prev_week.start,data.prev_week.end)} · {data.totals.reviews} Daraz reviews · {data.totals.posts} social posts</p></div><div className="v2-controls"><div className="country-toggle"><button className={country==='PK'?'active':''} onClick={()=>update('country','PK')}>Pakistan</button><button className={country==='BD'?'active':''} onClick={()=>update('country','BD')}>Bangladesh</button></div><div className="week-switcher"><button disabled={!olderWeek} onClick={()=>olderWeek&&update('week',olderWeek)} aria-label="Previous week">‹</button><span>{data.week.iso.replace(/^\d{4}-/,'')}</span><button disabled={!newerWeek} onClick={()=>newerWeek&&update('week',newerWeek)} aria-label="Next week">›</button></div><button className="copy-button" onClick={async()=>{await copyText(data);setCopied(true);window.setTimeout(()=>setCopied(false),1600)}}>{copied?'Copied':'Copy as text'}</button></div></header>
    <section className="v2-card topline-card"><header><span>WHAT HAPPENED THIS WEEK</span></header><div>{data.topline.map((item,index)=><article key={`${item.source}-${index}`}><SourceTag source={item.source}/><p><strong>{item.headline}</strong>{item.detail && <small>{item.detail}</small>}</p></article>)}</div></section>
    <div className="v2-insight-grid"><ComparisonBars data={data}/><div className="v2-side-grid"><DailyReviews data={data}/><Topics data={data}/></div></div>
    <BrandTable data={data}/><Market data={data}/>
  </div>;
}

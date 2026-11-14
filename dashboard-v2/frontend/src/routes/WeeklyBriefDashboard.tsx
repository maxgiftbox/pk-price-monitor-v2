import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { weeklyBriefApi } from '../lib/api';
import type { WeeklyBrandBrief } from '../types/weeklyBrief';

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

function delta(value: number | null | undefined, digits = 1) {
  if (value == null) return '—';
  if (Math.abs(value) < 0.005) return '→';
  return `${value > 0 ? '↑' : '↓'} ${Math.abs(value).toFixed(digits)}`;
}

function metric(value: number | null | undefined, suffix = '') {
  return value == null ? 'No data' : `${value.toFixed(1)}${suffix}`;
}

function BrandBrief({ item }: { item: WeeklyBrandBrief }) {
  const cv = item.consumerVoice;
  const sv = item.socialVoice;
  const followUp = item.status === 'watch_closely'
    ? `Ask the local team to validate whether ${cv?.topRiskTopics[0]?.toLowerCase() ?? 'negative feedback'} is concentrated in one product or seller.`
    : item.status === 'social_momentum'
      ? 'Review the content and channel mix behind this increase for repeatable campaign learnings.'
      : 'Continue monitoring; no immediate management intervention is indicated.';

  return <details className="brief-brand-card">
    <summary>
      <span><strong>{item.brand}</strong><small>{item.keySignal}</small></span>
      <span className={`brief-status ${item.status}`}>{item.statusLabel}</span>
    </summary>
    <div className="brief-brand-body">
      <div className="brief-voice-panel">
        <header><span>Consumer Voice</span><b>{metric(cv?.averageRating, ' ★')} <i>{delta(cv?.ratingChange, 2)}</i></b></header>
        <dl><div><dt>Reviews</dt><dd>{cv?.reviewCount ?? 0}</dd></div><div><dt>Positive</dt><dd>{cv?.positiveRate == null ? '—' : `${Math.round(cv.positiveRate * 100)}%`}</dd></div><div><dt>Risk trend</dt><dd>{delta(cv?.negativeRateChange == null ? null : cv.negativeRateChange * 100, 0)} pp</dd></div></dl>
        <p><b>Positive themes</b>{cv?.topPositiveTopics.join(' · ') || 'No verified theme'}</p>
        <p className="risk"><b>Risk themes</b>{cv?.topRiskTopics.join(' · ') || 'No material risk theme'}</p>
      </div>
      <div className="brief-voice-panel">
        <header><span>Social Voice</span><b>{metric(sv?.socialRating)} <i>{delta(sv?.ratingChange)}</i></b></header>
        <dl><div><dt>Market rank</dt><dd>{sv ? `#${sv.rank}` : '—'}</dd></div><div><dt>Signals</dt><dd>{sv?.signalCount ?? 0}</dd></div><div><dt>Likes</dt><dd>{compact.format(sv?.totalLikes ?? 0)}</dd></div></dl>
        <p><b>Top topics</b>{sv?.topTopics.join(' · ') || 'No verified theme'}</p>
        <p><b>Data confidence</b>{item.confidence}</p>
      </div>
      <aside><span>Suggested follow-up</span><p>{followUp}</p></aside>
    </div>
  </details>;
}

export function WeeklyBriefDashboard() {
  const [country, setCountry] = useState('PK');
  const [weekEnd, setWeekEnd] = useState('');
  const params = useMemo(() => {
    const result = new URLSearchParams();
    if (country) result.set('country', country);
    if (weekEnd) result.set('weekEnd', weekEnd);
    return result;
  }, [country, weekEnd]);
  const query = useQuery({ queryKey: ['weekly-brief', params.toString()], queryFn: () => weeklyBriefApi.get(params) });
  const data = query.data;

  if (query.isError) return <div className="error-panel"><p>Weekly Brief is temporarily unavailable.</p><button onClick={() => query.refetch()}>Retry</button></div>;
  if (!data) return <div className="module-loading">Preparing the executive brief…</div>;

  return <div className="weekly-brief-page">
    <header className="brief-page-header">
      <div><span>Weekly Voice Executive Brief</span><h1>{data.country.name} market pulse</h1><p>{data.week.start} – {data.week.end} · compared with the previous 7 days</p></div>
      <div className="brief-controls"><label>Country<select value={data.country.code} onChange={(event) => setCountry(event.target.value)}>{data.countries.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}</select></label><label>Week ending<input type="date" value={weekEnd || data.week.end} onChange={(event) => setWeekEnd(event.target.value)} /></label></div>
    </header>

    <section className="brief-hero">
      <div className="brief-summary"><span>Market pulse</span><h2>{data.marketSummary}</h2><p>{data.meta.consumerRows} consumer reviews · {data.meta.socialSignals} verified social signals</p></div>
      <div className="brief-callouts">
        <article><span>Strongest brand</span><strong>{data.callouts.strongest ?? 'No signal'}</strong><small>Cross-channel performance</small></article>
        <article><span>Fastest momentum</span><strong>{data.callouts.momentum ?? 'No signal'}</strong><small>Week-on-week movement</small></article>
        <article className={data.callouts.watch ? 'watch' : ''}><span>Watch closely</span><strong>{data.callouts.watch ?? 'No material risk'}</strong><small>Management attention</small></article>
      </div>
    </section>

    <section className="brief-section">
      <header><div><span>Competitive scoreboard</span><h2>Brand performance at a glance</h2></div><small>Ordered by management relevance</small></header>
      <div className="brief-table-wrap"><table className="brief-table"><thead><tr><th>Brand</th><th>Weekly status</th><th>Consumer Voice</th><th>Social Voice</th><th>Key signal</th><th>Confidence</th></tr></thead><tbody>{data.brands.map((item) => <tr key={item.brand}><td><strong>{item.brand}</strong></td><td><span className={`brief-status ${item.status}`}>{item.statusLabel}</span></td><td>{metric(item.consumerVoice?.averageRating, ' ★')} <i>{delta(item.consumerVoice?.ratingChange, 2)}</i></td><td>{metric(item.socialVoice?.socialRating)} <i>{delta(item.socialVoice?.ratingChange)}</i></td><td>{item.keySignal}</td><td><span className={`brief-confidence ${item.confidence.toLowerCase()}`}>{item.confidence}</span></td></tr>)}</tbody></table></div>
    </section>

    <section className="brief-section brief-changes">
      <header><div><span>What changed</span><h2>Material movements this week</h2></div></header>
      {data.highlights.length ? <div>{data.highlights.map((item) => <article key={`${item.brand}-${item.status}`}><b>{item.status === 'watch_closely' ? '↓' : '↑'}</b><span><strong>{item.brand} · {item.statusLabel}</strong><p>{item.text}</p></span><small>{item.confidence} confidence</small></article>)}</div> : <p className="brief-empty">No material market shifts were detected this week.</p>}
    </section>

    <section className="brief-section brief-brand-list">
      <header><div><span>Brand briefs</span><h2>Evidence and suggested follow-up</h2></div><small>Expand a brand for detail</small></header>
      {data.brands.map((item) => <BrandBrief key={item.brand} item={item} />)}
    </section>
    <footer className="brief-methodology">Highlights require a meaningful week-on-week change and sufficient verified data. Low-confidence signals are kept out of the executive headline.</footer>
  </div>;
}

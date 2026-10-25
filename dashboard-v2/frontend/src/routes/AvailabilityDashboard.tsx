import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { availabilityApi } from '../lib/api';
import type { AvailabilityRow, AvailabilityStatus } from '../types/availability';

const statusLabel: Record<AvailabilityStatus, string> = {
  available: 'Available', unavailable: 'Unavailable', unknown: 'Unknown',
};

function StatusBadge({ status }: { status: AvailabilityStatus }) {
  return <span className={`availability-status ${status}`}>{statusLabel[status]}</span>;
}

function formatDate(value: string | null) {
  if (!value) return 'Not available';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function formatGmv(value: number | string | null) {
  const parsed = Number(String(value ?? '').replace(/,/g, ''));
  return Number.isFinite(parsed) && parsed > 0 ? parsed.toLocaleString() : '—';
}

export function AvailabilityDashboard() {
  const [view, setView] = useState<'overview' | 'matrix'>('overview');
  const [venture, setVenture] = useState('');
  const [brand, setBrand] = useState('');
  const [category, setCategory] = useState('');
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
  const [search, setSearch] = useState('');

  const params = useMemo(() => {
    const value = new URLSearchParams();
    if (venture) value.append('venture', venture);
    if (brand) value.append('brand', brand);
    if (category) value.append('category', category);
    if (status) value.append('status', status);
    if (priority) value.append('priority', priority);
    if (search) value.set('search', search);
    return value;
  }, [venture, brand, category, status, priority, search]);

  const query = useQuery({
    queryKey: ['availability-dashboard', params.toString()],
    queryFn: () => availabilityApi.dashboard(params),
  });
  const data = query.data;

  const products = useMemo(() => {
    const groups = new Map<string, AvailabilityRow[]>();
    for (const row of data?.rows ?? []) {
      const key = `${row.venture}:${row.productId}`;
      groups.set(key, [...(groups.get(key) ?? []), row]);
    }
    return Array.from(groups.values()).sort((a, b) => a[0].productName.localeCompare(b[0].productName));
  }, [data?.rows]);

  if (query.isLoading) return <div className="loading-panel">Loading availability dashboard…</div>;
  if (query.isError || !data) return <div className="error-panel"><p>Availability data is temporarily unavailable.</p><button onClick={() => query.refetch()}>Retry</button></div>;

  const summaryCards = [
    ['Products', data.summary.products], ['Variants', data.summary.variants],
    ['Available', data.summary.available], ['Unavailable', data.summary.unavailable],
    ['Unknown', data.summary.unknown],
    ['Availability rate', data.summary.availabilityRate == null ? '—' : `${(data.summary.availabilityRate * 100).toFixed(1)}%`],
    ['High-priority unavailable', data.summary.highPriorityUnavailable],
  ];

  return <div className="availability-page">
    <header className="availability-header">
      <div><span>Stock intelligence</span><h1>Availability</h1><p>Daraz variant availability across PK, BD and NP</p></div>
      <div className={`availability-freshness ${data.meta.stale ? 'stale' : ''}`}>
        <strong>{data.meta.stale ? 'Showing cached snapshot' : 'Latest successful crawl'}</strong>
        <span>{formatDate(data.meta.dataAsOf)} · {data.meta.coverage} variants covered</span>
      </div>
    </header>

    <section className="availability-filters">
      <select aria-label="Country" value={venture} onChange={e => setVenture(e.target.value)}><option value="">All countries</option>{data.options.ventures.map(v => <option key={v}>{v}</option>)}</select>
      <select aria-label="Brand" value={brand} onChange={e => setBrand(e.target.value)}><option value="">All brands</option>{data.options.brands.map(v => <option key={v}>{v}</option>)}</select>
      <select aria-label="Category" value={category} onChange={e => setCategory(e.target.value)}><option value="">All categories</option>{data.options.categories.map(v => <option key={v}>{v}</option>)}</select>
      <select aria-label="Availability" value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{data.options.statuses.map(v => <option key={v} value={v}>{statusLabel[v]}</option>)}</select>
      <select aria-label="Priority" value={priority} onChange={e => setPriority(e.target.value)}><option value="">All priorities</option><option value="high">High priority</option><option value="standard">Standard</option></select>
      <input aria-label="Search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search product, memory, color or SKU" />
    </section>

    <div className="availability-view-tabs">
      <button className={view === 'overview' ? 'active' : ''} onClick={() => setView('overview')}>Overview</button>
      <button className={view === 'matrix' ? 'active' : ''} onClick={() => setView('matrix')}>Variant Matrix</button>
    </div>

    {view === 'overview' ? <>
      <section className="availability-kpis">{summaryCards.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}</section>

      <section className="availability-card"><header><div><span>Brand overview</span><h2>Availability by brand</h2></div></header>
        <div className="availability-table-scroll"><table><thead><tr><th>Brand</th><th>Products</th><th>Variants</th><th>Available</th><th>Unavailable</th><th>Unknown</th><th>Rate</th></tr></thead><tbody>
          {data.brands.map(row => <tr key={row.brand}><td><strong>{row.brand}</strong></td><td>{row.products}</td><td>{row.variants}</td><td>{row.available}</td><td>{row.unavailable}</td><td>{row.unknown}</td><td>{row.availabilityRate == null ? '—' : `${(row.availabilityRate * 100).toFixed(1)}%`}</td></tr>)}
        </tbody></table></div>
      </section>

      <section className="availability-card"><header><div><span>Needs action</span><h2>Unavailable and unverified variants</h2></div><small>{data.actions.length} variants</small></header>
        <div className="availability-table-scroll"><table><thead><tr><th>Priority</th><th>Country</th><th>Brand</th><th>Product</th><th>Memory</th><th>Color</th><th>Status</th><th>L90 GMV</th><th>Checked</th><th>Action</th></tr></thead><tbody>
          {data.actions.map(row => <tr key={row.darazSku}><td><span className={`priority-badge ${row.priority}`}>{row.priority === 'high' ? 'High' : 'Standard'}</span></td><td>{row.venture}</td><td>{row.brand}</td><td><strong>{row.productName}</strong><small>{row.darazSku}</small></td><td>{row.memory || '—'}</td><td>{row.color}</td><td><StatusBadge status={row.status} /></td><td>{formatGmv(row.l90Gmv)}</td><td>{formatDate(row.crawledAt)}</td><td><a href={row.url} target="_blank" rel="noreferrer">Open Daraz</a></td></tr>)}
          {!data.actions.length && <tr><td colSpan={10} className="availability-empty">No variants require action.</td></tr>}
        </tbody></table></div>
      </section>
    </> : <section className="availability-matrix">
      {products.map(rows => {
        const available = rows.filter(row => row.status === 'available').length;
        return <article key={`${rows[0].venture}:${rows[0].productId}`}><header><div><span>{rows[0].venture} · {rows[0].brand}</span><h2>{rows[0].productName}</h2></div><small>{rows.length} variants · {Math.round(available / rows.length * 100)}% available</small></header><div className="variant-chips">
          {rows.map(row => <a key={row.darazSku} className={`variant-chip ${row.status}`} href={row.url} target="_blank" rel="noreferrer"><span>{row.color}</span><strong>{statusLabel[row.status]}</strong>{row.priority === 'high' && <em>High priority</em>}</a>)}
        </div></article>;
      })}
      {!products.length && <div className="availability-empty">No products match the selected filters.</div>}
    </section>}
  </div>;
}

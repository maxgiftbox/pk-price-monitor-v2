import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { availabilityApi } from '../lib/api';
import type { AvailabilityRow, AvailabilityStatus } from '../types/availability';

type ProductGroup = { key: string; rows: AvailabilityRow[]; unavailable: number; unknown: number; issues: number };
const statusLabel: Record<AvailabilityStatus, string> = { available: 'Available', unavailable: 'Unavailable', unknown: 'Unknown' };
const statusRank: Record<AvailabilityStatus, number> = { available: 0, unknown: 1, unavailable: 2 };

function formatDate(value: string | null) {
  if (!value) return 'Not available';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}

function formatGmv(value: number | string | null) {
  const parsed = Number(String(value ?? '').replace(/,/g, ''));
  return Number.isFinite(parsed) && parsed > 0 ? parsed.toLocaleString() : '—';
}

function memoryLabel(row: AvailabilityRow) {
  const matches = row.productName.match(/\b\d+(?:\.\d+)?\s*(?:GB|TB)\b/gi) ?? [];
  const normalized = matches.map(value => value.replace(/\s+/g, '').toUpperCase());
  if (normalized.length >= 2) return normalized.slice(-2).join('+');
  return row.memory || normalized[0] || 'Not specified';
}

function ProductMatrixCard({ group, onSelect }: { group: ProductGroup; onSelect: (row: AvailabilityRow) => void }) {
  const [open, setOpen] = useState(group.issues > 0);
  const first = group.rows[0];
  const memories = Array.from(new Set(group.rows.map(memoryLabel))).sort();
  const colors = Array.from(new Set(group.rows.map(row => row.color || 'Not specified'))).sort();
  const lookup = new Map<string, AvailabilityRow>();
  for (const row of group.rows) {
    const key = `${memoryLabel(row)}\u0000${row.color || 'Not specified'}`;
    const existing = lookup.get(key);
    if (!existing || statusRank[row.status] > statusRank[existing.status]) lookup.set(key, row);
  }
  const headlineStatus: AvailabilityStatus = group.unavailable ? 'unavailable' : group.unknown ? 'unknown' : 'available';
  return <article className={`product-matrix-card ${open ? 'open' : ''}`}>
    <button className="product-matrix-header" type="button" onClick={() => setOpen(value => !value)} aria-expanded={open}>
      <span className={`matrix-head-status ${headlineStatus}`} aria-hidden="true" />
      <span className="matrix-product-name"><small>{first.venture} · {first.brand} · {first.category}</small><strong>{first.productName}</strong></span>
      <span className="matrix-product-counts">{group.rows.length} Variants <i>·</i> <b>{group.issues} Issues</b></span>
      <span className="matrix-chevron" aria-hidden="true">⌄</span>
    </button>
    {open && <div className="product-matrix-scroll"><table className="product-variant-matrix">
      <thead><tr><th>Memory / Color</th>{colors.map(color => <th key={color}>{color}</th>)}</tr></thead>
      <tbody>{memories.map(memory => <tr key={memory}><th>{memory}</th>{colors.map(color => {
        const row = lookup.get(`${memory}\u0000${color}`);
        return <td key={color}>{row
          ? <button className={`matrix-status-cell ${row.status}`} type="button" title={`${color}: ${statusLabel[row.status]}`} onClick={() => onSelect(row)}><span /><em>{statusLabel[row.status]}</em></button>
          : <span className="matrix-status-cell na" title={`${color}: N/A`}><span /><em>N/A</em></span>}
        </td>;
      })}</tr>)}</tbody>
    </table></div>}
  </article>;
}

function SkuDetail({ row, onClose }: { row: AvailabilityRow; onClose: () => void }) {
  return <div className="sku-detail-backdrop" role="presentation" onMouseDown={event => event.target === event.currentTarget && onClose()}>
    <section className="sku-detail-popover" role="dialog" aria-modal="true" aria-label="SKU detail">
      <button className="sku-detail-close" type="button" onClick={onClose} aria-label="Close">×</button>
      <span>SKU DETAIL</span><h2>{row.productName}</h2>
      <div className="sku-detail-status"><i className={row.status} />{statusLabel[row.status]}</div>
      <dl><div><dt>Memory</dt><dd>{memoryLabel(row)}</dd></div><div><dt>Color</dt><dd>{row.color}</dd></div><div><dt>SKU ID</dt><dd>{row.darazSku}</dd></div><div><dt>Last checked</dt><dd>{formatDate(row.crawledAt)}</dd></div><div><dt>L90D GMV</dt><dd>{formatGmv(row.l90Gmv)}</dd></div></dl>
      <a href={row.url} target="_blank" rel="noreferrer">Open Daraz</a>
    </section>
  </div>;
}

export function AvailabilityDashboard() {
  const [venture, setVenture] = useState('');
  const [brand, setBrand] = useState('');
  const [category, setCategory] = useState('');
  const [availability, setAvailability] = useState<'issues' | 'all'>('issues');
  const [search, setSearch] = useState('');
  const [selectedSku, setSelectedSku] = useState<AvailabilityRow | null>(null);
  const params = useMemo(() => {
    const value = new URLSearchParams();
    if (venture) value.append('venture', venture);
    if (brand) value.append('brand', brand);
    if (category) value.append('category', category);
    if (search) value.set('search', search);
    return value;
  }, [venture, brand, category, search]);
  const query = useQuery({ queryKey: ['availability-dashboard', params.toString()], queryFn: () => availabilityApi.dashboard(params) });
  const data = query.data;
  const products = useMemo(() => {
    const groups = new Map<string, AvailabilityRow[]>();
    for (const row of data?.rows ?? []) {
      const key = `${row.venture}:${row.productId}`;
      groups.set(key, [...(groups.get(key) ?? []), row]);
    }
    return Array.from(groups, ([key, rows]) => {
      const unavailable = rows.filter(row => row.status === 'unavailable').length;
      const unknown = rows.filter(row => row.status === 'unknown').length;
      return { key, rows, unavailable, unknown, issues: unavailable + unknown };
    }).sort((a, b) => b.unavailable - a.unavailable || b.unknown - a.unknown || a.rows[0].productName.localeCompare(b.rows[0].productName));
  }, [data?.rows]);
  if (query.isLoading) return <div className="loading-panel">Loading availability dashboard…</div>;
  if (query.isError || !data) return <div className="error-panel"><p>Availability data is temporarily unavailable.</p><button onClick={() => query.refetch()}>Retry</button></div>;
  const issueProducts = products.filter(product => product.issues > 0);
  const visibleProducts = availability === 'issues' ? issueProducts : products;
  const unavailableVariants = products.reduce((total, product) => total + product.unavailable, 0);
  return <div className="availability-page compact-availability-page">
    <header className="availability-header"><div><span>Stock intelligence</span><h1>Availability</h1><p>One Product, One Matrix, All Variants Visible</p></div><div className={`availability-freshness ${data.meta.stale ? 'stale' : ''}`}><strong>{data.meta.stale ? 'Showing cached snapshot' : 'Last updated'}</strong><span>{formatDate(data.meta.dataAsOf)} · {data.meta.coverage} variants covered</span></div></header>
    <section className="availability-filters compact-availability-filters">
      <label><span>Country</span><select value={venture} onChange={event => setVenture(event.target.value)}><option value="">All Countries</option>{data.options.ventures.map(value => <option key={value}>{value}</option>)}</select></label>
      <label><span>Brand</span><select value={brand} onChange={event => setBrand(event.target.value)}><option value="">All Brands</option>{data.options.brands.map(value => <option key={value}>{value}</option>)}</select></label>
      <label><span>Category</span><select value={category} onChange={event => setCategory(event.target.value)}><option value="">All Categories</option>{data.options.categories.map(value => <option key={value}>{value}</option>)}</select></label>
      <label><span>Availability</span><select value={availability} onChange={event => setAvailability(event.target.value as 'issues' | 'all')}><option value="issues">Issues Only</option><option value="all">All</option></select></label>
      <label className="availability-search"><span>Search</span><input value={search} onChange={event => setSearch(event.target.value)} placeholder="Product Name / SKU ID" /></label>
    </section>
    <section className="availability-kpis compact-availability-kpis"><article><span>Total Products</span><strong>{products.length}</strong></article><article className="issue-kpi"><span>Products with Issues</span><strong>{issueProducts.length}</strong></article><article className="unavailable-kpi"><span>Unavailable Variants</span><strong>{unavailableVariants}</strong></article></section>
    <section className="product-matrix-section"><header><div><span>PRODUCT AVAILABILITY MATRIX</span><h2>{availability === 'issues' ? 'Products requiring attention' : 'All monitored products'}</h2></div><div className="matrix-legend"><span><i className="available" />Available</span><span><i className="unavailable" />Unavailable</span><span><i className="unknown" />Unknown</span><span><i className="na" />N/A</span></div></header><div className="product-matrix-list">{visibleProducts.map(product => <ProductMatrixCard key={product.key} group={product} onSelect={setSelectedSku} />)}</div>{!visibleProducts.length && <div className="availability-empty">No products match the selected filters.</div>}</section>
    {selectedSku && <SkuDetail row={selectedSku} onClose={() => setSelectedSku(null)} />}
  </div>;
}

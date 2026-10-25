import { useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';

import { availabilityApi } from '../lib/api';
import type { AvailabilityRow, AvailabilityStatus } from '../types/availability';

type ProductGroup = { key: string; rows: AvailabilityRow[]; available: number; unavailable: number; unknown: number; issues: number };
type DisplayPriority = 'high' | 'medium' | 'low';
const statusLabel: Record<AvailabilityStatus, string> = { available: 'Available', unavailable: 'Unavailable', unknown: 'Unknown' };
const statusRank: Record<AvailabilityStatus, number> = { available: 0, unknown: 1, unavailable: 2 };
const countryOrder = ['PK', 'BD', 'NP'];

function formatDate(value: string | null) {
  if (!value) return 'Not available';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
}
function numeric(value: number | string | null) { const parsed = Number(String(value ?? '').replace(/,/g, '')); return Number.isFinite(parsed) ? parsed : 0; }
function formatGmv(value: number | string | null) { const parsed = numeric(value); return parsed > 0 ? parsed.toLocaleString() : '—'; }
function rate(part: number, total: number) { return total ? part / total : null; }
function rateLabel(value: number | null) { return value == null ? 'N/A' : `${(value * 100).toFixed(1)}%`; }
function memoryLabel(row: AvailabilityRow) {
  const matches = row.productName.match(/\b\d+(?:\.\d+)?\s*(?:GB|TB)\b/gi) ?? [];
  const normalized = matches.map(value => value.replace(/\s+/g, '').toUpperCase());
  return normalized.length >= 2 ? normalized.slice(-2).join('+') : row.memory || normalized[0] || 'Not specified';
}
function displayPriority(row: AvailabilityRow): DisplayPriority {
  if (row.priority === 'high') return 'high';
  return numeric(row.l90Gmv) > 0 ? 'medium' : 'low';
}
function groupProducts(rows: AvailabilityRow[]): ProductGroup[] {
  const groups = new Map<string, AvailabilityRow[]>();
  for (const row of rows) {
    const key = `${row.venture}:${row.productId}`;
    groups.set(key, [...(groups.get(key) ?? []), row]);
  }
  return Array.from(groups, ([key, productRows]) => {
    const available = productRows.filter(row => row.status === 'available').length;
    const unavailable = productRows.filter(row => row.status === 'unavailable').length;
    const unknown = productRows.filter(row => row.status === 'unknown').length;
    return { key, rows: productRows, available, unavailable, unknown, issues: unavailable + unknown };
  }).sort((a, b) => b.unavailable - a.unavailable || b.unknown - a.unknown || a.rows[0].productName.localeCompare(b.rows[0].productName));
}
function sortedRows(rows: AvailabilityRow[]) {
  return [...rows].sort((a, b) => memoryLabel(a).localeCompare(memoryLabel(b)) || a.color.localeCompare(b.color) || a.darazSku.localeCompare(b.darazSku));
}

function SkuTooltip({ row, rect }: { row: AvailabilityRow; rect: DOMRect }) {
  const below = rect.top < 210;
  const left = Math.max(170, Math.min(window.innerWidth - 170, rect.left + rect.width / 2));
  const top = below ? rect.bottom + 8 : rect.top - 8;
  return createPortal(<div className={`sku-hover-tooltip ${below ? 'below' : 'above'}`} style={{ left, top }}>
    <strong>{row.productName}</strong><span>{memoryLabel(row)} · {row.color}</span>
    <dl><div><dt>SKU ID</dt><dd>{row.darazSku}</dd></div><div><dt>Status</dt><dd className={row.status}>{statusLabel[row.status]}</dd></div><div><dt>Last checked</dt><dd>{formatDate(row.crawledAt)}</dd></div><div><dt>L90D GMV</dt><dd>{formatGmv(row.l90Gmv)}</dd></div></dl>
  </div>, document.body);
}

function SkuStatus({ row, compact = false }: { row: AvailabilityRow; compact?: boolean }) {
  const [rect, setRect] = useState<DOMRect | null>(null);
  const className = `${compact ? 'availability-block' : 'matrix-status-cell'} ${row.status}`;
  const content = <><span /><em>{compact ? '' : statusLabel[row.status]}</em></>;
  const events = { onMouseEnter: (event: React.MouseEvent<HTMLElement>) => setRect(event.currentTarget.getBoundingClientRect()), onMouseLeave: () => setRect(null) };
  return <>{row.url ? <a className={className} href={row.url} target="_blank" rel="noreferrer" {...events} aria-label={`${row.darazSku}: ${statusLabel[row.status]}`}>{content}</a> : <span className={`${className} disabled`} {...events}>{content}</span>}{rect && <SkuTooltip row={row} rect={rect} />}</>;
}

function ProductMonitorRow({ group }: { group: ProductGroup }) {
  const [open, setOpen] = useState(false);
  const first = group.rows[0];
  const ordered = sortedRows(group.rows);
  const memories = Array.from(new Set(ordered.map(memoryLabel)));
  const colors = Array.from(new Set(ordered.map(row => row.color || 'Not specified')));
  const lookup = new Map<string, AvailabilityRow>();
  for (const row of ordered) {
    const key = `${memoryLabel(row)}\u0000${row.color || 'Not specified'}`;
    const existing = lookup.get(key);
    if (!existing || statusRank[row.status] > statusRank[existing.status]) lookup.set(key, row);
  }
  return <article className={`product-monitor-row ${open ? 'open' : ''}`}>
    <div className="product-monitor-summary">
      <div className="monitor-product"><small>{first.brand} · {first.category}</small><strong>{first.productName}</strong></div>
      <div className="monitor-count"><strong>{group.rows.length}</strong><span>Variants</span></div>
      <div className="monitor-count available"><strong>{group.available}</strong><span>Available</span></div>
      <div className="monitor-count unavailable"><strong>{group.unavailable}</strong><span>Unavailable</span></div>
      <div className="monitor-count unknown"><strong>{group.unknown}</strong><span>Unknown</span></div>
      <div className="availability-bar" aria-label="Variant availability overview">{ordered.map(row => <SkuStatus key={row.darazSku} row={row} compact />)}</div>
      <button className="monitor-expand" type="button" onClick={() => setOpen(value => !value)} aria-expanded={open}>{open ? 'Hide' : 'Matrix'} <span>⌄</span></button>
    </div>
    {open && <div className="product-matrix-scroll"><table className="product-variant-matrix"><thead><tr><th>Memory / Color</th>{colors.map(color => <th key={color}>{color}</th>)}</tr></thead><tbody>{memories.map(memory => <tr key={memory}><th>{memory}</th>{colors.map(color => { const row = lookup.get(`${memory}\u0000${color}`); return <td key={color}>{row ? <SkuStatus row={row} /> : <span className="matrix-status-cell na"><span /><em>N/A</em></span>}</td>; })}</tr>)}</tbody></table></div>}
  </article>;
}

export function AvailabilityDashboard() {
  const [venture, setVenture] = useState('PK');
  const [brand, setBrand] = useState('');
  const [productSearch, setProductSearch] = useState('');
  const [priority, setPriority] = useState<'all' | DisplayPriority>('all');
  const [availability, setAvailability] = useState<'issues' | 'all'>('issues');
  const query = useQuery({ queryKey: ['availability-dashboard-all'], queryFn: () => availabilityApi.dashboard(new URLSearchParams()) });
  const data = query.data;
  const allRows = data?.rows ?? [];
  const brandOptions = useMemo(() => Array.from(new Set(allRows.filter(row => row.venture === venture).map(row => row.brand))).sort(), [allRows, venture]);
  const monitorRows = useMemo(() => allRows.filter(row => row.venture === venture && (!brand || row.brand === brand) && row.productName.toLowerCase().includes(productSearch.trim().toLowerCase()) && (priority === 'all' || displayPriority(row) === priority)), [allRows, venture, brand, productSearch, priority]);
  const monitorProducts = useMemo(() => groupProducts(monitorRows), [monitorRows]);
  const visibleProducts = availability === 'issues' ? monitorProducts.filter(product => product.issues > 0) : monitorProducts;

  if (query.isLoading) return <div className="loading-panel">Loading availability dashboard…</div>;
  if (query.isError || !data) return <div className="error-panel"><p>Availability data is temporarily unavailable.</p><button onClick={() => query.refetch()}>Retry</button></div>;

  return <div className="availability-page availability-v3">
    <header className="availability-header"><div><span>Stock intelligence</span><h1>Availability</h1><p>Daily brand health and product-level variant monitoring</p></div><div className={`availability-freshness ${data.meta.stale ? 'stale' : ''}`}><strong>{data.meta.stale ? 'Showing cached snapshot' : 'Last updated'}</strong><span>{formatDate(data.meta.dataAsOf)} · {data.meta.coverage} variants covered</span></div></header>
    <section className="brand-availability-overview"><header><div><span>BRAND AVAILABILITY OVERVIEW</span><h2>Today by country and brand</h2></div></header>{countryOrder.map(country => {
      const countryRows = allRows.filter(row => row.venture === country);
      const brands = Array.from(new Set(countryRows.map(row => row.brand))).sort();
      return <div className="country-brand-group" key={country}><div className="country-label"><strong>{country}</strong><span>{brands.length} Brands</span></div><div className="brand-table-scroll"><table><thead><tr><th>Brand</th><th>Total Products</th><th>Total SKUs</th><th>Available Products</th><th>Available SKUs</th><th>Unavailable SKUs</th><th>Product Availability Rate</th><th>SKU Availability Rate</th></tr></thead><tbody>{brands.map(brandName => {
        const rows = countryRows.filter(row => row.brand === brandName); const products = groupProducts(rows); const availableProducts = products.filter(product => product.available > 0).length; const availableSkus = rows.filter(row => row.status === 'available').length; const unavailableSkus = rows.filter(row => row.status === 'unavailable').length; const productRate = rate(availableProducts, products.length); const skuRate = rate(availableSkus, availableSkus + unavailableSkus);
        return <tr key={brandName}><td><strong>{brandName}</strong></td><td>{products.length}</td><td>{rows.length}</td><td>{availableProducts}</td><td>{availableSkus}</td><td className="unavailable-value">{unavailableSkus}</td><td><div className="rate-cell"><span>{rateLabel(productRate)}</span><i><b style={{ width: `${(productRate ?? 0) * 100}%` }} /></i></div></td><td><div className="rate-cell"><span>{rateLabel(skuRate)}</span><i><b style={{ width: `${(skuRate ?? 0) * 100}%` }} /></i></div></td></tr>;
      })}</tbody></table>{!brands.length && <div className="country-empty">No monitored brands</div>}</div></div>;
    })}</section>
    <section className="product-availability-monitor"><header><div><span>PRODUCT AVAILABILITY MONITOR</span><h2>Find products with unavailable or unverified variants</h2></div><small>{visibleProducts.length} Products</small></header><div className="monitor-filters">
      <label><span>Country</span><select value={venture} onChange={event => { setVenture(event.target.value); setBrand(''); }}><option>PK</option><option>BD</option><option>NP</option></select></label>
      <label><span>Brand</span><select value={brand} onChange={event => setBrand(event.target.value)}><option value="">All Brands</option>{brandOptions.map(value => <option key={value}>{value}</option>)}</select></label>
      <label className="monitor-search"><span>Product Name</span><input value={productSearch} onChange={event => setProductSearch(event.target.value)} placeholder="Search product name" /></label>
      <label><span>Priority</span><select value={priority} onChange={event => setPriority(event.target.value as 'all' | DisplayPriority)}><option value="all">All</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option></select></label>
      <label><span>Availability</span><select value={availability} onChange={event => setAvailability(event.target.value as 'issues' | 'all')}><option value="issues">Issues Only</option><option value="all">All</option></select></label>
    </div><div className="product-monitor-head"><span>Product Name</span><span>Variants</span><span>Available</span><span>Unavailable</span><span>Unknown</span><span>Availability Overview</span><span>Action</span></div><div className="product-monitor-list">{visibleProducts.map(product => <ProductMonitorRow key={product.key} group={product} />)}</div>{!visibleProducts.length && <div className="availability-empty">No products match the selected filters.</div>}</section>
  </div>;
}

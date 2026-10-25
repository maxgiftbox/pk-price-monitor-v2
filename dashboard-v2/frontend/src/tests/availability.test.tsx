import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import { availabilityApi } from '../lib/api';
import { AvailabilityDashboard } from '../routes/AvailabilityDashboard';
import type { AvailabilityDashboard as DashboardData, AvailabilityRow } from '../types/availability';

const row = (overrides: Partial<AvailabilityRow>): AvailabilityRow => ({
  runId: 'r1', crawledAt: '2026-10-25T10:00:00Z', venture: 'PK', brand: 'Samsung', productId: '1',
  darazSku: '1_PK-1', productName: 'Galaxy S26 Ultra 12GB 256GB', memory: '256GB', color: 'Black',
  category: 'Mobile', url: 'https://daraz.test/1', status: 'available', statusReason: 'purchase_action_available',
  selectedSkuVerified: true, l90Gmv: 100, priority: 'high', ...overrides,
});
const rows = [
  row({}), row({ darazSku: '1_PK-2', color: 'Blue', status: 'unavailable', url: 'https://daraz.test/2' }),
  row({ productId: '2', darazSku: '2_PK-1', productName: 'Galaxy A57 8GB 128GB', color: 'Green' }),
  row({ venture: 'BD', brand: 'Xiaomi', productId: '3', darazSku: '3_BD-1', productName: 'Redmi 15 128GB', status: 'unknown' }),
  row({ venture: 'NP', brand: 'Xiaomi', productId: '4', darazSku: '4_NP-1', productName: 'Redmi 14 128GB', priority: 'standard', l90Gmv: 0 }),
];
const data: DashboardData = {
  summary: { products: 4, variants: 5, available: 3, unavailable: 1, unknown: 1, availabilityRate: .75, highPriorityUnavailable: 1 }, brands: [], actions: [], rows,
  options: { ventures: ['PK', 'BD', 'NP'], brands: ['Samsung', 'Xiaomi'], categories: ['Mobile'], statuses: ['available', 'unavailable', 'unknown'], priorities: ['high', 'standard'] },
  meta: { dataAsOf: '2026-10-25T10:00:00Z', cacheGeneratedAt: '2026-10-25T10:00:00Z', stale: false, coverage: 5 },
};

test('keeps brand overview global while monitor defaults to PK issues and supports hover, PDP, and matrix expansion', async () => {
  vi.spyOn(availabilityApi, 'dashboard').mockResolvedValue(data);
  render(<QueryClientProvider client={new QueryClient()}><AvailabilityDashboard /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText('Today by country and brand')).toBeInTheDocument());
  expect(screen.getAllByText('1 Brands')).toHaveLength(3);
  expect(screen.getByText('Galaxy S26 Ultra 12GB 256GB')).toBeInTheDocument();
  expect(screen.queryByText('Galaxy A57 8GB 128GB')).not.toBeInTheDocument();
  const productRow = screen.getByText('Galaxy S26 Ultra 12GB 256GB').closest('article')!;
  const unavailableBlock = screen.getByLabelText('1_PK-2: Unavailable');
  expect(unavailableBlock).toHaveAttribute('href', 'https://daraz.test/2');
  fireEvent.mouseEnter(unavailableBlock);
  expect(screen.getByText('1_PK-2')).toBeInTheDocument();
  fireEvent.click(within(productRow).getByRole('button', { name: /Matrix/ }));
  expect(within(productRow).getByText('Memory / Color')).toBeInTheDocument();
  fireEvent.change(screen.getByDisplayValue('Issues Only'), { target: { value: 'all' } });
  expect(screen.getByText('Galaxy A57 8GB 128GB')).toBeInTheDocument();
});

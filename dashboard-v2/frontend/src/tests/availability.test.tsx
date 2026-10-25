import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import { availabilityApi } from '../lib/api';
import { AvailabilityDashboard } from '../routes/AvailabilityDashboard';
import type { AvailabilityDashboard as DashboardData, AvailabilityRow } from '../types/availability';

const row = (overrides: Partial<AvailabilityRow>): AvailabilityRow => ({
  runId: 'r1', crawledAt: '2026-10-25T10:00:00Z', venture: 'PK', brand: 'Samsung',
  productId: '1', darazSku: '1_PK-1', productName: 'Galaxy S26 Ultra 12GB 256GB',
  memory: '256GB', color: 'Black', category: 'Mobile', url: 'https://daraz.test/1',
  status: 'available', statusReason: 'purchase_action_available', selectedSkuVerified: true,
  l90Gmv: 100, priority: 'high', ...overrides,
});

const rows = [
  row({}),
  row({ darazSku: '1_PK-2', color: 'Blue', status: 'unavailable' }),
  row({ productId: '2', darazSku: '2_PK-1', productName: 'Galaxy A57 8GB 128GB', color: 'Green' }),
];
const data: DashboardData = {
  summary: { products: 2, variants: 3, available: 2, unavailable: 1, unknown: 0, availabilityRate: 2 / 3, highPriorityUnavailable: 1 },
  brands: [], actions: [], rows,
  options: { ventures: ['PK'], brands: ['Samsung'], categories: ['Mobile'], statuses: ['available', 'unavailable', 'unknown'], priorities: ['high', 'standard'] },
  meta: { dataAsOf: '2026-10-25T10:00:00Z', cacheGeneratedAt: '2026-10-25T10:00:00Z', stale: false, coverage: 3 },
};

test('defaults to issue products, retains all their variants, and opens SKU detail', async () => {
  vi.spyOn(availabilityApi, 'dashboard').mockResolvedValue(data);
  render(<QueryClientProvider client={new QueryClient()}><AvailabilityDashboard /></QueryClientProvider>);
  await waitFor(() => expect(screen.getByText('Products requiring attention')).toBeInTheDocument());
  expect(screen.getByText('Galaxy S26 Ultra 12GB 256GB')).toBeInTheDocument();
  expect(screen.queryByText('Galaxy A57 8GB 128GB')).not.toBeInTheDocument();
  expect(screen.getByTitle('Black: Available')).toBeInTheDocument();
  fireEvent.click(screen.getByTitle('Blue: Unavailable'));
  expect(screen.getByRole('dialog', { name: 'SKU detail' })).toBeInTheDocument();
  expect(screen.getByText('1_PK-2')).toBeInTheDocument();
  fireEvent.change(screen.getByDisplayValue('Issues Only'), { target: { value: 'all' } });
  expect(screen.getByText('Galaxy A57 8GB 128GB')).toBeInTheDocument();
});

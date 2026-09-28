import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { ComparisonBoard } from '../features/products/ComparisonBoard';
import type { ProductComparisonResponse } from '../types/product';

const comparison: ProductComparisonResponse = {
  products: [
    {
      skuId: 'pk-samsung-galaxy-a56-8-256',
      venture: 'PK',
      brand: 'Samsung',
      model: 'Galaxy A56',
      memory: '8/256',
      productUrl: null,
      specs: { memory: '8/256', displayType: 'AMOLED', sellingPrice: null },
    },
    {
      skuId: 'pk-xiaomi-redmi-15-8-128',
      venture: 'PK',
      brand: 'Xiaomi',
      model: 'Redmi 15',
      memory: '8/128',
      productUrl: null,
      specs: { memory: '8/128', displayType: 'LCD', sellingPrice: null },
    },
  ],
  groups: [
    { id: 'commercial', label: 'Commercial', fields: [{ key: 'sellingPrice', label: 'Selling Price' }] },
    { id: 'display', label: 'Display', fields: [{ key: 'displayType', label: 'Display Type' }] },
  ],
  warnings: [],
  meta: { dataAsOf: '2026-09-27', cacheGeneratedAt: '2026-09-27T00:00:00Z', stale: false },
};

test('renders products, grouped fields and missing values', () => {
  render(<ComparisonBoard data={comparison} loading={false} />);
  expect(screen.getByText('Galaxy A56')).toBeInTheDocument();
  expect(screen.getByText('Redmi 15')).toBeInTheDocument();
  expect(screen.getByText('Commercial')).toBeInTheDocument();
  expect(screen.getByText('AMOLED')).toBeInTheDocument();
  expect(screen.getAllByText('—')).toHaveLength(2);
});

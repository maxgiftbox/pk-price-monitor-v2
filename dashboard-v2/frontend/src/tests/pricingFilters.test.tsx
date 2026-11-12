import { useState } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';

import { Filters } from '../features/pricing/gap-analysis/Filters';
import type { FilterResponse } from '../types/pricing';

afterEach(cleanup);

const data: FilterResponse = {
  options: {
    countries: ['pk', 'bd'],
    brands: ['infinix', 'samsung', 'vivo'],
    skus: ['Infinix Hot 70', 'Galaxy S26+', 'vivo V70'],
    memories: ['6/128', '8/256'],
    competitors: ['priceoye', 'pickaboo'],
    dateRange: { min: '2026-11-01', max: '2026-11-12' },
  },
  meta: {
    dataAsOf: '2026-11-12',
    cacheGeneratedAt: '2026-11-12T10:00:00Z',
    stale: false,
  },
};

function FilterHarness({ initial = '' }: { initial?: string }) {
  const [params, setParams] = useState(() => new URLSearchParams(initial));
  return (
    <>
      <Filters data={data} params={params} set={setParams} />
      <output data-testid="params">{params.toString()}</output>
    </>
  );
}

test('supports multiple values for a filter', () => {
  render(<FilterHarness />);

  fireEvent.click(screen.getByRole('checkbox', { name: 'infinix' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'vivo' }));

  const params = new URLSearchParams(screen.getByTestId('params').textContent ?? '');
  expect(params.getAll('brand')).toEqual(['infinix', 'vivo']);
  expect(screen.getByLabelText('Brand: 2 selected')).toBeInTheDocument();
});

test('changing a parent filter clears dependent selections and the page', () => {
  render(<FilterHarness initial="country=pk&brand=samsung&sku=Galaxy+S26%2B&memory=8%2F256&page=3" />);

  fireEvent.click(screen.getByRole('checkbox', { name: 'bd' }));

  const params = new URLSearchParams(screen.getByTestId('params').textContent ?? '');
  expect(params.getAll('country')).toEqual(['pk', 'bd']);
  expect(params.has('brand')).toBe(false);
  expect(params.has('sku')).toBe(false);
  expect(params.has('memory')).toBe(false);
  expect(params.has('page')).toBe(false);
});

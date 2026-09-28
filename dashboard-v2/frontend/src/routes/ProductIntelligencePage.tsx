import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { ComparisonBoard } from '../features/products/ComparisonBoard';
import { ProductSelector } from '../features/products/ProductSelector';
import { productApi } from '../lib/api';
import type { ProductSkuOption } from '../types/product';

export function ProductIntelligencePage() {
  const [brand, setBrand] = useState('');
  const [model, setModel] = useState('');
  const [memory, setMemory] = useState('');
  const [skuId, setSkuId] = useState('');
  const [selected, setSelected] = useState<ProductSkuOption[]>([]);

  const params = useMemo(() => {
    const result = new URLSearchParams();
    if (brand) result.append('brand', brand);
    if (model) result.append('model', model);
    return result;
  }, [brand, model]);

  const filterQuery = useQuery({
    queryKey: ['product-filters', params.toString()],
    queryFn: () => productApi.filters(params),
  });
  const comparisonQuery = useQuery({
    queryKey: ['product-comparison', selected.map((item) => item.skuId)],
    queryFn: () => productApi.compare(selected.map((item) => item.skuId)),
    enabled: selected.length > 0,
    placeholderData: (previous) => previous,
  });

  const options = filterQuery.data?.options;
  const visibleSkus = (options?.skus ?? []).filter((sku) => !memory || sku.memory === memory);

  function changeBrand(value: string) {
    setBrand(value); setModel(''); setMemory(''); setSkuId('');
  }
  function changeModel(value: string) {
    setModel(value); setMemory(''); setSkuId('');
  }
  function changeMemory(value: string) {
    setMemory(value); setSkuId('');
  }
  function addSku() {
    const chosen = visibleSkus.find((sku) => sku.skuId === skuId);
    if (chosen && selected.length < 6 && !selected.some((item) => item.skuId === chosen.skuId)) {
      setSelected((current) => [...current, chosen]);
      setSkuId('');
    }
  }

  return <div className="product-page">
    <header className="product-page-header">
      <div>
        <p className="product-eyebrow">PRODUCT INTELLIGENCE</p>
        <h1>Compare product specifications</h1>
        <p className="product-page-subtitle">Select phone variants and review their key features side by side.</p>
      </div>
      <div className="product-data-status">
        <span>Product data updated</span>
        <strong>{filterQuery.data?.meta.dataAsOf ?? '—'}</strong>
        {filterQuery.data?.meta.stale && <em>Saved snapshot</em>}
      </div>
    </header>

    {filterQuery.isError && !filterQuery.data ? <div className="product-error-banner">
      <span>Product data is temporarily unavailable.</span>
      <button type="button" onClick={() => filterQuery.refetch()}>Retry</button>
    </div> : <>
      <ProductSelector
        brands={options?.brands ?? []} models={options?.models ?? []}
        memories={options?.memories ?? []} skus={visibleSkus}
        brand={brand} model={model} memory={memory} skuId={skuId} selected={selected}
        onBrand={changeBrand} onModel={changeModel} onMemory={changeMemory} onSku={setSkuId}
        onAdd={addSku} onRemove={(id) => setSelected((items) => items.filter((item) => item.skuId !== id))}
        onClear={() => setSelected([])}
      />
      {comparisonQuery.isError && <div className="product-error-banner">
        <span>Could not refresh the comparison. The previous result remains visible where available.</span>
        <button type="button" onClick={() => comparisonQuery.refetch()}>Retry</button>
      </div>}
      <ComparisonBoard
        data={selected.length > 0 ? comparisonQuery.data : undefined}
        loading={selected.length > 0 && comparisonQuery.isLoading}
      />
    </>}
  </div>;
}

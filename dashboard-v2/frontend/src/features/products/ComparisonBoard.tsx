import type { ProductComparisonResponse } from '../../types/product';

function displayValue(value: string | number | null | undefined, suffix?: string) {
  if (value === null || value === undefined || value === '') return '—';
  return suffix && typeof value === 'number' ? `${value} ${suffix}` : String(value);
}

export function ComparisonBoard({ data, loading }: {
  data?: ProductComparisonResponse;
  loading: boolean;
}) {
  if (loading) {
    return <section className="product-empty-state">Loading product specifications…</section>;
  }
  if (!data?.products.length) {
    return <section className="product-empty-state">
      <div className="product-empty-icon">PI</div>
      <h2>Build your comparison</h2>
      <p>Select up to six product variants. Their specifications will appear side by side here.</p>
    </section>;
  }

  return <section className="product-board-card">
    <div className="product-card-heading product-board-heading">
      <div>
        <p className="product-eyebrow">FEATURE COMPARISON</p>
        <h2>Comparison board</h2>
      </div>
      <span className="product-selection-count">{data.products.length} products</span>
    </div>
    <div className="product-table-scroll">
      <table className="product-comparison-table">
        <thead>
          <tr>
            <th className="product-spec-column">Specification</th>
            {data.products.map((product) => <th key={product.skuId}>
              <div className="product-column-brand">{product.brand}</div>
              <div className="product-column-title">{product.model}</div>
              <div className="product-column-memory">{product.memory || 'Variant not specified'}</div>
            </th>)}
          </tr>
        </thead>
        <tbody>
          {data.groups.map((group) => [
            <tr className="product-group-row" key={`${group.id}-heading`}>
              <th colSpan={data.products.length + 1}>{group.label}</th>
            </tr>,
            ...group.fields.map((field) => <tr key={`${group.id}-${field.key}`}>
              <th className="product-spec-column">{field.label}</th>
              {data.products.map((product) => <td key={`${product.skuId}-${field.key}`}>
                {displayValue(product.specs[field.key], field.suffix)}
              </td>)}
            </tr>),
          ])}
        </tbody>
      </table>
    </div>
  </section>;
}


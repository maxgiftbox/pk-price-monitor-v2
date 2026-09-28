import type { ProductSkuOption } from '../../types/product';

interface Props {
  brands: string[];
  models: string[];
  memories: string[];
  skus: ProductSkuOption[];
  brand: string;
  model: string;
  memory: string;
  skuId: string;
  selected: ProductSkuOption[];
  onBrand: (value: string) => void;
  onModel: (value: string) => void;
  onMemory: (value: string) => void;
  onSku: (value: string) => void;
  onAdd: () => void;
  onRemove: (skuId: string) => void;
  onClear: () => void;
}

function SelectField({ label, value, options, onChange, disabled = false }: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return <label className="product-select-field">
    <span>{label}</span>
    <select value={value} onChange={(event) => onChange(event.target.value)} disabled={disabled}>
      <option value="">Select {label.toLowerCase()}</option>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  </label>;
}

export function ProductSelector(props: Props) {
  return <section className="product-selector-card">
    <div className="product-card-heading">
      <div>
        <p className="product-eyebrow">PRODUCT SELECTION</p>
        <h2>Choose products to compare</h2>
      </div>
      <span className="product-selection-count">{props.selected.length}/6 selected</span>
    </div>

    <div className="product-selector-grid">
      <SelectField label="Brand" value={props.brand} onChange={props.onBrand}
        options={props.brands.map((value) => ({ value, label: value }))} />
      <SelectField label="Model" value={props.model} onChange={props.onModel} disabled={!props.brand}
        options={props.models.map((value) => ({ value, label: value }))} />
      <SelectField label="Memory" value={props.memory} onChange={props.onMemory} disabled={!props.model}
        options={props.memories.map((value) => ({ value, label: value }))} />
      <SelectField label="SKU" value={props.skuId} onChange={props.onSku} disabled={!props.model}
        options={props.skus.map((sku) => ({ value: sku.skuId, label: sku.label }))} />
      <button className="product-add-button" type="button" onClick={props.onAdd}
        disabled={!props.skuId || props.selected.length >= 6 || props.selected.some((item) => item.skuId === props.skuId)}>
        Add to comparison
      </button>
    </div>

    {props.selected.length > 0 && <div className="product-selected-row">
      <div className="product-chips">
        {props.selected.map((sku) => <button key={sku.skuId} type="button" className="product-chip"
          onClick={() => props.onRemove(sku.skuId)} title="Remove from comparison">
          <span>{sku.label}</span><strong aria-hidden="true">×</strong>
        </button>)}
      </div>
      <button type="button" className="product-clear-button" onClick={props.onClear}>Clear all</button>
    </div>}
  </section>;
}


export interface ProductMeta {
  dataAsOf: string | null;
  cacheGeneratedAt: string;
  stale: boolean;
}

export interface ProductSkuOption {
  skuId: string;
  brand: string;
  model: string;
  memory: string | null;
  label: string;
}

export interface ProductFiltersResponse {
  options: {
    ventures: string[];
    brands: string[];
    models: string[];
    memories: string[];
    skus: ProductSkuOption[];
  };
  meta: ProductMeta;
}

export interface ProductFeatureField {
  key: string;
  label: string;
  suffix?: string;
}

export interface ProductFeatureGroup {
  id: string;
  label: string;
  fields: ProductFeatureField[];
}

export interface ComparedProduct {
  skuId: string;
  venture: string;
  brand: string;
  model: string;
  memory: string | null;
  productUrl: string | null;
  specs: Record<string, string | number | null>;
}

export interface ProductComparisonResponse {
  products: ComparedProduct[];
  groups: ProductFeatureGroup[];
  warnings: string[];
  meta: ProductMeta;
}


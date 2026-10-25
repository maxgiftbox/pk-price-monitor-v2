export type AvailabilityStatus = 'available' | 'unavailable' | 'unknown';
export type AvailabilityPriority = 'high' | 'standard';

export interface AvailabilitySummary {
  products: number;
  variants: number;
  available: number;
  unavailable: number;
  unknown: number;
  availabilityRate: number | null;
  highPriorityUnavailable: number;
}

export interface AvailabilityRow {
  runId: string;
  crawledAt: string | null;
  venture: string;
  brand: string;
  productId: string;
  darazSku: string;
  productName: string;
  memory: string | null;
  color: string;
  category: string;
  url: string;
  status: AvailabilityStatus;
  statusReason: string;
  selectedSkuVerified: boolean;
  l90Gmv: number | string | null;
  priority: AvailabilityPriority;
}

export interface AvailabilityBrand extends AvailabilitySummary { brand: string }

export interface AvailabilityDashboard {
  summary: AvailabilitySummary;
  brands: AvailabilityBrand[];
  actions: AvailabilityRow[];
  rows: AvailabilityRow[];
  options: {
    ventures: string[];
    brands: string[];
    categories: string[];
    statuses: AvailabilityStatus[];
    priorities: AvailabilityPriority[];
  };
  meta: {
    dataAsOf: string | null;
    cacheGeneratedAt: string;
    stale: boolean;
    coverage: number;
  };
}

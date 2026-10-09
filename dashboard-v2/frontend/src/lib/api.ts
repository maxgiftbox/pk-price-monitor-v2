import type {
  FilterResponse,
  GapResponse,
  PricingDashboardResponse,
  TrendResponse,
} from "../types/pricing";
import type { ConsumerVoiceDashboard, ConsumerVoiceFilters } from "../types/consumerVoice";
import type { ProductComparisonResponse, ProductFiltersResponse } from "../types/product";
import type { SocialDashboard, SocialFilters } from "../types/socialIntelligence";

// Production:
// VITE_API_BASE_URL=https://your-api-service.onrender.com
//
// Local:
// empty string -> use Vite proxy /api
const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");

export function resolveApiAssetUrl(url: string): string {
  if (!url || !url.startsWith("/api/")) return url;
  return `${apiBaseUrl}${url}`;
}

const REQUEST_TIMEOUT_MS = 35_000;
const PRICING_TOKEN_KEY = "el-pricing-session";

function pricingAuthHeaders(): HeadersInit {
  const token = window.sessionStorage.getItem(PRICING_TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function isRetryableApiError(error: unknown): boolean {
  return (
    error instanceof TypeError ||
    (error instanceof ApiError && (error.status === 503 || error.status === undefined))
  );
}


async function request<T>(
  path: string,
  params: URLSearchParams
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;

  try {
    response = await fetch(
      `${apiBaseUrl}${path}?${params.toString()}`,
      { signal: controller.signal, credentials: "include", headers: pricingAuthHeaders() }
    );
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("Data request timed out.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }

  if (!response.ok) {
    throw new ApiError("Data is temporarily unavailable.", response.status);
  }

  return response.json() as Promise<T>;
}

export const pricingAuthApi = {
  status: async (): Promise<{ authenticated: boolean }> => {
    const response = await fetch(`${apiBaseUrl}/api/pricing/auth`, {
      credentials: "include",
      headers: pricingAuthHeaders(),
    });
    if (!response.ok) throw new ApiError("Could not check access.", response.status);
    return response.json();
  },
  login: async (password: string): Promise<{ authenticated: boolean; token: string }> => {
    const response = await fetch(`${apiBaseUrl}/api/pricing/auth`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    if (!response.ok) throw new ApiError("Incorrect password.", response.status);
    const result = await response.json() as { authenticated: boolean; token: string };
    window.sessionStorage.setItem(PRICING_TOKEN_KEY, result.token);
    return result;
  },
};


export const api = {

  dashboard: () =>
    request<PricingDashboardResponse>(
      "/api/pricing/dashboard",
      new URLSearchParams()
    ),

  filters: (
    params: URLSearchParams
  ) =>
    request<FilterResponse>(
      "/api/pricing/filters",
      params
    ),


  gap: (
    params: URLSearchParams
  ) =>
    request<GapResponse>(
      "/api/pricing/gap",
      params
    ),


  trend: (
    params: URLSearchParams
  ) =>
    request<TrendResponse>(
      "/api/pricing/trend",
      params
    ),

};

export const consumerVoiceApi = {
  filters: () => request<ConsumerVoiceFilters>("/api/consumer-voice/filters", new URLSearchParams()),
  dashboard: (params: URLSearchParams) =>
    request<ConsumerVoiceDashboard>("/api/consumer-voice/dashboard", params),
};

export const productApi = {
  filters: (params = new URLSearchParams()) =>
    request<ProductFiltersResponse>("/api/products/filters", params),
  compare: (skuIds: string[]) => {
    const params = new URLSearchParams();
    skuIds.forEach((skuId) => params.append("skuId", skuId));
    return request<ProductComparisonResponse>("/api/products/compare", params);
  },
};

export const socialIntelligenceApi = {
  filters: () => request<SocialFilters>("/api/social-intelligence/filters", new URLSearchParams()),
  dashboard: (params: URLSearchParams) => request<SocialDashboard>("/api/social-intelligence/dashboard", params),
};

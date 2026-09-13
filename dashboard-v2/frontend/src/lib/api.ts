import type {
  FilterResponse,
  GapResponse,
  TrendResponse,
} from "../types/pricing";

// Production:
// VITE_API_BASE_URL=https://your-api-service.onrender.com
//
// Local:
// empty string -> use Vite proxy /api
const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");


async function request<T>(
  path: string,
  params: URLSearchParams
): Promise<T> {

  const response = await fetch(
    `${apiBaseUrl}${path}?${params.toString()}`
  );

  if (!response.ok) {
    throw new Error(
      "Pricing data is temporarily unavailable."
    );
  }

  return response.json() as Promise<T>;
}


export const api = {

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

import type {
  FilterResponse,
  GapResponse,
  TrendResponse,
} from "../types/pricing";
import type { ConsumerVoiceDashboard, ConsumerVoiceFilters } from "../types/consumerVoice";

// Production:
// VITE_API_BASE_URL=https://your-api-service.onrender.com
//
// Local:
// empty string -> use Vite proxy /api
const apiBaseUrl = (
  import.meta.env.VITE_API_BASE_URL ?? ""
).replace(/\/$/, "");

const REQUEST_TIMEOUT_MS = 35_000;

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
      { signal: controller.signal }
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

export const consumerVoiceApi = {
  filters: () => request<ConsumerVoiceFilters>("/api/consumer-voice/filters", new URLSearchParams()),
  dashboard: (params: URLSearchParams) =>
    request<ConsumerVoiceDashboard>("/api/consumer-voice/dashboard", params),
};

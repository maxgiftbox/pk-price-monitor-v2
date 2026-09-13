import type {FilterResponse,GapResponse} from '../types/pricing';
// Local development uses Vite's /api proxy; Vercel targets the Render origin.
const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '');
async function request<T>(path:string,params:URLSearchParams){const response=await fetch(`${apiBaseUrl}${path}?${params}`);if(!response.ok)throw new Error('Pricing data is temporarily unavailable.');return response.json() as Promise<T>}
export const api={filters:(p:URLSearchParams)=>request<FilterResponse>('/api/pricing/filters',p),gap:(p:URLSearchParams)=>request<GapResponse>('/api/pricing/gap',p)};

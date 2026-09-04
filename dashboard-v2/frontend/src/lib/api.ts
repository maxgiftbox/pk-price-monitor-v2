import type {FilterResponse,GapResponse} from '../types/pricing';
async function request<T>(path:string,params:URLSearchParams){const response=await fetch(`${path}?${params}`);if(!response.ok)throw new Error('Pricing data is temporarily unavailable.');return response.json() as Promise<T>}
export const api={filters:(p:URLSearchParams)=>request<FilterResponse>('/api/pricing/filters',p),gap:(p:URLSearchParams)=>request<GapResponse>('/api/pricing/gap',p)};

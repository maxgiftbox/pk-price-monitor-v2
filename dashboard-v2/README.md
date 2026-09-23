# Mob Price Monitor V2 — Phase 2A

Read-only vertical slice: Google Sheets (`price_daily`, `sku_master`) → FastAPI → React. V1 remains independent and unchanged.

## Run
```bash
cd dashboard-v2/api && python -m uvicorn src.main:app --reload
cd dashboard-v2/frontend && npm install && npm run dev
```
The API requires `GOOGLE_SERVICE_ACCOUNT_JSON`; `GOOGLE_SHEET_NAME` defaults to `Mob Price Monitor`. `FRONTEND_ORIGINS` is a comma-separated allowlist and defaults to local Vite only. Credentials never reach the browser. Sheet reads use a configurable 900-second in-process TTL (`PRICING_CACHE_TTL_SECONDS`). The initial load has a 12-second response budget (`PRICING_INITIAL_LOAD_TIMEOUT_SECONDS`); the single background load is allowed to finish so a retry can reuse it. A previous snapshot is served with `stale: true` if refresh fails; without one the API returns a sanitized 503.

## Production deployment preparation

No production deployment is performed by this repository change. The intended
topology is Vercel (frontend) → Render (API) → the existing Google Sheet.

### Render API

Create a Render Blueprint using `dashboard-v2/render.yaml`, or create a Python
web service with root directory `dashboard-v2/api`. The Blueprint installs the
deployment-only `requirements.txt`, starts Uvicorn on Render's assigned `PORT`,
and checks `/api/health` without reading Google Sheets.

Set these Render environment variables before the first deployment:

- `GOOGLE_SERVICE_ACCOUNT_JSON`: the complete Google service-account key JSON.
  Keep it secret and never add it to an `.env` file or Vercel.
- `GOOGLE_SHEET_NAME`: the existing spreadsheet name (the default is
  `Mob Price Monitor`).
- `FRONTEND_ORIGINS`: the exact Vercel production origin, for example
  `https://your-dashboard.vercel.app`. Multiple origins must be comma-separated.

The spreadsheet must be shared with the service account's `client_email` as a
viewer. The API already reads credentials exclusively from the environment.

### Vercel frontend

Import the repository into Vercel and set the root directory to
`dashboard-v2/frontend`. `vercel.json` supplies the Vite build/output settings
and the SPA fallback required for React Router routes.

Set `VITE_API_BASE_URL` to the Render service origin (for example,
`https://your-api-service.onrender.com`) for Production and any desired Preview
environment. Vite embeds this public value at build time; it must not contain
credentials. A trailing slash is accepted and normalized. When the variable is
unset, requests remain relative so local development continues to use Vite's
localhost-only development proxy.

After both services have URLs, update `FRONTEND_ORIGINS` on Render with the
final Vercel origin and redeploy the API. Verify `/api/health`, then open Price
Gap Analysis in the deployed frontend and confirm browser requests target the
Render origin without CORS errors.

## Parity and identity
The framework-neutral domain module safely copies/adapts V1 preparation, `sku_master` primary and unique URL fallback mapping, latest platform-row selection, and gap calculation. No Streamlit formatting was copied. `gapPct` remains `(darazPrice - competitorPrice) / darazPrice`. Alert policy intentionally changes to Green ≤ 0, Orange > 0 and < 0.03, Red ≥ 0.03.

`productId` is a deterministic slug of normalized `country + brand + standardized model + normalized memory` (for example `pk-samsung-galaxy-a55-8-256`). It never depends on DataFrame order or Python `hash()`.

## Endpoints
- `GET /api/health` (never accesses Sheets)
- `GET /api/pricing/filters`
- `GET /api/pricing/gap` (server filtered; 100 rows by default, maximum 500)
- `GET /api/pricing/trend`

Gap and trend endpoints default to the latest seven calendar days available in
the data. Today Action requests a one-day window. Trend responses are capped to
a maximum 31-day window even when a wider explicit range is supplied.

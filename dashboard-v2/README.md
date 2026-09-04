# Mob Price Monitor V2 — Phase 2A

Read-only vertical slice: Google Sheets (`price_daily`, `sku_master`) → FastAPI → React. V1 remains independent and unchanged.

## Run
```bash
cd dashboard-v2/api && python -m uvicorn src.main:app --reload
cd dashboard-v2/frontend && npm install && npm run dev
```
The API requires `GOOGLE_SERVICE_ACCOUNT_JSON`; `GOOGLE_SHEET_NAME` defaults to `Mob Price Monitor`. `FRONTEND_ORIGINS` is a comma-separated allowlist and defaults to local Vite only. Credentials never reach the browser. Sheet reads use a 300-second in-process TTL. A previous snapshot is served with `stale: true` if refresh fails; without one the API returns a sanitized 503.

## Parity and identity
The framework-neutral domain module safely copies/adapts V1 preparation, `sku_master` primary and unique URL fallback mapping, latest platform-row selection, and gap calculation. No Streamlit formatting was copied. `gapPct` remains `(darazPrice - competitorPrice) / darazPrice`. Alert policy intentionally changes to Green ≤ 0, Orange > 0 and < 0.03, Red ≥ 0.03.

`productId` is a deterministic slug of normalized `country + brand + standardized model + normalized memory` (for example `pk-samsung-galaxy-a55-8-256`). It never depends on DataFrame order or Python `hash()`.

## Endpoints
- `GET /api/health` (never accesses Sheets)
- `GET /api/pricing/filters`
- `GET /api/pricing/gap` (server filtered/sorted; 100 rows by default, maximum 250)

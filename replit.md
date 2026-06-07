# Deriv Market Scanner

A real-time trading dashboard for Deriv synthetic volatility indices using Bill Williams Fractal analysis, Trend Strength Index (TSI), and MACD to detect market structure states.

## Run & Operate

- `python artifacts/api-server/server.py` — run the Python API server (port 8080)
- `pnpm --filter @workspace/dashboard run dev` — run the React dashboard
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks from OpenAPI spec

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- **Backend**: Python 3.11 + FastAPI + uvicorn + python-deriv-api
- **Frontend**: React + Vite + Tailwind CSS + Recharts
- API codegen: Orval (from OpenAPI spec)

## Where things live

- `artifacts/api-server/server.py` — Python FastAPI server (source of truth for all analysis)
- `artifacts/dashboard/src/pages/Dashboard.tsx` — main market scanner page
- `artifacts/dashboard/src/pages/SymbolDetail.tsx` — per-symbol chart detail page
- `lib/api-spec/openapi.yaml` — API contract
- `lib/api-client-react/src/generated/` — generated React Query hooks

## Architecture decisions

- Python backend using `python-deriv-api` to connect to Deriv WebSocket API — matches original Python implementation exactly
- 500 candles for trend/fractal analysis, 1000 candles for charting
- In-memory cache with 60s TTL per endpoint — avoids hammering Deriv API
- Fractal period = 36, MACD = (21, 55, 21), TSI period = 55
- Trend Strength Index (TSI) = |sum of closes direction over N| / sum of |abs changes| × 100 — measures directional consistency (0=choppy, 100=strong one-direction trend)

## Product

- Real-time scanner for 13 Deriv synthetic volatility indices
- Detects: PULLBACK (potential entries), BOS (Break of Structure), CHoCH (Change of Character), IN_TREND, CONSOLIDATION
- Summary cards with counts per signal type
- Per-symbol detail page: 1000-candle chart with fractal support/resistance levels, TSI subplot, MACD subplot
- Auto-refreshes every 60 seconds

## User preferences

- Python backend (uses python-deriv-api, not Node.js)
- Fractal period = 36
- MACD settings = (21, 55, 21)
- TSI = Trend Strength Index (NOT True Strength Index), period 55
- 1000 candles for chart, 500 candles for trend detection

## Gotchas

- First API scan takes ~30-60s (connects to Deriv WebSocket, fetches 13 symbols × 500 candles)
- The artifact.toml runs `python server.py` (working dir = artifacts/api-server/)
- Deriv app_id=104094, token stored in DERIV_TOKEN env var (defaults to shared token)
- pip install must be run at workspace root, not inside artifact dir

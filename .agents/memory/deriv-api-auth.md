---
name: Deriv API authentication
description: How Deriv API tokens work — new PAT (pat_...) tokens vs legacy, trading flow, and deployment notes
---

## Rule
Market data (ticks_history/candles) on `wss://ws.derivws.com/websockets/v3?app_id=1089` is PUBLIC — no `authorize` call needed. Use app_id=1089 for all public market data requests.

PAT tokens (`pat_...`) are for the NEW Deriv API only (developers.deriv.com). They are REJECTED by the old WebSocket `authorize` flow.

**Why:** Deriv migrated to a new OAuth2-based API. `pat_` prefix tokens work exclusively with the new platform at `api.derivws.com`. The old `ws.derivws.com` `authorize` message will return `InvalidToken` for PAT tokens.

## New API Trading Flow (PAT tokens)
1. **REST — get accounts:** `GET https://api.derivws.com/trading/v1/options/accounts` with headers `Authorization: Bearer <pat_token>` and `Deriv-App-ID: <app_id>` — both headers required or returns 401.
2. **REST — get OTP WS URL:** `POST https://api.derivws.com/trading/v1/options/accounts/{accountId}/otp` with same headers — returns `data.url` (e.g. `wss://api.derivws.com/trading/v1/options/ws/demo?otp=...`)
3. **WebSocket — trade:** Connect to the OTP URL, send proposal/buy using NEW field names.

## New WebSocket Message Format (DIFFERENT from legacy)
```json
{
  "proposal": 1, "amount": 1, "basis": "stake",
  "contract_type": "MULTUP", "currency": "USD",
  "duration_unit": "s", "multiplier": 40,
  "underlying_symbol": "1HZ100V",
  "limit_order": {"stop_loss": 0.50, "take_profit": 1.00},
  "req_id": 1
}
```
Key differences from legacy: `underlying_symbol` (not `symbol`), `duration_unit` is required.

## App ID Requirement
- Legacy App IDs (e.g. 104094) do NOT work with the new API.
- App ID must be registered at developers.deriv.com for PAT auth.
- Both `Authorization` header AND `Deriv-App-ID` header are required for every REST call.

## Wallet Accounts Cannot Trade
Account types `CRW` (Wallet) and `VRW` (Virtual Wallet) cannot trade via API. Must use a standard `VRTC` (Virtual) or `CR` (Real) account.

## Deployment Note
Trading bots using this app MUST use `vm` (Always On) deployment — not `autoscale`. Autoscale sleeps between requests and misses trade signals. The background scanner uses `@app.on_event("startup")` with `asyncio.create_task` to run analysis every 60s independently of HTTP traffic.

---
name: Deriv API authentication
description: How Deriv API tokens work — PAT tokens vs old-style tokens, and what needs auth
---

## Rule
Market data (ticks_history/candles) on `wss://ws.derivws.com/websockets/v3` is PUBLIC — no `authorize` call needed.
PAT tokens (`pat_...`) are for the NEW Deriv API (OAuth2, developers.deriv.com) and are REJECTED by the old WebSocket API.
The old `python-deriv-api` library always calls `authorize` first — use raw `websockets` instead for the data layer.

**Why:** Deriv is migrating to a new OAuth2-based API. The `pat_` prefix Personal Access Tokens only work with the new platform, not the legacy WebSocket API at `ws.derivws.com`. The old `api.deriv.com` now redirects to `legacy-api.deriv.com`. Market data remains public on the legacy endpoint.

**How to apply:**
- For candle/tick fetching: connect to `wss://ws.derivws.com/websockets/v3?app_id=104094`, send `ticks_history` directly, NO `authorize`.
- For trading (buy/sell): still needs auth — but PAT tokens will fail with `InvalidToken`. User needs a legacy Deriv API token (old format) for trading to work.
- The current server.py uses raw `websockets` library (not `python-deriv-api`) and skips auth for data fetching. Trading auth is attempted but will fail gracefully.

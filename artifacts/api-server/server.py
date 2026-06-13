import asyncio
import os
import time
import math
import json
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
from swingtrend import Swing
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from pydantic import BaseModel
import websockets
import uvicorn

APP_ID   = os.getenv("DERIV_APP_ID", "")
TOKEN    = os.getenv("DERIV_TOKEN", "")
PORT     = int(os.getenv("PORT", "8080"))
WS_URL   = "wss://ws.derivws.com/websockets/v3?app_id=1089"
API_BASE = "https://api.derivws.com/trading/v1/options"

# Limit concurrent WebSocket connections
_ws_semaphore = asyncio.Semaphore(15)

SYMBOL_CONFIG = {
    # Volatility Indices
    "1HZ10V":    {"multiplier": 400,  "name": "Volatility 10"},
    "R_10":      {"multiplier": 400,  "name": "Volatility 10 (1s)"},
    # 1HZ15V removed — Deriv: not offered for multipliers
    "1HZ25V":    {"multiplier": 160,  "name": "Volatility 25"},
    "R_25":      {"multiplier": 160,  "name": "Volatility 25 (1s)"},
    # 1HZ30V removed — Deriv: not offered for multipliers
    "1HZ50V":    {"multiplier": 80,   "name": "Volatility 50"},
    "R_50":      {"multiplier": 80,   "name": "Volatility 50 (1s)"},
    "1HZ75V":    {"multiplier": 50,   "name": "Volatility 75"},
    "R_75":      {"multiplier": 50,   "name": "Volatility 75 (1s)"},
    # 1HZ90V removed — Deriv: not offered for multipliers
    "1HZ100V":   {"multiplier": 40,   "name": "Volatility 100"},
    "R_100":     {"multiplier": 40,   "name": "Volatility 100 (1s)"},
    # Jump Indices
    "JD10":      {"multiplier": 100,  "name": "Jump 10"},
    "JD25":      {"multiplier": 50,   "name": "Jump 25"},
    "JD50":      {"multiplier": 20,   "name": "Jump 50"},
    "JD75":      {"multiplier": 15,   "name": "Jump 75"},
    "JD100":     {"multiplier": 10,   "name": "Jump 100"},
    # Forex Pairs
    "FRXAUDJPY": {"multiplier": 500,  "name": "AUD/JPY"},
    "FRXAUDUSD": {"multiplier": 500,  "name": "AUD/USD"},
    "FRXEURAUD": {"multiplier": 800,  "name": "EUR/AUD"},
    "FRXEURCAD": {"multiplier": 800,  "name": "EUR/CAD"},
    "FRXEURCHF": {"multiplier": 500,  "name": "EUR/CHF"},
    "FRXEURGBP": {"multiplier": 800,  "name": "EUR/GBP"},
    "FRXEURJPY": {"multiplier": 500,  "name": "EUR/JPY"},
    "FRXEURUSD": {"multiplier": 800,  "name": "EUR/USD"},
    "FRXGBPUSD": {"multiplier": 800,  "name": "GBP/USD"},
    "FRXGBPJPY": {"multiplier": 800,  "name": "GBP/JPY"},
    "FRXGBPAUD": {"multiplier": 800,  "name": "GBP/AUD"},
    "FRXUSDCAD": {"multiplier": 800,  "name": "USD/CAD"},
    "FRXUSDCHF": {"multiplier": 500,  "name": "USD/CHF"},
}

# ── Indicator settings ──────────────────────────────────────
TSI_PERIOD           = 55     # Pearson r trend strength
TSI_OVERSOLD         = -0.8
TSI_OVERBOUGHT       =  0.8
MOMENTUM_PERIOD      = 55     # bars for momentum confirmation
MACD_FAST            = 21     # MACD fast EMA period
MACD_SLOW            = 36     # MACD slow EMA period
MACD_SIGNAL          = 36     # MACD signal EMA period
CACHE_TTL            = 60
TRADE_COOLDOWN_SECS  = 300

# ── SwingTrend settings ─────────────────────────────────────
RETRACE_THRESHOLD  = 1.5
SIDEWAYS_THRESHOLD = 20
MINIMUM_BAR_COUNT  = 40
ANALYSIS_CANDLES   = 200
CHART_CANDLES      = 200

_analysis_cache:      Optional[Dict] = None
_analysis_cache_time: float = 0
_chart_cache:         Dict[str, Dict]  = {}
_chart_cache_time:    Dict[str, float] = {}
_trade_log:      List[Dict] = []
_trade_cooldown: Dict[str, float] = {}


# ──────────────────────────────────────────────────
# WebSocket helpers
# ──────────────────────────────────────────────────

async def ws_send_recv(ws, payload: Dict, timeout: float = 15.0) -> Dict:
    await ws.send(json.dumps(payload))
    resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
    if resp.get("error"):
        raise RuntimeError(resp["error"].get("message", "Unknown error"))
    return resp


async def _fetch_candles_once(symbol: str, count: int) -> List[Dict]:
    async def _do():
        async with websockets.connect(WS_URL, open_timeout=15) as ws:
            return await ws_send_recv(ws, {
                "ticks_history": symbol,
                "adjust_start_time": 1,
                "count": count,
                "end": "latest",
                "granularity": 60,
                "style": "candles",
            }, timeout=15.0)
    async with _ws_semaphore:
        resp = await asyncio.wait_for(_do(), timeout=25)
    return resp.get("candles", [])


async def fetch_candles_ws(symbol: str, count: int) -> List[Dict]:
    """Fetch with one automatic retry and a hard per-attempt timeout."""
    try:
        return await _fetch_candles_once(symbol, count)
    except Exception as e:
        await asyncio.sleep(2)
        try:
            return await _fetch_candles_once(symbol, count)
        except Exception as e2:
            raise RuntimeError(f"fetch failed after 2 attempts: {e2}") from e2


# ──────────────────────────────────────────────────
# Indicators
# ──────────────────────────────────────────────────

def calc_tsi(closes: List[float], period: int = TSI_PERIOD) -> Dict:
    """Trend Strength Index — Pearson's r, range −1 to +1."""
    values: List[float] = []
    xs = list(range(period))
    mx = (period - 1) / 2.0
    sx = sum((x - mx) ** 2 for x in xs)
    for end in range(period, len(closes) + 1):
        window = closes[end - period:end]
        my    = sum(window) / period
        num   = sum((xs[i] - mx) * (window[i] - my) for i in range(period))
        sy    = sum((window[i] - my) ** 2 for i in range(period))
        denom = math.sqrt(sx * sy)
        values.append(round(num / denom if denom else 0.0, 4))
    current = values[-1] if values else 0.0
    return {
        "value":         current,
        "is_oversold":   current < TSI_OVERSOLD,
        "is_overbought": current > TSI_OVERBOUGHT,
        "values":        values[-100:],
    }


def calc_momentum(closes: List[float], period: int = MOMENTUM_PERIOD) -> Dict:
    """Simple momentum: close[i] - close[i-period].
    Confirmation layer: momentum < 0 confirms uptrend pullback,
                        momentum > 0 confirms downtrend pullback.
    """
    if len(closes) < period + 2:
        return {"value": 0.0, "prev": 0.0, "values": []}
    values = [round(closes[i] - closes[i - period], 6)
              for i in range(period, len(closes))]
    curr = values[-1]
    prev = values[-2]
    return {
        "value":  curr,
        "prev":   prev,
        "values": values[-100:],
    }


def _ema(values: List[float], period: int) -> List[float]:
    """Exponential moving average."""
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    ema = [sum(values[:period]) / period]
    for v in values[period:]:
        ema.append(v * k + ema[-1] * (1 - k))
    return ema


def calc_macd(closes: List[float],
              fast: int = MACD_FAST,
              slow: int = MACD_SLOW,
              signal: int = MACD_SIGNAL) -> Dict:
    """MACD (fast, slow, signal) with crossover detection.
      bullish_cross = MACD line crosses above signal line
      bearish_cross = MACD line crosses below signal line
    """
    empty = {"macd": 0.0, "signal": 0.0, "hist": 0.0,
             "bullish_cross": False, "bearish_cross": False,
             "macd_values": [], "signal_values": [], "hist_values": []}
    if len(closes) < slow + signal + 2:
        return empty
    fast_ema  = _ema(closes, fast)
    slow_ema  = _ema(closes, slow)
    # Align: fast_ema is longer, trim to match slow_ema length
    offset    = len(fast_ema) - len(slow_ema)
    macd_line = [round(fast_ema[i + offset] - slow_ema[i], 6)
                 for i in range(len(slow_ema))]
    sig_line  = _ema(macd_line, signal)
    # Align macd_line to sig_line
    m_offset  = len(macd_line) - len(sig_line)
    macd_aligned = macd_line[m_offset:]
    hist      = [round(macd_aligned[i] - sig_line[i], 6)
                 for i in range(len(sig_line))]
    if len(sig_line) < 2:
        return empty
    curr_macd, prev_macd = macd_aligned[-1], macd_aligned[-2]
    curr_sig,  prev_sig  = sig_line[-1],     sig_line[-2]
    return {
        "macd":          round(curr_macd, 6),
        "signal":        round(curr_sig,  6),
        "hist":          round(hist[-1],  6),
        "bullish_cross": prev_macd <= prev_sig and curr_macd > curr_sig,
        "bearish_cross": prev_macd >= prev_sig and curr_macd < curr_sig,
        "macd_values":   [round(v, 6) for v in macd_aligned[-100:]],
        "signal_values": [round(v, 6) for v in sig_line[-100:]],
        "hist_values":   [round(v, 6) for v in hist[-100:]],
    }


# ──────────────────────────────────────────────────
# Analysis
# ──────────────────────────────────────────────────

async def analyze_symbol(symbol: str, config: Dict) -> Optional[Dict]:
    try:
        candles = await fetch_candles_ws(symbol, ANALYSIS_CANDLES)
        if len(candles) < 120:
            return None

        highs  = [float(c["high"])  for c in candles]
        lows   = [float(c["low"])   for c in candles]
        closes = [float(c["close"]) for c in candles]
        price  = closes[-1]

        df = pd.DataFrame({
            "datetime": [pd.Timestamp(c["epoch"], unit="s") for c in candles],
            "open":  [float(c["open"]) for c in candles],
            "high":  highs,
            "low":   lows,
            "close": closes,
        })
        df.set_index("datetime", inplace=True)

        # SwingTrend — official library
        swing = Swing(
            retrace_threshold_pct=RETRACE_THRESHOLD,
            sideways_threshold=SIDEWAYS_THRESHOLD,
            minimum_bar_count=MINIMUM_BAR_COUNT,
        )
        swing.run(sym=symbol, df=df)

        raw_trend = swing.trend  # "UP" | "DOWN" | None
        trend     = ("UPTREND"   if raw_trend == "UP"
                     else "DOWNTREND" if raw_trend == "DOWN"
                     else "SIDEWAYS")

        sph = round(float(swing.sph), 4) if swing.sph else None
        spl = round(float(swing.spl), 4) if swing.spl else None
        coc = round(float(swing.coc), 4) if swing.coc else None

        tsi      = calc_tsi(closes, TSI_PERIOD)
        momentum = calc_momentum(closes, MOMENTUM_PERIOD)
        macd     = calc_macd(closes)

        volatility = round(
            ((max(highs[-20:]) - min(lows[-20:])) / min(lows[-20:])) * 100, 1
        ) if len(highs) >= 20 else 0.0

        # State:
        #   PULLBACK      = momentum < 0 in UPTREND (price pulling back) OR
        #                   momentum > 0 in DOWNTREND (price pulling back up)
        #   IN_TREND      = trend active but no current pullback
        #   CONSOLIDATION = SwingTrend reports sideways
        mom_val = momentum["value"]
        if trend == "UPTREND" and mom_val < 0:
            state = "PULLBACK"
            desc  = (f"Pullback ▲ | Momentum {mom_val:+.4f} (neg = pulling back)"
                     f" | TSI {tsi['value']:+.3f} | CoC {coc}")
        elif trend == "DOWNTREND" and mom_val > 0:
            state = "PULLBACK"
            desc  = (f"Pullback ▼ | Momentum {mom_val:+.4f} (pos = pulling back)"
                     f" | TSI {tsi['value']:+.3f} | CoC {coc}")
        elif swing.is_sideways:
            state = "CONSOLIDATION"
            desc  = f"Sideways | SPH {sph} · SPL {spl}"
        else:
            state = "IN_TREND"
            trend_arrow = "▲" if trend == "UPTREND" else "▼" if trend == "DOWNTREND" else "—"
            desc  = (f"In trend {trend_arrow} | SPH {sph} · SPL {spl} · CoC {coc}"
                     f" | Momentum {mom_val:+.4f} | TSI {tsi['value']:+.3f}")

        structure = {
            "trend":           trend,
            "sph":             sph,
            "spl":             spl,
            "coc":             coc,
            "last_resistance": sph,
            "last_support":    spl,
            "bos_level":       None,
            "choch_level":     coc,
            "description":     desc,
        }

        return {
            "symbol":      symbol,
            "name":        config["name"],
            "price":       round(price, 4),
            "volatility":  volatility,
            "state":       state,
            "trend":       trend,
            "sph":         sph,
            "spl":         spl,
            "coc":         coc,
            "support":     spl,
            "resistance":  sph,
            "bos_level":   None,
            "choch_level": coc,
            "description": desc,
            "structure":   structure,
            "tsi":         tsi,
            "momentum":    momentum,
            "macd":        macd,
            "last_updated": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        print(f"[SCAN ERROR] {symbol}: {e}")
        return None


async def run_full_analysis() -> Dict:
    symbols_list = list(SYMBOL_CONFIG.items())
    tasks        = [analyze_symbol(symbol, config) for symbol, config in symbols_list]
    all_results  = await asyncio.gather(*tasks, return_exceptions=True)

    results: List[Dict] = []
    failed:  List[str]  = []
    skipped: List[str]  = []
    for (symbol, _), r in zip(symbols_list, all_results):
        if isinstance(r, dict):
            results.append(r)
        elif r is None:
            skipped.append(symbol)
        else:
            failed.append(f"{symbol}({r})")

    if skipped:
        print(f"[SCAN SKIP]  no/insufficient candles: {', '.join(skipped)}")
    if failed:
        print(f"[SCAN FAIL]  exceptions: {', '.join(failed)}")
    print(f"[SCAN OK]    {len(results)}/{len(symbols_list)} symbols succeeded")

    await asyncio.gather(*[_trigger_trade_if_confirmed(r) for r in results])

    counts: Dict[str, int] = {
        "PULLBACK": 0, "IN_TREND": 0, "CONSOLIDATION": 0,
    }
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    return {
        "timestamp":           datetime.utcnow().isoformat(),
        "pullback_count":      counts["PULLBACK"],
        "bos_count":           0,
        "choch_count":         0,
        "trending_count":      counts["IN_TREND"],
        "consolidation_count": counts["CONSOLIDATION"],
        "symbols":             results,
    }


async def build_chart_data(symbol: str) -> Dict:
    candles = await fetch_candles_ws(symbol, CHART_CANDLES)

    highs  = [float(c["high"])  for c in candles]
    lows   = [float(c["low"])   for c in candles]
    closes = [float(c["close"]) for c in candles]

    df = pd.DataFrame({
        "datetime": [pd.Timestamp(c["epoch"], unit="s") for c in candles],
        "open":  [float(c["open"]) for c in candles],
        "high":  highs, "low": lows, "close": closes,
    })
    df.set_index("datetime", inplace=True)
    swing = Swing(
        retrace_threshold_pct=RETRACE_THRESHOLD,
        sideways_threshold=SIDEWAYS_THRESHOLD,
        minimum_bar_count=MINIMUM_BAR_COUNT,
    )
    swing.run(sym=symbol, df=df)

    raw_trend = swing.trend
    trend     = ("UPTREND"   if raw_trend == "UP"
                 else "DOWNTREND" if raw_trend == "DOWN"
                 else "SIDEWAYS")

    sph = round(float(swing.sph), 4) if swing.sph else None
    spl = round(float(swing.spl), 4) if swing.spl else None
    coc = round(float(swing.coc), 4) if swing.coc else None

    macd = calc_macd(closes)

    candle_data = [
        {"time": c["epoch"], "open": float(c["open"]), "high": float(c["high"]),
         "low": float(c["low"]), "close": float(c["close"])}
        for c in candles
    ]
    return {
        "symbol":       symbol,
        "trend":        trend,
        "candles":      candle_data,
        "sph":          sph,
        "spl":          spl,
        "coc":          coc,
        "hh_level":     sph,
        "hl_level":     spl,
        "lh_level":     sph,
        "ll_level":     spl,
        "markers":      [],
        "macd":         macd,
        "bar_count":    len(candles),
        "last_updated": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────────
# Auto-trading engine
# ──────────────────────────────────────────────────

def _get_demo_account_id() -> Optional[str]:
    if not TOKEN or not APP_ID:
        return None
    try:
        req = urllib.request.Request(
            f"{API_BASE}/accounts",
            headers={"Authorization": f"Bearer {TOKEN}",
                     "Deriv-App-ID": APP_ID,
                     "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            for account in data.get("data", []):
                if account.get("account_type") == "demo":
                    return account["account_id"]
    except Exception as e:
        print(f"[AUTH] Failed to fetch accounts: {e}")
    return None


def _get_otp_ws_url(account_id: str) -> Optional[str]:
    try:
        req = urllib.request.Request(
            f"{API_BASE}/accounts/{account_id}/otp",
            data=b"{}", method="POST",
            headers={"Authorization": f"Bearer {TOKEN}",
                     "Deriv-App-ID": APP_ID,
                     "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("data", {}).get("url")
    except Exception as e:
        print(f"[AUTH] Failed to get OTP URL: {e}")
    return None


async def _place_multiplier_trade(symbol: str, contract_type: str) -> Dict:
    """Place MULTUP or MULTDOWN — $1 stake, SL $0.50, TP $1.00."""
    multiplier = SYMBOL_CONFIG[symbol]["multiplier"]
    try:
        account_id = _get_demo_account_id()
        if not account_id:
            return {"ok": False, "error": "No demo account found or auth failed",
                    "contract_type": contract_type, "symbol": symbol}
        ws_url = _get_otp_ws_url(account_id)
        if not ws_url:
            return {"ok": False, "error": "Failed to get OTP WebSocket URL",
                    "contract_type": contract_type, "symbol": symbol}

        async with websockets.connect(ws_url, open_timeout=15) as ws:
            await ws.send(json.dumps({
                "proposal":          1,
                "amount":            1,
                "basis":             "stake",
                "contract_type":     contract_type,
                "currency":          "USD",
                "duration_unit":     "s",
                "multiplier":        multiplier,
                "underlying_symbol": symbol,
                "limit_order":       {"stop_loss": 0.50, "take_profit": 1.00},
                "req_id":            1,
            }))
            prop_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if prop_resp.get("error"):
                return {"ok": False, "error": prop_resp["error"].get("message", "proposal failed"),
                        "contract_type": contract_type, "symbol": symbol}

            proposal_id = prop_resp["proposal"]["id"]
            ask_price   = prop_resp["proposal"]["ask_price"]

            await ws.send(json.dumps({"buy": proposal_id, "price": ask_price, "req_id": 2}))
            buy_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if buy_resp.get("error"):
                return {"ok": False, "error": buy_resp["error"].get("message", "buy failed"),
                        "contract_type": contract_type, "symbol": symbol}

            return {
                "ok":            True,
                "contract_id":   buy_resp["buy"]["contract_id"],
                "contract_type": contract_type,
                "symbol":        symbol,
                "multiplier":    multiplier,
                "ask_price":     ask_price,
                "balance_after": buy_resp["buy"].get("balance_after"),
            }
    except Exception as e:
        return {"ok": False, "error": str(e), "contract_type": contract_type, "symbol": symbol}


async def _trigger_trade_if_confirmed(sym: Dict) -> None:
    """Trade conditions (all three must be met at the current bar):
      UPTREND:   1) TSI ≤ -0.8 RIGHT NOW (oversold)
                 2) MACD bullish crossover (fast crosses above signal)
                 3) Momentum < 0 (price still in pullback)
                 → MULTUP

      DOWNTREND: 1) TSI ≥ +0.8 RIGHT NOW (overbought)
                 2) MACD bearish crossover (fast crosses below signal)
                 3) Momentum > 0 (price still in pullback)
                 → MULTDOWN
    """
    global _trade_log, _trade_cooldown

    if sym["state"] != "PULLBACK":
        return

    trend    = sym["trend"]
    tsi      = sym.get("tsi") or {}
    momentum = sym.get("momentum") or {}
    macd     = sym.get("macd") or {}
    symbol   = sym["symbol"]

    tsi_val  = tsi.get("value", 0.0)
    mom_val  = momentum.get("value", 0.0)
    macd_val = macd.get("macd", 0.0)
    sig_val  = macd.get("signal", 0.0)

    if trend == "UPTREND":
        # 1) TSI must be oversold RIGHT NOW
        if tsi_val > TSI_OVERSOLD:
            return
        # 2) MACD bullish crossover
        if not macd.get("bullish_cross"):
            return
        # 3) Momentum still below zero (price in pullback)
        if mom_val >= 0:
            return
        contract_type = "MULTUP"

    elif trend == "DOWNTREND":
        # 1) TSI must be overbought RIGHT NOW
        if tsi_val < TSI_OVERBOUGHT:
            return
        # 2) MACD bearish crossover
        if not macd.get("bearish_cross"):
            return
        # 3) Momentum still above zero (price in pullback)
        if mom_val <= 0:
            return
        contract_type = "MULTDOWN"

    else:
        return

    now = time.time()
    if now - _trade_cooldown.get(symbol, 0) < TRADE_COOLDOWN_SECS:
        return

    _trade_cooldown[symbol] = now
    result = await _place_multiplier_trade(symbol, contract_type)

    entry = {
        "timestamp":     datetime.utcnow().isoformat(),
        "symbol":        symbol,
        "direction":     "BUY" if contract_type == "MULTUP" else "SELL",
        "contract_type": contract_type,
        "trend":         trend,
        "tsi":           round(tsi_val, 4),
        "momentum":      round(mom_val, 6),
        "macd":          round(macd_val, 6),
        "macd_signal":   round(sig_val, 6),
        "contract_id":   result.get("contract_id"),
        "ok":            result.get("ok", False),
        "error":         result.get("error"),
    }
    _trade_log.insert(0, entry)
    if len(_trade_log) > 50:
        _trade_log = _trade_log[:50]

    status = f"✅ {result.get('contract_id')}" if result.get("ok") else f"❌ {result.get('error')}"
    print(f"[TRADE] {symbol} {contract_type} | TSI {tsi_val:+.3f} | MACD {macd_val:+.6f} | Mom {mom_val:+.4f} | {status}")


# ──────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────

app = FastAPI(title="Deriv Market Scanner")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
router = APIRouter(prefix="/api")


@router.get("/healthz")
async def health():
    return {"status": "ok"}


@router.get("/account/balance")
async def account_balance():
    if not TOKEN or not APP_ID:
        raise HTTPException(status_code=503, detail="DERIV_TOKEN / DERIV_APP_ID not configured")
    try:
        req = urllib.request.Request(
            f"{API_BASE}/accounts",
            headers={"Authorization": f"Bearer {TOKEN}",
                     "Deriv-App-ID": APP_ID,
                     "Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        accounts = data.get("data", [])
        demo = next((a for a in accounts if a.get("account_type") == "demo"), None)
        real = next((a for a in accounts if a.get("account_type") == "real"), None)
        return {"demo": demo, "real": real, "all_accounts": accounts}
    except urllib.error.HTTPError as e:
        raise HTTPException(status_code=e.code, detail=e.read().decode())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/symbols")
async def get_symbols():
    return [
        {"symbol": s, "name": c["name"], "multiplier": c["multiplier"]}
        for s, c in SYMBOL_CONFIG.items()
    ]


@router.get("/market/analysis")
async def market_analysis():
    global _analysis_cache, _analysis_cache_time
    now = time.time()
    if _analysis_cache and (now - _analysis_cache_time) < CACHE_TTL:
        return _analysis_cache
    try:
        data = await run_full_analysis()
        _analysis_cache      = data
        _analysis_cache_time = now
        return data
    except Exception as e:
        if _analysis_cache:
            return _analysis_cache
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/market/chart/{symbol}")
async def get_chart(symbol: str):
    if symbol not in SYMBOL_CONFIG:
        raise HTTPException(status_code=404, detail="Symbol not found")
    now = time.time()
    if symbol in _chart_cache and (now - _chart_cache_time.get(symbol, 0)) < CACHE_TTL:
        return _chart_cache[symbol]
    try:
        data = await build_chart_data(symbol)
        _chart_cache[symbol]      = data
        _chart_cache_time[symbol] = now
        return data
    except Exception as e:
        if symbol in _chart_cache:
            return _chart_cache[symbol]
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trading/status")
async def trading_status():
    now = time.time()
    cooldowns = {
        s: round(TRADE_COOLDOWN_SECS - (now - t))
        for s, t in _trade_cooldown.items()
        if now - t < TRADE_COOLDOWN_SECS
    }
    return {"trades": _trade_log, "cooldowns": cooldowns}


app.include_router(router)


@app.on_event("startup")
async def start_background_scanner():
    async def _loop():
        print("[SCANNER] Background scanner started — SwingTrend + TSI(55) + Momentum")
        while True:
            tick_start = time.time()
            try:
                data = await run_full_analysis()
                global _analysis_cache, _analysis_cache_time
                _analysis_cache      = data
                _analysis_cache_time = time.time()
                pb      = data.get("pullback_count", 0)
                elapsed = time.time() - tick_start
                print(f"[SCANNER] Scan complete — {len(data.get('symbols', []))} symbols | {pb} pullback(s) | {elapsed:.1f}s")
            except Exception as e:
                print(f"[SCANNER] Error during scan: {e}")
            elapsed = time.time() - tick_start
            await asyncio.sleep(max(0, 60 - elapsed))
    asyncio.create_task(_loop())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

import asyncio
import os
import time
import math
from datetime import datetime
from typing import Optional, List, Dict, Any
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from pydantic import BaseModel
from deriv_api import DerivAPI
from swingtrend import Swing
import uvicorn

APP_ID = os.getenv("DERIV_APP_ID", "104094")
TOKEN  = os.getenv("DERIV_TOKEN", "iaw8gpjk3H1wV1K")
PORT   = int(os.getenv("PORT", "8080"))

SYMBOL_CONFIG = {
    "1HZ10V":  {"multiplier": 400, "name": "Volatility 10"},
    "R_10":    {"multiplier": 400, "name": "R_10"},
    "1HZ15V":  {"multiplier": 300, "name": "Volatility 15"},
    "1HZ25V":  {"multiplier": 160, "name": "Volatility 25"},
    "R_25":    {"multiplier": 160, "name": "R_25"},
    "1HZ30V":  {"multiplier": 140, "name": "Volatility 30"},
    "1HZ50V":  {"multiplier": 80,  "name": "Volatility 50"},
    "R_50":    {"multiplier": 80,  "name": "R_50"},
    "1HZ75V":  {"multiplier": 50,  "name": "Volatility 75"},
    "R_75":    {"multiplier": 50,  "name": "R_75"},
    "1HZ90V":  {"multiplier": 45,  "name": "Volatility 90"},
    "1HZ100V": {"multiplier": 40,  "name": "Volatility 100"},
    "R_100":   {"multiplier": 40,  "name": "R_100"},
    "STPRNG":  {"multiplier": 750, "name": "Step Index"},
    "STPRNG2": {"multiplier": 400, "name": "Step Index 2"},
    "STPRNG3": {"multiplier": 300, "name": "Step Index 3"},
    "STPRNG4": {"multiplier": 200, "name": "Step Index 4"},
    "STPRNG5": {"multiplier": 100, "name": "Step Index 5"},
    "JD10":    {"multiplier": 100, "name": "Jump 10"},
    "JD25":    {"multiplier": 50,  "name": "Jump 25"},
    "JD50":    {"multiplier": 20,  "name": "Jump 50"},
    "JD75":    {"multiplier": 15,  "name": "Jump 75"},
    "JD100":   {"multiplier": 10,  "name": "Jump 100"},
}

# ── SwingTrend settings ────────────────────────────
RETRACE_THRESHOLD  = 5     # % retracement to confirm a swing leg
SIDEWAYS_THRESHOLD = 20    # % range threshold → sideways market
MINIMUM_BAR_COUNT  = 60    # minimum candles needed by swingtrend

# ── TSI settings ───────────────────────────────────
TSI_PERIOD           = 55
TSI_OVERSOLD         = -0.7
TSI_OVERBOUGHT       =  0.7
TSI_EXTREME_LOOKBACK = 20

CACHE_TTL           = 60
TRADE_COOLDOWN_SECS = 300

_analysis_cache:      Optional[Dict] = None
_analysis_cache_time: float = 0
_chart_cache:         Dict[str, Dict]  = {}
_chart_cache_time:    Dict[str, float] = {}

_trade_log:      List[Dict] = []
_trade_cooldown: Dict[str, float] = {}


# ──────────────────────────────────────────────────
# Indicators
# ──────────────────────────────────────────────────

def ema_series(prices: List[float], period: int) -> List[float]:
    if not prices:
        return []
    k = 2.0 / (period + 1)
    out = [prices[0]]
    for p in prices[1:]:
        out.append(p * k + out[-1] * (1 - k))
    return out


def calc_macd(closes: List[float], fast=21, slow=55, signal=21) -> Dict:
    if len(closes) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0,
                "values": [], "signal_values": [], "histogram_values": []}
    fe = ema_series(closes, fast)
    se = ema_series(closes, slow)
    ml = [f - s for f, s in zip(fe, se)]
    sl = ema_series(ml, signal)
    hi = [m - s for m, s in zip(ml, sl)]
    tail = 100
    return {
        "macd":             round(ml[-1], 6),
        "signal":           round(sl[-1], 6),
        "histogram":        round(hi[-1], 6),
        "values":           [round(x, 6) for x in ml[-tail:]],
        "signal_values":    [round(x, 6) for x in sl[-tail:]],
        "histogram_values": [round(x, 6) for x in hi[-tail:]],
    }


def calc_tsi(closes: List[float], period: int = TSI_PERIOD) -> Dict:
    """Trend Strength Index — Pearson's r over a rolling window. Range −1 to +1."""
    values: List[float] = []
    xs = list(range(period))
    mx = (period - 1) / 2.0
    sx = sum((x - mx) ** 2 for x in xs)
    for end in range(period, len(closes) + 1):
        window = closes[end - period:end]
        my  = sum(window) / period
        num = sum((xs[i] - mx) * (window[i] - my) for i in range(period))
        sy  = sum((window[i] - my) ** 2 for i in range(period))
        denom = math.sqrt(sx * sy)
        values.append(round(num / denom if denom else 0.0, 4))
    current = values[-1] if values else 0.0
    return {
        "value":         current,
        "is_oversold":   current < TSI_OVERSOLD,
        "is_overbought": current > TSI_OVERBOUGHT,
        "values":        values[-100:],
    }


# ──────────────────────────────────────────────────
# State detection (SwingTrend-based)
# ──────────────────────────────────────────────────

def detect_state_swing(
    price: float,
    trend: str,
    sph: Optional[float],
    spl: Optional[float],
    coc: Optional[float],
    tsi_values: List[float],
    is_sideways: bool,
) -> Dict[str, Any]:
    tsi_now = tsi_values[-1] if tsi_values else 0.0

    if is_sideways:
        return {"state": "IN_TREND", "trend": trend,
                "bos_level": None, "choch_level": None,
                "description": f"Sideways/Consolidation · TSI {tsi_now:+.3f}"}

    if trend == "UPTREND":
        # BOS ▲ — price breaks above SPH (uptrend continuation)
        if sph is not None and price > sph:
            return {"state": "BOS_CONTINUATION", "trend": "UPTREND",
                    "bos_level": sph, "choch_level": None,
                    "description": f"BOS ▲ Broke SPH {sph:.4f} · Price {price:.4f} · Uptrend continuation"}

        # CHoCH ▼ — price breaks below CoC (uptrend → downtrend reversal)
        if coc is not None and price < coc:
            return {"state": "CHoCH_REVERSAL", "trend": "DOWNTREND",
                    "bos_level": None, "choch_level": coc,
                    "description": f"CHoCH ▼ Broke CoC {coc:.4f} · Price {price:.4f} · Uptrend → Downtrend"}

        # PULLBACK ▲ — price retreated below SPH
        if sph is not None and price < sph:
            coc_desc = f" · CoC {coc:.4f}" if coc else ""
            return {"state": "PULLBACK", "trend": "UPTREND",
                    "bos_level": None, "choch_level": None,
                    "description": f"Pullback ▲ {price:.4f} below SPH {sph:.4f} · TSI {tsi_now:+.3f}{coc_desc}"}

        return {"state": "IN_TREND", "trend": "UPTREND",
                "bos_level": None, "choch_level": None,
                "description": f"Uptrend · SPH {sph or '—'} · TSI {tsi_now:+.3f}"}

    else:  # DOWNTREND
        # BOS ▼ — price breaks below SPL (downtrend continuation)
        if spl is not None and price < spl:
            return {"state": "BOS_CONTINUATION", "trend": "DOWNTREND",
                    "bos_level": spl, "choch_level": None,
                    "description": f"BOS ▼ Broke SPL {spl:.4f} · Price {price:.4f} · Downtrend continuation"}

        # CHoCH ▲ — price breaks above CoC (downtrend → uptrend reversal)
        if coc is not None and price > coc:
            return {"state": "CHoCH_REVERSAL", "trend": "UPTREND",
                    "bos_level": None, "choch_level": coc,
                    "description": f"CHoCH ▲ Broke CoC {coc:.4f} · Price {price:.4f} · Downtrend → Uptrend"}

        # PULLBACK ▼ — price bounced above SPL
        if spl is not None and price > spl:
            coc_desc = f" · CoC {coc:.4f}" if coc else ""
            return {"state": "PULLBACK", "trend": "DOWNTREND",
                    "bos_level": None, "choch_level": None,
                    "description": f"Pullback ▼ {price:.4f} above SPL {spl:.4f} · TSI {tsi_now:+.3f}{coc_desc}"}

        return {"state": "IN_TREND", "trend": "DOWNTREND",
                "bos_level": None, "choch_level": None,
                "description": f"Downtrend · SPL {spl or '—'} · TSI {tsi_now:+.3f}"}


# ──────────────────────────────────────────────────
# Deriv helpers
# ──────────────────────────────────────────────────

async def fetch_candles(api: DerivAPI, symbol: str, count: int) -> List[Dict]:
    resp = await api.ticks_history({
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "granularity": 60,
        "style": "candles",
    })
    return resp.get("candles", [])


def candles_to_df(candles: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(candles)
    df["datetime"] = pd.to_datetime(df["epoch"], unit="s")
    df.set_index("datetime", inplace=True)
    return df[["open", "high", "low", "close"]].astype(float)


async def analyze_symbol(api: DerivAPI, symbol: str, config: Dict) -> Optional[Dict]:
    try:
        candles = await fetch_candles(api, symbol, 1000)
        if len(candles) < MINIMUM_BAR_COUNT:
            return None

        closes = [float(c["close"]) for c in candles]
        highs  = [float(c["high"])  for c in candles]
        lows   = [float(c["low"])   for c in candles]
        price  = closes[-1]

        df = candles_to_df(candles)

        swing = Swing(
            retrace_threshold_pct=RETRACE_THRESHOLD,
            sideways_threshold=SIDEWAYS_THRESHOLD,
            minimum_bar_count=MINIMUM_BAR_COUNT,
            debug=False,
        )
        swing.run(sym=symbol, df=df)

        tsi  = calc_tsi(closes, TSI_PERIOD)
        macd = calc_macd(closes, fast=21, slow=55, signal=21)

        raw_trend = swing.trend
        is_sideways = swing.is_sideways or raw_trend is None
        trend = ("UPTREND" if raw_trend == "UP" else "DOWNTREND") if raw_trend else "UPTREND"

        sph = round(float(swing.sph), 4) if swing.sph else None
        spl = round(float(swing.spl), 4) if swing.spl else None
        coc = round(float(swing.coc), 4) if swing.coc else None

        state_info = detect_state_swing(price, trend, sph, spl, coc, tsi["values"], is_sideways)

        support    = spl
        resistance = sph

        volatility = round(
            ((max(highs[-20:]) - min(lows[-20:])) / min(lows[-20:])) * 100, 1
        ) if len(highs) >= 20 else 0.0

        return {
            "symbol":        symbol,
            "name":          config["name"],
            "price":         round(price, 4),
            "volatility":    volatility,
            "state":         state_info["state"],
            "trend":         trend,
            "is_sideways":   is_sideways,
            "leg_count":     swing.leg_count,
            "bars_since":    swing.bars_since,
            "support":       support,
            "resistance":    resistance,
            "coc":           coc,
            "bos_level":     state_info.get("bos_level"),
            "choch_level":   state_info.get("choch_level"),
            "description":   state_info["description"],
            "tsi":           tsi,
            "macd":          macd,
            "last_updated":  datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None


async def run_full_analysis() -> Dict:
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN)

    results: List[Dict] = []
    for symbol, config in SYMBOL_CONFIG.items():
        result = await analyze_symbol(api, symbol, config)
        if result:
            results.append(result)
        await asyncio.sleep(0.2)

    await api.disconnect()

    await asyncio.gather(*[_trigger_trade_if_confirmed(r) for r in results])

    counts: Dict[str, int] = {
        "PULLBACK": 0, "BOS_CONTINUATION": 0, "CHoCH_REVERSAL": 0, "IN_TREND": 0,
    }
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    return {
        "timestamp":           datetime.utcnow().isoformat(),
        "pullback_count":      counts["PULLBACK"],
        "bos_count":           counts["BOS_CONTINUATION"],
        "choch_count":         counts["CHoCH_REVERSAL"],
        "trending_count":      counts["IN_TREND"],
        "consolidation_count": 0,
        "symbols":             results,
    }


async def build_chart_data(symbol: str) -> Dict:
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN)
    candles = await fetch_candles(api, symbol, 1000)
    await api.disconnect()

    closes = [float(c["close"]) for c in candles]
    highs  = [float(c["high"])  for c in candles]
    lows   = [float(c["low"])   for c in candles]

    df = candles_to_df(candles)
    swing = Swing(
        retrace_threshold_pct=RETRACE_THRESHOLD,
        sideways_threshold=SIDEWAYS_THRESHOLD,
        minimum_bar_count=MINIMUM_BAR_COUNT,
        debug=False,
    )
    swing.run(sym=symbol, df=df)

    raw_trend   = swing.trend
    trend       = ("UPTREND" if raw_trend == "UP" else "DOWNTREND") if raw_trend else "UPTREND"
    sph = round(float(swing.sph), 4) if swing.sph else None
    spl = round(float(swing.spl), 4) if swing.spl else None
    coc = round(float(swing.coc), 4) if swing.coc else None

    candle_data = [
        {"time": c["epoch"], "open": float(c["open"]), "high": float(c["high"]),
         "low": float(c["low"]), "close": float(c["close"])}
        for c in candles
    ]

    return {
        "symbol":       symbol,
        "trend":        trend,
        "candles":      candle_data,
        "markers":      [],
        "sph_level":    sph,
        "spl_level":    spl,
        "coc_level":    coc,
        "bar_count":    len(candles),
        "last_updated": datetime.utcnow().isoformat(),
    }


# ──────────────────────────────────────────────────
# Auto-trading engine
# ──────────────────────────────────────────────────

def _macd_crossover(histogram_values: List[float], lookback: int = 3) -> Optional[str]:
    if len(histogram_values) < 2:
        return None
    window = histogram_values[-(lookback + 1):]
    for i in range(1, len(window)):
        prev = window[i - 1]
        curr = window[i]
        if prev < 0 and curr >= 0:
            return "bullish"
        if prev > 0 and curr <= 0:
            return "bearish"
    return None


async def _place_multiplier_trade(symbol: str, contract_type: str) -> Dict:
    multiplier = SYMBOL_CONFIG[symbol]["multiplier"]
    api = DerivAPI(app_id=APP_ID)
    try:
        await api.authorize(TOKEN)
        proposal = await api.proposal({
            "proposal":       1,
            "amount":         1,
            "basis":          "stake",
            "contract_type":  contract_type,
            "currency":       "USD",
            "symbol":         symbol,
            "multiplier":     multiplier,
        })
        proposal_id = proposal["proposal"]["id"]
        ask_price   = proposal["proposal"]["ask_price"]

        buy = await api.buy({"buy": proposal_id, "price": ask_price})
        contract_id = buy["buy"]["contract_id"]

        await api.contract_update({
            "contract_id": contract_id,
            "limit_order": {"stop_loss": 0.5, "take_profit": 1.0},
        })
        return {"ok": True, "contract_id": contract_id,
                "contract_type": contract_type, "symbol": symbol,
                "multiplier": multiplier, "ask_price": ask_price}
    except Exception as e:
        return {"ok": False, "error": str(e),
                "contract_type": contract_type, "symbol": symbol}
    finally:
        try:
            await api.disconnect()
        except Exception:
            pass


async def _trigger_trade_if_confirmed(sym: Dict) -> None:
    """
    Fire a trade when ALL three conditions are met:
      1. state == PULLBACK
      2. TSI at extreme: ≤ −0.7 (uptrend pullback) / ≥ +0.7 (downtrend pullback)
         AND TSI hit that extreme within the last TSI_EXTREME_LOOKBACK bars
      3. MACD histogram crossover in trend direction
    """
    global _trade_log, _trade_cooldown

    if sym["state"] != "PULLBACK":
        return

    trend = sym["trend"]
    tsi   = sym.get("tsi") or {}
    macd  = sym.get("macd") or {}

    tsi_val    = tsi.get("value", 0.0)
    tsi_series = tsi.get("values", [])
    hist_vals  = macd.get("histogram_values", [])
    crossover  = _macd_crossover(hist_vals)
    symbol     = sym["symbol"]

    recent = tsi_series[-TSI_EXTREME_LOOKBACK:] if tsi_series else []
    if trend == "UPTREND":
        armed = any(v <= TSI_OVERSOLD for v in recent)
        if tsi_val > TSI_OVERSOLD or not armed:
            return
    if trend == "DOWNTREND":
        armed = any(v >= TSI_OVERBOUGHT for v in recent)
        if tsi_val < TSI_OVERBOUGHT or not armed:
            return

    if trend == "UPTREND"   and crossover != "bullish":
        return
    if trend == "DOWNTREND" and crossover != "bearish":
        return

    now = time.time()
    if now - _trade_cooldown.get(symbol, 0) < TRADE_COOLDOWN_SECS:
        return

    contract_type = "MULTUP" if trend == "UPTREND" else "MULTDOWN"
    _trade_cooldown[symbol] = now

    result = await _place_multiplier_trade(symbol, contract_type)

    entry = {
        "timestamp":     datetime.utcnow().isoformat(),
        "symbol":        symbol,
        "direction":     "BUY" if contract_type == "MULTUP" else "SELL",
        "contract_type": contract_type,
        "trend":         trend,
        "tsi":           round(tsi_val, 4),
        "macd_hist":     round(macd.get("histogram", 0), 6),
        "contract_id":   result.get("contract_id"),
        "ok":            result.get("ok", False),
        "error":         result.get("error"),
    }
    _trade_log.insert(0, entry)
    if len(_trade_log) > 50:
        _trade_log = _trade_log[:50]

    status = f"✅ {result.get('contract_id')}" if result.get("ok") else f"❌ {result.get('error')}"
    print(f"[TRADE] {symbol} {contract_type} | TSI {tsi_val:+.3f} | {status}")


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
    return {
        "trades":    _trade_log,
        "cooldowns": cooldowns,
    }


app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

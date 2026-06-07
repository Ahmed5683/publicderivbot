import asyncio
import os
import time
import math
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from deriv_api import DerivAPI
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
}

FRACTAL_PERIOD = 36
TSI_PERIOD     = 55
TSI_OVERSOLD   = -0.7
TSI_OVERBOUGHT =  0.7
CACHE_TTL      = 60

_analysis_cache: Optional[Dict] = None
_analysis_cache_time: float = 0
_chart_cache:      Dict[str, Dict]  = {}
_chart_cache_time: Dict[str, float] = {}


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
        "macd":              round(ml[-1], 6),
        "signal":            round(sl[-1], 6),
        "histogram":         round(hi[-1], 6),
        "values":            [round(x, 6) for x in ml[-tail:]],
        "signal_values":     [round(x, 6) for x in sl[-tail:]],
        "histogram_values":  [round(x, 6) for x in hi[-tail:]],
    }


def calc_tsi(closes: List[float], period: int = TSI_PERIOD) -> Dict:
    """Trend Strength Index — Pearson's r over a rolling window. Range −1 to +1."""
    values: List[float] = []
    xs  = list(range(period))
    mx  = (period - 1) / 2.0
    sx  = sum((x - mx) ** 2 for x in xs)
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
# Fractals
# ──────────────────────────────────────────────────

def get_fractals(highs: List[float], lows: List[float], period: int = FRACTAL_PERIOD) -> List[Dict]:
    out: List[Dict] = []
    n = len(highs)
    for i in range(period, n - period):
        if all(highs[i] > highs[i - j] and highs[i] > highs[i + j] for j in range(1, period + 1)):
            out.append({"type": "RESISTANCE", "index": i, "price": round(highs[i], 4)})
        if all(lows[i] < lows[i - j] and lows[i] < lows[i + j] for j in range(1, period + 1)):
            out.append({"type": "SUPPORT", "index": i, "price": round(lows[i], 4)})
    return out


def classify_fractals(fractals: List[Dict]) -> List[Dict]:
    """
    Label each fractal in the time-ordered sequence:
      Resistance highs → HH (higher than prev) or LH (lower than prev)
      Support lows     → HL (higher than prev) or LL (lower than prev)
    """
    highs = sorted([f for f in fractals if f["type"] == "RESISTANCE"], key=lambda x: x["index"])
    lows  = sorted([f for f in fractals if f["type"] == "SUPPORT"],    key=lambda x: x["index"])

    result: List[Dict] = []
    for i, f in enumerate(highs):
        label = "HH" if i == 0 or f["price"] > highs[i - 1]["price"] else "LH"
        result.append({"index": f["index"], "price": f["price"], "type": label})
    for i, f in enumerate(lows):
        label = "HL" if i == 0 or f["price"] > lows[i - 1]["price"] else "LL"
        result.append({"index": f["index"], "price": f["price"], "type": label})

    return sorted(result, key=lambda x: x["index"])


def get_key_levels(classified: List[Dict]) -> Dict[str, Optional[float]]:
    """Most-recent price for each of HH, HL, LH, LL."""
    levels: Dict[str, Optional[float]] = {"HH": None, "HL": None, "LH": None, "LL": None}
    for f in classified:               # already sorted oldest→newest
        levels[f["type"]] = f["price"] # last write = most recent
    return levels


def get_trend(classified: List[Dict]) -> str:
    """
    Determine current trend from the most-recent high-type and low-type fractal.
    HH + HL → UPTREND   |   LH + LL → DOWNTREND   |   else → UPTREND (default bias)
    """
    highs = [f for f in classified if f["type"] in ("HH", "LH")]
    lows  = [f for f in classified if f["type"] in ("HL", "LL")]
    if not highs or not lows:
        return "UPTREND"
    rh = highs[-1]["type"]
    rl = lows[-1]["type"]
    if rh == "HH" and rl == "HL":
        return "UPTREND"
    if rh == "LH" and rl == "LL":
        return "DOWNTREND"
    # Mixed — defer to the more-recent fractal
    last_high_idx = highs[-1]["index"]
    last_low_idx  = lows[-1]["index"]
    if last_high_idx >= last_low_idx:
        return "UPTREND" if rh == "HH" else "DOWNTREND"
    else:
        return "UPTREND" if rl == "HL" else "DOWNTREND"


# ──────────────────────────────────────────────────
# State detection  (no CONSOLIDATION)
# ──────────────────────────────────────────────────

def _tsi_slope(tsi_values: List[float], lookback: int = 5) -> float:
    """Slope of TSI over the last `lookback` values (positive = rising)."""
    if len(tsi_values) < lookback + 1:
        return 0.0
    return tsi_values[-1] - tsi_values[-lookback - 1]


def detect_state(
    price: float,
    classified: List[Dict],
    tsi_values: List[float],
) -> Dict[str, Any]:
    """
    Priority order:
      1. BOS  — close above HH  OR  close below LL
      2. CHoCH— close above LH  OR  close below HL
      3. PULLBACK — TSI slope opposes the current trend direction
      4. IN_TREND — default
    """
    if not classified:
        return {"state": "IN_TREND", "trend": "UPTREND",
                "bos_level": None, "choch_level": None,
                "description": "No fractal structure yet"}

    levels = get_key_levels(classified)
    trend  = get_trend(classified)
    hh, hl, lh, ll = levels["HH"], levels["HL"], levels["LH"], levels["LL"]

    # ── 1. BOS ───────────────────────────────────────────
    if hh is not None and price > hh:
        return {"state": "BOS_CONTINUATION", "trend": trend,
                "bos_level": hh, "choch_level": None,
                "description": f"BOS ▲ Close {price:.4f} > HH {hh:.4f} (+{(price-hh)/hh*100:.2f}%)"}
    if ll is not None and price < ll:
        return {"state": "BOS_CONTINUATION", "trend": trend,
                "bos_level": ll, "choch_level": None,
                "description": f"BOS ▼ Close {price:.4f} < LL {ll:.4f} (-{(ll-price)/ll*100:.2f}%)"}

    # ── 2. CHoCH ─────────────────────────────────────────
    if lh is not None and price > lh:
        return {"state": "CHoCH_REVERSAL", "trend": trend,
                "bos_level": None, "choch_level": lh,
                "description": f"CHoCH ▲ Close {price:.4f} > LH {lh:.4f} — Bullish reversal signal"}
    if hl is not None and price < hl:
        return {"state": "CHoCH_REVERSAL", "trend": trend,
                "bos_level": None, "choch_level": hl,
                "description": f"CHoCH ▼ Close {price:.4f} < HL {hl:.4f} — Bearish reversal signal"}

    # ── 3. PULLBACK — TSI slope opposes trend ────────────
    slope = _tsi_slope(tsi_values)
    is_pullback = (trend == "UPTREND"   and slope < 0) or \
                  (trend == "DOWNTREND" and slope > 0)
    if is_pullback:
        tsi_now  = tsi_values[-1] if tsi_values else 0.0
        key_lvl  = hl if trend == "UPTREND" else lh
        lvl_desc = f" → key level {key_lvl:.4f}" if key_lvl else ""
        return {
            "state":      "PULLBACK",
            "trend":      trend,
            "bos_level":  None,
            "choch_level": None,
            "description": (
                f"Pullback ({trend}): TSI {'falling' if slope < 0 else 'rising'} "
                f"({tsi_now:+.3f}, Δ{slope:+.4f}){lvl_desc}"
            ),
        }

    # ── 4. IN_TREND ──────────────────────────────────────
    if trend == "UPTREND":
        desc = f"Uptrend: HH {hh or '—'} · HL {hl or '—'}"
        if lh: desc += f" · LH {lh}"
    else:
        desc = f"Downtrend: LH {lh or '—'} · LL {ll or '—'}"
        if hh: desc += f" · HH {hh}"
    return {"state": "IN_TREND", "trend": trend,
            "bos_level": None, "choch_level": None, "description": desc}


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


async def analyze_symbol(api: DerivAPI, symbol: str, config: Dict) -> Optional[Dict]:
    try:
        candles = await fetch_candles(api, symbol, 500)
        if len(candles) < 120:
            return None

        highs  = [float(c["high"])  for c in candles]
        lows   = [float(c["low"])   for c in candles]
        closes = [float(c["close"]) for c in candles]
        price  = closes[-1]

        fractals    = get_fractals(highs, lows, FRACTAL_PERIOD)
        classified  = classify_fractals(fractals)
        levels      = get_key_levels(classified)

        tsi  = calc_tsi(closes, TSI_PERIOD)
        macd = calc_macd(closes, fast=21, slow=55, signal=21)

        state_info = detect_state(price, classified, tsi["values"])
        trend      = state_info["trend"]

        # Support = most recent HL (uptrend) or LL (downtrend)
        support    = levels["HL"] if trend == "UPTREND" else levels["LL"]
        resistance = levels["HH"] if trend == "UPTREND" else levels["LH"]

        volatility = round(
            ((max(highs[-20:]) - min(lows[-20:])) / min(lows[-20:])) * 100, 1
        ) if len(highs) >= 20 else 0.0

        structure = {
            "trend":          trend,
            "last_resistance": resistance,
            "last_support":    support,
            "bos_level":      state_info.get("bos_level"),
            "choch_level":    state_info.get("choch_level"),
            "description":    state_info["description"],
        }

        return {
            "symbol":       symbol,
            "name":         config["name"],
            "price":        round(price, 4),
            "volatility":   volatility,
            "state":        state_info["state"],
            "trend":        trend,
            "fractal_count": len(fractals),
            "support":      support,
            "resistance":   resistance,
            "bos_level":    state_info.get("bos_level"),
            "choch_level":  state_info.get("choch_level"),
            "description":  state_info["description"],
            "structure":    structure,
            "tsi":          tsi,
            "macd":         macd,
            "last_fractals": classified[-4:],
            "last_updated": datetime.utcnow().isoformat(),
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

    counts: Dict[str, int] = {
        "PULLBACK": 0, "BOS_CONTINUATION": 0,
        "CHoCH_REVERSAL": 0, "IN_TREND": 0,
    }
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    return {
        "timestamp":           datetime.utcnow().isoformat(),
        "pullback_count":      counts["PULLBACK"],
        "bos_count":           counts["BOS_CONTINUATION"],
        "choch_count":         counts["CHoCH_REVERSAL"],
        "trending_count":      counts["IN_TREND"],
        "consolidation_count": 0,   # kept for API compat — always 0
        "symbols": results,
    }


async def build_chart_data(symbol: str) -> Dict:
    """1000 candles + classified fractal markers for the chart page."""
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN)
    candles = await fetch_candles(api, symbol, 1000)
    await api.disconnect()

    highs = [float(c["high"]) for c in candles]
    lows  = [float(c["low"])  for c in candles]

    raw_fractals = get_fractals(highs, lows, FRACTAL_PERIOD)
    markers      = classify_fractals(raw_fractals)
    levels       = get_key_levels(markers)
    trend        = get_trend(markers)

    candle_data = [
        {"time": c["epoch"], "open": float(c["open"]), "high": float(c["high"]),
         "low": float(c["low"]), "close": float(c["close"])}
        for c in candles
    ]
    return {
        "symbol":       symbol,
        "trend":        trend,
        "candles":      candle_data,
        "markers":      markers,
        "hh_level":     levels["HH"],
        "hl_level":     levels["HL"],
        "lh_level":     levels["LH"],
        "ll_level":     levels["LL"],
        "bar_count":    len(candles),
        "last_updated": datetime.utcnow().isoformat(),
    }


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


app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

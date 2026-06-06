import asyncio
import os
import time
import math
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from deriv_api import DerivAPI
import uvicorn

APP_ID = os.getenv("DERIV_APP_ID", "104094")
TOKEN = os.getenv("DERIV_TOKEN", "iaw8gpjk3H1wV1K")
PORT = int(os.getenv("PORT", "8080"))

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

FRACTAL_PERIOD = 55
TSI_PERIOD = 55
TSI_OVERSOLD = -0.7
TSI_OVERBOUGHT = 0.7
CACHE_TTL = 60

_analysis_cache: Optional[Dict] = None
_analysis_cache_time: float = 0
_chart_cache: Dict[str, Dict] = {}
_chart_cache_time: Dict[str, float] = {}


# ─────────────────────────────────────────
# Indicators
# ─────────────────────────────────────────

def ema_series(prices: List[float], period: int) -> List[float]:
    if not prices:
        return []
    k = 2.0 / (period + 1)
    result = [prices[0]]
    for p in prices[1:]:
        result.append(p * k + result[-1] * (1 - k))
    return result


def calc_macd(closes: List[float], fast=21, slow=55, signal=21) -> Dict:
    if len(closes) < slow + signal:
        return {"macd": 0.0, "signal": 0.0, "histogram": 0.0,
                "values": [], "signal_values": [], "histogram_values": []}
    fast_ema = ema_series(closes, fast)
    slow_ema = ema_series(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    sig_line = ema_series(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, sig_line)]
    tail = 100
    return {
        "macd":      round(macd_line[-1], 6),
        "signal":    round(sig_line[-1], 6),
        "histogram": round(hist[-1], 6),
        "values":           [round(x, 6) for x in macd_line[-tail:]],
        "signal_values":    [round(x, 6) for x in sig_line[-tail:]],
        "histogram_values": [round(x, 6) for x in hist[-tail:]],
    }


def calc_tsi(closes: List[float], period: int = TSI_PERIOD) -> Dict:
    """Trend Strength Index — Pearson's r. Range −1 to +1."""
    values: List[float] = []
    for end in range(period, len(closes) + 1):
        window = closes[end - period:end]
        n = len(window)
        xs = list(range(n))
        mx = (n - 1) / 2.0
        my = sum(window) / n
        num = sum((xs[i] - mx) * (window[i] - my) for i in range(n))
        sx  = sum((xs[i] - mx) ** 2 for i in range(n))
        sy  = sum((window[i] - my) ** 2 for i in range(n))
        denom = math.sqrt(sx * sy)
        values.append(round(num / denom if denom else 0.0, 4))
    current = values[-1] if values else 0.0
    return {
        "value": current,
        "is_oversold":   current < TSI_OVERSOLD,
        "is_overbought": current > TSI_OVERBOUGHT,
        "values": values[-100:],
    }


def get_fractals(highs: List[float], lows: List[float], period: int = FRACTAL_PERIOD) -> List[Dict]:
    fractals: List[Dict] = []
    for i in range(period, len(highs) - period):
        if all(highs[i] > highs[i - j] and highs[i] > highs[i + j] for j in range(1, period + 1)):
            fractals.append({"type": "RESISTANCE", "index": i, "price": round(highs[i], 4)})
        if all(lows[i] < lows[i - j] and lows[i] < lows[i + j] for j in range(1, period + 1)):
            fractals.append({"type": "SUPPORT", "index": i, "price": round(lows[i], 4)})
    return fractals


def classify_fractals(fractals: List[Dict]) -> List[Dict]:
    """
    Classify fractal sequence:
      Resistance highs → HH (higher) or LH (lower than previous)
      Support lows    → HL (higher than previous) or LL (lower)
    """
    highs = sorted([f for f in fractals if f["type"] == "RESISTANCE"], key=lambda x: x["index"])
    lows  = sorted([f for f in fractals if f["type"] == "SUPPORT"],    key=lambda x: x["index"])

    result: List[Dict] = []
    for i, frac in enumerate(highs):
        label = "HH" if i == 0 or frac["price"] > highs[i - 1]["price"] else "LH"
        result.append({"index": frac["index"], "price": frac["price"], "type": label})

    for i, frac in enumerate(lows):
        label = "HL" if i == 0 or frac["price"] > lows[i - 1]["price"] else "LL"
        result.append({"index": frac["index"], "price": frac["price"], "type": label})

    return sorted(result, key=lambda x: x["index"])


def identify_trend(fractals: List[Dict]) -> Optional[Dict]:
    if len(fractals) < 4:
        return None
    supports    = [f for f in fractals if f["type"] == "SUPPORT"][-2:]
    resistances = [f for f in fractals if f["type"] == "RESISTANCE"][-2:]
    if len(supports) < 2 or len(resistances) < 2:
        return None
    lr, pr = resistances[-1]["price"], resistances[-2]["price"]
    ls, ps = supports[-1]["price"],    supports[-2]["price"]
    rc = (lr - pr) / pr * 100
    sc = (ls - ps) / ps * 100
    if lr > pr and ls > ps:
        return {"trend": "UPTREND", "pattern": "HH_HL",
                "last_resistance": lr, "prev_resistance": pr,
                "last_support": ls, "prev_support": ps,
                "bos_level": lr, "choch_level": ls, "pullback_level": ls,
                "description": f"HH: {pr:.4f}→{lr:.4f} (+{rc:.1f}%) | HL: {ps:.4f}→{ls:.4f} (+{sc:.1f}%)"}
    elif lr < pr and ls < ps:
        return {"trend": "DOWNTREND", "pattern": "LH_LL",
                "last_resistance": lr, "prev_resistance": pr,
                "last_support": ls, "prev_support": ps,
                "bos_level": ls, "choch_level": lr, "pullback_level": lr,
                "description": f"LH: {pr:.4f}→{lr:.4f} ({rc:.1f}%) | LL: {ps:.4f}→{ls:.4f} ({sc:.1f}%)"}
    else:
        return {"trend": "CONSOLIDATION",
                "last_resistance": lr, "prev_resistance": pr,
                "last_support": ls, "prev_support": ps,
                "description": f"Mixed: R {pr:.4f}→{lr:.4f} | S {ps:.4f}→{ls:.4f}"}


def detect_state(structure: Optional[Dict], price: float) -> Dict:
    if not structure or structure["trend"] == "CONSOLIDATION":
        desc = structure["description"] if structure else "No fractal structure yet"
        return {"state": "CONSOLIDATION", "trend": "CONSOLIDATION", "description": desc}
    trend = structure["trend"]
    info: Dict[str, Any] = {"trend": trend}
    if trend == "UPTREND":
        res, sup = structure["last_resistance"], structure["last_support"]
        d_sup = abs(price - sup) / sup * 100
        if price > res:
            info.update({"state": "BOS_CONTINUATION",
                         "description": f"BOS: Broke resistance {res:.4f} (+{(price-res)/res*100:.2f}%)"})
        elif price < sup:
            info.update({"state": "CHoCH_REVERSAL",
                         "description": f"CHoCH: Broke support {sup:.4f} — TREND REVERSAL"})
        elif d_sup <= 1.0:
            info.update({"state": "PULLBACK",
                         "description": f"Pullback to support {sup:.4f} (dist: {d_sup:.2f}%)"})
        else:
            info.update({"state": "IN_TREND",
                         "description": f"Uptrend: Support {sup:.4f} → Resistance {res:.4f}"})
    else:
        res, sup = structure["last_resistance"], structure["last_support"]
        d_res = abs(res - price) / price * 100
        if price < sup:
            info.update({"state": "BOS_CONTINUATION",
                         "description": f"BOS: Broke support {sup:.4f} (-{(sup-price)/sup*100:.2f}%)"})
        elif price > res:
            info.update({"state": "CHoCH_REVERSAL",
                         "description": f"CHoCH: Broke resistance {res:.4f} — TREND REVERSAL"})
        elif d_res <= 1.0:
            info.update({"state": "PULLBACK",
                         "description": f"Pullback to resistance {res:.4f} (dist: {d_res:.2f}%)"})
        else:
            info.update({"state": "IN_TREND",
                         "description": f"Downtrend: Resistance {res:.4f} → Support {sup:.4f}"})
    return info


# ─────────────────────────────────────────
# Deriv API helpers
# ─────────────────────────────────────────

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
        if len(candles) < 100:
            return None
        highs  = [float(c["high"])  for c in candles]
        lows   = [float(c["low"])   for c in candles]
        closes = [float(c["close"]) for c in candles]
        price  = closes[-1]
        fractals  = get_fractals(highs, lows, FRACTAL_PERIOD)
        structure = identify_trend(fractals)
        state     = detect_state(structure, price)
        tsi  = calc_tsi(closes[:-1], TSI_PERIOD)
        macd = calc_macd(closes, fast=21, slow=55, signal=21)
        volatility = round(
            ((max(highs[-20:]) - min(lows[-20:])) / min(lows[-20:])) * 100, 1
        ) if len(highs) >= 20 else 0.0
        last_fractals = fractals[-4:] if len(fractals) >= 4 else fractals
        return {
            "symbol": symbol, "name": config["name"],
            "price": round(price, 4), "volatility": volatility,
            "state": state["state"], "trend": state["trend"],
            "fractal_count": len(fractals),
            "support":    structure["last_support"]    if structure and "last_support"    in structure else None,
            "resistance": structure["last_resistance"] if structure and "last_resistance" in structure else None,
            "bos_level":  structure.get("bos_level")  if structure else None,
            "choch_level":structure.get("choch_level") if structure else None,
            "description": state["description"],
            "structure": structure,
            "tsi": tsi, "macd": macd,
            "last_fractals": last_fractals,
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
        "PULLBACK": 0, "BOS_CONTINUATION": 0, "CHoCH_REVERSAL": 0,
        "IN_TREND": 0, "CONSOLIDATION": 0,
    }
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "pullback_count":     counts["PULLBACK"],
        "bos_count":          counts["BOS_CONTINUATION"],
        "choch_count":        counts["CHoCH_REVERSAL"],
        "trending_count":     counts["IN_TREND"],
        "consolidation_count":counts["CONSOLIDATION"],
        "symbols": results,
    }


async def build_chart_data(symbol: str) -> Dict:
    """Fetch 1000 candles + classify fractals for chart display."""
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN)
    candles = await fetch_candles(api, symbol, 1000)
    await api.disconnect()

    highs  = [float(c["high"])  for c in candles]
    lows   = [float(c["low"])   for c in candles]

    # Fractal detection on 1000 candles
    raw_fractals = get_fractals(highs, lows, FRACTAL_PERIOD)
    markers = classify_fractals(raw_fractals)

    # Most recent level of each type
    levels: Dict[str, Optional[float]] = {"HH": None, "HL": None, "LH": None, "LL": None}
    for m in markers:
        levels[m["type"]] = m["price"]  # keeps last (most recent) due to sort order

    # Trend from most recent fractal pair
    recent_highs = [m for m in markers if m["type"] in ("HH", "LH")]
    recent_lows  = [m for m in markers if m["type"] in ("HL", "LL")]
    trend = "CONSOLIDATION"
    if recent_highs and recent_lows:
        rh = recent_highs[-1]["type"]
        rl = recent_lows[-1]["type"]
        if rh == "HH" and rl == "HL":
            trend = "UPTREND"
        elif rh == "LH" and rl == "LL":
            trend = "DOWNTREND"

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


# ─────────────────────────────────────────
# FastAPI
# ─────────────────────────────────────────

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
        _analysis_cache = data
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
        _chart_cache[symbol] = data
        _chart_cache_time[symbol] = now
        return data
    except Exception as e:
        if symbol in _chart_cache:
            return _chart_cache[symbol]
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

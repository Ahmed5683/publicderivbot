import asyncio
import os
import time
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
    "1HZ10V": {"multiplier": 400, "name": "Volatility 10"},
    "R_10":   {"multiplier": 400, "name": "R_10"},
    "1HZ15V": {"multiplier": 300, "name": "Volatility 15"},
    "1HZ25V": {"multiplier": 160, "name": "Volatility 25"},
    "R_25":   {"multiplier": 160, "name": "R_25"},
    "1HZ30V": {"multiplier": 140, "name": "Volatility 30"},
    "1HZ50V": {"multiplier": 80,  "name": "Volatility 50"},
    "R_50":   {"multiplier": 80,  "name": "R_50"},
    "1HZ75V": {"multiplier": 50,  "name": "Volatility 75"},
    "R_75":   {"multiplier": 50,  "name": "R_75"},
    "1HZ90V": {"multiplier": 45,  "name": "Volatility 90"},
    "1HZ100V":{"multiplier": 40,  "name": "Volatility 100"},
    "R_100":  {"multiplier": 40,  "name": "R_100"},
}

FRACTAL_PERIOD = 55
CACHE_TTL = 60

_analysis_cache: Optional[Dict] = None
_analysis_cache_time: float = 0
_candle_cache: Dict[str, Dict] = {}
_candle_cache_time: Dict[str, float] = {}
CANDLE_CACHE_TTL = 60

# ─────────────────────────────────────────
# Indicators
# ─────────────────────────────────────────

def ema(values: List[float], period: int) -> List[float]:
    result = []
    k = 2.0 / (period + 1)
    for i, v in enumerate(values):
        if i == 0:
            result.append(v)
        else:
            result.append(v * k + result[-1] * (1 - k))
    return result


def calc_macd(closes: List[float], fast=21, slow=55, signal=21):
    if len(closes) < slow + signal:
        return {"macd": 0, "signal": 0, "histogram": 0,
                "values": [], "signal_values": [], "histogram_values": []}
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]
    signal_line = ema(macd_line, signal)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    tail = 60
    return {
        "macd": round(macd_line[-1], 6),
        "signal": round(signal_line[-1], 6),
        "histogram": round(hist[-1], 6),
        "values": [round(x, 6) for x in macd_line[-tail:]],
        "signal_values": [round(x, 6) for x in signal_line[-tail:]],
        "histogram_values": [round(x, 6) for x in hist[-tail:]],
    }


def calc_tsi(closes: List[float], period=55) -> Dict:
    """
    Trend Strength Index (NOT True Strength Index).
    Measures directional consistency over N bars:
      TSI = |sum(close[i] - close[i-1])| / sum(|close[i] - close[i-1]|) * 100
    Range 0-100. Higher = stronger trend in one direction.
    """
    if len(closes) < period + 1:
        return {"value": 0, "values": [], "strength": "WEAK"}

    tsi_values = []
    for end in range(period, len(closes)):
        window = closes[end - period:end + 1]
        changes = [window[i] - window[i - 1] for i in range(1, len(window))]
        directional = abs(sum(changes))
        total = sum(abs(c) for c in changes)
        tsi_values.append(round((directional / total * 100) if total > 0 else 0, 2))

    current = tsi_values[-1] if tsi_values else 0
    strength = "STRONG" if current >= 70 else "MODERATE" if current >= 40 else "WEAK"
    return {
        "value": current,
        "values": tsi_values[-60:],
        "strength": strength,
    }


def get_fractals(highs, lows, period=FRACTAL_PERIOD):
    fractals = []
    for i in range(period, len(highs) - period):
        is_up = all(highs[i] > highs[i - j] and highs[i] > highs[i + j] for j in range(1, period + 1))
        if is_up:
            fractals.append({"type": "RESISTANCE", "index": i, "price": round(highs[i], 4)})
        is_down = all(lows[i] < lows[i - j] and lows[i] < lows[i + j] for j in range(1, period + 1))
        if is_down:
            fractals.append({"type": "SUPPORT", "index": i, "price": round(lows[i], 4)})
    return fractals


def identify_trend(fractals):
    if len(fractals) < 4:
        return None
    supports = [f for f in fractals if f["type"] == "SUPPORT"][-2:]
    resistances = [f for f in fractals if f["type"] == "RESISTANCE"][-2:]
    if len(supports) < 2 or len(resistances) < 2:
        return None
    lr, pr = resistances[-1]["price"], resistances[-2]["price"]
    ls, ps = supports[-1]["price"], supports[-2]["price"]
    rc = (lr - pr) / pr * 100
    sc = (ls - ps) / ps * 100
    if lr > pr and ls > ps:
        return {
            "trend": "UPTREND", "pattern": "HH_HL",
            "last_resistance": lr, "prev_resistance": pr,
            "last_support": ls, "prev_support": ps,
            "bos_level": lr, "choch_level": ls, "pullback_level": ls,
            "description": f"HH: {pr:.4f}→{lr:.4f} (+{rc:.1f}%) | HL: {ps:.4f}→{ls:.4f} (+{sc:.1f}%)"
        }
    elif lr < pr and ls < ps:
        return {
            "trend": "DOWNTREND", "pattern": "LH_LL",
            "last_resistance": lr, "prev_resistance": pr,
            "last_support": ls, "prev_support": ps,
            "bos_level": ls, "choch_level": lr, "pullback_level": lr,
            "description": f"LH: {pr:.4f}→{lr:.4f} ({rc:.1f}%) | LL: {ps:.4f}→{ls:.4f} ({sc:.1f}%)"
        }
    else:
        return {
            "trend": "CONSOLIDATION",
            "last_resistance": lr, "prev_resistance": pr,
            "last_support": ls, "prev_support": ps,
            "description": f"Mixed: R {pr:.4f}→{lr:.4f} | S {ps:.4f}→{ls:.4f}"
        }


def detect_state(structure, current_price):
    if not structure or structure["trend"] == "CONSOLIDATION":
        desc = structure["description"] if structure else "No fractal structure yet"
        return {"state": "CONSOLIDATION", "trend": "CONSOLIDATION", "description": desc}

    trend = structure["trend"]
    info = {"trend": trend, "current_price": round(current_price, 4)}

    if trend == "UPTREND":
        res, sup = structure["last_resistance"], structure["last_support"]
        d_sup = abs(current_price - sup) / sup * 100
        if current_price > res:
            info.update({"state": "BOS_CONTINUATION",
                          "description": f"BOS: Broke resistance {res:.4f} (+{((current_price-res)/res*100):.2f}%)"})
        elif current_price < sup:
            info.update({"state": "CHoCH_REVERSAL",
                          "description": f"CHoCH: Broke support {sup:.4f} - TREND REVERSAL"})
        elif d_sup <= 1.0:
            info.update({"state": "PULLBACK",
                          "description": f"Pullback to support {sup:.4f} (dist: {d_sup:.2f}%)"})
        else:
            info.update({"state": "IN_TREND",
                          "description": f"Uptrend: Support {sup:.4f} → Resistance {res:.4f}"})
    else:
        res, sup = structure["last_resistance"], structure["last_support"]
        d_res = abs(res - current_price) / current_price * 100
        if current_price < sup:
            info.update({"state": "BOS_CONTINUATION",
                          "description": f"BOS: Broke support {sup:.4f} (-{((sup-current_price)/sup*100):.2f}%)"})
        elif current_price > res:
            info.update({"state": "CHoCH_REVERSAL",
                          "description": f"CHoCH: Broke resistance {res:.4f} - TREND REVERSAL"})
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
    req = {
        "ticks_history": symbol,
        "adjust_start_time": 1,
        "count": count,
        "end": "latest",
        "granularity": 60,
        "style": "candles",
    }
    resp = await api.ticks_history(req)
    return resp.get("candles", [])


async def analyze_symbol(api: DerivAPI, symbol: str, config: Dict) -> Optional[Dict]:
    try:
        candles = await fetch_candles(api, symbol, 500)
        if len(candles) < 100:
            return None
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        closes = [float(c["close"]) for c in candles]
        current = closes[-1]

        fractals = get_fractals(highs, lows)
        structure = identify_trend(fractals)
        state = detect_state(structure, current)
        tsi = calc_tsi(closes, period=55)
        macd = calc_macd(closes, fast=21, slow=55, signal=21)
        volatility = round(((max(highs[-20:]) - min(lows[-20:])) / min(lows[-20:])) * 100, 1) if len(highs) >= 20 else 0

        last_fractals = fractals[-4:] if len(fractals) >= 4 else fractals
        return {
            "symbol": symbol,
            "name": config["name"],
            "price": round(current, 4),
            "volatility": volatility,
            "state": state["state"],
            "trend": state["trend"],
            "fractal_count": len(fractals),
            "support": structure["last_support"] if structure and "last_support" in structure else None,
            "resistance": structure["last_resistance"] if structure and "last_resistance" in structure else None,
            "bos_level": structure.get("bos_level") if structure else None,
            "choch_level": structure.get("choch_level") if structure else None,
            "description": state["description"],
            "structure": structure,
            "tsi": tsi,
            "macd": macd,
            "last_fractals": last_fractals,
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None


async def run_full_analysis() -> Dict:
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN)
    results = []
    for symbol, config in SYMBOL_CONFIG.items():
        result = await analyze_symbol(api, symbol, config)
        if result:
            results.append(result)
        await asyncio.sleep(0.2)
    await api.disconnect()

    counts = {"PULLBACK": 0, "BOS_CONTINUATION": 0, "CHoCH_REVERSAL": 0, "IN_TREND": 0, "CONSOLIDATION": 0}
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "pullback_count": counts["PULLBACK"],
        "bos_count": counts["BOS_CONTINUATION"],
        "choch_count": counts["CHoCH_REVERSAL"],
        "trending_count": counts["IN_TREND"],
        "consolidation_count": counts["CONSOLIDATION"],
        "symbols": results,
    }


async def get_1000_candles(symbol: str) -> List[Dict]:
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN)
    candles = await fetch_candles(api, symbol, 1000)
    await api.disconnect()
    return [
        {"time": c["epoch"], "open": float(c["open"]), "high": float(c["high"]),
         "low": float(c["low"]), "close": float(c["close"])}
        for c in candles
    ]


# ─────────────────────────────────────────
# FastAPI app
# ─────────────────────────────────────────

app = FastAPI(title="Deriv Market Analysis")
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
        {"symbol": sym, "name": cfg["name"], "multiplier": cfg["multiplier"]}
        for sym, cfg in SYMBOL_CONFIG.items()
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


@router.get("/market/candles/{symbol}")
async def get_candles(symbol: str):
    if symbol not in SYMBOL_CONFIG:
        raise HTTPException(status_code=404, detail="Symbol not found")
    now = time.time()
    if symbol in _candle_cache and (now - _candle_cache_time.get(symbol, 0)) < CANDLE_CACHE_TTL:
        return _candle_cache[symbol]
    try:
        data = await get_1000_candles(symbol)
        _candle_cache[symbol] = data
        _candle_cache_time[symbol] = now
        return data
    except Exception as e:
        if symbol in _candle_cache:
            return _candle_cache[symbol]
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

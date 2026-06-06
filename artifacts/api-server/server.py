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

CACHE_TTL = 60
CANDLE_CACHE_TTL = 60

_analysis_cache: Optional[Dict] = None
_analysis_cache_time: float = 0
_candle_cache: Dict[str, Any] = {}
_candle_cache_time: Dict[str, float] = {}
_trade_history: List[Dict] = []


# ─────────────────────────────────────────
# Indicators (matching the bot exactly)
# ─────────────────────────────────────────

def calculate_ema_series(prices: List[float], period: int) -> List[float]:
    if len(prices) < period:
        return [prices[-1]] * len(prices)
    multiplier = 2 / (period + 1)
    ema_series = [prices[0]]
    for price in prices[1:]:
        ema_series.append((price - ema_series[-1]) * multiplier + ema_series[-1])
    return ema_series


def calculate_ema(prices: List[float], period: int) -> float:
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    multiplier = 2 / (period + 1)
    ema = prices[0]
    for price in prices[1:]:
        ema = (price - ema) * multiplier + ema
    return ema


def calculate_macd(close_prices: List[float], fast_period=21, slow_period=55, signal_period=9) -> Dict:
    """
    Calculates MACD and detects crossovers using closed candles (-2 for current, -3 for prev).
    Returns bullish/bearish crossover flags plus series for charting.
    """
    if len(close_prices) < slow_period + signal_period + 2:
        return {
            "macd": 0.0, "signal": 0.0, "histogram": 0.0,
            "macd_bullish": False, "macd_bearish": False,
            "values": [], "signal_values": [], "histogram_values": [],
        }

    ema_fast_series = calculate_ema_series(close_prices, fast_period)
    ema_slow_series = calculate_ema_series(close_prices, slow_period)
    macd_line_series = [f - s for f, s in zip(ema_fast_series, ema_slow_series)]
    signal_line_series = calculate_ema_series(macd_line_series, signal_period)

    if len(macd_line_series) < 3 or len(signal_line_series) < 3:
        return {
            "macd": 0.0, "signal": 0.0, "histogram": 0.0,
            "macd_bullish": False, "macd_bearish": False,
            "values": [], "signal_values": [], "histogram_values": [],
        }

    # Use closed candles: -2 is last closed, -3 is previous closed
    current_macd = macd_line_series[-2]
    current_signal = signal_line_series[-2]
    prev_macd = macd_line_series[-3]
    prev_signal = signal_line_series[-3]

    bullish = (prev_macd < prev_signal) and (current_macd > current_signal)
    bearish = (prev_macd > prev_signal) and (current_macd < current_signal)
    hist_series = [m - s for m, s in zip(macd_line_series, signal_line_series)]
    tail = 60

    return {
        "macd": round(current_macd, 6),
        "signal": round(current_signal, 6),
        "histogram": round(current_macd - current_signal, 6),
        "macd_bullish": bullish,
        "macd_bearish": bearish,
        "values": [round(x, 6) for x in macd_line_series[-tail:]],
        "signal_values": [round(x, 6) for x in signal_line_series[-tail:]],
        "histogram_values": [round(x, 6) for x in hist_series[-tail:]],
    }


def calculate_tsi(close_prices: List[float], period=55) -> Dict:
    """
    Trend Strength Index using Pearson's correlation coefficient.
    Range: -1 to +1. Oversold < -0.8, Overbought > +0.8.
    Uses closed candles (excludes last price).
    """
    if len(close_prices) < period + 1:
        return {"value": 0.0, "is_oversold": False, "is_overbought": False, "values": []}

    closed_prices = close_prices[:-1]  # exclude last (open) candle
    if len(closed_prices) < period:
        return {"value": 0.0, "is_oversold": False, "is_overbought": False, "values": []}

    # Compute rolling TSI for charting
    tsi_values = []
    for end in range(period, len(closed_prices) + 1):
        window = closed_prices[end - period:end]
        n = len(window)
        bar_indices = list(range(n))
        mean_x = sum(bar_indices) / n
        mean_y = sum(window) / n
        numerator = 0.0
        sum_sq_x = 0.0
        sum_sq_y = 0.0
        for i in range(n):
            xd = bar_indices[i] - mean_x
            yd = window[i] - mean_y
            numerator += xd * yd
            sum_sq_x += xd * xd
            sum_sq_y += yd * yd
        denom = math.sqrt(sum_sq_x * sum_sq_y)
        tsi_values.append(round(numerator / denom if denom != 0 else 0.0, 4))

    current = tsi_values[-1] if tsi_values else 0.0
    return {
        "value": current,
        "is_oversold": current < -0.8,
        "is_overbought": current > 0.8,
        "values": tsi_values[-60:],
    }


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
        candles = await fetch_candles(api, symbol, 400)
        if len(candles) < 351:
            return None

        close_prices = [float(c["close"]) for c in candles]
        closed_prices = close_prices[:-1]

        # Trend: EMA100 vs EMA350
        ema100 = calculate_ema(closed_prices, 100)
        ema350 = calculate_ema(closed_prices, 350)
        is_uptrend = ema100 > ema350

        # MACD (21, 55, 9)
        macd = calculate_macd(closed_prices, 21, 55, 9)

        # TSI Pearson correlation (period=55)
        tsi = calculate_tsi(close_prices, 55)

        # Signal detection
        signal = "NONE"
        if is_uptrend and macd["macd_bullish"] and tsi["is_oversold"]:
            signal = "BUY"
        elif (not is_uptrend) and macd["macd_bearish"] and tsi["is_overbought"]:
            signal = "SELL"

        volatility = round(
            ((max(float(c["high"]) for c in candles[-20:]) - min(float(c["low"]) for c in candles[-20:])) /
             min(float(c["low"]) for c in candles[-20:])) * 100, 1
        ) if len(candles) >= 20 else 0.0

        return {
            "symbol": symbol,
            "name": config["name"],
            "price": round(float(candles[-1]["close"]), 4),
            "volatility": volatility,
            "trend": "UPTREND" if is_uptrend else "DOWNTREND",
            "ema100": round(ema100, 4),
            "ema350": round(ema350, 4),
            "signal": signal,
            "tsi": tsi,
            "macd": macd,
            "last_updated": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        return None


async def place_trade(api: DerivAPI, symbol: str, contract_type: str, side: str, config: Dict,
                      tsi_val: float, macd_hist: float):
    record: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "side": side,
        "contract_type": contract_type,
        "contract_id": None,
        "ask_price": None,
        "multiplier": config["multiplier"],
        "tsi": round(tsi_val, 4),
        "macd_histogram": round(macd_hist, 6),
        "status": "FAILED",
        "error": None,
    }
    try:
        proposal = await api.proposal({
            "proposal": 1,
            "amount": 1,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "symbol": symbol,
            "multiplier": config["multiplier"],
        })
        proposal_id = proposal["proposal"]["id"]
        ask_price = proposal["proposal"]["ask_price"]
        record["ask_price"] = ask_price

        buy_resp = await api.buy({"buy": proposal_id, "price": ask_price})
        contract_id = buy_resp["buy"]["contract_id"]
        record["contract_id"] = str(contract_id)

        await api.contract_update({
            "contract_id": contract_id,
            "limit_order": {
                "stop_loss": 1.0,
                "take_profit": 0.5,
            },
        })
        record["status"] = "PLACED"
        print(f"[TRADE] {side} {symbol} contract={contract_id} ask={ask_price}")
    except Exception as e:
        record["error"] = str(e)
        print(f"[TRADE FAILED] {side} {symbol}: {e}")

    _trade_history.insert(0, record)
    if len(_trade_history) > 100:
        _trade_history.pop()


async def run_full_scan() -> Dict:
    api = DerivAPI(app_id=APP_ID)
    await api.authorize(TOKEN)
    results = []
    for symbol, config in SYMBOL_CONFIG.items():
        result = await analyze_symbol(api, symbol, config)
        if result:
            results.append(result)
            # Place trades for signals
            if result["signal"] == "BUY":
                await place_trade(
                    api, symbol, "MULTUP", "BUY", config,
                    result["tsi"]["value"], result["macd"]["histogram"]
                )
            elif result["signal"] == "SELL":
                await place_trade(
                    api, symbol, "MULTDOWN", "SELL", config,
                    result["tsi"]["value"], result["macd"]["histogram"]
                )
        await asyncio.sleep(0.2)
    await api.disconnect()

    buy_count = sum(1 for r in results if r["signal"] == "BUY")
    sell_count = sum(1 for r in results if r["signal"] == "SELL")
    uptrend_count = sum(1 for r in results if r["trend"] == "UPTREND")
    downtrend_count = sum(1 for r in results if r["trend"] == "DOWNTREND")

    return {
        "timestamp": datetime.utcnow().isoformat(),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "uptrend_count": uptrend_count,
        "downtrend_count": downtrend_count,
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
# Background scanning loop
# ─────────────────────────────────────────

async def background_scan_loop():
    """Runs the full scan every 60 seconds, exactly like the bot's main loop."""
    global _analysis_cache, _analysis_cache_time
    while True:
        try:
            print(f"[SCAN] Starting market scan at {datetime.utcnow().isoformat()}")
            data = await run_full_scan()
            _analysis_cache = data
            _analysis_cache_time = time.time()
            buys = data["buy_count"]
            sells = data["sell_count"]
            print(f"[SCAN] Complete. BUY signals: {buys}, SELL signals: {sells}")
        except Exception as e:
            print(f"[SCAN ERROR] {e}")
        await asyncio.sleep(60)


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


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_scan_loop())


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
    if _analysis_cache:
        return _analysis_cache
    # Return empty stub while first scan is running
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "buy_count": 0,
        "sell_count": 0,
        "uptrend_count": 0,
        "downtrend_count": 0,
        "symbols": [],
    }


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


@router.get("/market/trades")
async def get_trades():
    return _trade_history


app.include_router(router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)

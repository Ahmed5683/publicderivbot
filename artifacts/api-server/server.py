import asyncio
import os
import time
import math
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRouter
from pydantic import BaseModel
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

FRACTAL_PERIOD      = 36
CHOCH_SWING_PERIOD  = 5     # shorter period for real-time CHoCH level detection
TSI_PERIOD          = 55
TSI_OVERSOLD        = -0.7
TSI_OVERBOUGHT      =  0.7
CACHE_TTL           = 60
TRADE_COOLDOWN_SECS = 300   # 5 minutes per symbol

_analysis_cache:      Optional[Dict] = None
_analysis_cache_time: float = 0
_chart_cache:         Dict[str, Dict]  = {}
_chart_cache_time:    Dict[str, float] = {}

# ── Trading state ─────────────────────────────────
_trade_log:      List[Dict] = []          # capped at 50
_trade_cooldown: Dict[str, float] = {}    # symbol → last trade epoch


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
    levels: Dict[str, Optional[float]] = {"HH": None, "HL": None, "LH": None, "LL": None}
    for f in classified:
        levels[f["type"]] = f["price"]
    return levels


def get_structural_swing(highs: List[float], lows: List[float],
                         period: int = CHOCH_SWING_PERIOD) -> Dict[str, Optional[float]]:
    """
    Detect the most recent swing high and swing low using a short look-back/look-ahead.
    Used for CHoCH detection so we don't wait for the full FRACTAL_PERIOD confirmation.
    """
    n = len(highs)
    last_swing_high: Optional[float] = None
    last_swing_low:  Optional[float] = None
    for i in range(period, n - period):
        if all(highs[i] > highs[i - j] and highs[i] > highs[i + j] for j in range(1, period + 1)):
            last_swing_high = round(highs[i], 4)
        if all(lows[i] < lows[i - j] and lows[i] < lows[i + j] for j in range(1, period + 1)):
            last_swing_low = round(lows[i], 4)
    return {"swing_high": last_swing_high, "swing_low": last_swing_low}


def get_trend(classified: List[Dict]) -> str:
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
    last_high_idx = highs[-1]["index"]
    last_low_idx  = lows[-1]["index"]
    if last_high_idx >= last_low_idx:
        return "UPTREND" if rh == "HH" else "DOWNTREND"
    else:
        return "UPTREND" if rl == "HL" else "DOWNTREND"


# ──────────────────────────────────────────────────
# State detection
# ──────────────────────────────────────────────────


def detect_state(price: float, classified: List[Dict], tsi_values: List[float],
                 structural_swing: Optional[Dict] = None) -> Dict[str, Any]:
    if not classified:
        return {"state": "IN_TREND", "trend": "UPTREND",
                "bos_level": None, "choch_level": None,
                "description": "No fractal structure yet"}

    levels = get_key_levels(classified)
    trend  = get_trend(classified)
    hh, hl, lh, ll = levels["HH"], levels["HL"], levels["LH"], levels["LL"]

    # ── BOS: price breaks the confirmed major structure level ─────────────────
    if hh is not None and price > hh:
        return {"state": "BOS_CONTINUATION", "trend": trend,
                "bos_level": hh, "choch_level": None,
                "description": f"BOS ▲ Broke HH {hh:.4f} · Price {price:.4f} (+{(price-hh)/hh*100:.2f}%) · Uptrend continuation"}
    if ll is not None and price < ll:
        return {"state": "BOS_CONTINUATION", "trend": trend,
                "bos_level": ll, "choch_level": None,
                "description": f"BOS ▼ Broke LL {ll:.4f} · Price {price:.4f} (-{(ll-price)/ll*100:.2f}%) · Downtrend continuation"}

    tsi_now = tsi_values[-1] if tsi_values else 0.0
    sw      = structural_swing or {}

    if trend == "UPTREND":
        # CHoCH ▼ — price breaks below confirmed HL fractal (primary) or 5-bar swing low (fallback)
        choch_support = hl or sw.get("swing_low")
        if choch_support is not None and price < choch_support:
            return {"state": "CHoCH_REVERSAL", "trend": trend,
                    "bos_level": None, "choch_level": choch_support,
                    "description": f"CHoCH ▼ Broke {choch_support:.4f} · Price {price:.4f} · Uptrend → Downtrend"}

        # PULLBACK ▲ — price has retreated BELOW the recent local high (swing high)
        # Meaning: price peaked, is now coming back down toward support — that IS a pullback
        # IN_TREND  — price is still AT or ABOVE the recent swing high (still climbing)
        swing_high = sw.get("swing_high") or hh
        if swing_high is not None and price < swing_high:
            sup_desc = f" · support {choch_support:.4f}" if choch_support else ""
            return {"state": "PULLBACK", "trend": trend,
                    "bos_level": None, "choch_level": None,
                    "description": f"Pullback ▲ {price:.4f} below peak {swing_high:.4f} · TSI {tsi_now:+.3f}{sup_desc}"}

        desc = f"Uptrend: HH {hh or '—'} · HL {hl or '—'}"
        if lh: desc += f" · LH {lh}"
        return {"state": "IN_TREND", "trend": trend,
                "bos_level": None, "choch_level": None, "description": desc}

    else:  # DOWNTREND
        # CHoCH ▲ — price breaks above recent structural resistance
        choch_resistance = lh or sw.get("swing_high")
        if choch_resistance is not None and price > choch_resistance:
            return {"state": "CHoCH_REVERSAL", "trend": trend,
                    "bos_level": None, "choch_level": choch_resistance,
                    "description": f"CHoCH ▲ Broke {choch_resistance:.4f} · Price {price:.4f} · Downtrend → Uptrend"}

        # PULLBACK ▼ — price has risen ABOVE the recent local low (swing low)
        # Meaning: price bottomed, is now bouncing back up toward resistance — that IS a pullback
        # IN_TREND  — price is still AT or BELOW the recent swing low (still falling)
        swing_low = sw.get("swing_low") or ll
        if swing_low is not None and price > swing_low:
            res_desc = f" · resistance {choch_resistance:.4f}" if choch_resistance else ""
            return {"state": "PULLBACK", "trend": trend,
                    "bos_level": None, "choch_level": None,
                    "description": f"Pullback ▼ {price:.4f} above trough {swing_low:.4f} · TSI {tsi_now:+.3f}{res_desc}"}

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

        fractals          = get_fractals(highs, lows, FRACTAL_PERIOD)
        classified        = classify_fractals(fractals)
        levels            = get_key_levels(classified)
        structural_swing  = get_structural_swing(highs, lows, CHOCH_SWING_PERIOD)

        tsi  = calc_tsi(closes, TSI_PERIOD)
        macd = calc_macd(closes, fast=21, slow=55, signal=21)

        state_info = detect_state(price, classified, tsi["values"], structural_swing)
        trend      = state_info["trend"]

        support    = levels["HL"] if trend == "UPTREND" else levels["LL"]
        resistance = levels["HH"] if trend == "UPTREND" else levels["LH"]

        volatility = round(
            ((max(highs[-20:]) - min(lows[-20:])) / min(lows[-20:])) * 100, 1
        ) if len(highs) >= 20 else 0.0

        structure = {
            "trend":           trend,
            "last_resistance": resistance,
            "last_support":    support,
            "bos_level":       state_info.get("bos_level"),
            "choch_level":     state_info.get("choch_level"),
            "description":     state_info["description"],
        }

        return {
            "symbol":        symbol,
            "name":          config["name"],
            "price":         round(price, 4),
            "volatility":    volatility,
            "state":         state_info["state"],
            "trend":         trend,
            "fractal_count": len(fractals),
            "support":       support,
            "resistance":    resistance,
            "bos_level":     state_info.get("bos_level"),
            "choch_level":   state_info.get("choch_level"),
            "description":   state_info["description"],
            "structure":     structure,
            "tsi":           tsi,
            "macd":          macd,
            "last_fractals": classified[-4:],
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

    # Auto-trade: always runs — check each symbol in parallel
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
# Auto-trading engine
# ──────────────────────────────────────────────────

def _macd_crossover(histogram_values: List[float], lookback: int = 3) -> Optional[str]:
    """
    Returns 'bullish' if MACD crossed above Signal within the last `lookback` bars,
            'bearish' if MACD crossed below Signal within the last `lookback` bars,
            None otherwise.
    Checking a 3-bar window avoids missing the crossover when it falls between scans.
    """
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
    """Place MULTUP or MULTDOWN — $1 stake, SL $0.50, TP $1.00."""
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
      2. TSI oversold (< −0.7) for UPTREND  OR  overbought (> +0.7) for DOWNTREND
      3. MACD line × Signal line crossover on the last bar (histogram flips sign)
    """
    global _trade_log, _trade_cooldown

    if sym["state"] != "PULLBACK":
        return

    trend = sym["trend"]
    tsi   = sym.get("tsi") or {}
    macd  = sym.get("macd") or {}

    tsi_val      = tsi.get("value", 0.0)
    hist_vals    = macd.get("histogram_values", [])
    crossover    = _macd_crossover(hist_vals)
    symbol       = sym["symbol"]

    # Condition 2 — TSI extreme
    if trend == "UPTREND"   and tsi_val >= TSI_OVERSOLD:
        return
    if trend == "DOWNTREND" and tsi_val <= TSI_OVERBOUGHT:
        return

    # Condition 3 — MACD × Signal crossover in trend direction
    if trend == "UPTREND"   and crossover != "bullish":
        return
    if trend == "DOWNTREND" and crossover != "bearish":
        return

    # Cooldown check
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


# ── Trading endpoints ─────────────────────────────

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

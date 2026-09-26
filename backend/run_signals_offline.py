import os
import asyncio
import logging
import json
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True)

ASSETS = {
    'XAUUSD': {'symbol': 'XAUUSD', 'market': 'FOREX'},
    'NASDAQ': {'symbol': 'NDX', 'market': 'INDEX'},
}

TIMEFRAMES = ['1d']

def cache_key(asset: str, timeframe: str) -> str:
    return f'ohlc_{asset}_{timeframe}.json'

def get_cache(asset: str, timeframe: str):
    ck = cache_key(asset, timeframe)
    cache_file = CACHE_DIR / ck
    if cache_file.exists():
        with open(cache_file) as f:
            data = json.load(f)
            if time.time() - data.get('timestamp', 0) < 3600:  # 1 hour TTL
                return data.get('value')
    return None

def parse_alpha_data(asset: str, data: dict, timeframe: str):
    try:
        if asset == 'XAUUSD':
            data_array = data.get('data', [])
            if not data_array:
                return None
            candles = []
            for item in data_array:
                ts = item.get('date')
                value = item.get('price') or item.get('value')
                if ts and value:
                    val = float(value)
                    candles.append({
                        'timestamp': ts,
                        'open': val,
                        'high': val,
                        'low': val,
                        'close': val,
                        'volume': 0
                    })
            return candles
        else:
            key = 'Time Series (Daily)'
            timeseries = data.get(key, {})
            if not timeseries:
                return None
            candles = []
            for ts, ohlc in sorted(timeseries.items()):
                candles.append({
                    'timestamp': ts,
                    'open': float(ohlc['1. open']),
                    'high': float(ohlc['2. high']),
                    'low': float(ohlc['3. low']),
                    'close': float(ohlc['4. close']),
                    'volume': float(ohlc.get('5. volume', 0))
                })
            return candles
    except Exception as e:
        logger.error(f'Parse error for {asset} {timeframe}: {e}')
        return None

# --- ICT Analysis (copied from app/analysis.py) ---
import numpy as np
from app.smart_money_concepts import smc

def ict_analysis(asset: str, timeframe: str, candles: list):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]
    swings = smc.swing_highs_lows(highs, lows)
    ms = "bullish" if swings[-1]["type"] == "higher_high" else "bearish"
    liq = None
    avg_vol = np.mean(volumes[-40:]) if len(volumes) >= 40 else np.mean(volumes)
    if len(highs) >= 20 and highs[-1] >= max(highs[-20:-1]) and volumes[-1] > 2 * avg_vol:
        liq = "liquidity_sweep_high"
    elif len(lows) >= 20 and lows[-1] <= min(lows[-20:-1]) and volumes[-1] > 2 * avg_vol:
        liq = "liquidity_sweep_low"
    ob = smc.ob(highs, lows, closes)
    fvg = smc.fvg(highs, lows, closes, volumes)
    ipda = smc.previous_high_low(highs, lows, [20, 40, 60])
    price_range = max(highs[-6:]) - min(lows[-6:]) if len(highs) >= 6 else 0
    consolidation = price_range < 0.005 * closes[-1] if closes else False
    expansion = False
    if len(highs) >= 20 and len(lows) >= 20:
        expansion = (highs[-1] > max(highs[-20:-1]) or lows[-1] < min(lows[-20:-1])) and volumes[-1] > 2 * avg_vol
    retracement = False
    if len(highs) >= 20 and len(lows) >= 20 and len(closes) >= 1:
        mid = (max(highs[-20:-1]) + min(lows[-20:-1])) / 2
        retracement = abs(closes[-1] - mid) < 0.01 * closes[-1]
    ict_score = 0
    if ms == "bullish":
        ict_score += 0.3
    if liq:
        ict_score += 0.2
    if ob:
        ict_score += 0.1
    if fvg:
        ict_score += 0.1
    if expansion:
        ict_score += 0.2
    if retracement:
        ict_score += 0.1
    return ict_score, ms

# --- Fundamental Analysis (simplified, no external APIs) ---
def fundamental_analysis(asset: str, candles: list):
    # Skip external API calls, return neutral
    return 0, 0, 0

# --- Entry Systems (copied from app/entries.py) ---
def atr(highs, lows, closes, period=14):
    if len(highs) < 2:
        return 0
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(1, len(highs))]
    return np.mean(trs[-period:]) if len(trs) >= period else np.mean(trs)

def get_higher_timeframe_bias(asset: str, timeframe: str, candles: list):
    closes = [c["close"] for c in candles]
    return "bullish" if closes[-1] > closes[0] else "bearish"

def turtle_soup(candles: list):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
    liq = smc.liquidity(highs, lows, closes)
    ob = smc.ob(highs, lows, closes)
    entries = []
    if liq and volumes[-1] > 2 * avg_vol:
        direction = "long" if closes[-1] > closes[-2] else "short"
        breakout = highs[-1] if direction == "long" else lows[-1]
        stop_loss = breakout + 1.5 * atr_val if direction == "long" else breakout - 1.5 * atr_val
        invalidation = breakout
        tp = ob[-1]["price"] if ob else closes[-1] + 2 * atr_val
        entries.append({
            "system": "Turtle Soup",
            "entry_price": closes[-1],
            "stop_loss": stop_loss,
            "take_profit": tp,
            "invalidation_point": invalidation,
            "liquidity_zones": liq,
            "bias": direction
        })
    return entries

def crt(candles: list):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    sessions = smc.sessions(highs, lows, closes)
    price_range = max(highs[-6:]) - min(lows[-6:]) if len(highs) >= 6 else 0
    if price_range < 0.005 * closes[-1]:
        direction = "long" if closes[-1] > closes[-2] else "short"
        mid = (max(highs[-6:]) + min(lows[-6:])) / 2
        stop_loss = mid + 1.5 * atr_val if direction == "long" else mid - 1.5 * atr_val
        invalidation = mid
        liq = smc.liquidity(highs, lows, closes)
        tp = liq[-1]["price"] if liq else closes[-1] + 2 * atr_val
        return [{
            "system": "CRT",
            "entry_price": closes[-1],
            "stop_loss": stop_loss,
            "take_profit": tp,
            "invalidation_point": invalidation,
            "liquidity_zones": liq,
            "bias": direction
        }]
    return []

def market_maker_ipda(candles: list):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
    fvg = smc.fvg(highs, lows, closes, volumes)
    liq = smc.liquidity(highs, lows, closes)
    entries = []
    if fvg and volumes[-1] > 1.5 * avg_vol:
        zone = fvg[-1]["zone"] if "zone" in fvg[-1] else "premium"
        direction = "long" if zone == "discount" else "short"
        zone_boundary = highs[-1] if direction == "long" else lows[-1]
        stop_loss = zone_boundary + 1.5 * atr_val if direction == "long" else zone_boundary - 1.5 * atr_val
        invalidation = zone_boundary
        tp = liq[-1]["price"] if liq else closes[-1] + 2 * atr_val
        entries.append({
            "system": "Market Maker/IPDA",
            "entry_price": closes[-1],
            "stop_loss": stop_loss,
            "take_profit": tp,
            "invalidation_point": invalidation,
            "liquidity_zones": liq,
            "bias": direction
        })
    return entries

def select_strategy(candles: list, bias: str):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    atr_avg = atr_val  # simplified
    if atr_val > atr_avg:
        return [*turtle_soup(candles), *market_maker_ipda(candles)]
    else:
        return crt(candles)

# --- Signal Output ---
SIGNALS_FILE = CACHE_DIR / 'generated_signals.json'

def load_existing_signals():
    if SIGNALS_FILE.exists():
        with open(SIGNALS_FILE) as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_signals(signals):
    with open(SIGNALS_FILE, 'w') as f:
        json.dump(signals, f, indent=2)

async def generate_signals():
    logger.info(f'🎯 Generating signals at {datetime.now()}')
    all_signals = load_existing_signals()
    
    for asset_name in ASSETS.keys():
        for tf in TIMEFRAMES:
            data = get_cache(asset_name, tf)
            if data:
                candles = parse_alpha_data(asset_name, data, tf)
                if candles and len(candles) >= 40:
                    # Run ICT analysis
                    ict_score, ict_bias = ict_analysis(asset_name, tf, candles)
                    fund_score, coef, sentiment = fundamental_analysis(asset_name, candles)
                    total_score = 0.7 * ict_score + 0.3 * fund_score
                    bias = 'bullish' if total_score > 0.2 else 'bearish' if total_score < -0.2 else 'neutral'
                    
                    # Generate entries
                    higher_tf_bias = get_higher_timeframe_bias(asset_name, tf, candles)
                    entries = select_strategy(candles, higher_tf_bias)
                    
                    signal = {
                        "asset": asset_name,
                        "timeframe": tf,
                        "bias": bias,
                        "ict_score": ict_score,
                        "fund_score": fund_score,
                        "news_sentiment": sentiment,
                        "total_score": total_score,
                        "higher_tf_bias": higher_tf_bias,
                        "entries": entries,
                        "timestamp": datetime.now().isoformat()
                    }
                    
                    # Remove old signal for this asset/timeframe
                    all_signals = [s for s in all_signals if not (s.get('asset') == asset_name and s.get('timeframe') == tf)]
                    all_signals.append(signal)
                    
                    logger.info(f'✅ Signals generated for {asset_name} {tf}: bias={bias}, ict={ict_score:.2f}, fund={fund_score:.2f}, entries={len(entries)}')
                else:
                    logger.warning(f'⚠️ Not enough data for {asset_name} {tf}')
            else:
                logger.warning(f'⚠️ No cached data for {asset_name} {tf}')
    
    save_signals(all_signals)
    logger.info(f'🎯 Signal generation complete. Saved {len(all_signals)} signals to {SIGNALS_FILE}')

async def main():
    await generate_signals()

if __name__ == '__main__':
    asyncio.run(main())
import os
import asyncio
import logging
import json
import time
from datetime import datetime
from pathlib import Path
import numpy as np
import ta

os.environ['ALPHA_VANTAGE_API_KEY'] = '9GKCFT2904UPUA9Z'
os.environ['SUPABASE_URL'] = 'https://rzrbxahpanvmtuyfxfpy.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbG...mzjY'
os.environ['FRED_API_KEY'] = '48fee2567177e43a8e3979a830f786fd'
os.environ['NEWS_API_KEY'] = 'df5ada8244c941c79f50e5785a79c3d0'

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.cache'

ASSETS = {
    'XAUUSD': {'symbol': 'XAUUSD', 'market': 'FOREX'},
    'NASDAQ': {'symbol': 'NDX', 'market': 'INDEX'},
}

TIMEFRAMES = ['1d', '4h', '1h']
ALPHA_INTERVALS = {
    '1d': 'Daily',
    '4h': '60min',
    '1h': '60min',
}

CONFIDENCE_THRESHOLD = 0.65

def cache_key(asset: str, timeframe: str) -> str:
    return f'ohlc_{asset}_{timeframe}.json'

def get_cache(asset: str, timeframe: str):
    ck = cache_key(asset, timeframe)
    cache_file = CACHE_DIR / ck
    if cache_file.exists():
        with open(cache_file) as f:
            data = json.load(f)
            if time.time() - data.get('timestamp', 0) < 86400:
                return data.get('value')
    return None

def set_cache(asset: str, timeframe: str, value):
    ck = cache_key(asset, timeframe)
    cache_file = CACHE_DIR / ck
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump({'timestamp': time.time(), 'value': value}, f)

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
            key = 'Time Series (Daily)' if timeframe == '1d' else 'Time Series (60min)'
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

def atr(highs, lows, closes, period=14):
    if len(highs) < 2:
        return 0
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(1, len(highs))]
    return np.mean(trs[-period:]) if len(trs) >= period else np.mean(trs)

def swing_highs_lows(highs, lows, length=5):
    swings = []
    for i in range(length, len(highs) - length):
        is_high = all(highs[i] > highs[i-j] and highs[i] > highs[i+j] for j in range(1, length+1))
        is_low = all(lows[i] < lows[i-j] and lows[i] < lows[i+j] for j in range(1, length+1))
        if is_high:
            swings.append({'type': 'higher_high', 'price': highs[i], 'index': i})
        elif is_low:
            swings.append({'type': 'lower_low', 'price': lows[i], 'index': i})
    return swings

def market_structure(highs, lows, closes):
    swings = swing_highs_lows(highs, lows)
    if not swings:
        return 'neutral', 0
    
    hh_count = sum(1 for s in swings if s['type'] == 'higher_high')
    ll_count = sum(1 for s in swings if s['type'] == 'lower_low')
    
    if hh_count > ll_count:
        return 'bullish', min(0.8, 0.4 + 0.1 * (hh_count - ll_count))
    elif ll_count > hh_count:
        return 'bearish', min(0.8, 0.4 + 0.1 * (ll_count - hh_count))
    return 'neutral', 0.3

def liquidity(highs, lows, closes):
    liq = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            liq.append({'type': 'buy_side', 'price': highs[i], 'index': i})
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            liq.append({'type': 'sell_side', 'price': lows[i], 'index': i})
    return liq

def order_blocks(highs, lows, closes, opens):
    blocks = []
    for i in range(2, len(closes) - 1):
        body_size = abs(closes[i] - opens[i])
        avg_body = np.mean([abs(closes[j] - opens[j]) for j in range(max(0, i-10), i)])
        
        if closes[i] > opens[i] and closes[i+1] < opens[i+1] and body_size > avg_body:
            blocks.append({
                'type': 'bearish_ob', 
                'price': (highs[i] + lows[i]) / 2, 
                'top': highs[i],
                'bottom': lows[i],
                'index': i,
                'strength': min(1.0, body_size / avg_body) if avg_body > 0 else 0.5
            })
        elif closes[i] < opens[i] and closes[i+1] > opens[i+1] and body_size > avg_body:
            blocks.append({
                'type': 'bullish_ob', 
                'price': (highs[i] + lows[i]) / 2,
                'top': highs[i],
                'bottom': lows[i],
                'index': i,
                'strength': min(1.0, body_size / avg_body) if avg_body > 0 else 0.5
            })
    return blocks

def fair_value_gaps(highs, lows, closes, volumes):
    gaps = []
    for i in range(2, len(closes)):
        if lows[i] > highs[i-2]:
            gaps.append({
                'type': 'bullish_fvg', 
                'zone': 'discount', 
                'price_low': highs[i-2], 
                'price_high': lows[i], 
                'index': i,
                'size': lows[i] - highs[i-2]
            })
        elif highs[i] < lows[i-2]:
            gaps.append({
                'type': 'bearish_fvg', 
                'zone': 'premium', 
                'price_low': highs[i], 
                'price_high': lows[i-2], 
                'index': i,
                'size': lows[i-2] - highs[i]
            })
    return gaps

def liquidity_pools(highs, lows, closes, length=20):
    pools = []
    for i in range(length, len(highs) - 1):
        recent_high = max(highs[i-length:i])
        recent_low = min(lows[i-length:i])
        if highs[i] > recent_high and closes[i] < recent_high:
            pools.append({'type': 'buy_side_liquidity', 'price': recent_high, 'index': i})
        if lows[i] < recent_low and closes[i] > recent_low:
            pools.append({'type': 'sell_side_liquidity', 'price': recent_low, 'index': i})
    return pools

def breaker_blocks(highs, lows, closes, opens):
    breakers = []
    for i in range(3, len(closes) - 1):
        if closes[i-2] > opens[i-2] and closes[i-1] < opens[i-1] and closes[i] > opens[i]:
            if closes[i] > highs[i-2]:
                breakers.append({
                    'type': 'bullish_breaker',
                    'price': lows[i-1],
                    'index': i
                })
        elif closes[i-2] < opens[i-2] and closes[i-1] > opens[i-1] and closes[i] < opens[i]:
            if closes[i] < lows[i-2]:
                breakers.append({
                    'type': 'bearish_breaker',
                    'price': highs[i-1],
                    'index': i
                })
    return breakers

def ict_analysis(asset: str, timeframe: str, candles: list):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]
    opens = [c["open"] for c in candles]
    
    ms, ms_conf = market_structure(highs, lows, closes)
    
    liq = liquidity(highs, lows, closes)
    ob_blocks = order_blocks(highs, lows, closes, opens)
    fvg_gaps = fair_value_gaps(highs, lows, closes, volumes)
    liq_pools = liquidity_pools(highs, lows, closes)
    breakers = breaker_blocks(highs, lows, closes, opens)
    
    atr_val = atr(highs, lows, closes, 20)
    avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
    vol_spike = volumes[-1] > 1.5 * avg_vol if avg_vol > 0 else False
    
    ict_score = 0
    confidence = 0
    factors = []
    
    if ms == 'bullish':
        ict_score += 0.25
        confidence += ms_conf
        factors.append(f"Market Structure: Bullish ({ms_conf:.0%})")
    elif ms == 'bearish':
        ict_score -= 0.25
        confidence += ms_conf
        factors.append(f"Market Structure: Bearish ({ms_conf:.0%})")
    
    if liq:
        last_liq = liq[-1]
        if last_liq['type'] == 'buy_side' and ms == 'bullish':
            ict_score += 0.15
            confidence += 0.1
            factors.append("Buy-side Liquidity Sweep")
        elif last_liq['type'] == 'sell_side' and ms == 'bearish':
            ict_score -= 0.15
            confidence += 0.1
            factors.append("Sell-side Liquidity Sweep")
    
    if ob_blocks:
        last_ob = ob_blocks[-1]
        if last_ob['type'] == 'bullish_ob' and ms == 'bullish':
            ict_score += 0.2 * last_ob['strength']
            confidence += 0.15 * last_ob['strength']
            factors.append(f"Bullish Order Block (strength: {last_ob['strength']:.0%})")
        elif last_ob['type'] == 'bearish_ob' and ms == 'bearish':
            ict_score -= 0.2 * last_ob['strength']
            confidence += 0.15 * last_ob['strength']
            factors.append(f"Bearish Order Block (strength: {last_ob['strength']:.0%})")
    
    if fvg_gaps:
        last_fvg = fvg_gaps[-1]
        if last_fvg['type'] == 'bullish_fvg' and ms == 'bullish':
            ict_score += 0.15
            confidence += 0.1
            factors.append("Bullish FVG in Discount")
        elif last_fvg['type'] == 'bearish_fvg' and ms == 'bearish':
            ict_score -= 0.15
            confidence += 0.1
            factors.append("Bearish FVG in Premium")
    
    if liq_pools:
        last_pool = liq_pools[-1]
        if last_pool['type'] == 'buy_side_liquidity' and ms == 'bearish':
            ict_score += 0.1
            confidence += 0.05
            factors.append("Buy-side Liquidity Pool (Potential Reversal)")
        elif last_pool['type'] == 'sell_side_liquidity' and ms == 'bullish':
            ict_score -= 0.1
            confidence += 0.05
            factors.append("Sell-side Liquidity Pool (Potential Reversal)")
    
    if breakers:
        last_breaker = breakers[-1]
        if last_breaker['type'] == 'bullish_breaker' and ms == 'bullish':
            ict_score += 0.15
            confidence += 0.1
            factors.append("Bullish Breaker Block")
        elif last_breaker['type'] == 'bearish_breaker' and ms == 'bearish':
            ict_score -= 0.15
            confidence += 0.1
            factors.append("Bearish Breaker Block")
    
    if vol_spike:
        confidence += 0.1
        factors.append("Volume Spike")
    
    ict_score = max(-1, min(1, ict_score))
    confidence = min(1.0, confidence + 0.2)
    
    return ict_score, ms, confidence, factors

def fundamental_analysis(asset: str, candles: list):
    return 0, 0, 0

def get_higher_timeframe_bias(asset: str, timeframe: str):
    data = get_cache(asset, "1d")
    if data:
        candles = parse_alpha_data(asset, data, "1d")
        if candles:
            closes = [c["close"] for c in candles]
            return "bullish" if closes[-1] > closes[0] else "bearish"
    return "neutral"

def calculate_entry_exit(candles: list, bias: str, ict_score: float, confidence: float):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]
    opens = [c["open"] for c in candles]
    
    atr_val = atr(highs, lows, closes, 20)
    current_price = closes[-1]
    
    if bias == 'bullish' and ict_score > 0:
        direction = "long"
        entry = current_price
        stop_loss = current_price - 1.5 * atr_val
        take_profit = current_price + 3 * atr_val
        invalidation = current_price - atr_val
    elif bias == 'bearish' and ict_score < 0:
        direction = "short"
        entry = current_price
        stop_loss = current_price + 1.5 * atr_val
        take_profit = current_price - 3 * atr_val
        invalidation = current_price + atr_val
    else:
        return None
    
    rr_ratio = abs(take_profit - entry) / abs(entry - stop_loss) if abs(entry - stop_loss) > 0 else 0
    
    return {
        "direction": direction,
        "entry_price": round(entry, 5),
        "stop_loss": round(stop_loss, 5),
        "take_profit": round(take_profit, 5),
        "invalidation_point": round(invalidation, 5),
        "risk_reward": round(rr_ratio, 2),
        "atr": round(atr_val, 5)
    }

async def generate_signals():
    logger.info(f'🎯 Generating ICT signals at {datetime.now()}')
    
    signals_output = []
    high_confidence_signals = []
    
    for asset_name in ASSETS.keys():
        for tf in TIMEFRAMES:
            data = get_cache(asset_name, tf)
            if data:
                raw_data = data
                candles = parse_alpha_data(asset_name, raw_data, tf)
                if candles and len(candles) >= 50:
                    ict_score, ict_bias, confidence, factors = ict_analysis(asset_name, tf, candles)
                    fund_score, coef, sentiment = fundamental_analysis(asset_name, candles)
                    total_score = 0.7 * ict_score + 0.3 * fund_score
                    bias = 'bullish' if total_score > 0.15 else 'bearish' if total_score < -0.15 else 'neutral'
                    
                    higher_tf_bias = get_higher_timeframe_bias(asset_name, tf)
                    entry_exit = calculate_entry_exit(candles, bias, ict_score, confidence)
                    
                    signal_data = {
                        'asset': asset_name,
                        'timeframe': tf,
                        'bias': bias,
                        'ict_score': round(ict_score, 2),
                        'fund_score': round(fund_score, 2),
                        'news_sentiment': sentiment,
                        'total_score': round(total_score, 2),
                        'confidence': round(confidence, 2),
                        'confidence_pct': f"{confidence*100:.0f}%",
                        'higher_tf_bias': higher_tf_bias,
                        'ict_factors': factors,
                        'entry_exit': entry_exit,
                        'timestamp': datetime.now().isoformat()
                    }
                    signals_output.append(signal_data)
                    
                    if confidence >= CONFIDENCE_THRESHOLD and entry_exit:
                        high_confidence_signals.append(signal_data)
                        logger.info(f'🔥 HIGH CONFIDENCE: {asset_name} {tf} - {bias.upper()} ({confidence*100:.0f}%) - {entry_exit["direction"].upper()}')
                    else:
                        logger.info(f'✅ Signals for {asset_name} {tf}: bias={bias}, ict={ict_score:.2f}, conf={confidence:.2f}, entries={1 if entry_exit else 0}')
                else:
                    logger.warning(f'⚠️ Not enough data for {asset_name} {tf}')
    
    signals_file = CACHE_DIR / 'generated_signals.json'
    with open(signals_file, 'w') as f:
        json.dump(signals_output, f, indent=2)
    logger.info(f'📁 Signals saved to {signals_file}')
    
    high_conf_file = CACHE_DIR / 'high_confidence_signals.json'
    with open(high_conf_file, 'w') as f:
        json.dump(high_confidence_signals, f, indent=2)
    logger.info(f'🔥 High confidence signals: {len(high_confidence_signals)}')
    
    return signals_output, high_confidence_signals

def format_telegram_message(signals, high_conf_signals):
    if not signals:
        return "No signals generated."
    
    msg = "📊 <b>ICT Trading Signals</b>\n"
    msg += f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    if high_conf_signals:
        msg += "🔥 <b>HIGH CONFIDENCE ALERTS</b>\n"
        for s in high_conf_signals:
            ee = s['entry_exit']
            msg += f"\n<b>{s['asset']} {s['timeframe']}</b> - {s['bias'].upper()} ({s['confidence_pct']})\n"
            msg += f"  📈 {ee['direction'].upper()} @ {ee['entry_price']}\n"
            msg += f"  🛑 SL: {ee['stop_loss']} | 🎯 TP: {ee['take_profit']}\n"
            msg += f"  ⚖️ R:R = 1:{ee['risk_reward']}\n"
            msg += f"  📋 Factors: {', '.join(s['ict_factors'])}\n"
    
    msg += "\n📋 <b>All Signals</b>\n"
    for s in signals:
        emoji = "🟢" if s['bias'] == 'bullish' else "🔴" if s['bias'] == 'bearish' else "⚪"
        conf_emoji = "🔥" if s['confidence'] >= CONFIDENCE_THRESHOLD else "📊"
        msg += f"{emoji} {conf_emoji} <b>{s['asset']} {s['timeframe']}</b>: {s['bias'].upper()} (ICT: {s['ict_score']}, Conf: {s['confidence_pct']})\n"
        if s['entry_exit']:
            ee = s['entry_exit']
            msg += f"    {ee['direction'].upper()} @ {ee['entry_price']} | SL: {ee['stop_loss']} | TP: {ee['take_profit']} | R:R 1:{ee['risk_reward']}\n"
    
    return msg

async def main():
    signals, high_conf = await generate_signals()
    
    # Always send to local file
    signals_file = CACHE_DIR / 'generated_signals.json'
    with open(signals_file, 'w') as f:
        json.dump(signals, f, indent=2)
    
    # Print formatted message for Telegram delivery
    msg = format_telegram_message(signals, high_conf)
    print(msg)
    
    # Also output just high confidence for conditional delivery
    if high_conf:
        print("\n---HIGH_CONFIDENCE---")
        print(json.dumps(high_conf, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
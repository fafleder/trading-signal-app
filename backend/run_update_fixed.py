import os
os.environ['SUPABASE_URL'] = 'https://rzrbxahpanvmtuyfxfpy.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbG...mzjY'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'eyJhbG...GQ2g'
os.environ['FRED_API_KEY'] = '48fee2567177e43a8e3979a830f786fd'
os.environ['NEWS_API_KEY'] = 'df5ada8244c941c79f50e5785a79c3d0'

import asyncio
import logging
import json
import time
from datetime import datetime
from pathlib import Path
import yfinance as yf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True)

ASSETS = {
    'XAUUSD': {'symbol': 'GC=F', 'market': 'FOREX'},
    'NASDAQ': {'symbol': '^NDX', 'market': 'INDEX'},
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

def set_cache(asset: str, timeframe: str, value):
    ck = cache_key(asset, timeframe)
    cache_file = CACHE_DIR / ck
    with open(cache_file, 'w') as f:
        json.dump({'value': value, 'timestamp': time.time()}, f)

def parse_alpha_data(asset: str, data: dict, timeframe: str):
    try:
        # Handle yfinance format for XAUUSD (gold)
        if asset == 'XAUUSD' and 'data' in data:
            # Format: {'data': [{'date': '2026-06-24', 'price': 4008.8}, ...]}
            candles = []
            for item in data['data']:
                # For gold, we only have close price, so use it for open/high/low/close
                price = float(item['price'])
                candles.append({
                    'timestamp': item['date'],
                    'open': price,
                    'high': price,
                    'low': price,
                    'close': price,
                    'volume': 0
                })
            return candles
        
        # Handle yfinance format for NASDAQ
        if asset == 'NASDAQ' and 'Time Series (Daily)' in data:
            key = 'Time Series (Daily)'
        elif asset == 'XAUUSD':
            key = f'Time Series FX ({timeframe})'
        else:
            key = f'Time Series ({timeframe})'
        
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

def fetch_yfinance(asset: str, timeframe: str):
    symbol = ASSETS[asset]['symbol']
    try:
        df = yf.download(symbol, period='3mo', interval='1d', progress=False, auto_adjust=False)
        if df.empty:
            logger.warning(f'No data from yfinance for {symbol}')
            return {}
        
        # Handle MultiIndex columns
        if hasattr(df.columns, 'nlevels') and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        
        # Reset index to get date as column
        df = df.reset_index()
        
        # Convert to Alpha Vantage-like format for compatibility
        if asset == 'XAUUSD':
            # For gold, we'll create a format similar to GOLD_SILVER_HISTORY
            data_array = []
            for _, row in df.iterrows():
                data_array.append({
                    'date': row['Date'].strftime('%Y-%m-%d') if hasattr(row['Date'], 'strftime') else str(row['Date']),
                    'price': float(row['Close'])
                })
            return {'data': data_array}
        else:
            # For NASDAQ, format like TIME_SERIES_DAILY
            timeseries = {}
            for _, row in df.iterrows():
                date_str = row['Date'].strftime('%Y-%m-%d') if hasattr(row['Date'], 'strftime') else str(row['Date'])
                timeseries[date_str] = {
                    '1. open': str(float(row['Open'])),
                    '2. high': str(float(row['High'])),
                    '3. low': str(float(row['Low'])),
                    '4. close': str(float(row['Close'])),
                    '5. volume': str(int(row['Volume'])) if row['Volume'] > 0 else '0'
                }
            return {'Time Series (Daily)': timeseries}
    except Exception as e:
        logger.error(f'yfinance fetch error for {asset} {timeframe}: {e}')
        return {}

async def update_market_data():
    logger.info(f'📊 Updating market data at {datetime.now()}')
    
    for asset_name, asset_info in ASSETS.items():
        for tf in TIMEFRAMES:
            data = fetch_yfinance(asset_name, tf)
            if data and 'Information' not in data:
                set_cache(asset_name, tf, data)
                logger.info(f'✅ Cached {asset_name} {tf}')
            else:
                logger.warning(f'⚠️ No data or rate limited: {asset_name} {tf}')
    
    logger.info('📊 Market data update complete')

async def generate_signals():
    logger.info(f'🎯 Generating signals at {datetime.now()}')
    
    # Local signal analysis functions (avoid Supabase dependency)
    import numpy as np
    import ta
    
    def atr(highs, lows, closes, period=14):
        if len(highs) < 2:
            return 0
        trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(1, len(highs))]
        return np.mean(trs[-period:]) if len(trs) >= period else np.mean(trs)
    
    def swing_highs_lows(highs, lows):
        swings = []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swings.append({'type': 'higher_high', 'price': highs[i], 'index': i})
            elif lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swings.append({'type': 'lower_low', 'price': lows[i], 'index': i})
        return swings
    
    def liquidity(highs, lows, closes):
        liq = []
        for i in range(1, len(highs) - 1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                liq.append({'type': 'buy_side', 'price': highs[i], 'index': i})
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                liq.append({'type': 'sell_side', 'price': lows[i], 'index': i})
        return liq
    
    def ob(highs, lows, closes):
        blocks = []
        for i in range(2, len(closes) - 1):
            if closes[i] > closes[i-1] and closes[i+1] < closes[i]:
                blocks.append({'type': 'bearish_ob', 'price': (highs[i] + lows[i]) / 2, 'index': i})
            elif closes[i] < closes[i-1] and closes[i+1] > closes[i]:
                blocks.append({'type': 'bullish_ob', 'price': (highs[i] + lows[i]) / 2, 'index': i})
        return blocks
    
    def fvg(highs, lows, closes, volumes):
        gaps = []
        for i in range(2, len(closes)):
            if lows[i] > highs[i-2]:
                gaps.append({'type': 'bullish_fvg', 'zone': 'discount', 'price_low': highs[i-2], 'price_high': lows[i], 'index': i})
            elif highs[i] < lows[i-2]:
                gaps.append({'type': 'bearish_fvg', 'zone': 'premium', 'price_low': highs[i], 'price_high': lows[i-2], 'index': i})
        return gaps
    
    def sessions(highs, lows, closes):
        return []
    
    def previous_high_low(highs, lows, lookbacks):
        result = {}
        for lb in lookbacks:
            if len(highs) >= lb:
                result[f'prev_high_{lb}'] = max(highs[-lb:])
                result[f'prev_low_{lb}'] = min(lows[-lb:])
        return result
    
    def ict_analysis(asset: str, timeframe: str, candles: list):
        closes = [c['close'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        volumes = [c['volume'] for c in candles]
        opens = [c['open'] for c in candles]
        
        swings = swing_highs_lows(highs, lows)
        ms = 'bullish' if swings and swings[-1]['type'] == 'higher_high' else 'bearish'
        
        liq = None
        avg_vol = np.mean(volumes[-40:]) if len(volumes) >= 40 else np.mean(volumes)
        if len(highs) >= 20 and highs[-1] >= max(highs[-20:-1]) and volumes[-1] > 2 * avg_vol:
            liq = 'liquidity_sweep_high'
        elif len(lows) >= 20 and lows[-1] <= min(lows[-20:-1]) and volumes[-1] > 2 * avg_vol:
            liq = 'liquidity_sweep_low'
        
        ob_blocks = ob(highs, lows, closes)
        fvg_gaps = fvg(highs, lows, closes, volumes)
        ipda = previous_high_low(highs, lows, [20, 40, 60])
        
        price_range = max(highs[-6:]) - min(lows[-6:]) if len(highs) >= 6 else 0
        consolidation = price_range < 0.005 * closes[-1] if closes[-1] != 0 else False
        expansion = (highs[-1] > max(highs[-20:-1]) or lows[-1] < min(lows[-20:-1])) and volumes[-1] > 2 * avg_vol if len(highs) >= 20 else False
        retracement = abs(closes[-1] - (max(highs[-20:-1]) + min(lows[-20:-1])) / 2) < 0.01 * closes[-1] if len(highs) >= 20 and closes[-1] != 0 else False
        
        ict_score = 0
        if ms == 'bullish':
            ict_score += 0.3
        if liq:
            ict_score += 0.2
        if ob_blocks:
            ict_score += 0.1
        if fvg_gaps:
            ict_score += 0.1
        if expansion:
            ict_score += 0.2
        if retracement:
            ict_score += 0.1
        
        return ict_score, ms
    
    def fundamental_analysis(asset: str, candles: list):
        return 0, 0, 0
    
    def get_higher_timeframe_bias(asset: str, timeframe: str):
        data = get_cache(asset, '1d')
        if data:
            candles = parse_alpha_data(asset, data, '1d')
            if candles:
                closes = [c['close'] for c in candles]
                return 'bullish' if closes[-1] > closes[0] else 'bearish'
        return 'neutral'
    
    def turtle_soup(candles: list):
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        closes = [c['close'] for c in candles]
        volumes = [c['volume'] for c in candles]
        opens = [c['open'] for c in candles]
        
        atr_val = atr(highs, lows, closes, 20)
        avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
        liq = liquidity(highs, lows, closes)
        ob_blocks = ob(highs, lows, closes)
        entries = []
        
        if liq and volumes[-1] > 2 * avg_vol:
            direction = 'long' if closes[-1] > closes[-2] else 'short'
            breakout = highs[-1] if direction == 'long' else lows[-1]
            stop_loss = breakout + 1.5 * atr_val if direction == 'long' else breakout - 1.5 * atr_val
            invalidation = breakout
            tp = ob_blocks[-1]['price'] if ob_blocks else closes[-1] + 2 * atr_val
            entries.append({
                'system': 'Turtle Soup',
                'entry_price': closes[-1],
                'stop_loss': stop_loss,
                'take_profit': tp,
                'invalidation_point': invalidation,
                'liquidity_zones': str(liq),
                'bias': direction
            })
        return entries
    
    def crt(candles: list):
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        closes = [c['close'] for c in candles]
        atr_val = atr(highs, lows, closes, 20)
        sessions_data = sessions(highs, lows, closes)
        price_range = max(highs[-6:]) - min(lows[-6:]) if len(highs) >= 6 else 0
        
        if price_range < 0.005 * closes[-1] and closes[-1] != 0:
            direction = 'long' if closes[-1] > closes[-2] else 'short'
            stop_loss = (max(highs[-6:]) + min(lows[-6:])) / 2 + 1.5 * atr_val
            invalidation = (max(highs[-6:]) + min(lows[-6:])) / 2
            liq = liquidity(highs, lows, closes)
            tp = liq[-1]['price'] if liq else closes[-1] + 2 * atr_val
            return [{
                'system': 'CRT',
                'entry_price': closes[-1],
                'stop_loss': stop_loss,
                'take_profit': tp,
                'invalidation_point': invalidation,
                'liquidity_zones': str(liq),
                'bias': direction
            }]
        return []
    
    def market_maker_ipda(candles: list):
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        closes = [c['close'] for c in candles]
        volumes = [c['volume'] for c in candles]
        opens = [c['open'] for c in candles]
        
        atr_val = atr(highs, lows, closes, 20)
        avg_vol = np.mean(volumes[-20:]) if len(volumes) >= 20 else np.mean(volumes)
        fvg_gaps = fvg(highs, lows, closes, volumes)
        liq = liquidity(highs, lows, closes)
        entries = []
        
        if fvg_gaps and volumes[-1] > 1.5 * avg_vol:
            zone = fvg_gaps[-1]['zone'] if 'zone' in fvg_gaps[-1] else 'premium'
            direction = 'long' if zone == 'discount' else 'short'
            zone_boundary = highs[-1] if direction == 'long' else lows[-1]
            stop_loss = zone_boundary + 1.5 * atr_val if direction == 'long' else zone_boundary - 1.5 * atr_val
            invalidation = zone_boundary
            tp = liq[-1]['price'] if liq else closes[-1] + 2 * atr_val
            entries.append({
                'system': 'Market Maker/IPDA',
                'entry_price': closes[-1],
                'stop_loss': stop_loss,
                'take_profit': tp,
                'invalidation_point': invalidation,
                'liquidity_zones': str(liq),
                'bias': direction
            })
        return entries
    
    def select_strategy(candles: list, bias: str):
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        closes = [c['close'] for c in candles]
        atr_val = atr(highs, lows, closes, 20)
        atr_avg = np.mean([atr(highs, lows, closes, 20) for _ in range(5)])
        
        if atr_val > atr_avg:
            return [*turtle_soup(candles), *market_maker_ipda(candles)]
        else:
            return crt(candles)
    
    signals_output = []
    
    for asset_name in ASSETS.keys():
        for tf in TIMEFRAMES:
            data = get_cache(asset_name, tf)
            if data:
                raw_data = data
                candles = parse_alpha_data(asset_name, raw_data, tf)
                if candles and len(candles) >= 40:
                    ict_score, ict_bias = ict_analysis(asset_name, tf, candles)
                    fund_score, coef, sentiment = fundamental_analysis(asset_name, candles)
                    total_score = 0.7 * ict_score + 0.3 * fund_score
                    bias = 'bullish' if total_score > 0.2 else 'bearish' if total_score < -0.2 else 'neutral'
                    
                    higher_tf_bias = get_higher_timeframe_bias(asset_name, tf)
                    entries = select_strategy(candles, higher_tf_bias)
                    
                    signal_data = {
                        'asset': asset_name,
                        'timeframe': tf,
                        'bias': bias,
                        'ict_score': round(ict_score, 2),
                        'fund_score': round(fund_score, 2),
                        'news_sentiment': sentiment,
                        'total_score': round(total_score, 2),
                        'higher_tf_bias': higher_tf_bias,
                        'entries': entries,
                        'timestamp': datetime.now().isoformat()
                    }
                    signals_output.append(signal_data)
                    
                    logger.info(f'✅ Signals generated for {asset_name} {tf}: bias={bias}, ict={ict_score:.2f}, fund={fund_score:.2f}, entries={len(entries)}')
                else:
                    logger.warning(f'⚠️ Not enough data for {asset_name} {tf}')
    
    # Save signals to local file
    signals_file = CACHE_DIR / 'generated_signals.json'
    with open(signals_file, 'w') as f:
        json.dump(signals_output, f, indent=2)
    logger.info(f'📁 Signals saved to {signals_file}')
    
    logger.info('🎯 Signal generation complete')

async def main():
    await update_market_data()
    await generate_signals()

asyncio.run(main())
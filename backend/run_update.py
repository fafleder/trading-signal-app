import os
os.environ['ALPHA_VANTAGE_API_KEY'] = '9GKCFT2904UPUA9Z'
os.environ['SUPABASE_URL'] = 'https://rzrbxahpanvmtuyfxfpy.supabase.co'
os.environ['SUPABASE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ6cmJ4YWhwYW52bXR1eWZ4ZnB5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDU2NTQwNzMsImV4cCI6MjA2MTIzMDA3M30.uL2vdpqpg_U_NjqkL5k3PkYzU8wGfN4-GrXEMtNmzjY'
os.environ['SUPABASE_SERVICE_ROLE_KEY'] = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJ6cmJ4YWhwYW52bXR1eWZ4ZnB5Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTY1NDA3MywiZXhwIjoyMDYxMjMwMDczfQ.gZqx3V8uG0R3_9JcWbE8v3D9xzj6vKzPVnJ4fWnGQ2g'
os.environ['REDIS_URL'] = 'redis://localhost:6379/0'
os.environ['FRED_API_KEY'] = '48fee2567177e43a8e3979a830f786fd'
os.environ['NEWS_API_KEY'] = 'df5ada8244c941c79f50e5785a79c3d0'

import asyncio
import logging
import redis
import requests
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)
ALPHA_VANTAGE_API_KEY = os.getenv('ALPHA_VANTAGE_API_KEY')

ASSETS = {
    'XAUUSD': {'symbol': 'XAUUSD', 'market': 'FOREX'},
    'NASDAQ': {'symbol': 'NDX', 'market': 'INDEX'},
}

TIMEFRAMES = ['5min', '15min', '60min', '240min', '1d']
ALPHA_INTERVALS = {
    '5min': '5min',
    '15min': '15min',
    '60min': '60min',
    '240min': '60min',
    '1d': 'Daily',
}

def fetch_alpha_vantage(asset: str, timeframe: str):
    if asset == 'XAUUSD':
        function = 'FX_INTRADAY'
        from_symbol = 'XAU'
        to_symbol = 'USD'
        interval = ALPHA_INTERVALS[timeframe]
        url = f'https://www.alphavantage.co/query?function={function}&from_symbol={from_symbol}&to_symbol={to_symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}'
    elif asset == 'NASDAQ':
        function = 'TIME_SERIES_INTRADAY'
        symbol = 'NDX'
        interval = ALPHA_INTERVALS[timeframe]
        url = f'https://www.alphavantage.co/query?function={function}&symbol={symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}'
    else:
        return {}

    try:
        response = requests.get(url, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f'Alpha Vantage fetch error for {asset} {timeframe}: {e}')
        return {}

def cache_key(asset: str, timeframe: str) -> str:
    return f'ohlc:{asset}:{timeframe}'

def rate_limit_key(asset: str, timeframe: str) -> str:
    return f'rate_limit:{asset}:{timeframe}'

async def update_market_data():
    logger.info(f'📊 Updating market data at {datetime.now()}')
    
    for asset_name, asset_info in ASSETS.items():
        for tf in TIMEFRAMES:
            rl_key = rate_limit_key(asset_name, tf)
            if redis_client.get(rl_key):
                logger.debug(f'Rate limited: {asset_name} {tf}')
                continue
            
            data = fetch_alpha_vantage(asset_name, tf)
            if data and 'Note' not in data:
                ck = cache_key(asset_name, tf)
                redis_client.setex(ck, 300, str(data))
                redis_client.setex(rl_key, 12, '1')
                logger.info(f'✅ Cached {asset_name} {tf}')
            else:
                logger.warning(f'⚠️ No data or rate limited: {asset_name} {tf}')
    
    logger.info('📊 Market data update complete')

async def generate_signals():
    logger.info(f'🎯 Generating signals at {datetime.now()}')
    
    from app.analysis import ict_analysis, fundamental_analysis
    from app.entries import get_higher_timeframe_bias, select_strategy
    from app.risk import position_size, risk_management
    from app.smart_money_concepts import smc
    import numpy as np
    import ta
    from supabase import create_client
    
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    def fetch_market_data_from_cache(asset: str, timeframe: str):
        ck = cache_key(asset, timeframe)
        data = redis_client.get(ck)
        if data:
            import ast
            return ast.literal_eval(data)
        return None
    
    def parse_alpha_data(asset: str, data: dict, timeframe: str):
        try:
            if asset == 'XAUUSD':
                key = f'Time Series FX ({ALPHA_INTERVALS[timeframe]})'
            else:
                key = f'Time Series ({ALPHA_INTERVALS[timeframe]})'
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
    
    for asset_name in ASSETS.keys():
        for tf in TIMEFRAMES:
            ck = cache_key(asset_name, tf)
            data = redis_client.get(ck)
            if data:
                import ast
                raw_data = ast.literal_eval(data)
                candles = parse_alpha_data(asset_name, raw_data, tf)
                if candles and len(candles) >= 40:
                    # Run ICT analysis
                    ict_score, ict_bias = ict_analysis(asset_name, tf, candles)
                    fund_score, coef, sentiment = fundamental_analysis(asset_name, candles)
                    total_score = 0.7 * ict_score + 0.3 * fund_score
                    bias = 'bullish' if total_score > 0.2 else 'bearish' if total_score < -0.2 else 'neutral'
                    
                    # Store signal
                    supabase.table('trade_signals').insert({
                        'asset': asset_name,
                        'timeframe': tf,
                        'bias': bias,
                        'ict_score': ict_score,
                        'fund_score': fund_score,
                        'news_sentiment': sentiment
                    }).execute()
                    
                    # Generate entries
                    higher_tf_bias = get_higher_timeframe_bias(asset_name, tf)
                    entries = select_strategy(candles, higher_tf_bias)
                    for entry in entries:
                        supabase.table('trade_signals').insert({
                            'asset': asset_name,
                            'timeframe': tf,
                            'bias': entry['bias'],
                            'liquidity_zones': str(entry['liquidity_zones']),
                            'entry_price': entry['entry_price'],
                            'stop_loss': entry['stop_loss'],
                            'take_profit': entry['take_profit'],
                            'invalidation_point': entry['invalidation_point'],
                            'system': entry['system']
                        }).execute()
                    
                    logger.info(f'✅ Signals generated for {asset_name} {tf}: bias={bias}, ict={ict_score:.2f}, fund={fund_score:.2f}, entries={len(entries)}')
                else:
                    logger.warning(f'⚠️ Not enough data for {asset_name} {tf}')
    
    logger.info('🎯 Signal generation complete')

async def main():
    await update_market_data()
    await generate_signals()

asyncio.run(main())
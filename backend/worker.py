"""
Background worker for Trading Signal App
Handles scheduled analysis, market data fetching, and signal generation
"""

import os
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any
import redis

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Redis connection
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.Redis.from_url(redis_url, decode_responses=True)

# Alpha Vantage API
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
import requests

ASSETS = {
    "XAUUSD": {"symbol": "XAUUSD", "market": "FOREX"},
    "NASDAQ": {"symbol": "NDX", "market": "INDEX"},
}

TIMEFRAMES = ["5min", "15min", "60min", "240min", "1d"]
ALPHA_INTERVALS = {
    "5min": "5min",
    "15min": "15min",
    "60min": "60min",
    "240min": "60min",
    "1d": "Daily",
}

def fetch_alpha_vantage(asset: str, timeframe: str) -> Dict[str, Any]:
    """Fetch data from Alpha Vantage API"""
    if asset == "XAUUSD":
        function = "FX_INTRADAY"
        from_symbol = "XAU"
        to_symbol = "USD"
        interval = ALPHA_INTERVALS[timeframe]
        url = f"https://www.alphavantage.co/query?function={function}&from_symbol={from_symbol}&to_symbol={to_symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}"
    elif asset == "NASDAQ":
        function = "TIME_SERIES_INTRADAY"
        symbol = "NDX"
        interval = ALPHA_INTERVALS[timeframe]
        url = f"https://www.alphavantage.co/query?function={function}&symbol={symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}"
    else:
        return {}

    try:
        response = requests.get(url, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Alpha Vantage fetch error for {asset} {timeframe}: {e}")
        return {}

def cache_key(asset: str, timeframe: str) -> str:
    return f"ohlc:{asset}:{timeframe}"

def rate_limit_key(asset: str, timeframe: str) -> str:
    return f"rate_limit:{asset}:{timeframe}"

async def update_market_data():
    """Fetch and cache latest market data for all assets/timeframes"""
    logger.info(f"📊 Updating market data at {datetime.now()}")
    
    for asset_name, asset_info in ASSETS.items():
        for tf in TIMEFRAMES:
            # Check rate limit
            rl_key = rate_limit_key(asset_name, tf)
            if redis_client.get(rl_key):
                logger.debug(f"Rate limited: {asset_name} {tf}")
                continue
            
            data = fetch_alpha_vantage(asset_name, tf)
            if data and "Note" not in data:
                # Cache the data
                ck = cache_key(asset_name, tf)
                redis_client.setex(ck, 300, str(data))  # 5 min cache
                
                # Set rate limit (Alpha Vantage: 5 req/min, 500/day)
                redis_client.setex(rl_key, 12, "1")  # 12 second rate limit
                
                logger.info(f"✅ Cached {asset_name} {tf}")
            else:
                logger.warning(f"⚠️ No data or rate limited: {asset_name} {tf}")
    
    logger.info("📊 Market data update complete")

async def generate_signals():
    """Generate trading signals from cached data"""
    logger.info(f"🎯 Generating signals at {datetime.now()}")
    
    # This would import and use your analysis modules
    # from app.analysis import analyze_market
    # from app.entries import find_entries
    # from app.risk import calculate_risk
    
    # For now, just log that we would generate signals
    for asset_name in ASSETS.keys():
        for tf in TIMEFRAMES:
            ck = cache_key(asset_name, tf)
            data = redis_client.get(ck)
            if data:
                # Process data to generate signals
                logger.info(f"Signal check: {asset_name} {tf}")
    
    logger.info("🎯 Signal generation complete")

async def cleanup_old_cache():
    """Remove stale cache entries"""
    logger.info("🧹 Cleaning old cache...")
    # Redis auto-expires, but we can do additional cleanup
    logger.info("🧹 Cache cleanup complete")

async def main_loop():
    """Main worker loop"""
    logger.info("🚀 Trading Signal Worker started")
    
    # Initial data fetch
    await update_market_data()
    await generate_signals()
    
    # Schedule tasks
    last_data_update = 0
    last_signal_gen = 0
    last_cleanup = 0
    
    while True:
        try:
            now = datetime.now().timestamp()
            
            # Update market data every 5 minutes
            if now - last_data_update >= 300:
                await update_market_data()
                last_data_update = now
            
            # Generate signals every 15 minutes
            if now - last_signal_gen >= 900:
                await generate_signals()
                last_signal_gen = now
            
            # Cleanup daily
            if now - last_cleanup >= 86400:
                await cleanup_old_cache()
                last_cleanup = now
            
            await asyncio.sleep(30)  # Check every 30 seconds
            
        except Exception as e:
            logger.error(f"Worker error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("🛑 Worker stopped")
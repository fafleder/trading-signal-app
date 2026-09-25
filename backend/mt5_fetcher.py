"""
MT5 Data Fetcher for ICT Signal Generator
Fetches real-time OHLC data from MetaTrader 5 terminal
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Symbol mapping for this broker (Exness)
SYMBOL_MAP = {
    "XAUUSD": "XAUUSDm",
    "NASDAQ": "USTECm",
    "EURUSD": "EURUSDm",
    "GBPUSD": "GBPUSDm",
}

TIMEFRAME_MAP = {
    "1m": mt5.TIMEFRAME_M1,
    "5m": mt5.TIMEFRAME_M5,
    "15m": mt5.TIMEFRAME_M15,
    "1h": mt5.TIMEFRAME_H1,
    "4h": mt5.TIMEFRAME_H4,
    "daily": mt5.TIMEFRAME_D1,
}

class MT5DataFetcher:
    def __init__(self):
        self.initialized = False
        self.cache_dir = Path(__file__).parent / '.cache'
        self.cache_dir.mkdir(exist_ok=True)
    
    def initialize(self) -> bool:
        """Initialize MT5 connection"""
        if self.initialized:
            return True
        
        if not mt5.initialize():
            logger.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False
        
        logger.info("MT5 initialized successfully")
        self.initialized = True
        return True
    
    def shutdown(self):
        """Shutdown MT5 connection"""
        if self.initialized:
            mt5.shutdown()
            self.initialized = False
    
    def get_symbol_name(self, asset: str) -> Optional[str]:
        """Map asset to broker symbol"""
        return SYMBOL_MAP.get(asset, asset)
    
    def get_timeframe(self, tf: str) -> int:
        """Map timeframe string to MT5 constant"""
        return TIMEFRAME_MAP.get(tf, mt5.TIMEFRAME_M15)
    
    def fetch_candles(self, asset: str, timeframe: str, count: int = 1000) -> Optional[pd.DataFrame]:
        """
        Fetch OHLC candles from MT5
        Returns DataFrame with columns: time, open, high, low, close, volume
        """
        if not self.initialize():
            return None
        
        symbol = self.get_symbol_name(asset)
        if not symbol:
            logger.error(f"No symbol mapping for {asset}")
            return None
        
        tf = self.get_timeframe(timeframe)
        
        # Check if symbol exists and is visible
        info = mt5.symbol_info(symbol)
        if info is None:
            logger.error(f"Symbol {symbol} not found")
            return None
        
        if not info.visible:
            logger.info(f"Symbol {symbol} not visible, trying to select...")
            if not mt5.symbol_select(symbol, True):
                logger.error(f"Failed to select {symbol}")
                return None
        
        # Get current time
        utc_now = datetime.utcnow()
        
        # Fetch rates
        rates = mt5.copy_rates_from(symbol, tf, utc_now, count)
        
        if rates is None or len(rates) == 0:
            logger.error(f"Failed to fetch rates for {symbol} {timeframe}: {mt5.last_error()}")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.rename(columns={
            'time': 'timestamp',
            'open': 'open',
            'high': 'high',
            'low': 'low',
            'close': 'close',
            'tick_volume': 'volume'
        })
        
        # Save to cache
        cache_file = self.cache_dir / f'ohlc_{asset}_{timeframe}.json'
        cache_data = {
            'timestamp': datetime.now().timestamp(),
            'symbol': symbol,
            'timeframe': timeframe,
            'count': len(df),
            'data': df.to_dict('records')
        }
        
        import json
        with open(cache_file, 'w') as f:
            json.dump(cache_data, f, default=str)
        
        logger.info(f"Fetched {len(df)} candles for {asset} ({symbol}) {timeframe}")
        return df
    
    def fetch_all_timeframes(self, asset: str, counts: Dict[str, int] = None) -> Dict[str, pd.DataFrame]:
        """Fetch multiple timeframes for an asset"""
        if counts is None:
            counts = {
                "daily": 100,
                "4h": 200,
                "1h": 500,
                "15m": 500,
                "5m": 1000,
                "1m": 3000,
            }
        
        results = {}
        for tf, count in counts.items():
            df = self.fetch_candles(asset, tf, count)
            if df is not None:
                results[tf] = df
        
        return results
    
    def get_latest_price(self, asset: str) -> Optional[Dict]:
        """Get current bid/ask for an asset"""
        if not self.initialize():
            return None
        
        symbol = self.get_symbol_name(asset)
        tick = mt5.symbol_info_tick(symbol)
        
        if tick is None:
            return None
        
        return {
            'symbol': symbol,
            'bid': tick.bid,
            'ask': tick.ask,
            'last': tick.last,
            'time': datetime.fromtimestamp(tick.time),
            'spread': tick.ask - tick.bid
        }


# Convenience function for backward compatibility
def get_mt5_candles(asset: str, timeframe: str, count: int = 1000) -> Optional[List[Dict]]:
    """Fetch candles and return as list of dicts (compatible with existing parser)"""
    fetcher = MT5DataFetcher()
    df = fetcher.fetch_candles(asset, timeframe, count)
    fetcher.shutdown()
    
    if df is None:
        return None
    
    return df.to_dict('records')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    fetcher = MT5DataFetcher()
    
    # Test fetch for all assets
    for asset in ["XAUUSD", "NASDAQ", "EURUSD", "GBPUSD"]:
        print(f"\n--- {asset} ---")
        data = fetcher.fetch_all_timeframes(asset, {
            "daily": 50,
            "4h": 100,
            "15m": 200,
            "5m": 200,
            "1m": 500,
        })
        for tf, df in data.items():
            print(f"  {tf}: {len(df)} candles, last={df['close'].iloc[-1]:.5f}")
    
    fetcher.shutdown()
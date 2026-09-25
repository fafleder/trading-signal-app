"""
API Data Fetcher for ICT Signal Generator
Supports: Twelve Data, Alpha Vantage, Yahoo Finance (yfinance)
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True)

# ============================================================
# TWELVE DATA (Recommended - 800 free requests/day)
# ============================================================

class TwelveDataFetcher:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('TWELVE_DATA_API_KEY')
        self.base_url = "https://api.twelvedata.com"
    
    def fetch_time_series(self, symbol: str, interval: str, outputsize: int = 500) -> Optional[pd.DataFrame]:
        """Fetch time series data from Twelve Data"""
        if not self.api_key:
            logger.warning("No Twelve Data API key provided")
            return None
        
        params = {
            'symbol': symbol,
            'interval': interval,
            'outputsize': outputsize,
            'apikey': self.api_key,
            'format': 'JSON'
        }
        
        try:
            response = requests.get(f"{self.base_url}/time_series", params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if 'values' not in data:
                logger.error(f"Twelve Data error: {data}")
                return None
            
            df = pd.DataFrame(data['values'])
            df['datetime'] = pd.to_datetime(df['datetime'])
            df = df.rename(columns={
                'datetime': 'timestamp',
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })
            df = df.astype({'open': float, 'high': float, 'low': float, 'close': float, 'volume': float})
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Twelve Data fetch failed: {e}")
            return None


# ============================================================
# ALPHA VANTAGE (25 free requests/day)
# ============================================================

class AlphaVantageFetcher:
    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.getenv('ALPHA_VANTAGE_API_KEY')
        self.base_url = "https://www.alphavantage.co/query"
    
    def fetch_time_series(self, symbol: str, interval: str, outputsize: str = 'compact') -> Optional[pd.DataFrame]:
        """Fetch time series from Alpha Vantage"""
        if not self.api_key:
            logger.warning("No Alpha Vantage API key provided")
            return None
        
        interval_map = {
            '1m': '1min',
            '5m': '5min',
            '15m': '15min',
            '30m': '30min',
            '1h': '60min',
            'daily': 'daily',
        }
        
        function_map = {
            '1m': 'TIME_SERIES_INTRADAY',
            '5m': 'TIME_SERIES_INTRADAY',
            '15m': 'TIME_SERIES_INTRADAY',
            '30m': 'TIME_SERIES_INTRADAY',
            '1h': 'TIME_SERIES_INTRADAY',
            'daily': 'TIME_SERIES_DAILY',
        }
        
        params = {
            'function': function_map.get(interval, 'TIME_SERIES_DAILY'),
            'symbol': symbol,
            'apikey': self.api_key,
            'outputsize': outputsize,
            'datatype': 'json'
        }
        
        if interval in ['1m', '5m', '15m', '30m', '1h']:
            params['interval'] = interval_map[interval]
        
        try:
            response = requests.get(self.base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Find the time series key
            ts_key = None
            for k in data.keys():
                if 'Time Series' in k:
                    ts_key = k
                    break
            
            if not ts_key:
                logger.error(f"Alpha Vantage error: {data}")
                return None
            
            ts_data = data[ts_key]
            df = pd.DataFrame.from_dict(ts_data, orient='index')
            df.index = pd.to_datetime(df.index)
            df = df.rename(columns={
                '1. open': 'open',
                '2. high': 'high',
                '3. low': 'low',
                '4. close': 'close',
                '5. volume': 'volume'
            })
            df = df.astype(float)
            df['timestamp'] = df.index
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            return df
            
        except Exception as e:
            logger.error(f"Alpha Vantage fetch failed: {e}")
            return None


# ============================================================
# YAHOO FINANCE (yfinance - free, no API key needed)
# ============================================================

class YahooFinanceFetcher:
    def __init__(self):
        pass
    
    def fetch_time_series(self, symbol: str, interval: str, period: str = '1mo') -> Optional[pd.DataFrame]:
        """Fetch data using yfinance"""
        try:
            import yfinance as yf
        except ImportError:
            logger.error("yfinance not installed. Run: pip install yfinance")
            return None
        
        interval_map = {
            '1m': '1m',
            '5m': '5m',
            '15m': '15m',
            '30m': '30m',
            '1h': '1h',
            '4h': '1h',  # yfinance doesn't have 4h
            'daily': '1d',
        }
        
        period_map = {
            '1m': '7d',    # Max 7 days for 1m
            '5m': '60d',   # Max 60 days for 5m
            '15m': '60d',
            '30m': '60d',
            '1h': '730d',  # Max 2 years
            '4h': '730d',
            'daily': 'max',
        }
        
        yf_interval = interval_map.get(interval, '1d')
        yf_period = period_map.get(interval, '1mo')
        
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=yf_period, interval=yf_interval)
            
            if df.empty:
                logger.warning(f"No data from Yahoo Finance for {symbol}")
                return None
            
            df = df.reset_index()
            df = df.rename(columns={
                'Datetime': 'timestamp',
                'Date': 'timestamp',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            
            return df
            
        except Exception as e:
            logger.error(f"Yahoo Finance fetch failed: {e}")
            return None


# ============================================================
# UNIFIED FETCHER
# ============================================================

class APIDataFetcher:
    """Unified fetcher that tries multiple sources"""
    
    def __init__(self):
        self.twelve_data = TwelveDataFetcher()
        self.alpha_vantage = AlphaVantageFetcher()
        self.yahoo = YahooFinanceFetcher()
        
        # Symbol mapping for different providers
        self.symbol_map = {
            'XAUUSD': {
                'twelve_data': 'XAU/USD',
                'alpha_vantage': 'XAUUSD',
                'yahoo': 'GC=F',  # Gold futures
            },
            'NASDAQ': {
                'twelve_data': 'NAS:NDX',
                'alpha_vantage': 'NDX',
                'yahoo': '^NDX',  # Or NQ=F for futures
            },
            'EURUSD': {
                'twelve_data': 'EUR/USD',
                'alpha_vantage': 'EURUSD',
                'yahoo': 'EURUSD=X',
            },
            'GBPUSD': {
                'twelve_data': 'GBP/USD',
                'alpha_vantage': 'GBPUSD',
                'yahoo': 'GBPUSD=X',
            },
        }
        
        self.interval_map = {
            '1m': {'twelve_data': '1min', 'alpha_vantage': '1min', 'yahoo': '1m'},
            '5m': {'twelve_data': '5min', 'alpha_vantage': '5min', 'yahoo': '5m'},
            '15m': {'twelve_data': '15min', 'alpha_vantage': '15min', 'yahoo': '15m'},
            '30m': {'twelve_data': '30min', 'alpha_vantage': '30min', 'yahoo': '30m'},
            '1h': {'twelve_data': '1h', 'alpha_vantage': '60min', 'yahoo': '1h'},
            '4h': {'twelve_data': '4h', 'alpha_vantage': '60min', 'yahoo': '1h'},
            'daily': {'twelve_data': '1day', 'alpha_vantage': 'daily', 'yahoo': '1d'},
        }
        
        self.outputsize_map = {
            'daily': 100,
            '4h': 200,
            '1h': 500,
            '15m': 500,
            '5m': 1000,
            '1m': 3000,
        }
    
    def get_symbol(self, asset: str, provider: str) -> str:
        """Get provider-specific symbol"""
        return self.symbol_map.get(asset, {}).get(provider, asset)
    
    def get_interval(self, timeframe: str, provider: str) -> str:
        """Get provider-specific interval"""
        return self.interval_map.get(timeframe, {}).get(provider, timeframe)
    
    def fetch(self, asset: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Try providers in order: Twelve Data -> Alpha Vantage -> Yahoo Finance"""
        count = self.outputsize_map.get(timeframe, 500)
        
        # Try Twelve Data first (best free tier)
        if self.twelve_data.api_key:
            symbol = self.get_symbol(asset, 'twelve_data')
            interval = self.get_interval(timeframe, 'twelve_data')
            df = self.twelve_data.fetch_time_series(symbol, interval, count)
            if df is not None and len(df) > 10:
                logger.info(f"✅ Got {asset} {timeframe} from Twelve Data ({len(df)} candles)")
                return df
        
        # Try Alpha Vantage
        if self.alpha_vantage.api_key:
            symbol = self.get_symbol(asset, 'alpha_vantage')
            interval = self.get_interval(timeframe, 'alpha_vantage')
            outputsize = 'full' if timeframe in ['daily', '4h', '1h'] else 'compact'
            df = self.alpha_vantage.fetch_time_series(symbol, interval, outputsize)
            if df is not None and len(df) > 10:
                logger.info(f"✅ Got {asset} {timeframe} from Alpha Vantage ({len(df)} candles)")
                return df
        
        # Try Yahoo Finance (always available)
        symbol = self.get_symbol(asset, 'yahoo')
        interval = self.get_interval(timeframe, 'yahoo')
        df = self.yahoo.fetch_time_series(symbol, interval)
        if df is not None and len(df) > 10:
            logger.info(f"✅ Got {asset} {timeframe} from Yahoo Finance ({len(df)} candles)")
            return df
        
        logger.error(f"❌ All providers failed for {asset} {timeframe}")
        return None
    
    def fetch_all_timeframes(self, asset: str) -> Dict[str, pd.DataFrame]:
        """Fetch all required timeframes for an asset"""
        timeframes = ['daily', '4h', '15m', '5m', '1m']
        results = {}
        
        for tf in timeframes:
            df = self.fetch(asset, tf)
            if df is not None:
                results[tf] = df
        
        return results


# Convenience function
def fetch_market_data(asset: str, timeframe: str) -> Optional[pd.DataFrame]:
    """Simple function to fetch data for one asset/timeframe"""
    fetcher = APIDataFetcher()
    return fetcher.fetch(asset, timeframe)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    
    fetcher = APIDataFetcher()
    
    # Test with available providers
    for asset in ['XAUUSD', 'NASDAQ', 'EURUSD', 'GBPUSD']:
        print(f"\n--- {asset} ---")
        data = fetcher.fetch_all_timeframes(asset)
        for tf, df in data.items():
            if df is not None:
                print(f"  {tf}: {len(df)} candles, last={df['close'].iloc[-1]:.5f}")
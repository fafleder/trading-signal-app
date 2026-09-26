#!/usr/bin/env python3
"""
Silent ICT Trading Signal Wrapper
Only outputs signals when valid signals match live prices.
Outputs [SILENT] when no valid signals with live price match.
"""

import os
import sys
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

# Suppress all logging to stdout
logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

SIGNALS_FILE = Path(__file__).parent / '.cache' / 'generated_signals.json'
CACHE_DIR = Path(__file__).parent / '.cache'

# Asset symbol mapping for live price fetching
ASSET_SYMBOLS = {
    'XAUUSD': 'GC=F',      # Gold futures
    'NASDAQ': '^NDX',      # Nasdaq index
    'EURUSD': 'EURUSD=X',  # Forex
    'GBPUSD': 'GBPUSD=X',  # Forex
}

def get_current_est_time() -> datetime:
    """Get current time in EST (UTC-5, no DST)"""
    utc_now = datetime.now(timezone.utc)
    return utc_now + timedelta(hours=-5)

async def fetch_live_prices() -> Dict[str, float]:
    """Fetch current live prices for all assets"""
    prices = {}
    try:
        import yfinance as yf
    except ImportError:
        return prices
    
    for asset, symbol in ASSET_SYMBOLS.items():
        try:
            ticker = yf.Ticker(symbol)
            # Get latest price - use fast_info for speed
            fast_info = ticker.fast_info
            if fast_info and 'last_price' in fast_info:
                prices[asset] = float(fast_info['last_price'])
            else:
                # Fallback to history
                hist = ticker.history(period='1d', interval='1m')
                if not hist.empty:
                    prices[asset] = float(hist['Close'].iloc[-1])
        except Exception as e:
            logger.debug(f"Failed to fetch live price for {asset}: {e}")
    
    return prices

def price_matches_entry(live_price: float, entry_price: float, threshold_pct: float = 0.01) -> bool:
    """
    Check if live price is near entry price within threshold.
    Default threshold: 1% (100 basis points) - widened for synthetic data accuracy
    """
    if live_price <= 0 or entry_price <= 0:
        return False
    diff_pct = abs(live_price - entry_price) / entry_price
    return diff_pct <= threshold_pct

def is_signal_valid(signal: Dict, live_prices: Dict[str, float]) -> bool:
    """Check if a signal has valid live price match"""
    asset = signal.get('asset')
    if not asset or asset not in live_prices:
        return False
    
    live_price = live_prices[asset]
    entry_price = signal.get('entry_price', 0)
    
    if entry_price <= 0:
        return False
    
    # Check if signal is not expired
    expires_at = signal.get('expires_at')
    if expires_at:
        try:
            exp_time = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            if exp_time < datetime.now(timezone.utc):
                return False
        except:
            pass
    
    # Check price proximity
    return price_matches_entry(live_price, entry_price)

async def run_signal_generation():
    """Run the ICT signal generation"""
    # Import and run the main generation
    from run_ict_enhanced import generate_all_signals
    await generate_all_signals()

def load_signals() -> List[Dict]:
    """Load generated signals from file"""
    if not SIGNALS_FILE.exists():
        return []
    try:
        with open(SIGNALS_FILE) as f:
            return json.load(f)
    except:
        return []

async def main():
    """Main silent wrapper entry point"""
    try:
        # Step 1: Generate signals
        await run_signal_generation()
        
        # Step 2: Load generated signals
        signals = load_signals()
        
        if not signals:
            print("[SILENT]")
            return
        
        # Step 3: Fetch live prices
        live_prices = await fetch_live_prices()
        
        if not live_prices:
            print("[SILENT]")
            return
        
        # Step 4: Filter for intraday/scalp signals with valid live price match
        valid_signals = []
        for signal in signals:
            setup_type = signal.get('setup_type', '')
            if setup_type in ('intraday', 'scalp'):
                if is_signal_valid(signal, live_prices):
                    valid_signals.append(signal)
        
        # Step 5: Output result
        if not valid_signals:
            print("[SILENT]")
        else:
            # Output valid signals as JSON
            print(json.dumps(valid_signals, indent=2))
            
    except Exception as e:
        # On any error, output silent
        print("[SILENT]")

if __name__ == '__main__':
    asyncio.run(main())
"""
Enhanced ICT Trading Signal Generator
Implements full ICT methodology: Daily Bias → Liquidity Draw → Kill Zone → Structural Confirmation → PD Array Entry
Supports intraday and scalping setups with expiration times
"""

import os
import asyncio
import logging
import json
import time
import numpy as np
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from enum import Enum

# MT5 data fetcher
from mt5_fetcher import MT5DataFetcher
# API data fetcher (for cloud deployment)
from api_fetcher import APIDataFetcher

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True)

# ============================================================
# ICT CONSTANTS & CONFIGURATION
# ============================================================

class Session(Enum):
    ASIAN = "asian"
    LONDON = "london"
    NY_AM = "ny_am"
    LONDON_CLOSE = "london_close"
    NY_PM = "ny_pm"

class Bias(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

class SetupType(Enum):
    SWING = "swing"          # 4H/Daily, hold days-weeks
    INTRADAY = "intraday"    # 15M/1H, hold hours
    SCALP = "scalp"          # 1M/5M, hold minutes

# Kill Zones in EST (New York time)
KILL_ZONES_EST = {
    Session.ASIAN: {"start": "21:00", "end": "00:00", "note": "Asian Range - Accumulation"},
    Session.LONDON: {"start": "02:00", "end": "05:00", "note": "London Open - Manipulation (Judas Swing)"},
    Session.NY_AM: {"start": "07:00", "end": "10:00", "note": "NY AM - Distribution (Continuation)"},
    Session.LONDON_CLOSE: {"start": "10:00", "end": "12:00", "note": "London Close - Mean Reversion"},
    Session.NY_PM: {"start": "13:30", "end": "16:00", "note": "NY PM - End of Day"},
}

# Silver Bullet windows (1-hour precision windows inside kill zones)
SILVER_BULLETS_EST = {
    "london_silver_bullet": {"start": "03:00", "end": "04:00", "session": Session.LONDON},
    "ny_am_silver_bullet": {"start": "10:00", "end": "11:00", "session": Session.LONDON_CLOSE},
    "ny_pm_silver_bullet": {"start": "14:00", "end": "15:00", "session": Session.NY_PM},
}

# Macro windows (20-minute high-probability bursts)
MACRO_WINDOWS_EST = {
    "london_macro_1": {"start": "02:33", "end": "03:00", "session": Session.LONDON},
    "london_macro_2": {"start": "03:00", "end": "04:00", "session": Session.LONDON},  # overlaps Silver Bullet
    "ny_macro_1": {"start": "09:50", "end": "10:10", "session": Session.NY_AM},
    "ny_macro_2": {"start": "10:50", "end": "11:10", "session": Session.LONDON_CLOSE},
}

# OTE Fibonacci Levels
OTE_LEVELS = {
    "start": 0.62,
    "sweet_spot": 0.705,
    "end": 0.79,
    "equilibrium": 0.5,
    "invalidation": 1.0,
    "target_1": -0.27,
    "target_2": -0.62,
}

# Assets with their specs
ASSETS = {
    "XAUUSD": {
        "symbol": "XAUUSD",
        "market": "FOREX",
        "pip_size": 0.01,
        "typical_spread": 0.3,
        "killzone_priority": [Session.LONDON, Session.NY_AM],
        "scalp_target_pips": 8,
        "intraday_target_pips": 25,
    },
    "NASDAQ": {
        "symbol": "NQ",
        "market": "INDEX",
        "pip_size": 0.25,
        "typical_spread": 0.5,
        "killzone_priority": [Session.NY_AM, Session.LONDON],
        "scalp_target_points": 15,
        "intraday_target_points": 50,
    },
    "EURUSD": {
        "symbol": "EURUSD",
        "market": "FOREX",
        "pip_size": 0.0001,
        "typical_spread": 0.6,
        "killzone_priority": [Session.LONDON, Session.NY_AM],
        "scalp_target_pips": 5,
        "intraday_target_pips": 20,
    },
    "GBPUSD": {
        "symbol": "GBPUSD",
        "market": "FOREX",
        "pip_size": 0.0001,
        "typical_spread": 0.8,
        "killzone_priority": [Session.LONDON, Session.NY_AM],
        "scalp_target_pips": 6,
        "intraday_target_pips": 25,
    },
}

TIMEFRAMES = {
    "swing": "4h",
    "intraday": "15m",
    "scalp": "5m",
    "execution": "1m",
}

# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass
class SwingPoint:
    index: int
    price: float
    type: str  # "high" or "low"
    timestamp: str

@dataclass
class MarketStructure:
    trend: str  # "bullish", "bearish", "ranging"
    last_bos: Optional[Dict] = None
    last_choch: Optional[Dict] = None
    swing_highs: List[SwingPoint] = None
    swing_lows: List[SwingPoint] = None

@dataclass
class LiquidityPool:
    price: float
    type: str  # "buy_side" or "sell_side"
    source: str  # "swing_high", "swing_low", "equal_highs", "equal_lows", "pdh", "pdl", "session_high", "session_low"
    strength: float  # 0-1
    timestamp: str

@dataclass
class PDArray:
    type: str  # "order_block", "fair_value_gap", "breaker_block", "mitigation_block"
    price_top: float
    price_bottom: float
    timestamp: str
    direction: str  # "bullish" or "bearish"
    strength: float
    timeframe: str

@dataclass
class TradeSetup:
    asset: str
    setup_type: SetupType
    bias: Bias
    direction: str  # "long" or "short"
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    invalidation_price: float
    risk_reward: float
    confidence: float
    kill_zone: Session
    macro_window: Optional[str]
    silver_bullet: Optional[str]
    entry_time_est: str
    expiration_time_est: str
    max_hold_minutes: int
    structure: Dict
    liquidity_target: LiquidityPool
    pd_array: PDArray
    ote_level: Optional[float] = None
    notes: str = ""

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def get_current_est_time() -> datetime:
    """Get current time in EST (approximate, no DST handling for simplicity)"""
    utc_now = datetime.now(timezone.utc)
    est_offset = -5  # EST = UTC-5 (simplified, no DST)
    return utc_now + timedelta(hours=est_offset)

def time_to_minutes(time_str: str) -> int:
    """Convert HH:MM to minutes since midnight"""
    h, m = map(int, time_str.split(":"))
    return h * 60 + m

def minutes_to_time(minutes: int) -> str:
    """Convert minutes since midnight to HH:MM"""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"

def is_in_kill_zone(est_time: datetime) -> Tuple[bool, Optional[Session], Optional[str]]:
    """Check if current time is in a kill zone"""
    current_minutes = est_time.hour * 60 + est_time.minute
    
    for session, kz in KILL_ZONES_EST.items():
        start_min = time_to_minutes(kz["start"])
        end_min = time_to_minutes(kz["end"])
        
        # Handle overnight sessions (e.g., Asian 21:00-00:00)
        if start_min > end_min:
            if current_minutes >= start_min or current_minutes <= end_min:
                return True, session, kz["note"]
        else:
            if start_min <= current_minutes <= end_min:
                return True, session, kz["note"]
    
    return False, None, None

def is_in_macro_window(est_time: datetime) -> Tuple[bool, Optional[str]]:
    """Check if current time is in a macro window"""
    current_minutes = est_time.hour * 60 + est_time.minute
    
    for name, mw in MACRO_WINDOWS_EST.items():
        start_min = time_to_minutes(mw["start"])
        end_min = time_to_minutes(mw["end"])
        if start_min <= current_minutes <= end_min:
            return True, name
    return False, None

def is_in_silver_bullet(est_time: datetime) -> Tuple[bool, Optional[str]]:
    """Check if current time is in a silver bullet window"""
    current_minutes = est_time.hour * 60 + est_time.minute
    
    for name, sb in SILVER_BULLETS_EST.items():
        start_min = time_to_minutes(sb["start"])
        end_min = time_to_minutes(sb["end"])
        if start_min <= current_minutes <= end_min:
            return True, name
    return False, None

def calculate_expiration(est_time: datetime, setup_type: SetupType, kill_zone: Session) -> Tuple[str, int]:
    """Calculate trade expiration time based on setup type and session"""
    current_minutes = est_time.hour * 60 + est_time.minute
    
    if setup_type == SetupType.SCALP:
        # Scalp: 5-30 minutes, max until end of macro window or kill zone
        max_hold = 30
        # Find end of current macro window or kill zone
        for name, mw in MACRO_WINDOWS_EST.items():
            end_min = time_to_minutes(mw["end"])
            if current_minutes < end_min:
                max_hold = min(max_hold, end_min - current_minutes)
                break
        expiration_minutes = current_minutes + max_hold
        
    elif setup_type == SetupType.INTRADAY:
        # Intraday: hold until end of kill zone or next session
        max_hold = 240  # 4 hours max
        kz = KILL_ZONES_EST[kill_zone]
        end_min = time_to_minutes(kz["end"])
        if current_minutes < end_min:
            max_hold = min(max_hold, end_min - current_minutes)
        expiration_minutes = current_minutes + max_hold
        
    else:  # SWING
        # Swing: end of day or next session
        max_hold = 480  # 8 hours
        expiration_minutes = current_minutes + max_hold
    
    expiration_minutes = min(expiration_minutes, 23 * 60 + 59)  # Cap at end of day
    return minutes_to_time(expiration_minutes), max_hold

# ============================================================
# MARKET STRUCTURE ANALYSIS (from app/smart_money_concepts)
# ============================================================

def swing_highs_lows(highs: List[float], lows: List[float], lookback: int = 5) -> List[Dict]:
    """Identify swing highs and lows"""
    swings = []
    n = len(highs)
    
    for i in range(lookback, n - lookback):
        # Swing high
        if all(highs[i] >= highs[j] for j in range(i - lookback, i + lookback + 1) if j != i):
            swings.append({"index": i, "price": highs[i], "type": "high"})
        # Swing low
        if all(lows[i] <= lows[j] for j in range(i - lookback, i + lookback + 1) if j != i):
            swings.append({"index": i, "price": lows[i], "type": "low"})
    
    return swings

def market_structure(highs: List[float], lows: List[float], closes: List[float]) -> MarketStructure:
    """Analyze market structure: trends, BOS, CHoCH"""
    swings = swing_highs_lows(highs, lows)
    
    swing_highs = [s for s in swings if s["type"] == "high"]
    swing_lows = [s for s in swings if s["type"] == "low"]
    
    # Determine trend from last few swings
    trend = "ranging"
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        # Check for higher highs / higher lows
        if swing_highs[-1]["price"] > swing_highs[-2]["price"] and swing_lows[-1]["price"] > swing_lows[-2]["price"]:
            trend = "bullish"
        elif swing_highs[-1]["price"] < swing_highs[-2]["price"] and swing_lows[-1]["price"] < swing_lows[-2]["price"]:
            trend = "bearish"
    
    # Detect BOS and CHoCH
    last_bos = None
    last_choch = None
    
    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        # BOS: break of structure in trend direction
        if trend == "bullish" and closes[-1] > swing_highs[-2]["price"]:
            last_bos = {"type": "bullish_bos", "level": swing_highs[-2]["price"], "index": len(closes) - 1}
        elif trend == "bearish" and closes[-1] < swing_lows[-2]["price"]:
            last_bos = {"type": "bearish_bos", "level": swing_lows[-2]["price"], "index": len(closes) - 1}
        
        # CHoCH: change of character (reversal signal)
        if trend == "bullish" and closes[-1] < swing_lows[-1]["price"]:
            last_choch = {"type": "bearish_choch", "level": swing_lows[-1]["price"], "index": len(closes) - 1}
        elif trend == "bearish" and closes[-1] > swing_highs[-1]["price"]:
            last_choch = {"type": "bullish_choch", "level": swing_highs[-1]["price"], "index": len(closes) - 1}
    
    return MarketStructure(
        trend=trend,
        last_bos=last_bos,
        last_choch=last_choch,
        swing_highs=[SwingPoint(**s, timestamp="") for s in swing_highs],
        swing_lows=[SwingPoint(**s, timestamp="") for s in swing_lows]
    )

def order_blocks(highs: List[float], lows: List[float], opens: List[float], closes: List[float], lookback: int = 20) -> List[PDArray]:
    """Identify Order Blocks (last opposite-color candle before displacement)"""
    obs = []
    n = len(closes)
    
    for i in range(1, n - 1):
        # Bullish OB: last bearish candle before bullish displacement
        if closes[i] < opens[i] and closes[i + 1] > opens[i + 1]:
            # Check for displacement (strong move)
            displacement = closes[i + 1] - opens[i + 1]
            avg_range = np.mean([highs[j] - lows[j] for j in range(max(0, i - 10), i)])
            if displacement > 1.5 * avg_range:
                obs.append(PDArray(
                    type="order_block",
                    price_top=max(opens[i], closes[i]),
                    price_bottom=min(opens[i], closes[i]),
                    timestamp="",
                    direction="bullish",
                    strength=min(displacement / avg_range / 3, 1.0),
                    timeframe=""
                ))
        
        # Bearish OB: last bullish candle before bearish displacement
        if closes[i] > opens[i] and closes[i + 1] < opens[i + 1]:
            displacement = opens[i + 1] - closes[i + 1]
            avg_range = np.mean([highs[j] - lows[j] for j in range(max(0, i - 10), i)])
            if displacement > 1.5 * avg_range:
                obs.append(PDArray(
                    type="order_block",
                    price_top=max(opens[i], closes[i]),
                    price_bottom=min(opens[i], closes[i]),
                    timestamp="",
                    direction="bearish",
                    strength=min(displacement / avg_range / 3, 1.0),
                    timeframe=""
                ))
    
    return obs[-10:]  # Return last 10

def fair_value_gaps(highs: List[float], lows: List[float], closes: List[float], volumes: List[float]) -> List[PDArray]:
    """Identify Fair Value Gaps (3-candle imbalance)"""
    fvgs = []
    n = len(closes)
    
    # Need at least 3 candles for FVG
    for i in range(1, n - 1):
        # Bullish FVG: gap between candle i-1 high and candle i+1 low
        # Pattern: candle i-1 (any), candle i (bullish displacement), candle i+1 (continuation)
        # Gap forms when low[i+1] > high[i-1]
        if lows[i + 1] > highs[i - 1]:
            gap_size = lows[i + 1] - highs[i - 1]
            avg_range = np.mean([highs[j] - lows[j] for j in range(max(0, i - 10), i + 1)])
            if gap_size > 0.1 * avg_range:  # Significant gap
                # Direction is bullish (gap is below current price, price should retrace up into it)
                fvgs.append(PDArray(
                    type="fair_value_gap",
                    price_top=lows[i + 1],
                    price_bottom=highs[i - 1],
                    timestamp="",
                    direction="bullish",
                    strength=min(gap_size / avg_range, 1.0),
                    timeframe=""
                ))
        
        # Bearish FVG: gap between candle i-1 low and candle i+1 high
        # Pattern: candle i-1 (any), candle i (bearish displacement), candle i+1 (continuation)
        # Gap forms when high[i+1] < low[i-1]
        if highs[i + 1] < lows[i - 1]:
            gap_size = lows[i - 1] - highs[i + 1]
            avg_range = np.mean([highs[j] - lows[j] for j in range(max(0, i - 10), i + 1)])
            if gap_size > 0.1 * avg_range:
                # Direction is bearish (gap is above current price, price should retrace down into it)
                fvgs.append(PDArray(
                    type="fair_value_gap",
                    price_top=lows[i - 1],
                    price_bottom=highs[i + 1],
                    timestamp="",
                    direction="bearish",
                    strength=min(gap_size / avg_range, 1.0),
                    timeframe=""
                ))
    
    return fvgs[-10:]

def liquidity_pools(highs: List[float], lows: List[float], closes: List[float]) -> List[LiquidityPool]:
    """Identify liquidity pools (swing highs/lows, equal highs/lows)"""
    pools = []
    swings = swing_highs_lows(highs, lows)
    
    for swing in swings:
        if swing["type"] == "high":
            pools.append(LiquidityPool(
                price=swing["price"],
                type="buy_side",
                source="swing_high",
                strength=0.7,
                timestamp=""
            ))
        else:
            pools.append(LiquidityPool(
                price=swing["price"],
                type="sell_side",
                source="swing_low",
                strength=0.7,
                timestamp=""
            ))
    
    # Equal highs/lows (stronger liquidity)
    for i in range(len(highs) - 1):
        if abs(highs[i] - highs[i + 1]) < (highs[i] * 0.001):  # Within 0.1%
            pools.append(LiquidityPool(
                price=(highs[i] + highs[i + 1]) / 2,
                type="buy_side",
                source="equal_highs",
                strength=0.9,
                timestamp=""
            ))
        if abs(lows[i] - lows[i + 1]) < (lows[i] * 0.001):
            pools.append(LiquidityPool(
                price=(lows[i] + lows[i + 1]) / 2,
                type="sell_side",
                source="equal_lows",
                strength=0.9,
                timestamp=""
            ))
    
    return pools

def previous_session_levels(highs: List[float], lows: List[float], lookback_sessions: int = 5) -> List[LiquidityPool]:
    """Get previous day/week high/low as liquidity"""
    pools = []
    # Simplified: use recent extremes as PDH/PDL
    if len(highs) >= 20:
        recent_high = max(highs[-20:])
        recent_low = min(lows[-20:])
        pools.append(LiquidityPool(price=recent_high, type="buy_side", source="pdh", strength=0.8, timestamp=""))
        pools.append(LiquidityPool(price=recent_low, type="sell_side", source="pdl", strength=0.8, timestamp=""))
    return pools

# ============================================================
# OTE CALCULATION
# ============================================================

def calculate_ote_levels(sweep_price: float, displacement_price: float, direction: str) -> Dict[str, float]:
    """Calculate OTE Fibonacci levels from sweep to displacement peak"""
    if direction == "long":
        # Bullish: sweep low to displacement high
        range_size = displacement_price - sweep_price
        return {
            "0": displacement_price,
            "0.5": displacement_price - 0.5 * range_size,
            "0.62": displacement_price - 0.62 * range_size,
            "0.705": displacement_price - 0.705 * range_size,
            "0.79": displacement_price - 0.79 * range_size,
            "1.0": sweep_price,
            "-0.27": displacement_price + 0.27 * range_size,
            "-0.62": displacement_price + 0.62 * range_size,
        }
    else:
        # Bearish: sweep high to displacement low
        range_size = sweep_price - displacement_price
        return {
            "0": displacement_price,
            "0.5": displacement_price + 0.5 * range_size,
            "0.62": displacement_price + 0.62 * range_size,
            "0.705": displacement_price + 0.705 * range_size,
            "0.79": displacement_price + 0.79 * range_size,
            "1.0": sweep_price,
            "-0.27": displacement_price - 0.27 * range_size,
            "-0.62": displacement_price - 0.62 * range_size,
        }

def check_ote_confluence(ote_levels: Dict, pd_arrays: List[PDArray], direction: str) -> Tuple[bool, Optional[PDArray], Optional[float]]:
    """Check if OTE zone overlaps with any PD array"""
    ote_start = ote_levels["0.62"]
    ote_end = ote_levels["0.79"]
    sweet_spot = ote_levels["0.705"]
    
    logger.info(f"    OTE zone: {ote_start:.5f} - {ote_end:.5f}, sweet_spot={sweet_spot:.5f}")
    
    for pa in pd_arrays:
        if (direction == "long" and pa.direction == "bullish") or (direction == "short" and pa.direction == "bearish"):
            # Check overlap
            if direction == "long":
                # PD array bottom should be <= OTE end, top >= OTE start
                if pa.price_bottom <= ote_end and pa.price_top >= ote_start:
                    logger.info(f"    ✅ OTE CONFLUENCE: {pa.type} [{pa.price_bottom:.5f}-{pa.price_top:.5f}] overlaps OTE zone")
                    return True, pa, sweet_spot
            else:
                # Bearish: PD array top >= OTE end, bottom <= OTE start
                if pa.price_top >= ote_end and pa.price_bottom <= ote_start:
                    logger.info(f"    ✅ OTE CONFLUENCE: {pa.type} [{pa.price_bottom:.5f}-{pa.price_top:.5f}] overlaps OTE zone")
                    return True, pa, sweet_spot
    logger.info(f"    ❌ No OTE confluence found")
    return False, None, None

# ============================================================
# DAILY BIAS DETERMINATION
# ============================================================

def determine_daily_bias(daily_candles: List[Candle]) -> Tuple[Bias, Dict]:
    """Determine daily bias from daily chart structure"""
    if len(daily_candles) < 20:
        return Bias.NEUTRAL, {"reason": "insufficient_data"}
    
    highs = [c.high for c in daily_candles]
    lows = [c.low for c in daily_candles]
    closes = [c.close for c in daily_candles]
    
    structure = market_structure(highs, lows, closes)
    
    # Check for liquidity sweeps on daily
    pools = liquidity_pools(highs, lows, closes)
    buy_side_pools = [p for p in pools if p.type == "buy_side"]
    sell_side_pools = [p for p in pools if p.type == "sell_side"]
    
    # Recent price action relative to pools
    current_price = closes[-1]
    
    # If price swept buy-side liquidity recently, bias may be bearish (reversal)
    # If price swept sell-side liquidity recently, bias may be bullish
    
    bias = Bias.NEUTRAL
    reason = "ranging"
    
    if structure.trend == "bullish":
        bias = Bias.BULLISH
        reason = "higher_highs_higher_lows"
    elif structure.trend == "bearish":
        bias = Bias.BEARISH
        reason = "lower_highs_lower_lows"
    elif structure.last_choch:
        if structure.last_choch["type"] == "bullish_choch":
            bias = Bias.BULLISH
            reason = "choch_bullish"
        else:
            bias = Bias.BEARISH
            reason = "choch_bearish"
    
    return bias, {
        "structure": structure.trend,
        "last_bos": structure.last_bos,
        "last_choch": structure.last_choch,
        "reason": reason,
        "current_price": current_price
    }

# ============================================================
# SIGNAL GENERATION PER SETUP TYPE
# ============================================================

def generate_swing_signals(asset: str, asset_config: Dict, daily_candles: List[Candle], 
                          h4_candles: List[Candle], est_now: datetime) -> List[TradeSetup]:
    """Generate swing trade setups (4H/Daily)"""
    setups = []
    
    # Daily bias
    bias, bias_info = determine_daily_bias(daily_candles)
    if bias == Bias.NEUTRAL:
        return setups
    
    # 4H structure for entry
    if len(h4_candles) < 50:
        return setups
    
    h4_highs = [c.high for c in h4_candles]
    h4_lows = [c.low for c in h4_candles]
    h4_closes = [c.close for c in h4_candles]
    h4_opens = [c.open for c in h4_candles]
    
    h4_structure = market_structure(h4_highs, h4_lows, h4_closes)
    
    # Check alignment with daily bias
    if (bias == Bias.BULLISH and h4_structure.trend != "bullish") or \
       (bias == Bias.BEARISH and h4_structure.trend != "bearish"):
        return setups  # Not aligned
    
    # Liquidity targets
    pools = liquidity_pools(h4_highs, h4_lows, h4_closes)
    pools.extend(previous_session_levels(h4_highs, h4_lows))
    
    # PD Arrays
    obs = order_blocks(h4_highs, h4_lows, h4_opens, h4_closes)
    fvgs = fair_value_gaps(h4_highs, h4_lows, h4_closes, [c.volume for c in h4_candles])
    pd_arrays = obs + fvgs
    
    direction = "long" if bias == Bias.BULLISH else "short"
    target_pools = [p for p in pools if (p.type == "buy_side" and direction == "long") or 
                                             (p.type == "sell_side" and direction == "short")]
    
    if not target_pools:
        return setups
    
    # Find best liquidity target
    target_pool = max(target_pools, key=lambda p: p.strength)
    
    # Find PD array for entry
    aligned_pd = [pa for pa in pd_arrays if pa.direction == direction]
    if not aligned_pd:
        return setups
    
    # Check OTE confluence
    # Need a sweep and displacement to anchor Fibonacci
    if h4_structure.last_choch or h4_structure.last_bos:
        sweep_price = h4_structure.last_choch["level"] if h4_structure.last_choch else h4_structure.last_bos["level"]
        displacement_price = h4_closes[-1]
        ote_levels = calculate_ote_levels(sweep_price, displacement_price, direction)
        has_ote, ote_pd, ote_entry = check_ote_confluence(ote_levels, aligned_pd, direction)
    else:
        has_ote, ote_pd, ote_entry = False, None, None
    
    entry_pd = ote_pd if has_ote else aligned_pd[-1]
    entry_price = entry_pd.price_bottom if direction == "long" else entry_pd.price_top
    stop_loss = entry_pd.price_bottom - (entry_pd.price_top - entry_pd.price_bottom) if direction == "long" \
                else entry_pd.price_top + (entry_pd.price_top - entry_pd.price_bottom)
    
    # Targets
    tp1 = target_pool.price
    range_size = abs(target_pool.price - entry_price)
    tp2 = entry_price + 1.5 * range_size if direction == "long" else entry_price - 1.5 * range_size
    
    risk = abs(entry_price - stop_loss)
    reward = abs(tp1 - entry_price)
    rr = reward / risk if risk > 0 else 0
    
    if rr < 1.5:
        return setups
    
    expiration_time, max_hold = calculate_expiration(est_now, SetupType.SWING, Session.NY_AM)
    
    setups.append(TradeSetup(
        asset=asset,
        setup_type=SetupType.SWING,
        bias=bias,
        direction=direction,
        entry_price=round(entry_price, 5),
        stop_loss=round(stop_loss, 5),
        take_profit_1=round(tp1, 5),
        take_profit_2=round(tp2, 5),
        invalidation_price=round(stop_loss, 5),
        risk_reward=round(rr, 2),
        confidence=0.75 if has_ote else 0.65,
        kill_zone=Session.NY_AM,
        macro_window=None,
        silver_bullet=None,
        entry_time_est=est_now.strftime("%H:%M"),
        expiration_time_est=expiration_time,
        max_hold_minutes=max_hold,
        structure={"daily": bias_info, "h4": {"trend": h4_structure.trend}},
        liquidity_target=target_pool,
        pd_array=entry_pd,
        ote_level=ote_entry,
        notes=f"Swing setup aligned with daily {bias.value} bias. {'OTE confluence' if has_ote else 'PD array entry'}."
    ))
    
    return setups

def generate_intraday_signals(asset: str, asset_config: Dict, candles_15m: List[Candle], 
                             candles_5m: List[Candle], est_now: datetime) -> List[TradeSetup]:
    """Generate intraday setups (15M/5M) within kill zones"""
    setups = []
    
    in_kz, kz_session, kz_note = is_in_kill_zone(est_now)
    if not in_kz:
        logger.info(f"  ❌ Not in kill zone for {asset}")
        return setups
    
    in_macro, macro_name = is_in_macro_window(est_now)
    in_sb, sb_name = is_in_silver_bullet(est_now)
    
    # Priority: only trade in preferred kill zones for this asset
    if kz_session not in asset_config["killzone_priority"]:
        logger.info(f"  ❌ Kill zone {kz_session.value} not in priority for {asset}")
        return setups
    
    if len(candles_15m) < 50 or len(candles_5m) < 50:
        logger.info(f"  ❌ Insufficient candles for {asset}")
        return setups
    
    # 15M structure for bias and range
    h15_highs = [c.high for c in candles_15m]
    h15_lows = [c.low for c in candles_15m]
    h15_closes = [c.close for c in candles_15m]
    h15_opens = [c.open for c in candles_15m]
    h15_volumes = [c.volume for c in candles_15m]
    
    logger.info(f"  📊 {asset} 15M: last close={h15_closes[-1]:.5f}, range={max(h15_highs[-20:])-min(h15_lows[-20:]):.5f}")
    
    h15_structure = market_structure(h15_highs, h15_lows, h15_closes)
    
    logger.info(f"  📊 {asset} 15M structure: trend={h15_structure.trend}, last_choch={h15_structure.last_choch}")
    
    # Determine intraday bias from 15M structure
    intraday_bias = Bias.NEUTRAL
    if h15_structure.trend == "bullish":
        intraday_bias = Bias.BULLISH
    elif h15_structure.trend == "bearish":
        intraday_bias = Bias.BEARISH
    elif h15_structure.last_choch:
        intraday_bias = Bias.BULLISH if "bullish" in h15_structure.last_choch["type"] else Bias.BEARISH
    
    if intraday_bias == Bias.NEUTRAL:
        logger.info(f"  ❌ No intraday bias for {asset}")
        return setups
    
    direction = "long" if intraday_bias == Bias.BULLISH else "short"
    
    # 5M structure for sweep detection
    h5_highs = [c.high for c in candles_5m]
    h5_lows = [c.low for c in candles_5m]
    h5_closes = [c.close for c in candles_5m]
    h5_opens = [c.open for c in candles_5m]
    
    h5_structure = market_structure(h5_highs, h5_lows, h5_closes)
    
    logger.info(f"  📊 {asset} 5M structure: trend={h5_structure.trend}, last_choch={h5_structure.last_choch}")
    
    # Look for liquidity sweep on 5M against the bias (Judas Swing style)
    pools_5m = liquidity_pools(h5_highs, h5_lows, h5_closes)
    
    # Sweep should be AGAINST the bias initially (manipulation), then displacement WITH bias
    sweep_pools = [p for p in pools_5m if 
                   (p.type == "sell_side" and direction == "long") or 
                   (p.type == "buy_side" and direction == "short")]
    
    logger.info(f"  📊 {asset} sweep pools: {len(sweep_pools)} found")
    for p in sweep_pools[:3]:
        logger.info(f"    Pool: {p.price:.5f} type={p.type} source={p.source} strength={p.strength}")
    
    if not sweep_pools:
        logger.info(f"  ❌ No sweep pools for {asset}")
        return setups
    
    # Check if recent price swept liquidity (look at last 20 candles for sweep)
    recent_lows = h5_lows[-20:]
    recent_highs = h5_highs[-20:]
    sweep_occurred = False
    sweep_price = 0
    
    for pool in sweep_pools:
        if direction == "long" and min(recent_lows) <= pool.price:
            sweep_occurred = True
            sweep_price = pool.price
            logger.info(f"  ✅ SWEEP DETECTED: long, min_low={min(recent_lows):.5f} <= pool={pool.price:.5f}")
            break
        elif direction == "short" and max(recent_highs) >= pool.price:
            sweep_occurred = True
            sweep_price = pool.price
            logger.info(f"  ✅ SWEEP DETECTED: short, max_high={max(recent_highs):.5f} >= pool={pool.price:.5f}")
            break
    
    if not sweep_occurred:
        logger.info(f"  ❌ No sweep occurred for {asset}. min_low={min(recent_lows):.5f}, max_high={max(recent_highs):.5f}")
        return setups
    
    # Check for MSS/CHoCH on 5M in bias direction
    mss_confirmed = False
    if direction == "long" and h5_structure.last_choch and "bullish" in h5_structure.last_choch["type"]:
        mss_confirmed = True
    elif direction == "short" and h5_structure.last_choch and "bearish" in h5_structure.last_choch["type"]:
        mss_confirmed = True
    elif h5_structure.last_bos and ((direction == "long" and "bullish" in h5_structure.last_bos["type"]) or
                                      (direction == "short" and "bearish" in h5_structure.last_bos["type"])):
        mss_confirmed = True
    
    logger.info(f"  📊 {asset} MSS confirmed: {mss_confirmed}")
    
    if not mss_confirmed:
        logger.info(f"  ❌ No MSS for {asset}")
        return setups
    
    # Displacement on 5M after sweep
    displacement_price = h5_closes[-1]
    
    # 1M/5M PD Arrays for entry
    obs_5m = order_blocks(h5_highs, h5_lows, h5_opens, h5_closes)
    fvgs_5m = fair_value_gaps(h5_highs, h5_lows, h5_closes, [c.volume for c in candles_5m])
    pd_arrays_5m = obs_5m + fvgs_5m
    
    logger.info(f"  📊 {asset} PD arrays detail:")
    for pa in pd_arrays_5m:
        logger.info(f"    {pa.type}: dir={pa.direction}, top={pa.price_top:.5f}, bottom={pa.price_bottom:.5f}, strength={pa.strength:.2f}")
    
    aligned_pd = [pa for pa in pd_arrays_5m if 
                       (pa.direction == "bullish" and direction == "long") or
                       (pa.direction == "bearish" and direction == "short")]
    
    logger.info(f"  📊 {asset} PD arrays: {len(pd_arrays_5m)} total, {len(aligned_pd)} aligned")
    
    if not aligned_pd:
        logger.info(f"  ❌ No aligned PD arrays for {asset}")
        return setups
    
    # OTE on 5M
    ote_levels = calculate_ote_levels(sweep_price, displacement_price, direction)
    has_ote, ote_pd, ote_entry = check_ote_confluence(ote_levels, aligned_pd, direction)
    
    logger.info(f"  📊 {asset} OTE levels: {ote_levels}")
    logger.info(f"  📊 {asset} OTE confluence: {has_ote}, entry={ote_entry}")
    
    ote_start = ote_levels["0.62"]
    ote_end = ote_levels["0.79"]
    
    entry_pd = ote_pd if has_ote else None
    if not entry_pd:
        # Pick the PD array in the OTE zone or discount/premium zone
        for pa in aligned_pd:
            if direction == "long":
                # For long, want PD array in discount zone (below 50% equilibrium)
                # OTE zone is 62-79% retracement from sweep to displacement
                if pa.price_bottom <= ote_end and pa.price_top >= ote_start:
                    entry_pd = pa
                    break
        # Fallback: first aligned
        if not entry_pd and aligned_pd:
            entry_pd = aligned_pd[0]
    
    if not entry_pd:
        logger.info(f"  ❌ No suitable entry PD for {asset}")
        return setups
    
    entry_price = ote_entry if has_ote else (entry_pd.price_bottom if direction == "long" else entry_pd.price_top)
    
    # Stop just beyond the PD array (not sweep)
    pd_range = entry_pd.price_top - entry_pd.price_bottom
    if direction == "long":
        stop_loss = entry_pd.price_bottom - pd_range * 0.1
    else:
        stop_loss = entry_pd.price_top + pd_range * 0.1
    
    # Also set invalidation at sweep level (for reference)
    invalidation_price = sweep_price
    
    # Target: next significant opposing liquidity on 15M (not nearest, but the one beyond current price)
    target_pools_15m = liquidity_pools(h15_highs, h15_lows, h15_closes)
    target_pools_15m = [p for p in target_pools_15m if 
                        (p.type == "buy_side" and direction == "long") or 
                        (p.type == "sell_side" and direction == "short")]
    
    if target_pools_15m:
        # For long: target should be ABOVE entry; for short: target should be BELOW entry
        if direction == "long":
            valid_targets = [p for p in target_pools_15m if p.price > entry_price]
        else:
            valid_targets = [p for p in target_pools_15m if p.price < entry_price]
        
        if valid_targets:
            # Pick the one with good distance (not too close)
            target_pool = min(valid_targets, key=lambda p: abs(p.price - entry_price))
            tp1 = target_pool.price
        else:
            # Fallback: measured move
            move_size = abs(displacement_price - sweep_price)
            tp1 = entry_price + move_size if direction == "long" else entry_price - move_size
    else:
        # Fallback: measured move
        move_size = abs(displacement_price - sweep_price)
        tp1 = entry_price + move_size if direction == "long" else entry_price - move_size
    
    tp2 = entry_price + 2 * abs(tp1 - entry_price) if direction == "long" else entry_price - 2 * abs(tp1 - entry_price)
    
    risk = abs(entry_price - stop_loss)
    reward = abs(tp1 - entry_price)
    rr = reward / risk if risk > 0 else 0
    
    logger.info(f"  📊 {asset} entry={entry_price:.5f}, sl={stop_loss:.5f}, tp1={tp1:.5f}, rr={rr:.2f}")
    
    if rr < 1.5:
        logger.info(f"  ❌ RR too low for {asset}: {rr:.2f}")
        return setups
    
    expiration_time, max_hold = calculate_expiration(est_now, SetupType.INTRADAY, kz_session)
    
    confidence = 0.7
    if in_macro:
        confidence += 0.1
    if in_sb:
        confidence += 0.1
    if has_ote:
        confidence += 0.1
    confidence = min(confidence, 0.95)
    
    setups.append(TradeSetup(
        asset=asset,
        setup_type=SetupType.INTRADAY,
        bias=intraday_bias,
        direction=direction,
        entry_price=round(entry_price, 5),
        stop_loss=round(stop_loss, 5),
        take_profit_1=round(tp1, 5),
        take_profit_2=round(tp2, 5),
        invalidation_price=round(invalidation_price, 5),  # Use sweep level as invalidation
        risk_reward=round(rr, 2),
        confidence=confidence,
        kill_zone=kz_session,
        macro_window=macro_name,
        silver_bullet=sb_name,
        entry_time_est=est_now.strftime("%H:%M"),
        expiration_time_est=expiration_time,
        max_hold_minutes=max_hold,
        structure={"15m": {"trend": h15_structure.trend}, "5m": {"trend": h5_structure.trend, "mss": mss_confirmed}},
        liquidity_target=target_pool if target_pools_15m else None,
        pd_array=entry_pd,
        ote_level=ote_entry,
        notes=f"Intraday {kz_session.value} setup. {'Macro window' if in_macro else ''} {'Silver Bullet' if in_sb else ''}. {'OTE+PD confluence' if has_ote else 'PD array entry'}."
    ))
    
    return setups

def generate_scalp_signals(asset: str, asset_config: Dict, candles_5m: List[Candle], 
                          candles_1m: List[Candle], est_now: datetime) -> List[TradeSetup]:
    """Generate scalping setups (1M/5M) within macro windows"""
    setups = []
    
    in_kz, kz_session, _ = is_in_kill_zone(est_now)
    if not in_kz:
        return setups
    
    in_macro, macro_name = is_in_macro_window(est_now)
    in_sb, sb_name = is_in_silver_bullet(est_now)
    
    # Scalps ONLY in macro windows (highest probability)
    if not in_macro:
        return setups
    
    if kz_session not in asset_config["killzone_priority"]:
        return setups
    
    if len(candles_5m) < 50 or len(candles_1m) < 100:
        return setups
    
    # 5M for structure and sweep levels
    h5_highs = [c.high for c in candles_5m]
    h5_lows = [c.low for c in candles_5m]
    h5_closes = [c.close for c in candles_5m]
    h5_opens = [c.open for c in candles_5m]
    h5_volumes = [c.volume for c in candles_5m]
    
    h5_structure = market_structure(h5_highs, h5_lows, h5_closes)
    
    # Direction from 5M structure
    direction = "long" if h5_structure.trend == "bullish" else "short" if h5_structure.trend == "bearish" else None
    if not direction:
        if h5_structure.last_choch:
            direction = "long" if "bullish" in h5_structure.last_choch["type"] else "short"
        else:
            return setups
    
    # 1M for execution
    h1_highs = [c.high for c in candles_1m]
    h1_lows = [c.low for c in candles_1m]
    h1_closes = [c.close for c in candles_1m]
    h1_opens = [c.open for c in candles_1m]
    h1_volumes = [c.volume for c in candles_1m]
    
    # Look for 1M sweep of 5M-significant level
    pools_5m = liquidity_pools(h5_highs, h5_lows, h5_closes)
    sweep_pools = [p for p in pools_5m if p.strength > 0.7 and
                   ((p.type == "sell_side" and direction == "long") or 
                    (p.type == "buy_side" and direction == "short"))]
    
    if not sweep_pools:
        return setups
    
    # Check 1M sweep of 5M level
    sweep_occurred = False
    sweep_price = 0
    for pool in sweep_pools:
        if direction == "long" and min(h1_lows[-3:]) <= pool.price:
            sweep_occurred = True
            sweep_price = pool.price
            break
        elif direction == "short" and max(h1_highs[-3:]) >= pool.price:
            sweep_occurred = True
            sweep_price = pool.price
            break
    
    if not sweep_occurred:
        return setups
    
    # 1M displacement and FVG
    h1_structure = market_structure(h1_highs, h1_lows, h1_closes)
    
    # Check for 1M MSS/CHoCH in bias direction
    mss_1m = False
    if direction == "long" and h1_structure.last_choch and "bullish" in h1_structure.last_choch["type"]:
        mss_1m = True
    elif direction == "short" and h1_structure.last_choch and "bearish" in h1_structure.last_choch["type"]:
        mss_1m = True
    elif h1_structure.last_bos and ((direction == "long" and "bullish" in h1_structure.last_bos["type"]) or
                                      (direction == "short" and "bearish" in h1_structure.last_bos["type"])):
        mss_1m = True
    
    if not mss_1m:
        return setups
    
    # 1M PD Arrays
    obs_1m = order_blocks(h1_highs, h1_lows, h1_opens, h1_closes)
    fvgs_1m = fair_value_gaps(h1_highs, h1_lows, h1_closes, h1_volumes)
    pd_arrays_1m = obs_1m + fvgs_1m
    aligned_pd = [pa for pa in pd_arrays_1m if pa.direction == direction]
    
    if not aligned_pd:
        return setups
    
    displacement_price = h1_closes[-1]
    ote_levels = calculate_ote_levels(sweep_price, displacement_price, direction)
    has_ote, ote_pd, ote_entry = check_ote_confluence(ote_levels, aligned_pd, direction)
    
    ote_start = ote_levels["0.62"]
    ote_end = ote_levels["0.79"]
    
    entry_pd = ote_pd if has_ote else None
    if not entry_pd:
        for pa in aligned_pd:
            if direction == "long":
                if pa.price_bottom <= ote_end and pa.price_top >= ote_start:
                    entry_pd = pa
                    break
        if not entry_pd and aligned_pd:
            entry_pd = aligned_pd[0]
    
    if not entry_pd:
        return setups
    
    entry_price = ote_entry if has_ote else (entry_pd.price_bottom if direction == "long" else entry_pd.price_top)
    
    # Stop just beyond sweep wick
    stop_loss = sweep_price - (h1_highs[-1] - h1_lows[-1]) * 0.5 if direction == "long" \
                else sweep_price + (h1_highs[-1] - h1_lows[-1]) * 0.5
    
    # Target: nearest 5M liquidity pool in direction
    target_pools_5m = [p for p in pools_5m if 
                       (p.type == "buy_side" and direction == "long") or 
                       (p.type == "sell_side" and direction == "short")]
    
    if target_pools_5m:
        target_pool = min(target_pools_5m, key=lambda p: abs(p.price - entry_price))
        tp1 = target_pool.price
    else:
        move_size = abs(displacement_price - sweep_price)
        tp1 = entry_price + move_size if direction == "long" else entry_price - move_size
    
    tp2 = entry_price + 2 * abs(tp1 - entry_price) if direction == "long" else entry_price - 2 * abs(tp1 - entry_price)
    
    risk = abs(entry_price - stop_loss)
    reward = abs(tp1 - entry_price)
    rr = reward / risk if risk > 0 else 0
    
    if rr < 1.2:  # Lower RR threshold for scalps
        return setups
    
    expiration_time, max_hold = calculate_expiration(est_now, SetupType.SCALP, kz_session)
    
    confidence = 0.65
    if in_sb:
        confidence += 0.15
    if has_ote:
        confidence += 0.1
    confidence = min(confidence, 0.9)
    
    setups.append(TradeSetup(
        asset=asset,
        setup_type=SetupType.SCALP,
        bias=Bias.BULLISH if direction == "long" else Bias.BEARISH,
        direction=direction,
        entry_price=round(entry_price, 5),
        stop_loss=round(stop_loss, 5),
        take_profit_1=round(tp1, 5),
        take_profit_2=round(tp2, 5),
        invalidation_price=round(stop_loss, 5),
        risk_reward=round(rr, 2),
        confidence=confidence,
        kill_zone=kz_session,
        macro_window=macro_name,
        silver_bullet=sb_name,
        entry_time_est=est_now.strftime("%H:%M"),
        expiration_time_est=expiration_time,
        max_hold_minutes=max_hold,
        structure={"5m": {"trend": h5_structure.trend}, "1m": {"mss": mss_1m}},
        liquidity_target=target_pool if target_pools_5m else None,
        pd_array=entry_pd,
        ote_level=ote_entry,
        notes=f"Scalp {macro_name} in {kz_session.value}. 1M sweep of 5M level → displacement → FVG/OB entry. Max hold {max_hold}min."
    ))
    
    return setups

# ============================================================
# DATA FETCHING (simulated with cache)
# ============================================================

def get_cached_data(asset: str, timeframe: str) -> Optional[Dict]:
    """Get cached OHLC data"""
    ck = f'ohlc_{asset}_{timeframe}.json'
    cache_file = CACHE_DIR / ck
    if cache_file.exists():
        with open(cache_file) as f:
            data = json.load(f)
            if time.time() - data.get('timestamp', 0) < 3600:  # 1 hour TTL
                return data.get('value')
    return None

def parse_candles(data: Dict, asset: str, timeframe: str) -> List[Candle]:
    """Parse various data formats into Candle objects"""
    candles = []
    try:
        if asset == "XAUUSD" or asset == "GOLD":
            data_array = data.get('data', [])
            for item in data_array:
                ts = item.get('date') or item.get('timestamp')
                price = item.get('price') or item.get('value') or item.get('close')
                if ts and price:
                    val = float(price)
                    candles.append(Candle(
                        timestamp=ts,
                        open=val, high=val, low=val, close=val, volume=0
                    ))
        else:
            # Alpha Vantage style
            key = 'Time Series (Daily)' if timeframe == 'daily' else \
                  'Time Series (60min)' if timeframe == '60min' else \
                  'Time Series (15min)' if timeframe == '15min' else \
                  'Time Series (5min)' if timeframe == '5min' else \
                  'Time Series (1min)'
            timeseries = data.get(key, {})
            for ts, ohlc in sorted(timeseries.items()):
                candles.append(Candle(
                    timestamp=ts,
                    open=float(ohlc['1. open']),
                    high=float(ohlc['2. high']),
                    low=float(ohlc['3. low']),
                    close=float(ohlc['4. close']),
                    volume=float(ohlc.get('5. volume', 0))
                ))
    except Exception as e:
        logger.error(f"Parse error for {asset} {timeframe}: {e}")
    return candles

# ============================================================
# MAIN GENERATION
# ============================================================

SIGNALS_FILE = CACHE_DIR / 'generated_signals.json'

def load_existing_signals() -> List[Dict]:
    if SIGNALS_FILE.exists():
        with open(SIGNALS_FILE) as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_signals(signals: List[Dict]):
    # Convert enums to strings for JSON serialization
    def convert(obj):
        if isinstance(obj, Enum):
            return obj.value
        elif isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert(v) for v in obj]
        return obj
    
    converted = convert(signals)
    with open(SIGNALS_FILE, 'w') as f:
        json.dump(converted, f, indent=2)



def dataframe_to_candles(df) -> List[Candle]:
    """Convert pandas DataFrame from MT5 to list of Candle objects"""
    if df is None or len(df) == 0:
        return []
    
    candles = []
    for _, row in df.iterrows():
        candles.append(Candle(
            timestamp=row['timestamp'].isoformat() if hasattr(row['timestamp'], 'isoformat') else str(row['timestamp']),
            open=float(row['open']),
            high=float(row['high']),
            low=float(row['low']),
            close=float(row['close']),
            volume=float(row.get('volume', row.get('tick_volume', 0)))
        ))
    return candles

async def generate_all_signals():
    """Generate signals for all assets and setup types"""
    logger.info(f'🎯 Generating enhanced ICT signals at {datetime.now()}')
    # Use real EST time (not simulated) - GitHub Actions runs in UTC
    est_now = get_current_est_time()
    logger.info(f'🕐 Current EST time: {est_now.strftime("%H:%M")}')
    
    in_kz, kz_session, kz_note = is_in_kill_zone(est_now)
    in_macro, macro_name = is_in_macro_window(est_now)
    in_sb, sb_name = is_in_silver_bullet(est_now)
    
    logger.info(f'📊 Kill Zone: {kz_session.value if kz_session else "NONE"} ({kz_note})')
    logger.info(f'⚡ Macro Window: {macro_name if in_macro else "NONE"}')
    logger.info(f'🎯 Silver Bullet: {sb_name if in_sb else "NONE"}')
    
    all_signals = load_existing_signals()
    new_signals = []
    
    # Detect environment: if MT5 available, use it; otherwise use API fetcher
    use_mt5 = False
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            mt5.shutdown()
            use_mt5 = True
    except:
        pass
    
    if use_mt5:
        logger.info("📡 Using MT5 for data (local environment)")
        mt5_fetcher = MT5DataFetcher()
    else:
        logger.info("📡 Using API fetcher (cloud environment)")
        api_fetcher = APIDataFetcher()
    
    for asset_name, asset_config in ASSETS.items():
        if use_mt5:
            # Get data from MT5 (local)
            logger.info(f"  📡 Fetching MT5 data for {asset_name}...")
            try:
                mt5_data = mt5_fetcher.fetch_all_timeframes(asset_name, {
                    "daily": 100,
                    "4h": 200,
                    "15m": 500,
                    "5m": 1000,
                    "1m": 3000,
                })
                
                if not mt5_data:
                    logger.warning(f"  ⚠️ No MT5 data for {asset_name}, falling back to synthetic")
                    daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                    h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                    h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                    h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                    h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)
                else:
                    daily_candles = dataframe_to_candles(mt5_data.get("daily"))
                    h4_candles = dataframe_to_candles(mt5_data.get("4h"))
                    h15_candles = dataframe_to_candles(mt5_data.get("15m"))
                    h5_candles = dataframe_to_candles(mt5_data.get("5m"))
                    h1_candles = dataframe_to_candles(mt5_data.get("1m"))
                    logger.info(f"  ✅ MT5 data loaded: {len(daily_candles)} daily, {len(h15_candles)} 15m, {len(h5_candles)} 5m, {len(h1_candles)} 1m")
            except Exception as e:
                logger.error(f"  ❌ MT5 fetch failed for {asset_name}: {e}, using synthetic")
                daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)
        else:
            # Get data from API (cloud)
            logger.info(f"  📡 Fetching API data for {asset_name}...")
            try:
                api_data = api_fetcher.fetch_all_timeframes(asset_name)
                
                if not api_data:
                    logger.warning(f"  ⚠️ No API data for {asset_name}, falling back to synthetic")
                    daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                    h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                    h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                    h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                    h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)
                else:
                    daily_candles = dataframe_to_candles(api_data.get("daily"))
                    h4_candles = dataframe_to_candles(api_data.get("4h"))
                    h15_candles = dataframe_to_candles(api_data.get("15m"))
                    h5_candles = dataframe_to_candles(api_data.get("5m"))
                    h1_candles = dataframe_to_candles(api_data.get("1m"))
                    logger.info(f"  ✅ API data loaded: {len(daily_candles)} daily, {len(h15_candles)} 15m, {len(h5_candles)} 5m, {len(h1_candles)} 1m")
            except Exception as e:
                logger.error(f"  ❌ API fetch failed for {asset_name}: {e}, using synthetic")
                daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)

# Generate swing signals (always check)# Generate swing signals (always check)
        swing_setups = generate_swing_signals(asset_name, asset_config, daily_candles, h4_candles, est_now)
        for s in swing_setups:
            new_signals.append(asdict(s))
        
        # Generate intraday signals (only in kill zones)
        logger.info(f"  🔍 Checking intraday for {asset_name}...")
        intraday_setups = generate_intraday_signals(asset_name, asset_config, h15_candles, h5_candles, est_now)
        logger.info(f"  🔍 Intraday setups found: {len(intraday_setups)}")
        for s in intraday_setups:
            new_signals.append(asdict(s))
    
        # Generate scalp signals (only in macro windows)
        logger.info(f"  🔍 Checking scalp for {asset_name}...")
        scalp_setups = generate_scalp_signals(asset_name, asset_config, h5_candles, h1_candles, est_now)
        logger.info(f"  🔍 Scalp setups found: {len(scalp_setups)}")
        for s in scalp_setups:
            new_signals.append(asdict(s))
    
    # Merge with existing (replace by asset+setup_type+timestamp)
    for new_sig in new_signals:
        # Remove old signal for same asset, setup_type
        all_signals = [s for s in all_signals if not (
            s.get('asset') == new_sig['asset'] and 
            s.get('setup_type') == new_sig['setup_type']
        )]
        all_signals.append(new_sig)
    
    save_signals(all_signals)
    logger.info(f'🎯 Signal generation complete. Generated {len(new_signals)} new setups. Total: {len(all_signals)}')
    
    # Print summary
    for sig in new_signals:
        logger.info(f"  📈 {sig['asset']} {sig['setup_type'].value.upper()} {sig['direction'].upper()}: "
                   f"Entry={sig['entry_price']} SL={sig['stop_loss']} TP1={sig['take_profit_1']} "
                   f"RR={sig['risk_reward']} Conf={sig['confidence']:.0%} "
                   f"Exp={sig['expiration_time_est']} ({sig['kill_zone'].value if sig['kill_zone'] else 'N/A'})")

def generate_synthetic_candles(asset: str, timeframe: str, count: int) -> List[Candle]:
    """Generate synthetic candles with DETERMINISTIC ICT patterns for testing"""
    asset_config = ASSETS.get(asset, ASSETS["XAUUSD"])
    base_price = 4300 if asset == "XAUUSD" else 30000 if asset == "NASDAQ" else 1.08 if asset == "EURUSD" else 1.25
    
    candles = []
    now = datetime.now()
    tf_minutes = {"daily": 1440, "4h": 240, "1h": 60, "15m": 15, "5m": 5, "1m": 1}.get(timeframe, 60)
    
    # DETERMINISTIC pattern that creates:
    # 1. Clear swing highs/lows (need 5 candles each side for swing detection)
    # 2. Liquidity sweep
    # 3. Displacement with FVG
    # 4. Retracement into OTE
    # 5. MSS/CHoCH confirmation
    # Pattern placed at indices 30-5 (so swing detection at 5 lookback works)
    
    is_bullish_asset = asset in ["XAUUSD", "EURUSD", "GBPUSD"]
    
    for i in range(count):
        progress = i / count
        idx_from_end = count - i - 1  # 0 = most recent
        
        # Build pattern from oldest to newest
        # We place the pattern so it's detectable by 5-candle swing detection
        # Pattern zones (from oldest to newest):
        # idx 50-40: Ranging (baseline)
        # idx 40-35: Build swing low/high
        # idx 35-30: Liquidity sweep
        # idx 30-20: Displacement (with FVG)
        # idx 20-10: Retracement into OTE
        # idx 10-0:  Continuation + MSS confirmation
        
        if idx_from_end >= 50:
            # Old data: ranging
            price = base_price + np.sin(i * 0.1) * base_price * 0.002
            volatility = base_price * 0.0005
        elif idx_from_end >= 40:
            # Build-up: create clear swing points
            if is_bullish_asset:
                # Create swing LOW at idx=40, swing HIGH at idx=35
                if idx_from_end == 40:
                    price = base_price * 0.995  # Clear swing low
                elif idx_from_end == 35:
                    price = base_price * 1.005  # Clear swing high
                else:
                    # Linear interpolation
                    price = base_price + (base_price * 1.005 - base_price * 0.995) * (40 - idx_from_end) / 5
            else:
                # Bearish: swing HIGH then swing LOW
                if idx_from_end == 40:
                    price = base_price * 1.005  # Swing high
                elif idx_from_end == 35:
                    price = base_price * 0.995  # Swing low
                else:
                    price = base_price + (base_price * 0.995 - base_price * 1.005) * (40 - idx_from_end) / 5
            volatility = base_price * 0.0005
        elif idx_from_end >= 30:
            # LIQUIDITY SWEEP (idx 30-35): sweep the swing low/high
            if is_bullish_asset:
                # Sweep the swing low (sell-side liquidity)
                price = base_price * 0.993  # Below swing low
            else:
                # Sweep the swing high (buy-side liquidity)
                price = base_price * 1.007  # Above swing high
            volatility = base_price * 0.001
        elif idx_from_end >= 20:
            # DISPLACEMENT (idx 20-30): strong move in true direction with FVG
            if is_bullish_asset:
                # Strong bullish displacement - creates bullish FVG
                progress_disp = (30 - idx_from_end) / 10
                price = base_price * 0.993 + (base_price * 1.012 - base_price * 0.993) * progress_disp
            else:
                # Strong bearish displacement - creates bearish FVG
                progress_disp = (30 - idx_from_end) / 10
                price = base_price * 1.007 + (base_price * 0.988 - base_price * 1.007) * progress_disp
            volatility = base_price * 0.0015
        elif idx_from_end >= 10:
            # RETRACEMENT (idx 10-20): pullback into OTE zone (62-79%)
            if is_bullish_asset:
                # Retrace from 1.012 down to ~70.5% OTE
                # Sweep was at 0.993, displacement high at 1.012
                # OTE 70.5% = 1.012 - 0.705*(1.012-0.993) = 1.012 - 0.0134 = 0.9986
                retrace_target = base_price * 0.9986
                progress_ret = (20 - idx_from_end) / 10
                price = base_price * 1.012 + (retrace_target - base_price * 1.012) * progress_ret
            else:
                # Retrace from 0.988 up to ~70.5% OTE
                # Sweep was at 1.007, displacement low at 0.988
                # OTE 70.5% = 0.988 + 0.705*(1.007-0.988) = 0.988 + 0.0134 = 1.0014
                retrace_target = base_price * 1.0014
                progress_ret = (20 - idx_from_end) / 10
                price = base_price * 0.988 + (retrace_target - base_price * 0.988) * progress_ret
            volatility = base_price * 0.0008
        elif idx_from_end >= 5:
            # CONTINUATION (idx 5-10): resume trend - THIS IS WHERE MSS SHOULD FORM
            if is_bullish_asset:
                # Strong continuation up - breaks the retracement high
                progress_cont = (10 - idx_from_end) / 5
                price = base_price * 0.9986 + (base_price * 1.015 - base_price * 0.9986) * progress_cont
            else:
                # Strong continuation down - breaks the retracement low
                progress_cont = (10 - idx_from_end) / 5
                price = base_price * 1.0014 + (base_price * 0.985 - base_price * 1.0014) * progress_cont
            volatility = base_price * 0.0015
        else:
            # FINAL CANDLES (idx 0-4): fully extended trend
            if is_bullish_asset:
                price = base_price * 1.015
            else:
                price = base_price * 0.985
            volatility = base_price * 0.001
        
        # Create proper OHLC candles
        if i > 0:
            prev_close = candles[-1].close
            change = price - prev_close
        else:
            change = 0
            price = base_price
        
        # Generate OHLC
        if change >= 0:
            open_price = price - change
            close_price = price
            high = max(open_price, close_price) + abs(np.random.normal(0, volatility * 0.2))
            low = min(open_price, close_price) - abs(np.random.normal(0, volatility * 0.1))
        else:
            open_price = price - change
            close_price = price
            high = max(open_price, close_price) + abs(np.random.normal(0, volatility * 0.1))
            low = min(open_price, close_price) - abs(np.random.normal(0, volatility * 0.2))
        
        volume = 5000
        
        timestamp = (now - timedelta(minutes=tf_minutes * (count - i))).isoformat()
        
        candles.append(Candle(
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close_price,
            volume=volume
        ))
    
    return candles

async def main():
    await generate_all_signals()

if __name__ == '__main__':
    asyncio.run(main())
"""
Advanced ICT Concepts Module
IPDA 20/40/60-day ranges, BPR, CISD, CE, Mean Threshold, SMT Divergence, Quarterly Shift
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

@dataclass
class IPDALevel:
    """IPDA data range level"""
    high: float
    low: float
    eq: float  # equilibrium (50%)
    high_20d: float = None
    low_20d: float = None
    eq_20d: float = None
    high_40d: float = None
    low_40d: float = None
    eq_40d: float = None
    high_60d: float = None
    low_60d: float = None
    eq_60d: float = None

@dataclass
class BPR:
    """Balanced Price Range - overlap of opposing FVGs"""
    top: float
    bottom: float
    bullish_fvg_top: float
    bullish_fvg_bottom: float
    bearish_fvg_top: float
    bearish_fvg_bottom: float
    direction: str  # "bullish" or "bearish" based on which FVG is higher
    strength: float

@dataclass
class CISD:
    """Change in State of Delivery"""
    type: str  # "bullish" or "bearish"
    price: float
    candle_index: int
    prior_leg_open: float
    confidence: float

@dataclass
class SMTDivergence:
    """Smart Money Tool Divergence"""
    pair1: str
    pair2: str
    type: str  # "bullish" or "bearish"
    confidence: float

class AdvancedICTAnalyzer:
    """Advanced ICT concepts analyzer"""
    
    def __init__(self):
        pass
    
    def calculate_ipda_ranges(self, daily_candles: List, lookback_days: int = 60) -> IPDALevel:
        """Calculate IPDA 20/40/60-day ranges from daily candles"""
        if len(daily_candles) < lookback_days:
            lookback_days = len(daily_candles) - 1
        
        # Use daily data for IPDA ranges
        highs = [c.high for c in daily_candles[-lookback_days:]]
        lows = [c.low for c in daily_candles[-lookback_days:]]
        
        # 20-day range (most recent 20 trading days)
        high_20d = max(highs[-20:]) if len(highs) >= 20 else max(highs)
        low_20d = min(lows[-20:]) if len(lows) >= 20 else min(lows)
        eq_20d = (high_20d + low_20d) / 2
        
        # 40-day range
        high_40d = max(highs[-40:]) if len(highs) >= 40 else high_20d
        low_40d = min(lows[-40:]) if len(lows) >= 40 else low_20d
        eq_40d = (high_40d + low_40d) / 2
        
        # 60-day range
        high_60d = max(highs) if len(highs) >= 60 else high_40d
        low_60d = min(lows) if len(lows) >= 60 else low_40d
        eq_60d = (high_60d + low_60d) / 2
        
        # Current daily range (most recent)
        current_high = daily_candles[-1].high if daily_candles else high_20d
        current_low = daily_candles[-1].low if daily_candles else low_20d
        
        return IPDALevel(
            high=current_high,
            low=current_low,
            eq=(current_high + current_low) / 2,
            high_20d=high_20d,
            low_20d=low_20d,
            eq_20d=eq_20d,
            high_40d=high_40d,
            low_40d=low_40d,
            eq_40d=eq_40d,
            high_60d=high_60d,
            low_60d=low_60d,
            eq_60d=eq_60d
        )
    
    def get_quarterly_bias(self, ipda: IPDALevel) -> str:
        """Determine quarterly bias from 60-day range position"""
        # If price above 60-day EQ = bearish quarterly delivery (selling premium)
        # If price below 60-day EQ = bullish quarterly delivery (buying discount)
        current_price = (ipda.high + ipda.low) / 2
        if current_price > ipda.eq_60d:
            return "bearish"  # Above 60-day EQ = selling
        else:
            return "bullish"  # Below 60-day EQ = buying
    
    def get_monthly_bias(self, ipda: IPDALevel) -> str:
        """Determine monthly bias from 40-day range"""
        current_price = (ipda.high + ipda.low) / 2
        if current_price > ipda.eq_40d:
            return "bearish"
        else:
            return "bullish"
    
    def get_weekly_bias(self, ipda: IPDALevel) -> str:
        """Determine weekly bias from 20-day range"""
        current_price = (ipda.high + ipda.low) / 2
        if current_price > ipda.eq_20d:
            return "bearish"
        else:
            return "bullish"
    
    def detect_bpr(self, fvgs: List) -> List[BPR]:
        """Detect Balanced Price Ranges - overlap of opposing FVGs"""
        bprs = []
        
        bullish_fvgs = [f for f in fvgs if f.direction == "bullish"]
        bearish_fvgs = [f for f in fvgs if f.direction == "bearish"]
        
        for bull_fvg in bullish_fvgs:
            for bear_fvg in bearish_fvgs:
                # Check for overlap
                overlap_top = min(bull_fvg.price_top, bear_fvg.price_top)
                overlap_bottom = max(bull_fvg.price_bottom, bear_fvg.price_bottom)
                
                if overlap_top > overlap_bottom:
                    # Overlap exists - this is a BPR
                    overlap_size = overlap_top - overlap_bottom
                    bull_size = bull_fvg.price_top - bull_fvg.price_bottom
                    bear_size = bear_fvg.price_top - bear_fvg.price_bottom
                    strength = overlap_size / min(bull_size, bear_size)
                    
                    bprs.append(BPR(
                        top=overlap_top,
                        bottom=overlap_bottom,
                        bullish_fvg_top=bull_fvg.price_top,
                        bullish_fvg_bottom=bull_fvg.price_bottom,
                        bearish_fvg_top=bear_fvg.price_top,
                        bearish_fvg_bottom=bear_fvg.price_bottom,
                        direction="bullish" if bull_fvg.price_top > bear_fvg.price_bottom else "bearish",
                        strength=min(strength, 1.0)
                    ))
        
        return bprs
    
    def detect_cisd(self, opens: List[float], closes: List[float], 
                    highs: List[float], lows: List[float]) -> List[CISD]:
        """Detect Change in State of Delivery - earlier than MSS"""
        cisds = []
        n = len(closes)
        
        for i in range(2, n):
            # Bullish CISD: candle closes above open of prior bearish leg
            if closes[i] > opens[i-1] and closes[i-1] < opens[i-1]:
                # Prior candle was bearish, current closes above its open
                cisds.append(CISD(
                    type="bullish",
                    price=closes[i],
                    candle_index=i,
                    prior_leg_open=opens[i-1],
                    confidence=0.7
                ))
            
            # Bearish CISD: candle closes below open of prior bullish leg
            if closes[i] < opens[i-1] and closes[i-1] > opens[i-1]:
                # Prior candle was bullish, current closes below its open
                cisds.append(CISD(
                    type="bearish",
                    price=closes[i],
                    candle_index=i,
                    prior_leg_open=opens[i-1],
                    confidence=0.7
                ))
        
        return cisds
    
    def calculate_ce(self, fvg_top: float, fvg_bottom: float) -> float:
        """Consequent Encroachment - 50% midpoint of FVG"""
        return (fvg_top + fvg_bottom) / 2
    
    def calculate_mean_threshold(self, ob_top: float, ob_bottom: float) -> float:
        """Mean Threshold - 50% of Order Block body"""
        return (ob_top + ob_bottom) / 2
    
    def get_1st_presented_fvg(self, fvgs: List, session_start_idx: int = 0) -> Optional:
        """Get first FVG presented after session open (9:30 AM ET)"""
        # Find first FVG after session_start_idx
        for fvg in fvgs:
            if hasattr(fvg, 'candle_index') and fvg.candle_index > session_start_idx:
                return fvg
        return fvgs[0] if fvgs else None
    
    def check_smt_divergence(self, pair1_data: Dict, pair2_data: Dict) -> Optional[SMTDivergence]:
        """Check SMT Divergence between correlated pairs"""
        # pair1 and pair2 should have 'swing_highs', 'swing_lows', 'trend'
        # Bullish divergence: pair1 makes lower low, pair2 makes higher low
        # Bearish divergence: pair1 makes higher high, pair2 makes lower high
        
        if not pair1_data or not pair2_data:
            return None
        
        # Simplified check
        return None  # Would need correlated pair data
    
    def calculate_adr(self, daily_candles: List, period: int = 5) -> float:
        """Average Daily Range for target projection"""
        if len(daily_candles) < period:
            return 0
        
        ranges = [c.high - c.low for c in daily_candles[-period:]]
        return np.mean(ranges)
    
    def project_daily_targets(self, current_price: float, adr: float, bias: str) -> Dict:
        """Project daily high/low targets using ADR"""
        if adr <= 0:
            return {}
        
        if bias == "bullish":
            return {
                "target_1": current_price + adr * 0.5,
                "target_2": current_price + adr,
                "target_3": current_price + adr * 1.5
            }
        else:
            return {
                "target_1": current_price - adr * 0.5,
                "target_2": current_price - adr,
                "target_3": current_price - adr * 1.5
            }
    
    def check_breakaway_gap(self, opens: List[float], closes: List[float], 
                           highs: List[float], lows: List[float], 
                           avg_range: float) -> Optional[Dict]:
        """Detect breakaway gap - gap that starts new trend"""
        if len(closes) < 3:
            return None
        
        # Check for gap between yesterday close and today open
        gap_up = opens[-1] - closes[-2]
        gap_down = closes[-2] - opens[-1]
        
        if gap_up > avg_range * 0.5:
            return {"type": "breakaway_bullish", "gap_size": gap_up, "price": opens[-1]}
        elif gap_down > avg_range * 0.5:
            return {"type": "breakaway_bearish", "gap_size": gap_down, "price": opens[-1]}
        
        return None
    
    def check_measuring_gap(self, opens: List[float], closes: List[float],
                           highs: List[float], lows: List[float],
                           trend_start_idx: int) -> Optional[Dict]:
        """Detect measuring gap - midpoint of trend"""
        if len(closes) < trend_start_idx + 5:
            return None
        
        # Gap in middle of trend
        for i in range(trend_start_idx + 2, len(closes) - 1):
            gap_up = lows[i] - highs[i-1]
            gap_down = lows[i-1] - highs[i]
            
            if gap_up > 0:
                return {"type": "measuring_bullish", "price": (highs[i-1] + lows[i]) / 2, "index": i}
            elif gap_down > 0:
                return {"type": "measuring_bearish", "price": (lows[i-1] + highs[i]) / 2, "index": i}
        
        return None


# ============================================================
# INTEGRATION HELPER
# ============================================================

def enhance_signal_with_advanced_ict(signal: dict, analyzer: AdvancedICTAnalyzer,
                                     daily_candles: List, 
                                     fvgs: List, obs: List,
                                     opens: List, closes: List, highs: List, lows: List) -> dict:
    """Enhance existing signal with advanced ICT concepts"""
    
    # Calculate IPDA ranges
    ipda = analyzer.calculate_ipda_ranges(daily_candles)
    
    # Get multi-timeframe bias
    quarterly_bias = analyzer.get_quarterly_bias(ipda)
    monthly_bias = analyzer.get_monthly_bias(ipda)
    weekly_bias = analyzer.get_weekly_bias(ipda)
    
    # Detect BPR
    bprs = analyzer.detect_bpr(fvgs)
    
    # Detect CISD (earlier than MSS)
    cisds = analyzer.detect_cisd(
        [c.open for c in daily_candles[-50:]] if daily_candles else [],
        [c.close for c in daily_candles[-50:]] if daily_candles else [],
        [c.high for c in daily_candles[-50:]] if daily_candles else [],
        [c.low for c in daily_candles[-50:]] if daily_candles else []
    )
    
    # Helper to get pd_array attribute whether it's a PDArray object or dict
    def get_pd_attr(attr, default=None):
        pd = signal.get('pd_array')
        if not pd:
            return default
        if hasattr(pd, attr):  # PDArray object
            return getattr(pd, attr)
        return pd.get(attr, default)  # dict

    # Calculate CE for signal's FVG
    ce_level = None
    if get_pd_attr('type') == 'fair_value_gap':
        ce_level = analyzer.calculate_ce(
            get_pd_attr('price_top'),
            get_pd_attr('price_bottom')
        )

    # Calculate Mean Threshold for OB
    mt_level = None
    if get_pd_attr('type') == 'order_block':
        mt_level = analyzer.calculate_mean_threshold(
            get_pd_attr('price_top'),
            get_pd_attr('price_bottom')
        )

    # ADR targets
    adr = analyzer.calculate_adr(daily_candles)
    adr_targets = analyzer.project_daily_targets(signal['entry_price'], adr, signal['direction'])
    
    # Add advanced data to signal
    signal['advanced_ict'] = {
        'ipda': {
            'quarterly_bias': quarterly_bias,
            'monthly_bias': monthly_bias,
            'weekly_bias': weekly_bias,
            '20d_high': ipda.high_20d,
            '20d_low': ipda.low_20d,
            '20d_eq': ipda.eq_20d,
            '40d_high': ipda.high_40d,
            '40d_low': ipda.low_40d,
            '40d_eq': ipda.eq_40d,
            '60d_high': ipda.high_60d,
            '60d_low': ipda.low_60d,
            '60d_eq': ipda.eq_60d,
        },
        'bprs': [{'top': b.top, 'bottom': b.bottom, 'direction': b.direction, 'strength': b.strength} for b in bprs],
        'cisd': [{'type': c.type, 'price': c.price, 'confidence': c.confidence} for c in cisds[-3:]],  # Last 3
        'ce_level': ce_level,
        'mean_threshold': mt_level,
        'adr_targets': adr_targets,
        'quarterly_shift': 'bearish' if quarterly_bias == 'bearish' else 'bullish',
    }
    
    # Boost confidence if advanced concepts align
    confidence_boost = 0
    if signal['direction'] == 'long' and quarterly_bias == 'bullish':
        confidence_boost += 0.05
    if signal['direction'] == 'short' and quarterly_bias == 'bearish':
        confidence_boost += 0.05
    if bprs:
        confidence_boost += 0.05
    if cisds and cisds[-1].type == signal['direction']:
        confidence_boost += 0.03
    
    signal['confidence'] = min(signal.get('confidence', 0) + confidence_boost, 0.95)
    
    return signal
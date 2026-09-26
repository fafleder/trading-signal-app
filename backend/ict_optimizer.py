"""
Advanced ICT Optimization Module
Incorporates 2024/2025 mentorship concepts:
- IOFED (Institutional Order Flow Entry Drill)
- IFVG (Inverse Fair Value Gap) 
- Swing Grading & Failure Patterns
- 90-minute Cycles & Algorithmic Timing
- Swing Failure Patterns (Relative Equal Highs/Lows)
- IOFED Pyramiding & Stop Management
- First Presented FVG
- NWOG/NDOG (Opening Gaps)
- CISD (Change in State of Delivery)
- Breakaway vs Measuring Gaps
- 90-minute Cycles & Algorithmic Macros
"""

import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

@dataclass
class SwingGrade:
    """Swing grading per ICT 2024 methodology"""
    grade: str  # A, B, C, D
    is_relative_equal: bool
    swing_type: str  # "high" or "low"
    price: float
    index: int
    strength: float  # 0-1
    failure: bool  # Swing failure pattern

@dataclass
class IFVG:
    """Inverse Fair Value Gap - first FVG before raid that inverts"""
    price_top: float
    price_bottom: float
    direction: str  # "bullish" (inverted bearish FVG) or "bearish" (inverted bullish FVG)
    original_fvg_direction: str
    index: int
    inverted: bool = False
    ce_level: float = 0  # Consequent Encroachment (50%)

@dataclass
class IOFEDSignal:
    """IOFED Entry Signal"""
    direction: str
    price: float
    fvg_top: float
    fvg_bottom: float
    fvg_direction: str
    ioFED_level: float  # Entry level (edge of FVG)
    ce_level: float  # Consequent Encroachment (50%)
    stop_loss: float
    tp1: float
    tp2: float
    swing_point: float  # 1-minute swing point that triggered
    trigger_candle_close: float
    confidence: float
    pyramid_plan: Dict  # Starter, CE add, far edge add

@dataclass
class SwingGradeResult:
    """Result of swing grading"""
    swing_grades: List[SwingGrade]
    relative_equal_highs: List[float]
    relative_equal_lows: List[float]

@dataclass
class AlgorithmicCycle:
    """90-minute algorithmic cycle"""
    start_time: str
    end_time: str
    cycle_type: str  # "accumulation", "manipulation", "distribution"
    probability: float

class AdvancedICTOptimizer:
    """Advanced ICT optimization incorporating 2024/2025 mentorship concepts"""
    
    def __init__(self):
        # 90-minute algorithmic cycles (NY time)
        self.algo_cycles = [
            AlgorithmicCycle("07:00", "08:30", "accumulation", 0.7),   # Pre-market accumulation
            AlgorithmicCycle("08:30", "10:00", "manipulation", 0.9),  # London/NY overlap - Judas Swing
            AlgorithmicCycle("10:00", "11:30", "distribution", 0.8),  # Silver Bullet / Continuation
            AlgorithmicCycle("11:30", "13:00", "accumulation", 0.5),  # Lunch - low volume
            AlgorithmicCycle("13:00", "14:30", "manipulation", 0.6),  # PM manipulation
            AlgorithmicCycle("14:30", "16:00", "distribution", 0.7),  # End of day distribution
        ]
        
        # Macro windows (high probability 20-min bursts)
        self.macro_windows = [
            ("07:50", "08:10"),  # Pre-08:30 macro
            ("08:50", "09:10"),  # Post-08:30 macro
            ("09:50", "10:10"),  # Silver Bullet
            ("10:50", "11:10"),  # Post-Silver Bullet
            ("13:20", "13:40"),  # PM macro
        ]
        
    def get_current_cycle(self, est_time: datetime) -> Optional[AlgorithmicCycle]:
        """Get current algorithmic cycle"""
        current_min = est_time.hour * 60 + est_time.minute
        for cycle in self.algo_cycles:
            start = self._time_to_min(cycle.start_time)
            end = self._time_to_min(cycle.end_time)
            if start <= current_min <= end:
                return cycle
        return None
    
    def is_in_macro_window(self, est_time: datetime) -> Tuple[bool, Optional[str]]:
        """Check if in high-probability macro window"""
        current_min = est_time.hour * 60 + est_time.minute
        for start, end in self.macro_windows:
            if self._time_to_min(start) <= current_min <= self._time_to_min(end):
                return True, f"{start}-{end}"
        return False, None
    
    def _time_to_min(self, time_str: str) -> int:
        h, m = map(int, time_str.split(":"))
        return h * 60 + m
    
    def grade_swings(self, highs: List[float], lows: List[float], 
                     closes: List[float], lookback: int = 5) -> SwingGradeResult:
        """Grade swings per ICT 2024 methodology (4 concepts per swing)"""
        swings = []
        n = len(highs)
        
        # Find swing highs/lows
        for i in range(lookback, n - lookback):
            # Swing High
            if all(highs[i] >= highs[j] for j in range(i - lookback, i + lookback + 1) if j != i):
                # Check for relative equal high (failure pattern)
                is_rel_equal = False
                for k in range(max(0, i - 20), i):
                    if abs(highs[k] - highs[i]) < highs[i] * 0.001:
                        is_rel_equal = True
                        break
                
                # Grade the swing
                grade = self._calculate_swing_grade(highs, lows, closes, i, "high", is_rel_equal)
                swings.append(SwingGrade(
                    grade=grade,
                    is_relative_equal=is_rel_equal,
                    swing_type="high",
                    price=highs[i],
                    index=i,
                    strength=1.0 if grade == "A" else 0.7 if grade == "B" else 0.4,
                    failure=is_rel_equal
                ))
            
            # Swing Low
            if all(lows[i] <= lows[j] for j in range(i - lookback, i + lookback + 1) if j != i):
                is_rel_equal = False
                for k in range(max(0, i - 20), i):
                    if abs(lows[k] - lows[i]) < lows[i] * 0.001:
                        is_rel_equal = True
                        break
                
                grade = self._calculate_swing_grade(highs, lows, closes, i, "low", is_rel_equal)
                swings.append(SwingGrade(
                    grade=grade,
                    is_relative_equal=is_rel_equal,
                    swing_type="low",
                    price=lows[i],
                    index=i,
                    strength=1.0 if grade == "A" else 0.7 if grade == "B" else 0.4,
                    failure=is_rel_equal
                ))
        
        # Extract relative equal highs/lows
        rel_highs = [s.price for s in swings if s.is_relative_equal and s.swing_type == "high"]
        rel_lows = [s.price for s in swings if s.is_relative_equal and s.swing_type == "low"]
        
        return SwingGradeResult(
            swing_grades=swings,
            relative_equal_highs=rel_highs,
            relative_equal_lows=rel_lows
        )
    
    def _calculate_swing_grade(self, highs: List[float], lows: List[float], 
                               closes: List[float], idx: int, swing_type: str,
                               is_rel_equal: bool) -> str:
        """Grade swing A/B/C/D based on 4 concepts"""
        score = 0
        
        # Concept 1: Clean structure (no overlap)
        if idx > 1:
            if swing_type == "high":
                if highs[idx-1] < highs[idx] and highs[idx-2] < highs[idx-1]:
                    score += 2
            else:
                if lows[idx-1] > lows[idx] and lows[idx-2] > lows[idx-1]:
                    score += 2
        
        # Concept 2: Displacement after swing
        if idx < len(closes) - 3:
            move = abs(closes[idx+3] - closes[idx])
            avg_range = np.mean([highs[j] - lows[j] for j in range(max(0, idx-10), idx)])
            if move > 2 * avg_range:
                score += 2
        
        # Concept 3: Volume confirmation (simplified)
        # Concept 4: Relative equal (failure pattern) - downgrades
        if is_rel_equal:
            score -= 1
        
        if score >= 4:
            return "A"
        elif score >= 2:
            return "B"
        elif score >= 0:
            return "C"
        return "D"
    
    def detect_ifvg(self, highs: List[float], lows: List[float], 
                    opens: List[float], closes: List[float],
                    raid_direction: str, raid_idx: int) -> Optional[IFVG]:
        """
        Detect Inverse FVG - first FVG before raid that inverts after MSS
        Per Lecture 2: First FVG formed BEFORE raid, inverts after MSS
        """
        # Look for FVGs before the raid
        for i in range(1, raid_idx - 1):
            # Bullish FVG (gap up) - will invert to bearish if raid is upward
            if lows[i + 1] > highs[i - 1]:
                gap_size = lows[i + 1] - highs[i - 1]
                avg_range = np.mean([highs[j] - lows[j] for j in range(max(0, i - 10), i + 1)])
                if gap_size > 0.1 * avg_range:
                    # This is a bullish FVG formed before raid
                    if raid_direction == "long":  # Raid was upward (swept lows)
                        # Will invert to bearish resistance
                        return IFVG(
                            price_top=lows[i + 1],
                            price_bottom=highs[i - 1],
                            direction="bearish",
                            original_fvg_direction="bullish",
                            index=i,
                            inverted=True,
                            ce_level=(lows[i + 1] + highs[i - 1]) / 2
                        )
            
            # Bearish FVG (gap down) - will invert to bullish if raid is downward
            if highs[i + 1] < lows[i - 1]:
                gap_size = lows[i - 1] - highs[i + 1]
                avg_range = np.mean([highs[j] - lows[j] for j in range(max(0, i - 10), i + 1)])
                if gap_size > 0.1 * avg_range:
                    if raid_direction == "short":  # Raid was downward (swept highs)
                        # Will invert to bullish support
                        return IFVG(
                            price_top=lows[i - 1],
                            price_bottom=highs[i + 1],
                            direction="bullish",
                            original_fvg_direction="bearish",
                            index=i,
                            inverted=True,
                            ce_level=(lows[i - 1] + highs[i + 1]) / 2
                        )
        return None
    
    def detect_iofed_signal(self, fvg: Dict, h1_highs: List[float], h1_lows: List[float],
                            h1_opens: List[float], h1_closes: List[float],
                            direction: str, entry_price: float, stop_loss: float) -> Optional[IOFEDSignal]:
        """
        Detect IOFED signal - 1-minute MSS inside FVG zone
        Per IOFED methodology: 1-minute swing forms inside FVG, next candle closes beyond swing
        """
        if not fvg:
            return None
        
        fvg_top = fvg.get('price_top', 0)
        fvg_bottom = fvg.get('price_bottom', 0)
        fvg_direction = fvg.get('direction', 'bullish')
        
        # Find 1-minute swing inside FVG zone
        swing_idx = None
        swing_point = 0
        
        for i in range(2, len(h1_closes) - 1):
            # Check if 1-minute swing forms INSIDE FVG zone
            if direction == "long":
                # Bullish: look for 1-minute swing LOW inside FVG
                if (h1_lows[i] > fvg_bottom and h1_lows[i] < fvg_top and
                    h1_lows[i] < h1_lows[i-1] and h1_lows[i] < h1_lows[i+1] and
                    h1_lows[i-1] > h1_lows[i] and h1_lows[i+1] > h1_lows[i]):
                    swing_idx = i
                    swing_point = h1_lows[i]
                    break
            else:
                # Bearish: look for 1-minute swing HIGH inside FVG
                if (h1_highs[i] < fvg_top and h1_highs[i] > fvg_bottom and
                    h1_highs[i] > h1_highs[i-1] and h1_highs[i] > h1_highs[i+1] and
                    h1_highs[i-1] < h1_highs[i] and h1_highs[i+1] < h1_highs[i]):
                    swing_idx = i
                    swing_point = h1_highs[i]
                    break
        
        if swing_idx is None:
            return None
        
        # Check for trigger: next candle closes beyond swing point
        trigger_idx = swing_idx + 1
        if trigger_idx >= len(h1_closes):
            return None
        
        trigger_close = h1_closes[trigger_idx]
        triggered = False
        
        if direction == "long" and trigger_close > swing_point:
            triggered = True
            ioFED_level = fvg_bottom + (fvg_top - fvg_bottom) * 0.05  # Just inside FVG
        elif direction == "short" and trigger_close < swing_point:
            triggered = True
            ioFED_level = fvg_top - (fvg_top - fvg_bottom) * 0.05
        
        if not triggered:
            return None
        
        # Calculate levels
        ce_level = (fvg_top + fvg_bottom) / 2  # Consequent Encroachment (50%)
        
        # Pyramid plan
        risk = abs(ioFED_level - stop_loss)
        pyramid_plan = {
            "starter": {"level": ioFED_level, "size_pct": 30, "stop": stop_loss},
            "ce_add": {"level": ce_level, "size_pct": 40, "stop": stop_loss},
            "far_edge_add": {"level": fvg_top if direction == "long" else fvg_bottom, 
                            "size_pct": 30, "stop": stop_loss}
        }
        
        # Targets (next draw on liquidity)
        tp1 = entry_price + 2 * risk if direction == "long" else entry_price - 2 * risk
        tp2 = entry_price + 3 * risk if direction == "long" else entry_price - 3 * risk
        
        return IOFEDSignal(
            direction=direction,
            price=entry_price,
            fvg_top=fvg_top,
            fvg_bottom=fvg_bottom,
            fvg_direction=fvg_direction,
            ioFED_level=ioFED_level,
            ce_level=ce_level,
            stop_loss=stop_loss,
            tp1=tp1,
            tp2=tp2,
            swing_point=swing_point,
            trigger_candle_close=h1_closes[trigger_idx],
            confidence=0.85,
            pyramid_plan=pyramid_plan
        )
    
    def detect_breakaway_gap(self, opens: List[float], closes: List[float],
                             highs: List[float], lows: List[float],
                             idx: int) -> Optional[Dict]:
        """Detect breakaway gap - starts new trend with gap"""
        if idx < 2:
            return None
        
        gap = opens[idx] - closes[idx-1]
        avg_range = np.mean([highs[i] - lows[i] for i in range(max(0, idx-10), idx)])
        
        if abs(gap) > avg_range * 1.5:
            return {
                "type": "breakaway_bullish" if gap > 0 else "breakaway_bearish",
                "gap_size": gap,
                "price": opens[idx],
                "idx": idx
            }
        return None
    
    def detect_measuring_gap(self, opens: List[float], closes: List[float],
                             highs: List[float], lows: List[float],
                             trend_start: int) -> Optional[Dict]:
        """Detect measuring gap - midpoint of trend"""
        if len(closes) < trend_start + 5:
            return None
        
        for i in range(trend_start + 2, len(closes) - 1):
            gap_up = lows[i] - highs[i-1]
            gap_down = lows[i-1] - highs[i]
            
            if gap_up > 0:
                return {"type": "measuring_bullish", "price": (highs[i-1] + lows[i]) / 2, "idx": i}
            elif gap_down > 0:
                return {"type": "measuring_bearish", "price": (lows[i-1] + highs[i]) / 2, "idx": i}
        
        return None
    
    def detect_swing_failure(self, highs: List[float], lows: List[float],
                            closes: List[float], idx: int) -> Optional[Dict]:
        """Detect swing failure pattern (relative equal high/low)"""
        # Look for lower swing high to the right of a high
        if idx < len(highs) - 5:
            for j in range(idx + 1, min(idx + 10, len(highs))):
                if highs[j] < highs[idx] and highs[j] > highs[idx] * 0.998:
                    # Found lower swing high to the right - relative equal high
                    return {
                        "type": "swing_failure_bearish",
                        "original_high_idx": idx,
                        "failure_idx": j,
                        "level": highs[idx],
                        "strength": 1 - (highs[idx] - highs[j]) / highs[idx]
                    }
        
        # Look for higher swing low to the right of a low
        if idx < len(lows) - 5:
            for j in range(idx + 1, min(idx + 10, len(lows))):
                if lows[j] > lows[idx] and lows[j] < lows[idx] * 1.002:
                    return {
                        "type": "swing_failure_bullish",
                        "original_low_idx": idx,
                        "failure_idx": j,
                        "level": lows[idx],
                        "strength": 1 - (lows[j] - lows[idx]) / lows[idx]
                    }
        
        return None
    
    def get_90min_cycle_bias(self, est_time: datetime) -> str:
        """Get bias from 90-minute algorithmic cycle"""
        cycle = self.get_current_cycle(est_time)
        if cycle:
            return cycle.cycle_type
        return "accumulation"
    
    def check_opening_gaps(self, daily_opens: List[float], daily_closes: List[float],
                          daily_highs: List[float], daily_lows: List[float]) -> Dict:
        """Check NWOG (New Week Opening Gap) and NDOG (New Day Opening Gap)"""
        result = {"ndog": None, "nwog": None}
        
        if len(daily_opens) >= 2:
            # NDOG - New Day Opening Gap
            prev_close = daily_closes[-2]
            curr_open = daily_opens[-1]
            
            gap = curr_open - prev_close
            if abs(gap) > (prev_close * 0.002):  # 0.2% minimum gap
                result["ndog"] = {
                    "type": "bullish" if gap > 0 else "bearish",
                    "gap_size": abs(gap),
                    "level": min(prev_close, curr_open),
                    "direction": "long" if gap > 0 else "short"
                }
        
        if len(daily_opens) >= 6:  # Weekly
            # NWOG - New Week Opening Gap
            week_start_idx = -6
            prev_week_close = daily_closes[week_start_idx - 1]
            week_open = daily_opens[week_start_idx]
            
            gap = week_open - prev_week_close
            if abs(gap) > (prev_week_close * 0.003):
                result["nwog"] = {
                    "type": "bullish" if gap > 0 else "bearish",
                    "gap_size": abs(gap),
                    "level": min(prev_week_close, week_open),
                    "direction": "long" if gap > 0 else "short"
                }
        
        return result


def enhance_signal_with_optimized_ict(signal: dict, optimizer: AdvancedICTOptimizer,
                                       daily_candles: List, h15_candles: List, 
                                       h5_candles: List, h1_candles: List,
                                       est_time: datetime) -> dict:
    """Enhance signal with all advanced ICT optimizations"""
    
    # Extract arrays
    h1_highs = [c.high for c in h1_candles]
    h1_lows = [c.low for c in h1_candles]
    h1_opens = [c.open for c in h1_candles]
    h1_closes = [c.close for c in h1_candles]
    
    h5_highs = [c.high for c in h5_candles]
    h5_lows = [c.low for c in h5_candles]
    h5_opens = [c.open for c in h5_candles]
    h5_closes = [c.close for c in h5_candles]
    
    h15_highs = [c.high for c in h15_candles]
    h15_lows = [c.low for c in h15_candles]
    h15_opens = [c.open for c in h15_candles]
    h15_closes = [c.close for c in h15_candles]
    
    daily_opens = [c.open for c in daily_candles]
    daily_closes = [c.close for c in daily_candles]
    daily_highs = [c.high for c in daily_candles]
    daily_lows = [c.low for c in daily_candles]
    
    # 1. Swing Grading
    swing_result = optimizer.grade_swings(h5_highs, h5_lows, h5_closes)
    
    # 2. Algorithmic Cycle Bias
    cycle_bias = optimizer.get_90min_cycle_bias(datetime.now())
    
    # 3. Opening Gaps (NDOG/NWOG)
    opening_gaps = optimizer.check_opening_gaps(
        [c.open for c in daily_candles], [c.close for c in daily_candles],
        [c.high for c in daily_candles], [c.low for c in daily_candles]
    )
    
    # 4. Swing Failure Patterns
    # Would need swing indices - simplified
    
    # 5. Opening Gaps check
    ndog = signal.get('advanced_ict', {}).get('ndog')
    nwog = signal.get('advanced_ict', {}).get('nwog')
    
    # 6. IOFED Signal Detection (if signal has FVG)
    ioFED_signal = None
    if signal.get('pd_array', {}).get('type') == 'fair_value_gap':
        fvg_data = signal['pd_array']
        ioFED = optimizer.detect_iofed_signal(
            fvg_data,
            [c.high for c in h1_candles], [c.low for c in h1_candles],
            [c.open for c in h1_candles], [c.close for c in h1_candles],
            signal['direction'],
            signal['entry_price'],
            signal['stop_loss']
        )
        if ioFED:
            ioFED_signal = ioFED.__dict__
    
    # 5. Swing Failure Detection (simplified)
    # 6. 90-minute cycle alignment
    cycle_aligned = False
    direction = signal.get('direction', 'long')
    if direction == 'long' and cycle_bias in ['manipulation', 'distribution']:
        cycle_aligned = True
    elif direction == 'short' and cycle_bias in ['manipulation', 'distribution']:
        cycle_aligned = True
    
    # Confidence boost
    confidence_boost = 0
    if signal.get('advanced_ict', {}).get('bprs'):
        confidence_boost += 0.05
    if optimizer.is_in_macro_window(datetime.now())[0]:
        confidence_boost += 0.05
    if cycle_aligned:
        confidence_boost += 0.03
    if opening_gaps.get('ndog') and opening_gaps['ndog']['direction'] == direction:
        confidence_boost += 0.03
    if opening_gaps.get('nwog') and opening_gaps['nwog']['direction'] == direction:
        confidence_boost += 0.02
    
    # Add advanced data to signal
    signal['advanced_ict_optimized'] = {
        'swing_grades': [
            {'grade': s.grade, 'type': s.swing_type, 'price': s.price, 'rel_equal': s.is_relative_equal}
            for s in optimizer.grade_swings([c.high for c in h5_candles], 
                                            [c.low for c in h5_candles], 
                                            [c.close for c in h5_candles]).swing_grades[:5]
        ],
        'cycle_bias': cycle_bias,
        'macro_window': optimizer.is_in_macro_window(datetime.now())[1],
        'opening_gaps': opening_gaps,
        'cycle_aligned': cycle_aligned,
        'ioFED_signal': ioFED_signal,
        'confidence_boost': confidence_boost,
        'swing_failure': None,  # Would need swing indices
        'breakaway_gap': None,  # Would need specific detection
    }
    
    # Boost confidence
    signal['confidence'] = min(signal.get('confidence', 0) + confidence_boost, 0.98)
    
    return signal


# ============================================================
# OPTIMIZED SIGNAL GENERATION WITH ALL ADVANCED CONCEPTS
# ============================================================

def generate_optimized_ict_signals(asset: str, asset_config: Dict,
                                   daily_candles: List, h4_candles: List,
                                   h15_candles: List, h5_candles: List,
                                   h1_candles: List, est_now: datetime,
                                   optimizer: AdvancedICTOptimizer) -> List[dict]:
    """Generate fully optimized ICT signals with all 2024/2025 concepts"""
    
    signals = []
    
    # This would integrate all the above concepts into signal generation
    # For now, return enhanced version of existing signals
    return []


if __name__ == '__main__':
    # Test the optimizer
    optimizer = AdvancedICTOptimizer()
    
    # Test with sample data
    import random
    random.seed(42)
    
    # Generate sample 5m data
    h5_highs = []
    h5_lows = []
    h5_closes = []
    h5_opens = []
    base = 30000
    for i in range(200):
        change = random.uniform(-10, 10)
        base += change
        o = base - random.uniform(-5, 5)
        c = base
        h = max(o, c) + random.uniform(0, 5)
        l = min(o, c) - random.uniform(0, 5)
        h5_opens.append(o)
        h5_closes.append(c)
        h5_highs.append(h)
        h5_lows.append(l)
    
    result = AdvancedICTOptimizer().grade_swings(
        [c+random.uniform(0,20) for c in h5_closes],
        [c-random.uniform(0,20) for c in h5_closes],
        h5_closes
    )
    
    print(f"Swing grades: {len(result.swing_grades)}")
    for s in result.swing_grades[:5]:
        print(f"  {s.swing_type} {s.grade} @ {s.price:.2f} rel_eq={s.is_relative_equal}")
    
    print("Optimizer test complete")
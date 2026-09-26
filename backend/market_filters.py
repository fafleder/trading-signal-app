"""
Market Selection Filters & Regime Detection
Implements quantitative filters for high-quality setup selection
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    QUIET = "quiet"
    UNKNOWN = "unknown"

@dataclass
class MarketFilters:
    """Configuration for market selection filters"""
    # Spread filters
    max_spread_pct: Dict[str, float] = None  # symbol -> max spread %
    min_volume_percentile: float = 0.3       # Min volume vs 20-day avg
    # Liquidity filters
    min_liquidity_score: float = 0.5
    max_slippage_bps: float = 5.0
    # Narrative/News filters
    require_fresh_news: bool = False
    avoid_high_impact_news: bool = True
    news_blackout_minutes: int = 30
    # Technical filters
    min_adx: float = 20.0                    # For trending setups
    max_adx: float = 25.0                    # For ranging setups
    atr_percentile_range: Tuple[float, float] = (0.2, 0.8)  # Not too quiet/loud
    # Correlation filters
    max_portfolio_correlation: float = 0.7
    # Time filters
    avoid_first_15min: bool = True           # Avoid open volatility
    avoid_last_15min: bool = True            # Avoid close volatility
    # Volatility regime
    vol_regime_lookback: int = 20

class MarketAnalyzer:
    def __init__(self, mt5_fetcher, config: MarketFilters = None):
        self.mt5 = mt5_fetcher
        self.config = config or MarketFilters()
        self.regime_cache = {}
        self.volatility_cache = {}
        
        # Initialize default spread limits
        if self.config.max_spread_pct is None:
            self.config.max_spread_pct = {
                'XAUUSDm': 0.005,   # 50 pips = 0.005%
                'USTECm': 0.01,     # 1% 
                'EURUSDm': 0.0002,  # 2 pips
                'GBPUSDm': 0.0002,  # 2 pips
            }
    
    def analyze_market(self, symbol: str, timeframe: str = '15m', 
                       lookback: int = 500) -> Dict:
        """Comprehensive market analysis for a symbol"""
        data = self.mt5.fetch_candles(symbol, timeframe, lookback)
        if data is None or len(data) < 50:
            return {'valid': False, 'reason': 'Insufficient data'}
        
        df = data.copy()
        df['returns'] = df['close'].pct_change()
        df['log_returns'] = np.log(df['close'] / df['close'].shift(1))
        
        # Current tick for spread
        tick = self.mt5.get_symbol_tick(symbol)
        spread_pct = 0
        if tick and tick['ask'] > 0:
            spread_pct = (tick['ask'] - tick['bid']) / tick['ask'] * 100
        
        # Volume analysis
        vol_20_avg = df['volume'].rolling(20).mean().iloc[-1]
        current_vol = df['volume'].iloc[-1]
        vol_ratio = current_vol / vol_20_avg if vol_20_avg > 0 else 1
        
        # ATR for volatility
        df['tr'] = np.maximum(
            df['high'] - df['low'],
            np.maximum(
                abs(df['high'] - df['close'].shift(1)),
                abs(df['low'] - df['close'].shift(1))
            )
        )
        atr_14 = df['tr'].rolling(14).mean().iloc[-1]
        atr_20_avg = df['tr'].rolling(20).mean().iloc[-1]
        atr_percentile = self._percentile_rank(df['tr'].rolling(14).mean(), atr_14)
        
        # ADX for trend strength
        adx = self._calculate_adx(df, 14)
        
        # Returns statistics
        returns_20 = df['returns'].tail(20).dropna()
        realized_vol = returns_20.std() * np.sqrt(252 * 96)  # Annualized for 15m
        skew = returns_20.skew()
        kurt = returns_20.kurtosis()
        
        # Trend detection
        sma_20 = df['close'].rolling(20).mean().iloc[-1]
        sma_50 = df['close'].rolling(50).mean().iloc[-1]
        current_price = df['close'].iloc[-1]
        
        # Market structure
        higher_highs = df['high'].iloc[-1] > df['high'].iloc[-2] > df['high'].iloc[-3]
        lower_lows = df['low'].iloc[-1] < df['low'].iloc[-2] < df['low'].iloc[-3]
        
        # Detect regime
        regime = self._detect_regime(
            current_price, sma_20, sma_50, adx, realized_vol,
            higher_highs, lower_lows, atr_percentile
        )
        
        # Debug log
        logger.debug(f"{symbol} regime analysis: price={current_price:.5f}, sma20={sma_20:.5f}, sma50={sma_50:.5f}, adx={adx:.1f}, vol={realized_vol:.3f}, atr_pct={atr_percentile:.3f}, regime={regime.value}")
        
        # Calculate composite score
        score = self._calculate_market_score(
            spread_pct, vol_ratio, atr_percentile, adx, 
            realized_vol, regime, symbol
        )
        
        return {
            'valid': score > 0.5,
            'score': score,
            'regime': regime.value,
            'spread_pct': spread_pct,
            'vol_ratio': vol_ratio,
            'atr_percentile': atr_percentile,
            'adx': adx,
            'realized_vol': realized_vol,
            'skew': skew,
            'kurtosis': kurt,
            'trend': 'up' if current_price > sma_20 > sma_50 else 
                    'down' if current_price < sma_20 < sma_50 else 'mixed',
            'higher_highs': higher_highs,
            'lower_lows': lower_lows,
            'filters_passed': self._check_filters(spread_pct, vol_ratio, atr_percentile, adx, regime, symbol),
        }
    
    def _detect_regime(self, price: float, sma_20: float, sma_50: float,
                       adx: float, vol: float, 
                       higher_highs: bool, lower_lows: bool,
                       atr_pct: float) -> MarketRegime:
        """Detect market regime using multiple factors"""
        
        # Strong trend
        if adx > 25 and price > sma_20 > sma_50 and higher_highs:
            return MarketRegime.TRENDING_UP
        if adx > 25 and price < sma_20 < sma_50 and lower_lows:
            return MarketRegime.TRENDING_DOWN
        
        # Volatile
        if vol > 0.5 or atr_pct > 0.95:
            return MarketRegime.VOLATILE
        
        # Quiet
        if vol < 0.05 and atr_pct < 0.2:
            return MarketRegime.QUIET
        
        # Ranging (default)
        return MarketRegime.RANGING
    
    def _calculate_market_score(self, spread_pct: float, vol_ratio: float,
                                atr_pct: float, adx: float, vol: float,
                                regime: MarketRegime, symbol: str) -> float:
        """Composite market quality score (0-1)"""
        score = 1.0
        
        # Spread penalty
        max_spread = self.config.max_spread_pct.get(symbol, 0.01)
        if spread_pct > max_spread:
            score *= max(0.1, 1 - (spread_pct / max_spread - 1))
        
        # Volume bonus/penalty
        if vol_ratio < self.config.min_volume_percentile:
            score *= 0.5
        elif vol_ratio > 1.5:
            score *= 1.1
        
        # ATR percentile - avoid extremes
        if atr_pct < self.config.atr_percentile_range[0] or \
           atr_pct > self.config.atr_percentile_range[1]:
            score *= 0.7
        
        # ADX filter based on regime preference
        # For ICT: we want some trend (ADX > 20) but not extreme
        if adx < 15:
            score *= 0.6  # Too choppy
        elif adx > 40:
            score *= 0.8  # May be overextended
        
        # Regime bonus
        if regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            score *= 1.15  # ICT works best in trending
        elif regime == MarketRegime.RANGING:
            score *= 0.95  # Less penalty for ranging
        elif regime == MarketRegime.VOLATILE:
            score *= 0.8   # Less penalty for volatile
        elif regime == MarketRegime.QUIET:
            score *= 0.7
        
        return min(1.0, max(0.0, score))
    
    def _check_filters(self, spread_pct: float, vol_ratio: float,
                       atr_pct: float, adx: float,
                       regime: MarketRegime, symbol: str) -> Dict[str, bool]:
        """Check individual filters"""
        return {
            'spread_ok': spread_pct <= self.config.max_spread_pct.get(symbol, 0.01),
            'volume_ok': vol_ratio >= self.config.min_volume_percentile,
            'atr_ok': self.config.atr_percentile_range[0] <= atr_pct <= self.config.atr_percentile_range[1],
            'adx_ok': adx >= 15,
            'regime_ok': regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN, MarketRegime.RANGING],
            'not_volatile': regime != MarketRegime.VOLATILE,
            'not_quiet': regime != MarketRegime.QUIET,
        }
    
    def _calculate_adx(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average Directional Index"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        plus_dm = high.diff()
        minus_dm = low.diff()
        
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm > 0] = 0
        minus_dm = minus_dm.abs()
        
        tr = np.maximum(
            high - low,
            np.maximum(
                abs(high - close.shift(1)),
                abs(low - close.shift(1))
            )
        )
        
        atr = tr.rolling(period).mean()
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(period).mean()
        
        return adx.iloc[-1] if not np.isnan(adx.iloc[-1]) else 20.0
    
    def _percentile_rank(self, series: pd.Series, value: float) -> float:
        """Calculate percentile rank of value in series"""
        valid = series.dropna()
        if len(valid) == 0:
            return 0.5
        return (valid < value).sum() / len(valid)
    
    def check_time_filters(self, current_time) -> Dict[str, bool]:
        """Check time-based filters"""
        hour = current_time.hour
        minute = current_time.minute
        
        # Avoid first/last 15 min of session
        is_session_start = (hour in [0, 7, 13] and minute < 15)  # Approx session opens
        is_session_end = (hour in [5, 12, 20] and minute > 45)   # Approx session closes
        
        return {
            'avoid_start': self.config.avoid_first_15min and is_session_start,
            'avoid_end': self.config.avoid_last_15min and is_session_end,
            'ok': not (is_session_start and self.config.avoid_first_15min) and 
                  not (is_session_end and self.config.avoid_last_15min)
        }
    
    def scan_all_symbols(self, symbols: List[str]) -> Dict[str, Dict]:
        """Scan all symbols and return ranked results"""
        results = {}
        for symbol in symbols:
            try:
                analysis = self.analyze_market(symbol)
                results[symbol] = analysis
            except Exception as e:
                logger.error(f"Market analysis failed for {symbol}: {e}")
                results[symbol] = {'valid': False, 'reason': str(e)}
        
        # Rank by score
        ranked = sorted(
            [(s, r) for s, r in results.items() if r.get('valid', False)],
            key=lambda x: x[1].get('score', 0),
            reverse=True
        )
        
        return {
            'ranked': ranked,
            'all': results,
            'best': ranked[0][0] if ranked else None
        }


# Narrative/News alignment (placeholder for future LLM integration)
class NarrativeAnalyzer:
    """Analyze market narratives for alignment with setups"""
    
    def __init__(self):
        self.narratives = {
            'XAUUSD': ['inflation', 'fed_rate', 'geopolitical', 'dollar_weakness'],
            'NASDAQ': ['tech_earnings', 'ai_narrative', 'fed_liquidity', 'growth_scares'],
            'EURUSD': ['ecb_policy', 'eurozone_growth', 'dollar_strength', 'energy_crisis'],
            'GBPUSD': ['boe_policy', 'uk_growth', 'brexit', 'dollar_strength'],
        }
    
    def check_narrative_alignment(self, symbol: str, direction: str) -> Tuple[bool, str]:
        """Check if current narrative supports the trade direction"""
        # Placeholder - would integrate with news API + LLM
        # For now: return neutral
        return True, "No narrative data"


# Integration helper
def create_market_analyzer(mt5_fetcher, config_dict: Dict = None) -> MarketAnalyzer:
    """Factory function to create market analyzer from config"""
    if config_dict is None:
        config_dict = {}
    
    filters = MarketFilters(
        max_spread_pct=config_dict.get('max_spread_pct'),
        min_volume_percentile=config_dict.get('min_volume_percentile', 0.3),
        min_liquidity_score=config_dict.get('min_liquidity_score', 0.5),
        max_slippage_bps=config_dict.get('max_slippage_bps', 5.0),
        min_adx=config_dict.get('min_adx', 20.0),
        atr_percentile_range=tuple(config_dict.get('atr_percentile_range', [0.2, 0.8])),
        avoid_first_15min=config_dict.get('avoid_first_15min', True),
        avoid_last_15min=config_dict.get('avoid_last_15min', True),
    )
    
    return MarketAnalyzer(mt5_fetcher, filters)
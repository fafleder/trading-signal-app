"""
Paired/Delta-Neutral Position Manager
Implements risk-free pair arbitrage and hedged positions
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)

class PairType(Enum):
    ARBITRAGE = "arbitrage"        # Risk-free: YES+NO on same market
    HEDGED_DIRECTIONAL = "hedged"  # Directional + correlated hedge
    CROSS_ASSET = "cross_asset"    # Different assets (e.g., XAUUSD + DXY)
    STATISTICAL = "statistical"    # Mean-reverting pairs

@dataclass
class PairLeg:
    symbol: str
    side: str          # "buy" or "sell"
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    pair_id: str
    leg_id: str        # "leg_a" or "leg_b"

@dataclass
class PairedPosition:
    pair_id: str
    pair_type: PairType
    leg_a: PairLeg
    leg_b: PairLeg
    guaranteed_profit: float = 0.0      # For arbitrage pairs
    max_risk: float = 0.0               # For hedged pairs
    created_at: float = 0.0
    status: str = "open"                # open, closed, partial
    realized_pnl: float = 0.0

class PairedPositionManager:
    def __init__(self, mt5_fetcher, risk_manager, config: Dict):
        self.mt5 = mt5_fetcher
        self.risk = risk_manager
        self.config = config
        self.pairs: Dict[str, PairedPosition] = {}
        self.pair_counter = 0
        
        # Correlation matrix for hedging
        self.correlations = {
            ('XAUUSD', 'DXY'): -0.85,
            ('XAUUSD', 'USDJPY'): -0.75,
            ('NASDAQ', 'SPX'): 0.95,
            ('EURUSD', 'GBPUSD'): 0.85,
            ('EURUSD', 'DXY'): -0.90,
        }
        
    def find_hedge_symbol(self, symbol: str, direction: str) -> Optional[Tuple[str, str]]:
        """Find best hedge symbol and direction for a given position"""
        best_corr = 0
        best_hedge = None
        hedge_dir = None
        
        for (s1, s2), corr in self.correlations.items():
            if s1 == symbol:
                # Negative correlation = hedge with opposite direction
                # Positive correlation = hedge with same direction (reduce size)
                if abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_hedge = s2
                    hedge_dir = "sell" if (direction == "buy" and corr < 0) or (direction == "sell" and corr > 0) else "buy"
            elif s2 == symbol:
                if abs(corr) > abs(best_corr):
                    best_corr = corr
                    best_hedge = s1
                    hedge_dir = "sell" if (direction == "buy" and corr < 0) or (direction == "sell" and corr > 0) else "buy"
        
        if best_hedge and abs(best_corr) > 0.6:
            return best_hedge, hedge_dir
        return None
    
    def create_arbitrage_pair(self, market_id: str, yes_price: float, no_price: float, 
                               volume: float) -> Optional[PairedPosition]:
        """Create risk-free arbitrage pair (Polymarket style)"""
        pair_cost = yes_price + no_price
        if pair_cost >= 1.0:
            logger.warning(f"Pair cost {pair_cost} >= 1.0, no arbitrage")
            return None
        
        guaranteed_profit = (1.0 - pair_cost) * volume
        
        self.pair_counter += 1
        pair_id = f"ARB_{market_id}_{self.pair_counter}"
        
        leg_a = PairLeg(
            symbol=market_id,
            side="buy",
            volume=volume,
            entry_price=yes_price,
            stop_loss=yes_price,  # No SL for arbitrage
            take_profit=1.0,
            pair_id=pair_id,
            leg_id="leg_a"
        )
        
        leg_b = PairLeg(
            symbol=market_id,
            side="buy",  # Both are buys on different outcomes
            volume=volume,
            entry_price=no_price,
            stop_loss=no_price,
            take_profit=1.0,
            pair_id=pair_id,
            leg_id="leg_b"
        )
        
        pair = PairedPosition(
            pair_id=pair_id,
            pair_type=PairType.ARBITRAGE,
            leg_a=leg_a,
            leg_b=leg_b,
            guaranteed_profit=guaranteed_profit,
            max_risk=pair_cost * volume,
            created_at=self._now()
        )
        
        self.pairs[pair_id] = pair
        logger.info(f"Created arbitrage pair {pair_id}: guaranteed ${guaranteed_profit:.2f}")
        return pair
    
    def create_hedged_position(self, signal: Dict, hedge_ratio: float = 0.5) -> Optional[PairedPosition]:
        """Create directional position with correlated hedge"""
        symbol = signal['symbol']
        direction = signal['direction']
        volume = signal.get('volume', 0.01)
        entry = signal['entry_price']
        sl = signal['stop_loss']
        tp = signal['take_profit_1']
        
        # Find hedge
        hedge_info = self.find_hedge_symbol(symbol, direction)
        if not hedge_info:
            logger.warning(f"No suitable hedge for {symbol}")
            return None
        
        hedge_symbol, hedge_direction = hedge_info
        hedge_volume = volume * hedge_ratio
        
        # Get hedge entry price
        hedge_tick = self.mt5.get_symbol_tick(hedge_symbol)
        if not hedge_tick:
            return None
        
        hedge_entry = hedge_tick['ask'] if hedge_direction == "buy" else hedge_tick['bid']
        hedge_sl = hedge_entry * 1.002 if hedge_direction == "buy" else hedge_entry * 0.998
        hedge_tp = hedge_entry * 0.998 if hedge_direction == "buy" else hedge_entry * 1.002
        
        self.pair_counter += 1
        pair_id = f"HEDGE_{symbol}_{hedge_symbol}_{self.pair_counter}"
        
        leg_a = PairLeg(
            symbol=symbol,
            side=direction,
            volume=volume,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            pair_id=pair_id,
            leg_id="leg_a"
        )
        
        leg_b = PairLeg(
            symbol=hedge_symbol,
            side=hedge_direction,
            volume=hedge_volume,
            entry_price=hedge_entry,
            stop_loss=hedge_sl,
            take_profit=hedge_tp,
            pair_id=pair_id,
            leg_id="leg_b"
        )
        
        # Calculate max risk (both SL hit)
        risk_a = volume * abs(entry - sl)
        risk_b = hedge_volume * abs(hedge_entry - hedge_sl)
        max_risk = risk_a + risk_b
        
        pair = PairedPosition(
            pair_id=pair_id,
            pair_type=PairType.HEDGED_DIRECTIONAL,
            leg_a=leg_a,
            leg_b=leg_b,
            max_risk=max_risk,
            created_at=self._now()
        )
        
        self.pairs[pair_id] = pair
        logger.info(f"Created hedged pair {pair_id}: {symbol} {direction} + {hedge_symbol} {hedge_direction}")
        return pair
    
    def update_pairs(self):
        """Update all paired positions"""
        for pair_id, pair in list(self.pairs.items()):
            if pair.status != "open":
                continue
            
            # Check each leg
            for leg in [pair.leg_a, pair.leg_b]:
                tick = self.mt5.get_symbol_tick(leg.symbol)
                if not tick:
                    continue
                
                current_price = tick['bid'] if leg.side == "buy" else tick['ask']
                
                # Check TP
                if (leg.side == "buy" and current_price >= leg.take_profit) or \
                   (leg.side == "sell" and current_price <= leg.take_profit):
                    self._close_leg(pair, leg, "TP_HIT")
                
                # Check SL
                elif (leg.side == "buy" and current_price <= leg.stop_loss) or \
                     (leg.side == "sell" and current_price >= leg.stop_loss):
                    self._close_leg(pair, leg, "SL_HIT")
            
            # Check if pair fully closed
            if pair.leg_a.side == "closed" and pair.leg_b.side == "closed":
                pair.status = "closed"
    
    def _close_leg(self, pair: PairedPosition, leg: PairLeg, reason: str):
        """Close a single leg"""
        # In production: call MT5 close_position
        leg.side = "closed"
        pnl = (leg.take_profit - leg.entry_price) * leg.volume if reason == "TP_HIT" else \
              (leg.stop_loss - leg.entry_price) * leg.volume
        if leg.side == "sell":
            pnl = -pnl
        pair.realized_pnl += pnl
        logger.info(f"Closed {pair.pair_id} {leg.leg_id}: {reason}, PnL=${pnl:.2f}")
    
    def _now(self) -> float:
        import time
        return time.time()
    
    def get_open_pairs(self) -> List[PairedPosition]:
        return [p for p in self.pairs.values() if p.status == "open"]
    
    def get_total_exposure(self) -> float:
        """Total notional exposure across all pairs"""
        total = 0
        for pair in self.pairs.values():
            if pair.status == "open":
                total += pair.leg_a.volume * pair.leg_a.entry_price
                total += pair.leg_b.volume * pair.leg_b.entry_price
        return total
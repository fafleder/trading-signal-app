"""
ICT Trading Bot - Continuous MT5 Execution Engine
Integrates with enhanced ICT signal generator + full position management
"""

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
import json

from pathlib import Path
# Import existing ICT modules
from mt5_fetcher import MT5DataFetcher
from run_ict_enhanced import (
    generate_all_signals, SetupType, Session, Bias, TradeSetup,
    ASSETS, KILL_ZONES_EST, is_in_kill_zone, is_in_macro_window,
    is_in_silver_bullet, get_current_est_time, dataframe_to_candles,
    market_structure, liquidity_pools, fair_value_gaps, order_blocks,
    check_ote_confluence
)
from news_filter import get_news_filter
from telegram_notifier import get_notifier
from paired_positions import PairedPositionManager, PairType
from trade_journal import TradeJournal, TradeRecord, SelfLearningLoop, create_trade_record_from_signal, update_trade_on_close, LLMAnalyzer
from market_filters import create_market_analyzer, MarketRegime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ============================================================
# DATA STRUCTURES
# ============================================================

class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"

class ExitReason(Enum):
    TP1_HIT = "tp1_hit"
    TP2_HIT = "tp2_hit"
    SL_HIT = "sl_hit"
    TRAILING_SL = "trailing_sl"
    MANUAL = "manual"
    SESSION_END = "session_end"
    RISK_LIMIT = "risk_limit"

@dataclass
class Order:
    ticket: int = 0
    symbol: str = ""
    side: PositionSide = PositionSide.LONG
    volume: float = 0.0
    price: float = 0.0
    sl: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    filled_price: float = 0.0
    filled_volume: float = 0.0
    tp1_filled: bool = False
    tp2_filled: bool = False
    sl_moved_to_be: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    filled_at: Optional[datetime] = None
    magic: int = 0
    comment: str = ""

@dataclass
class Position:
    ticket: int
    symbol: str
    side: PositionSide
    volume: float
    entry_price: float
    current_sl: float
    current_tp1: float
    current_tp2: float
    entry_time: datetime
    tp1_filled: bool = False
    tp2_filled: bool = False
    sl_moved_to_be: bool = False
    trailing_active: bool = False
    trailing_distance: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    partial_closed: float = 0.0
    magic: int = 0
    comment: str = ""

@dataclass
class AccountState:
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    margin_level: float = 0.0
    daily_pnl: float = 0.0
    daily_start_equity: float = 0.0
    max_daily_dd: float = 0.0
    open_positions: int = 0
    total_volume: float = 0.0


# ============================================================
# RISK MANAGEMENT
# ============================================================

class RiskManager:
    def __init__(self, config: Dict):
        self.config = config
        self.max_daily_dd_pct = config.get('max_daily_dd_pct', 2.0)
        self.max_portfolio_heat_pct = config.get('max_portfolio_heat_pct', 5.0)
        self.max_position_risk_pct = config.get('max_position_risk_pct', 1.0)
        self.max_correlation = config.get('max_correlation', 0.7)
        self.max_positions = config.get('max_positions', 5)
        self.max_positions_per_symbol = config.get('max_positions_per_symbol', 1)
        self.daily_start_equity = 0.0
        self.peak_equity = 0.0
        
    def initialize_daily(self, equity: float):
        self.daily_start_equity = equity
        self.peak_equity = equity
        
    def check_daily_dd(self, current_equity: float) -> bool:
        if self.daily_start_equity <= 0:
            return True
        dd_pct = (self.daily_start_equity - current_equity) / self.daily_start_equity * 100
        return dd_pct < self.max_daily_dd_pct
    
    def check_portfolio_heat(self, positions: List[Any], account_equity: float) -> bool:
        if account_equity <= 0:
            return False
        total_risk = sum(p.volume * abs(p.entry_price - p.current_sl) for p in positions if hasattr(p, 'entry_price'))
        heat_pct = total_risk / account_equity * 100
        return heat_pct < self.max_portfolio_heat_pct
    
    def check_position_limit(self, symbol: str, positions: List[Any], side: str) -> bool:
        symbol_positions = [p for p in positions if p.symbol == symbol and p.side.value == side.lower()]
        return len(symbol_positions) < self.max_positions_per_symbol
    
    def check_total_positions(self, positions: List[Any]) -> bool:
        return len(positions) < self.max_positions
    
    def calculate_position_size(self, account_equity: float, entry: float, sl: float, 
                                 symbol_info: Dict) -> float:
        risk_amount = account_equity * self.max_position_risk_pct / 100
        risk_per_lot = abs(entry - sl) * symbol_info.get('trade_tick_value', 1)
        if risk_per_lot <= 0:
            return 0.01
        volume = risk_amount / risk_per_lot
        # Round to broker step
        step = symbol_info.get('volume_step', 0.01)
        volume = round(volume / step) * step
        min_vol = symbol_info.get('volume_min', 0.01)
        max_vol = symbol_info.get('volume_max', 100)
        return max(min_vol, min(max_vol, volume))


# ============================================================
# POSITION MANAGER
# ============================================================

class PositionManager:
    def __init__(self, mt5_fetcher: MT5DataFetcher, risk_manager: RiskManager, config: Dict):
        self.mt5 = mt5_fetcher
        self.risk = risk_manager
        self.config = config
        self.positions: Dict[int, Position] = {}
        self.orders: Dict[int, Order] = {}
        self.lock = Lock()
        self.magic_base = config.get('magic_base', 123456)
        self.next_magic = self.magic_base
        self.trailing_config = config.get('trailing', {
            'enabled': True,
            'activation_rr': 1.0,
            'distance_pct': 0.5,
            'step_pct': 0.1
        })
        self.partial_config = config.get('partials', {
            'tp1_pct': 50,
            'tp2_pct': 30,
            'runner_pct': 20
        })
        
    def get_next_magic(self) -> int:
        magic = self.next_magic
        self.next_magic += 1
        return magic
    
    def place_bracket_order(self, signal: Dict, account_state: Dict, symbol_info: Dict) -> Optional[int]:
        """Place bracket order (entry + SL + TP1 + TP2)"""
        try:
            symbol = signal['symbol']
            side = PositionSide.LONG if signal['direction'] == 'long' else PositionSide.SHORT
            entry = signal['entry_price']
            sl = signal['stop_loss']
            tp1 = signal['take_profit_1']
            tp2 = signal['take_profit_2']
            
            # Calculate position size
            volume = self.risk.calculate_position_size(
                account_state['equity'], entry, sl, symbol_info
            )
            if volume <= 0:
                logger.warning(f"Invalid volume for {symbol}")
                return None
            
            magic = self.get_next_magic()
            
            # Place order via MT5
            order_type = 0 if signal['direction'] == 'long' else 1  # 0=buy, 1=sell
            
            request = {
                "action": 0,  # TRADE_ACTION_DEAL
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": entry,
                "sl": sl,
                "tp": tp1,
                "magic": magic,
                "comment": f"ICT_{signal.get('setup_type', 'intraday')}",
                "type_filling": 1,  # ORDER_FILLING_IOC
                "type_time": 0,     # ORDER_TIME_GTC
            }
            
            # Use MT5 to place order
            result = self.mt5.place_order(request)
            if result and result.get('retcode') == 10009:  # TRADE_RETCODE_DONE
                ticket = result.get('order')
                self.track_position(ticket, symbol, side, volume, entry, sl, tp1, tp2)
                return ticket
            else:
                logger.error(f"Order failed: {result}")
                return None
                
        except Exception as e:
            logger.error(f"Order placement failed: {e}")
            return None
    
    def track_position(self, ticket: int, symbol: str, side: PositionSide, 
                       volume: float, entry: float, sl: float, tp1: float, tp2: float):
        pos = Position(
            ticket=ticket,
            symbol=symbol,
            side=PositionSide.LONG if volume > 0 else PositionSide.SHORT,
            volume=abs(volume),
            entry_price=entry,
            current_sl=sl,
            current_tp1=tp1,
            current_tp2=tp2,
            entry_time=datetime.now(),
            magic=self.next_magic - 1,
            comment="ICT Signal"
        )
        self.positions[ticket] = pos
        logger.info(f"Tracking position {ticket}: {symbol} {side.value} vol={abs(volume)}")
    
    def update_positions(self, account_state: Dict):
        """Update all positions - check TP/SL, manage trailing, partials"""
        with self.lock:
            for ticket, pos in list(self.positions.items()):
                try:
                    # Get current price
                    tick = self.mt5.get_symbol_tick(pos.symbol)
                    if not tick:
                        continue
                    
                    current_price = tick.bid if pos.side == PositionSide.LONG else tick.ask
                    pos.unrealized_pnl = (current_price - pos.entry_price) * pos.volume if pos.side == PositionSide.LONG else (pos.entry_price - current_price) * pos.volume
                    
                    # Check TP1
                    if not pos.tp1_filled:
                        if (pos.side == PositionSide.LONG and current_price >= pos.current_tp1) or \
                           (pos.side == PositionSide.SHORT and current_price <= pos.current_tp1):
                            self.close_partial(ticket, self.partial_config['tp1_pct'], "TP1_HIT")
                    
                    # Check TP2
                    if pos.tp1_filled and not pos.tp2_filled:
                        if (pos.side == PositionSide.LONG and current_price >= pos.current_tp2) or \
                           (pos.side == PositionSide.SHORT and current_price <= pos.current_tp2):
                            self.close_partial(ticket, self.partial_config['tp2_pct'], "TP2_HIT")
                    
                    # Check SL
                    if (pos.side == PositionSide.LONG and current_price <= pos.current_sl) or \
                       (pos.side == PositionSide.SHORT and current_price >= pos.current_sl):
                        self.close_position(ticket, "SL_HIT")
                        continue
                    
                    # Trailing stop logic
                    if self.trailing_config['enabled'] and pos.tp1_filled and not pos.trailing_active:
                        rr = pos.unrealized_pnl / (pos.volume * abs(pos.entry_price - pos.current_sl)) if abs(pos.entry_price - pos.current_sl) > 0 else 0
                        if rr >= self.trailing_config['activation_rr']:
                            pos.trailing_active = True
                            pos.trailing_distance = abs(pos.entry_price - pos.current_sl) * self.trailing_config['distance_pct']
                            logger.info(f"Trailing activated for {pos.ticket}")
                    
                    if pos.trailing_active:
                        new_sl = current_price - pos.trailing_distance if pos.side == PositionSide.LONG else current_price + pos.trailing_distance
                        if (pos.side == PositionSide.LONG and new_sl > pos.current_sl) or \
                           (pos.side == PositionSide.SHORT and new_sl < pos.current_sl):
                            self.modify_sl(ticket, new_sl)
                            pos.current_sl = new_sl
                    
                    # Move SL to breakeven after TP1
                    if pos.tp1_filled and not pos.sl_moved_to_be:
                        be_sl = pos.entry_price + (pos.entry_price * 0.0001) if pos.side == PositionSide.LONG else pos.entry_price - (pos.entry_price * 0.0001)
                        if (pos.side == PositionSide.LONG and pos.current_sl < be_sl) or \
                           (pos.side == PositionSide.SHORT and pos.current_sl > be_sl):
                            self.modify_sl(ticket, be_sl)
                            pos.current_sl = be_sl
                            pos.sl_moved_to_be = True
                            
                except Exception as e:
                    logger.error(f"Position update error for {ticket}: {e}")
    
    def close_partial(self, ticket: int, pct: float, reason: str):
        pos = self.positions.get(ticket)
        if not pos:
            return
        close_vol = pos.volume * pct / 100
        if close_vol <= 0:
            return
        
        # Close partial via MT5
        side = 1 if pos.side == PositionSide.LONG else 0  # Opposite to close
        result = self.mt5.close_position(ticket, close_vol, side)
        if result and result.get('retcode') == 10009:
            pos.volume -= close_vol
            pos.partial_closed += close_vol
            if 'tp1' in reason.lower():
                pos.tp1_filled = True
                logger.info(f"TP1 partial close {pct}% for {ticket}")
            elif 'tp2' in reason.lower():
                pos.tp2_filled = True
                logger.info(f"TP2 partial close {pct}% for {ticket}")
    
    def close_position(self, ticket: int, reason: str):
        pos = self.positions.get(ticket)
        if not pos:
            return
        
        side = 1 if pos.side == PositionSide.LONG else 0
        result = self.mt5.close_position(ticket, pos.volume, side)
        if result and result.get('retcode') == 10009:
            pos.realized_pnl += pos.unrealized_pnl
            del self.positions[ticket]
            logger.info(f"Closed position {ticket}: {reason}")
    
    def modify_sl(self, ticket: int, new_sl: float):
        pos = self.positions.get(ticket)
        if not pos:
            return
        result = self.mt5.modify_position(ticket, pos.current_sl, new_sl)
        if result and result.get('retcode') == 10009:
            logger.info(f"Modified SL for {ticket}: {new_sl}")


# ============================================================
# MAIN TRADING BOT
# ============================================================

class ICTTradingBot:
    def __init__(self, config: Dict):
        self.config = config
        self.running = False
        self.mt5 = MT5DataFetcher()
        self.risk = RiskManager(config.get('risk', {}))
        self.position_mgr = PositionManager(self.mt5, self.risk, config)
        self.paired_mgr = PairedPositionManager(self.mt5, self.risk, config)
        self.news_filter = get_news_filter(config)
        self.notifier = get_notifier()
        self.market_analyzer = create_market_analyzer(self.mt5, config.get('market_filters', {}))
        self.trade_journal = TradeJournal()
        self.learning_loop = SelfLearningLoop(self.trade_journal, LLMAnalyzer(), Path('bot_config.json'))
        self.session_config = config.get('sessions', {})
        self.scan_interval = config.get('scan_interval', 60)  # seconds
        self.last_daily_reset = None
        
        # Proactive notification tracking
        self.pending_signals = {}  # asset -> signal info (not yet executed)
        self.notified_approaching = set()  # track which signals we've notified as "approaching"
        self.entry_proximity_pct = 0.001  # 0.1% from entry = approaching
        
        self.daily_stats = {
            'daily_pnl': 0.0,
            'trade_count': 0,
            'wins': 0,
            'losses': 0,
            'max_drawdown': 0.0,
            'open_positions': 0,
            'start_equity': 0.0
        }
        
    async def initialize(self) -> bool:
        """Initialize MT5 connection and daily risk"""
        if not self.mt5.initialize():
            logger.error("MT5 initialization failed")
            return False
        
        # Get account state
        account = self.mt5.get_account_info()
        if account:
            self.risk.initialize_daily(account.equity)
            self.daily_stats['start_equity'] = account.equity
            logger.info(f"Account initialized: Balance={account.balance}, Equity={account.equity}")
        
        # Load symbols
        for asset in ASSETS:
            symbol = ASSETS[asset]['symbol']
            info = self.mt5.get_symbol_info(symbol)
            if not info:
                logger.warning(f"Symbol {symbol} not found")
        
        self.running = True
        logger.info("ICT Trading Bot initialized successfully")
        
        # Send startup notification
        self.notifier.send_alert("Bot Started", "ICT Trading Bot is now running and monitoring kill zones.", "success")
        
        return True
    
    async def run(self):
        """Main trading loop"""
        logger.info("Starting ICT Trading Bot main loop")
        
        # Track when we last ran nightly learning
        last_learning_run = None
        
        while self.running:
            try:
                loop_start = time.time()
                
                # Check daily reset
                await self.check_daily_reset()
                
                # Run nightly learning (once per day at ~22:00 EST = 03:00 EAT)
                now_est = get_current_est_time()
                if last_learning_run != now_est.date() and now_est.hour == 22 and now_est.minute < 5:
                    logger.info("Running nightly trade journal analysis...")
                    analysis = self.learning_loop.run_nightly_analysis()
                    if analysis.get('applied'):
                        self.notifier.send_alert(
                            "Parameters Updated", 
                            f"Nightly learning applied {len(analysis.get('changes', {}))} changes. "
                            f"Win rate: {analysis.get('stats_summary', {}).get('win_rate', 0):.1%}"
                        )
                    last_learning_run = now_est.date()
                
                # Get account state
                account = self.mt5.get_account_info()
                if not account:
                    logger.warning("Failed to get account info")
                    await asyncio.sleep(self.scan_interval)
                    continue
                
                account_state = {
                    'balance': account.balance,
                    'equity': account.equity,
                    'margin': account.margin,
                    'free_margin': getattr(account, 'margin_free', account.margin * 0.5),
                    'margin_level': account.margin_level,
                }
                
                # Daily drawdown check
                if not self.risk.check_daily_dd(account.equity):
                    logger.error(f"Daily DD limit reached! Stopping new entries.")
                    await self.close_all_positions("DAILY_DD_LIMIT")
                    await asyncio.sleep(3600)  # Wait 1 hour
                    continue
                
                # Portfolio heat check
                if not self.risk.check_portfolio_heat(list(self.position_mgr.positions.values()), account.equity):
                    logger.warning("Portfolio heat limit reached, skipping new entries")
                    # Still manage existing positions
                    self.position_mgr.update_positions({'equity': account.equity})
                    await asyncio.sleep(self.scan_interval)
                    continue
                
                # Check market regime and quality (replaces kill zone filter)
                est_now = get_current_est_time()
                in_kz, kz_session, kz_note = is_in_kill_zone(est_now)
                
                # Scan for signals continuously (not just in kill zones)
                # Kill zone still used for signal quality scoring
                kz_str = kz_session.value if kz_session else 'NONE'
                logger.info(f"Scanning for signals... (Kill zone: {kz_str} - {kz_note})")
                
                # Generate signals
                signals = await self.generate_signals()
                
                # Execute signals
                for signal in signals:
                    await self.execute_signal(signal, account)
                
                # Check for approaching entries on pending signals
                await self.check_approaching_entries(account)
                
                # Always update positions (including paired)
                self.position_mgr.update_positions({'equity': self.mt5.get_account_info().equity})
                
                # Sleep to maintain interval
                elapsed = time.time() - loop_start
                sleep_time = max(1, self.scan_interval - elapsed)
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(30)
    
    async def generate_signals(self) -> List[Dict]:
        """Generate signals using ICT logic + market filters + paired positions"""
        signals = []
        est_now = get_current_est_time()
        in_kz, kz_session, kz_note = is_in_kill_zone(est_now)
        
        # Check learned config for disabled symbols/setups/regimes
        learned = self.learning_loop.get_learned_config()
        disabled_symbols = set(learned.get('disabled_symbols', []))
        disabled_killzones = set(learned.get('disabled_killzones', []))
        avoid_regimes = set(learned.get('avoid_regimes', []))
        
        # Market scan for all symbols
        symbols = [ASSETS[a]['symbol'] for a in ASSETS if ASSETS[a].get('enabled', True)]
        market_scan = self.market_analyzer.scan_all_symbols(symbols)
        
        # Also update paired positions
        self.paired_mgr.update_pairs()
        
        for asset_name, asset_config in ASSETS.items():
            symbol = ASSETS[asset_name]['symbol']
            
            # Skip disabled symbols
            if asset_name in disabled_symbols or not self.config['symbols'].get(asset_name, {}).get('enabled', True):
                continue
            
            # Check kill zone filter (learned)
            if kz_session and kz_session.value in disabled_killzones:
                logger.info(f"Skipping {asset_name}: kill zone {kz_session.value} disabled by learning")
                continue
            
            # Market quality check
            market_data = market_scan['all'].get(symbol, {})
            if not market_data.get('valid', False):
                logger.debug(f"Market filter failed for {asset_name}: {market_data.get('reason', 'low score')}")
                continue
            
            # Regime filter
            regime = market_data.get('regime', 'unknown')
            if regime in avoid_regimes:
                logger.info(f"Skipping {asset_name}: regime {regime} avoided by learning")
                continue
            
            # News filter
            blocked, reason = self.news_filter.is_blocked(symbol)
            if blocked:
                logger.warning(f"Signal blocked by news filter for {symbol}: {reason}")
                continue
            
            try:
                # Fetch data
                data = self.mt5.fetch_all_timeframes(asset_name, {
                    'daily': 100,
                    '4h': 200,
                    '15m': 500,
                    '5m': 1000,
                    '1m': 3000,
                })
                
                if not data:
                    continue
                
                daily_candles = dataframe_to_candles(data.get('daily'))
                h4_candles = dataframe_to_candles(data.get('4h'))
                h15_candles = dataframe_to_candles(data.get('15m'))
                h5_candles = dataframe_to_candles(data.get('5m'))
                h1_candles = dataframe_to_candles(data.get('1m'))
                
                if len(h15_candles) < 100 or len(h5_candles) < 100:
                    continue
                
                # Generate intraday signals (enhanced with market quality)
                intraday_setups = self.generate_intraday_for_asset(
                    asset_name, asset_config, h15_candles, h5_candles, est_now
                )
                for s in intraday_setups:
                    # Apply market quality boost to confidence
                    kill_zone_str = s.kill_zone.value if s.kill_zone else 'none'
                    s_dict = {
                        'symbol': symbol,
                        'asset': asset_name,
                        'direction': s.direction,
                        'entry_price': s.entry_price,
                        'stop_loss': s.stop_loss,
                        'take_profit_1': s.take_profit_1,
                        'take_profit_2': s.take_profit_2,
                        'risk_reward': s.risk_reward,
                        'confidence': min(0.95, s.confidence * market_data.get('score', 1.0)),
                        'setup_type': s.setup_type.value,
                        'expires_at': s.expires_at.isoformat() if s.expires_at else None,
                        'kill_zone': kill_zone_str,
                        'session': s.session.value,
                        'market_regime': regime,
                        'market_score': market_data.get('score', 0),
                    }
                    signals.append(s_dict)
                
                # Generate scalp signals (macro windows or always with market quality)
                if is_in_macro_window(est_now) or is_in_silver_bullet(est_now) or market_data.get('score', 0) > 0.7:
                    scalp_setups = self.generate_scalp_for_asset(
                        asset_name, asset_config, h5_candles, h1_candles, est_now
                    )
                    for s in scalp_setups:
                        kill_zone_str = s.kill_zone.value if s.kill_zone else 'none'
                        s_dict = {
                            'symbol': symbol,
                            'asset': asset_name,
                            'direction': s.direction,
                            'entry_price': s.entry_price,
                            'stop_loss': s.stop_loss,
                            'take_profit_1': s.take_profit_1,
                            'take_profit_2': s.take_profit_2,
                            'risk_reward': s.risk_reward,
                            'confidence': min(0.95, s.confidence * market_data.get('score', 1.0)),
                            'setup_type': s.setup_type.value,
                            'expires_at': s.expires_at.isoformat() if s.expires_at else None,
                            'kill_zone': kill_zone_str,
                            'session': s.session.value,
                            'market_regime': regime,
                            'market_score': market_data.get('score', 0),
                        }
                        signals.append(s_dict)
                
                # Create hedged pairs for high-confidence signals
                for sig in [s for s in signals if s['asset'] == asset_name and s['confidence'] > 0.8]:
                    pair = self.paired_mgr.create_hedged_position(sig, hedge_ratio=0.3)
                    if pair:
                        # Add pair_id to both legs
                        for s in signals:
                            if s['asset'] == asset_name and abs(s['entry_price'] - sig['entry_price']) < 0.0001:
                                s['pair_id'] = pair.pair_id
                        
            except Exception as e:
                logger.error(f"Signal generation error for {asset_name}: {e}")
                continue
        
        return signals
    
    def generate_intraday_for_asset(self, asset_name: str, asset_config: Dict,
                                     h15_candles: List, h5_candles: List, 
                                     est_now: datetime) -> List:
        """Generate intraday setups for an asset"""
        # This uses the logic from run_ict_enhanced.generate_intraday_signals
        # Simplified version here - in production would import the full function
        from run_ict_enhanced import generate_intraday_signals
        return generate_intraday_signals(asset_name, asset_config, h15_candles, h5_candles, est_now)
    
    def generate_scalp_for_asset(self, asset_name: str, asset_config: Dict,
                                  h5_candles: List, h1_candles: List,
                                  est_now: datetime) -> List:
        """Generate scalp setups for an asset"""
        from run_ict_enhanced import generate_scalp_signals
        return generate_scalp_signals(asset_name, asset_config, h5_candles, h1_candles, est_now)
    
    async def execute_signal(self, signal: Dict, account_state: Dict):
        """Execute a trading signal"""
        # Risk checks
        if not self.risk.check_total_positions(list(self.position_mgr.positions.values())):
            logger.warning("Max total positions reached")
            return
        
        if not self.risk.check_position_limit(signal['symbol'], 
                                               list(self.position_mgr.positions.values()),
                                               signal['direction']):
            logger.warning(f"Max positions for {signal['symbol']} {signal['direction']} reached")
            return
        
        if not self.risk.check_portfolio_heat(
            list(self.position_mgr.positions.values()),
            self.mt5.get_account_info().equity
        ):
            logger.warning("Portfolio heat limit reached")
            return
        
        # Check news filter
        blocked, reason = self.news_filter.is_blocked(signal['symbol'])
        if blocked:
            logger.warning(f"Signal blocked by news filter: {reason}")
            return
        
        # Check spread
        symbol_info = self.mt5.get_symbol_info(signal['symbol'])
        if not symbol_info:
            logger.error(f"Symbol info not found for {signal['symbol']}")
            return
        
        max_spread = self.config['symbols'].get(signal.get('asset', ''), {}).get('max_spread', 100)
        if symbol_info['spread'] > max_spread:
            logger.warning(f"Spread too high for {signal['symbol']}: {symbol_info['spread']} > {max_spread}")
            return
        
        # Check min RR
        min_rr = self.config['symbols'].get(signal.get('asset', ''), {}).get('min_rr', 2.0)
        if signal.get('risk_reward', 0) < min_rr:
            logger.warning(f"RR too low for {signal['symbol']}: {signal.get('risk_reward')} < {min_rr}")
            return
        # Execute via position manager
        ticket = self.position_mgr.place_bracket_order(signal, 
                                                       {"equity": self.mt5.get_account_info().equity},
                                                       signal)
        if ticket:
            logger.info(f"Executed signal: {signal['symbol']} {signal['direction']} @ {signal['entry_price']}")
            # Send Telegram notification
            self.notifier.send_signal(signal)
            
            # Log trade to journal
            import uuid
            trade_id = str(uuid.uuid4())[:8]
            trade_record = create_trade_record_from_signal(signal, self.position_mgr, trade_id)
            self.trade_journal.log_trade(trade_record)
            
            # Update daily stats
            self.daily_stats['trade_count'] += 1
            
            # Remove from pending signals since we executed it
            asset = signal['asset']
            if asset in self.pending_signals:
                del self.pending_signals[asset]
            if asset in self.notified_approaching:
                self.notified_approaching.discard(asset)
        else:
            # Signal not executed yet - add to pending for approaching notifications
            asset = signal['asset']
            if asset not in self.pending_signals:
                self.pending_signals[asset] = {'signal': signal, 'created_at': datetime.now()}
            logger.info(f"Signal pending for {asset}: waiting for entry at {signal['entry_price']}")
    
    async def close_all_positions(self, reason: str):
        for ticket in list(self.position_mgr.positions.keys()):
            self.position_mgr.close_position(ticket, reason)
    
    async def check_daily_reset(self):
        now = datetime.now()
        if self.last_daily_reset is None or now.date() > self.last_daily_reset.date():
            account = self.mt5.get_account_info()
            if account:
                # Send daily summary before reset
                if self.last_daily_reset is not None:
                    self.daily_stats['daily_pnl'] = account.equity - self.daily_stats['start_equity']
                    self.daily_stats['open_positions'] = len(self.position_mgr.positions)
                    self.notifier.send_daily_summary(self.daily_stats)
                
                self.risk.initialize_daily(account.equity)
                self.daily_stats = {
                    'daily_pnl': 0.0,
                    'trade_count': 0,
                    'wins': 0,
                    'losses': 0,
                    'max_drawdown': 0.0,
                    'open_positions': 0,
                    'start_equity': account.equity
                }
                self.last_daily_reset = now
                logger.info(f"Daily risk reset: Equity={account.equity}")
    
    async def check_approaching_entries(self, account_state: Dict):
        """Check if any pending signals are approaching entry price - send proactive alert"""
        try:
            for asset, signal_info in list(self.pending_signals.items()):
                signal = signal_info['signal']
                symbol = signal['symbol']
                direction = signal['direction']
                entry_price = signal['entry_price']
                
                # Get current price
                tick = self.mt5.get_symbol_tick(symbol)
                if not tick:
                    continue
                
                current_price = tick.ask if direction == 'long' else tick.bid
                
                # Calculate proximity
                if direction == 'long':
                    proximity = (entry_price - current_price) / entry_price
                    is_approaching = proximity > 0 and proximity <= self.entry_proximity_pct
                    is_past = current_price > entry_price * 1.002
                else:
                    proximity = (current_price - entry_price) / entry_price
                    is_approaching = proximity > 0 and proximity <= self.entry_proximity_pct
                    is_past = current_price < entry_price * 0.998
                
                # If price has moved past entry (missed), remove from pending
                if is_past:
                    logger.info(f"Signal expired for {symbol}: price moved past entry")
                    del self.pending_signals[signal['asset']]
                    self.notified_approaching.discard(signal['asset'])
                    continue
                
                # If approaching and not yet notified
                if is_approaching and signal['asset'] not in self.notified_approaching:
                    self.notified_approaching.add(signal['asset'])
                    
                    # Send proactive notification
                    proximity_pct = proximity * 100
                    msg = (
                        f"⚡ <b>ENTRY APPROACHING</b> ⚡\n\n"
                        f"<b>{signal['asset']} {signal['direction'].upper()}</b>\n"
                        f"Entry: {entry_price:.5f}\n"
                        f"Current: {current_price:.5f}\n"
                        f"Distance: {proximity * 100:.2f}%\n"
                        f"SL: {signal['stop_loss']:.5f}\n"
                        f"TP1: {signal['take_profit_1']:.5f}\n"
                        f"RR: {signal.get('risk_reward', 0):.2f}\n"
                        f"Confidence: {signal.get('confidence', 0):.0%}\n"
                        f"Kill Zone: {signal.get('kill_zone', 'N/A')}\n\n"
                        f"<b>Prepare for entry!</b>"
                    )
                    self.notifier.send_alert(f"Entry Approaching: {signal['asset']}", msg, "warning")
                    
        except Exception as e:
            logger.error(f"Error checking approaching entries: {e}")

    def shutdown(self):
        self.running = False
        logger.info("Shutting down...")
        # Close all positions on shutdown
        asyncio.create_task(self.close_all_positions("SHUTDOWN"))
        self.mt5.shutdown()


# ============================================================
# ENTRY POINT
# ============================================================

async def main():
    import json
    with open('bot_config.json', 'r') as f:
        config = json.load(f)
    
    bot = ICTTradingBot(config)
    
    if not await bot.initialize():
        logger.error("Failed to initialize bot")
        return
    
    # Handle shutdown signals
    def signal_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        bot.shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await bot.run()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        bot.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
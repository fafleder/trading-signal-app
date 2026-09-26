"""
Trade Journal Analyzer with LLM Feedback Loop
Self-learning system: logs trades → nightly LLM analysis → parameter updates
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import sqlite3

logger = logging.getLogger(__name__)

@dataclass
class TradeRecord:
    trade_id: str
    timestamp: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    volume: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    confidence: float
    setup_type: str          # intraday, scalp, swing
    kill_zone: str           # london, ny, asian, none
    session: str
    market_regime: str       # trending, ranging, volatile, quiet
    pair_id: Optional[str]   # if part of paired position
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    hold_time_minutes: float = 0.0
    max_favorable: float = 0.0
    max_adverse: float = 0.0
    notes: str = ""

@dataclass
class ParameterSet:
    version: int
    timestamp: str
    # Risk parameters
    max_position_risk_pct: float
    max_portfolio_heat_pct: float
    max_daily_dd_pct: float
    max_positions: int
    max_positions_per_symbol: int
    # Signal filters
    min_rr: Dict[str, float]
    max_spread: Dict[str, float]
    min_confidence: Dict[str, float]
    # Trailing
    trailing_activation_rr: float
    trailing_distance_pct: float
    # Partials
    tp1_pct: float
    tp2_pct: float
    runner_pct: float
    # Session filters
    enabled_sessions: List[str]
    enabled_symbols: List[str]
    # News filter
    news_high_before_min: int
    news_high_after_min: int

class TradeJournal:
    def __init__(self, db_path: str = "trades.db"):
        self.db_path = Path(db_path)
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    symbol TEXT,
                    direction TEXT,
                    entry_price REAL,
                    exit_price REAL,
                    volume REAL,
                    stop_loss REAL,
                    take_profit_1 REAL,
                    take_profit_2 REAL,
                    risk_reward REAL,
                    confidence REAL,
                    setup_type TEXT,
                    kill_zone TEXT,
                    session TEXT,
                    market_regime TEXT,
                    pair_id TEXT,
                    exit_reason TEXT,
                    pnl REAL,
                    pnl_pct REAL,
                    hold_time_minutes REAL,
                    max_favorable REAL,
                    max_adverse REAL,
                    notes TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS parameter_versions (
                    version INTEGER PRIMARY KEY,
                    timestamp TEXT,
                    parameters TEXT,
                    performance_summary TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    period_start TEXT,
                    period_end TEXT,
                    analysis TEXT,
                    recommended_changes TEXT,
                    applied BOOLEAN DEFAULT FALSE
                )
            """)
    
    def log_trade(self, trade: TradeRecord):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, tuple(asdict(trade).values()))
    
    def get_trades(self, days: int = 30) -> List[TradeRecord]:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM trades WHERE timestamp >= ? ORDER BY timestamp", (cutoff,))
            rows = cursor.fetchall()
            return [TradeRecord(**dict(row)) for row in rows]
    
    def get_performance_stats(self, days: int = 30) -> Dict:
        trades = self.get_trades(days)
        if not trades:
            return {}
        
        closed = [t for t in trades if t.exit_price is not None]
        if not closed:
            return {}
        
        wins = [t for t in closed if t.pnl > 0]
        losses = [t for t in closed if t.pnl <= 0]
        
        by_symbol = {}
        for t in closed:
            if t.symbol not in by_symbol:
                by_symbol[t.symbol] = {'wins': 0, 'losses': 0, 'pnl': 0}
            if t.pnl > 0:
                by_symbol[t.symbol]['wins'] += 1
            else:
                by_symbol[t.symbol]['losses'] += 1
            by_symbol[t.symbol]['pnl'] += t.pnl
        
        by_setup = {}
        for t in closed:
            if t.setup_type not in by_setup:
                by_setup[t.setup_type] = {'wins': 0, 'losses': 0, 'pnl': 0}
            if t.pnl > 0:
                by_setup[t.setup_type]['wins'] += 1
            else:
                by_setup[t.setup_type]['losses'] += 1
            by_setup[t.setup_type]['pnl'] += t.pnl
        
        by_killzone = {}
        for t in closed:
            if t.kill_zone not in by_killzone:
                by_killzone[t.kill_zone] = {'wins': 0, 'losses': 0, 'pnl': 0}
            if t.pnl > 0:
                by_killzone[t.kill_zone]['wins'] += 1
            else:
                by_killzone[t.kill_zone]['losses'] += 1
            by_killzone[t.kill_zone]['pnl'] += t.pnl
        
        by_regime = {}
        for t in closed:
            if t.market_regime not in by_regime:
                by_regime[t.market_regime] = {'wins': 0, 'losses': 0, 'pnl': 0}
            if t.pnl > 0:
                by_regime[t.market_regime]['wins'] += 1
            else:
                by_regime[t.market_regime]['losses'] += 1
            by_regime[t.market_regime]['pnl'] += t.pnl
        
        total_pnl = sum(t.pnl for t in closed)
        win_rate = len(wins) / len(closed) if closed else 0
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        return {
            'total_trades': len(closed),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'total_pnl': total_pnl,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'avg_hold_minutes': sum(t.hold_time_minutes for t in closed) / len(closed),
            'by_symbol': by_symbol,
            'by_setup': by_setup,
            'by_killzone': by_killzone,
            'by_regime': by_regime,
        }

class LLMAnalyzer:
    def __init__(self, api_key: str = None):
        self.api_key = api_key
    
    def analyze_journal(self, journal: TradeJournal, days: int = 7) -> Dict:
        """Analyze trade journal and recommend parameter changes"""
        stats = journal.get_performance_stats(days)
        trades = journal.get_trades(days)
        
        if not stats:
            return {"analysis": "No trades to analyze", "changes": {}}
        
        # Build analysis prompt
        prompt = self._build_prompt(stats, trades)
        
        # In production: call LLM API
        # For now: rule-based analysis
        return self._rule_based_analysis(stats, trades)
    
    def _build_prompt(self, stats: Dict, trades: List[TradeRecord]) -> str:
        return f"""
Analyze this trading performance and recommend parameter adjustments:

PERFORMANCE SUMMARY ({stats['total_trades']} trades):
- Win Rate: {stats['win_rate']:.1%}
- Total PnL: ${stats['total_pnl']:.2f}
- Profit Factor: {stats['profit_factor']:.2f}
- Avg Win: ${stats['avg_win']:.2f}
- Avg Loss: ${stats['avg_loss']:.2f}
- Avg Hold: {stats['avg_hold_minutes']:.0f} min

BY SYMBOL:
{json.dumps(stats['by_symbol'], indent=2)}

BY SETUP:
{json.dumps(stats['by_setup'], indent=2)}

BY KILL ZONE:
{json.dumps(stats['by_killzone'], indent=2)}

BY REGIME:
{json.dumps(stats['by_regime'], indent=2)}

RECENT TRADES (last 20):
{json.dumps([{
    'symbol': t.symbol, 'dir': t.direction, 'pnl': t.pnl,
    'setup': t.setup_type, 'kz': t.kill_zone, 'regime': t.market_regime,
    'exit': t.exit_reason, 'rr': t.risk_reward, 'conf': t.confidence
} for t in trades[-20:]], indent=2)}

Recommend specific parameter changes with reasoning. Focus on:
1. Which symbols/setups/regimes to increase/decrease allocation
2. Risk parameter adjustments
3. Confidence/RR threshold changes
4. Session/kill zone filters
"""
    
    def _rule_based_analysis(self, stats: Dict, trades: List[TradeRecord]) -> Dict:
        changes = {}
        reasoning = []
        
        # Win rate too low
        if stats['win_rate'] < 0.45:
            changes['min_confidence'] = {k: v + 0.05 for k, v in {
                'intraday': 0.7, 'scalp': 0.75, 'swing': 0.65
            }.items()}
            reasoning.append(f"Win rate {stats['win_rate']:.1%} < 45%, raising confidence thresholds")
        
        # Profit factor too low
        if stats['profit_factor'] < 1.5:
            changes['min_rr'] = {k: v + 0.5 for k, v in {
                'XAUUSD': 2.0, 'NASDAQ': 2.0, 'EURUSD': 2.0, 'GBPUSD': 2.0
            }.items()}
            reasoning.append(f"Profit factor {stats['profit_factor']:.2f} < 1.5, raising min RR")
        
        # Symbol-specific
        for symbol, data in stats['by_symbol'].items():
            wr = data['wins'] / (data['wins'] + data['losses']) if (data['wins'] + data['losses']) > 0 else 0
            if wr < 0.4 and data['losses'] > 3:
                changes.setdefault('disabled_symbols', []).append(symbol)
                reasoning.append(f"Disabling {symbol}: win rate {wr:.1%} over {data['wins']+data['losses']} trades")
        
        # Setup-specific
        for setup, data in stats['by_setup'].items():
            wr = data['wins'] / (data['wins'] + data['losses']) if (data['wins'] + data['losses']) > 0 else 0
            if wr < 0.35 and data['losses'] > 3:
                changes.setdefault('disabled_setups', []).append(setup)
                reasoning.append(f"Disabling {setup}: win rate {wr:.1%}")
        
        # Kill zone
        for kz, data in stats['by_killzone'].items():
            wr = data['wins'] / (data['wins'] + data['losses']) if (data['wins'] + data['losses']) > 0 else 0
            if wr < 0.3 and data['losses'] > 5:
                changes.setdefault('disabled_killzones', []).append(kz)
                reasoning.append(f"Disabling {kz} kill zone: win rate {wr:.1%}")
        
        # Regime
        for regime, data in stats['by_regime'].items():
            wr = data['wins'] / (data['wins'] + data['losses']) if (data['wins'] + data['losses']) > 0 else 0
            if wr < 0.3 and data['losses'] > 3:
                changes.setdefault('avoid_regimes', []).append(regime)
                reasoning.append(f"Avoiding {regime} regime: win rate {wr:.1%}")
        
        # Hold time too long (chopping)
        if stats['avg_hold_minutes'] > 120:
            changes['trailing_activation_rr'] = 0.5
            reasoning.append(f"Avg hold {stats['avg_hold_minutes']:.0f}min > 2hr, faster trailing")
        
        return {
            "analysis": "Rule-based analysis of trade journal",
            "reasoning": reasoning,
            "changes": changes,
            "stats_summary": {
                'win_rate': stats['win_rate'],
                'profit_factor': stats['profit_factor'],
                'total_pnl': stats['total_pnl'],
                'total_trades': stats['total_trades']
            }
        }
    
    def save_analysis(self, journal: TradeJournal, analysis: Dict):
        with sqlite3.connect(journal.db_path) as conn:
            conn.execute("""
                INSERT INTO llm_analyses (timestamp, period_start, period_end, analysis, recommended_changes)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                (datetime.now() - timedelta(days=7)).isoformat(),
                datetime.now().isoformat(),
                json.dumps(analysis),
                json.dumps(analysis.get('changes', {}))
            ))


class SelfLearningLoop:
    """Nightly self-learning: analyze journal → update parameters → save version"""
    
    def __init__(self, journal: TradeJournal, analyzer: LLMAnalyzer, config_path: str):
        self.journal = journal
        self.analyzer = analyzer
        self.config_path = Path(config_path)
        self.current_params = self._load_current_params()
        self.param_version = 0
    
    def _load_current_params(self) -> ParameterSet:
        with open(self.config_path) as f:
            config = json.load(f)
        return ParameterSet(
            version=0,
            timestamp=datetime.now().isoformat(),
            max_position_risk_pct=config['risk']['max_position_risk_pct'],
            max_portfolio_heat_pct=config['risk']['max_portfolio_heat_pct'],
            max_daily_dd_pct=config['risk']['max_daily_dd_pct'],
            max_positions=config['risk']['max_positions'],
            max_positions_per_symbol=config['risk']['max_positions_per_symbol'],
            min_rr=config['symbols'],
            max_spread={k: v.get('max_spread', 100) for k, v in config['symbols'].items()},
            min_confidence={'intraday': 0.7, 'scalp': 0.75, 'swing': 0.65},
            trailing_activation_rr=config['trailing']['activation_rr'],
            trailing_distance_pct=config['trailing']['distance_pct'],
            tp1_pct=config['partials']['tp1_pct'],
            tp2_pct=config['partials']['tp2_pct'],
            runner_pct=config['partials']['runner_pct'],
            enabled_sessions=['london', 'ny'],
            enabled_symbols=list(config['symbols'].keys()),
            news_high_before_min=config['news_filter']['high_impact_minutes_before'],
            news_high_after_min=config['news_filter']['high_impact_minutes_after'],
        )
    
    def run_nightly_analysis(self) -> Dict:
        """Run the nightly learning cycle"""
        logger.info("Starting nightly trade journal analysis...")
        
        # Analyze
        analysis = self.analyzer.analyze_journal(self.journal, days=7)
        
        # Apply changes
        if analysis.get('changes'):
            self._apply_changes(analysis['changes'])
            analysis['applied'] = True
        else:
            analysis['applied'] = False
        
        # Save analysis
        self.analyzer.save_analysis(self.journal, analysis)
        
        # Save new parameter version
        self._save_param_version(analysis)
        
        logger.info(f"Nightly analysis complete. Applied: {analysis['applied']}")
        return analysis
    
    def _apply_changes(self, changes: Dict):
        """Apply recommended changes to current parameters"""
        # Update confidence thresholds
        if 'min_confidence' in changes:
            self.current_params.min_confidence.update(changes['min_confidence'])
        
        # Update min RR
        if 'min_rr' in changes:
            self.current_params.min_rr.update(changes['min_rr'])
        
        # Disable symbols
        if 'disabled_symbols' in changes:
            for sym in changes['disabled_symbols']:
                if sym in self.current_params.enabled_symbols:
                    self.current_params.enabled_symbols.remove(sym)
        
        # Disable setups
        if 'disabled_setups' in changes:
            # Would need to filter in signal generation
            pass
        
        # Disable kill zones
        if 'disabled_killzones' in changes:
            for kz in changes['disabled_killzones']:
                if kz in self.current_params.enabled_sessions:
                    self.current_params.enabled_sessions.remove(kz)
        
        # Avoid regimes
        if 'avoid_regimes' in changes:
            self.current_params.__dict__['avoid_regimes'] = changes['avoid_regimes']
        
        # Trailing
        if 'trailing_activation_rr' in changes:
            self.current_params.trailing_activation_rr = changes['trailing_activation_rr']
        
        self.param_version += 1
        self.current_params.version = self.param_version
        self.current_params.timestamp = datetime.now().isoformat()
    
    def _save_param_version(self, analysis: Dict):
        with sqlite3.connect(self.journal.db_path) as conn:
            conn.execute("""
                INSERT INTO parameter_versions (version, timestamp, parameters, performance_summary)
                VALUES (?, ?, ?, ?)
            """, (
                self.param_version,
                datetime.now().isoformat(),
                json.dumps(self.current_params.__dict__),
                json.dumps(analysis.get('stats_summary', {}))
            ))
        
        # Also save to JSON for bot reload
        config_update = {
            'risk': {
                'max_position_risk_pct': self.current_params.max_position_risk_pct,
                'max_portfolio_heat_pct': self.current_params.max_portfolio_heat_pct,
                'max_daily_dd_pct': self.current_params.max_daily_dd_pct,
                'max_positions': self.current_params.max_positions,
                'max_positions_per_symbol': self.current_params.max_positions_per_symbol,
            },
            'symbols': {k: {'min_rr': v, 'max_spread': self.current_params.max_spread.get(k, 100)} 
                       for k, v in self.current_params.min_rr.items()},
            'trailing': {
                'activation_rr': self.current_params.trailing_activation_rr,
                'distance_pct': self.current_params.trailing_distance_pct,
            },
            'partials': {
                'tp1_pct': self.current_params.tp1_pct,
                'tp2_pct': self.current_params.tp2_pct,
                'runner_pct': self.current_params.runner_pct,
            },
            'news_filter': {
                'high_impact_minutes_before': self.current_params.news_high_before_min,
                'high_impact_minutes_after': self.current_params.news_high_after_min,
            }
        }
        
        # Add learned filters
        if hasattr(self.current_params, 'avoid_regimes'):
            config_update['avoid_regimes'] = self.current_params.avoid_regimes
        if hasattr(self.current_params, 'disabled_symbols'):
            config_update['disabled_symbols'] = self.current_params.disabled_symbols
        
        with open(self.config_path.with_name('bot_config_learned.json'), 'w') as f:
            json.dump(config_update, f, indent=2)
    
    def get_learned_config(self) -> Dict:
        """Get the latest learned configuration"""
        learned_path = self.config_path.with_name('bot_config_learned.json')
        if learned_path.exists():
            with open(learned_path) as f:
                return json.load(f)
        return {}


# Integration with trading bot
def create_trade_record_from_signal(signal: Dict, position_mgr, trade_id: str) -> TradeRecord:
    """Create trade record when position opened"""
    return TradeRecord(
        trade_id=trade_id,
        timestamp=datetime.now().isoformat(),
        symbol=signal['symbol'],
        direction=signal['direction'],
        entry_price=signal['entry_price'],
        exit_price=None,
        volume=signal.get('volume', 0.01),
        stop_loss=signal['stop_loss'],
        take_profit_1=signal['take_profit_1'],
        take_profit_2=signal['take_profit_2'],
        risk_reward=signal.get('risk_reward', 0),
        confidence=signal.get('confidence', 0),
        setup_type=signal.get('setup_type', 'intraday'),
        kill_zone=signal.get('kill_zone', 'none'),
        session=signal.get('session', 'none'),
        market_regime=signal.get('market_regime', 'unknown'),
        pair_id=signal.get('pair_id')
    )


def update_trade_on_close(journal: TradeJournal, trade_id: str, exit_price: float, 
                          exit_reason: str, pnl: float, hold_minutes: float,
                          max_fav: float, max_adv: float):
    """Update trade record when position closed"""
    trades = journal.get_trades(365)  # Get all
    for t in trades:
        if t.trade_id == trade_id:
            t.exit_price = exit_price
            t.exit_reason = exit_reason
            t.pnl = pnl
            t.pnl_pct = pnl / (t.entry_price * t.volume) * 100
            t.hold_time_minutes = hold_minutes
            t.max_favorable = max_fav
            t.max_adverse = max_adv
            journal.log_trade(t)
            break
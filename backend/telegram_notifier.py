"""
Telegram Notifier for ICT Trading Bot
Sends trade signals, execution confirmations, and alerts
"""

import os
import requests
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, bot_token: str = None, chat_id: str = None):
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)
        
    def send(self, message: str, parse_mode: str = 'HTML') -> bool:
        """Send message to Telegram"""
        if not self.enabled:
            logger.debug("Telegram not configured, skipping send")
            return False
        
        try:
            url = f'https://api.telegram.org/bot{self.bot_token}/sendMessage'
            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram message sent")
                return True
            else:
                logger.error(f"Telegram send failed: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return False
    
    def send_signal(self, signal: Dict) -> bool:
        """Send new signal notification"""
        direction_emoji = "🟢" if signal['direction'] == 'long' else "🔴"
        setup_emoji = {"intraday": "📈", "scalp": "⚡", "swing": "📊"}.get(signal.get('setup_type', ''), "📈")
        
        message = f"{direction_emoji} <b>New ICT {signal.get('setup_type', 'Intraday').upper()} Signal</b>\n\n"
        message += f"<b>{signal['asset']} {signal['direction'].upper()}</b>\n"
        message += f"Entry: {signal['entry_price']:.5f}\n"
        message += f"SL: {signal['stop_loss']:.5f}\n"
        message += f"TP1: {signal['take_profit_1']:.5f}\n"
        message += f"TP2: {signal['take_profit_2']:.5f}\n"
        message += f"R:R: {signal.get('risk_reward', 0):.2f} | Conf: {signal.get('confidence', 0):.0%}\n"
        message += f"Exp: {signal.get('expires_at', 'N/A')}\n"
        message += f"KZ: {signal.get('kill_zone', 'N/A')}\n"
        
        if signal.get('notes'):
            message += f"\n📝 {signal['notes']}"
        
        return self.send(message)
    
    def send_execution(self, signal: Dict, ticket: int, volume: float, fill_price: float) -> bool:
        """Send trade execution confirmation"""
        direction_emoji = "🟢" if signal['direction'] == 'long' else "🔴"
        
        message = f"{direction_emoji} <b>Trade Executed</b>\n\n"
        message += f"<b>{signal['asset']} {signal['direction'].upper()}</b>\n"
        message += f"Ticket: #{ticket}\n"
        message += f"Volume: {volume:.2f}\n"
        message += f"Fill: {fill_price:.5f}\n"
        message += f"SL: {signal['stop_loss']:.5f}\n"
        message += f"TP1: {signal['take_profit_1']:.5f}\n"
        message += f"TP2: {signal['take_profit_2']:.5f}\n"
        
        return self.send(message)
    
    def send_tp_hit(self, symbol: str, tp_level: str, pnl: float, volume: float) -> bool:
        """Send take profit hit notification"""
        message = f"✅ <b>TP Hit: {symbol}</b>\n"
        message += f"Level: {tp_level}\n"
        message += f"PnL: ${pnl:.2f}\n"
        message += f"Volume: {volume:.2f}"
        return self.send(message)
    
    def send_sl_hit(self, symbol: str, pnl: float, volume: float) -> bool:
        """Send stop loss hit notification"""
        message = f"🛑 <b>SL Hit: {symbol}</b>\n"
        message += f"PnL: ${pnl:.2f}\n"
        message += f"Volume: {volume:.2f}"
        return self.send(message)
    
    def send_daily_summary(self, stats: Dict) -> bool:
        """Send daily performance summary"""
        pnl_emoji = "🟢" if stats.get('daily_pnl', 0) >= 0 else "🔴"
        
        message = f"{pnl_emoji} <b>Daily Summary</b>\n\n"
        message += f"Date: {datetime.now().strftime('%Y-%m-%d')}\n"
        message += f"PnL: ${stats.get('daily_pnl', 0):.2f}\n"
        message += f"Trades: {stats.get('trade_count', 0)}\n"
        message += f"Wins: {stats.get('wins', 0)} | Losses: {stats.get('losses', 0)}\n"
        message += f"Win Rate: {stats.get('win_rate', 0):.1f}%\n"
        message += f"Max DD: ${stats.get('max_drawdown', 0):.2f}\n"
        message += f"Open Positions: {stats.get('open_positions', 0)}"
        
        return self.send(message)
    
    def send_alert(self, title: str, message: str, level: str = 'info') -> bool:
        """Send custom alert"""
        emoji = {"info": "ℹ️", "warning": "⚠️", "error": "🚨", "success": "✅"}.get(level, "ℹ️")
        full_msg = f"{emoji} <b>{title}</b>\n\n{message}"
        return self.send(full_msg)


# Singleton
_notifier = None

def get_notifier(bot_token: str = None, chat_id: str = None) -> TelegramNotifier:
    global _notifier
    if _notifier is None:
        _notifier = TelegramNotifier(bot_token, chat_id)
    return _notifier
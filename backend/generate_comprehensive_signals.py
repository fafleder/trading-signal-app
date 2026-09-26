#!/usr/bin/env python3
"""
Comprehensive Trading Signal Generator
Generates signals for stocks, crypto, forex, and commodities using technical analysis
"""
import os
import json
import asyncio
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from pathlib import Path
import ta
from ta.trend import SMAIndicator, EMAIndicator, MACD
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).parent / '.cache'
CACHE_DIR.mkdir(exist_ok=True)

# Major market instruments to analyze
INSTRUMENTS = {
    # US Indices
    'SPX': {'symbol': '^GSPC', 'name': 'S&P 500', 'market': 'STOCK_INDEX', 'timezone': 'US'},
    'NDX': {'symbol': '^NDX', 'name': 'NASDAQ 100', 'market': 'STOCK_INDEX', 'timezone': 'US'},
    'DJI': {'symbol': '^DJI', 'name': 'Dow Jones Industrial', 'market': 'STOCK_INDEX', 'timezone': 'US'},
    'RUT': {'symbol': '^RUT', 'name': 'Russell 2000', 'market': 'STOCK_INDEX', 'timezone': 'US'},
    
    # Major Stocks
    'AAPL': {'symbol': 'AAPL', 'name': 'Apple Inc.', 'market': 'STOCK', 'timezone': 'US'},
    'MSFT': {'symbol': 'MSFT', 'name': 'Microsoft Corp.', 'market': 'STOCK', 'timezone': 'US'},
    'NVDA': {'symbol': 'NVDA', 'name': 'NVIDIA Corp.', 'market': 'STOCK', 'timezone': 'US'},
    'GOOGL': {'symbol': 'GOOGL', 'name': 'Alphabet Inc.', 'market': 'STOCK', 'timezone': 'US'},
    'TSLA': {'symbol': 'TSLA', 'name': 'Tesla Inc.', 'market': 'STOCK', 'timezone': 'US'},
    
    # Crypto
    'BTC-USD': {'symbol': 'BTC-USD', 'name': 'Bitcoin', 'market': 'CRYPTO', 'timezone': '24/7'},
    'ETH-USD': {'symbol': 'ETH-USD', 'name': 'Ethereum', 'market': 'CRYPTO', 'timezone': '24/7'},
    'SOL-USD': {'symbol': 'SOL-USD', 'name': 'Solana', 'market': 'CRYPTO', 'timezone': '24/7'},
    
    # Forex
    'EURUSD=X': {'symbol': 'EURUSD=X', 'name': 'EUR/USD', 'market': 'FOREX', 'timezone': '24/5'},
    'GBPUSD=X': {'symbol': 'GBPUSD=X', 'name': 'GBP/USD', 'market': 'FOREX', 'timezone': '24/5'},
    'USDJPY=X': {'symbol': 'USDJPY=X', 'name': 'USD/JPY', 'market': 'FOREX', 'timezone': '24/5'},
    'AUDUSD=X': {'symbol': 'AUDUSD=X', 'name': 'AUD/USD', 'market': 'FOREX', 'timezone': '24/5'},
    'USDCAD=X': {'symbol': 'USDCAD=X', 'name': 'USD/CAD', 'market': 'FOREX', 'timezone': '24/5'},
    'USDCHF=X': {'symbol': 'USDCHF=X', 'name': 'USD/CHF', 'market': 'FOREX', 'timezone': '24/5'},
    
    # Commodities
    'GC=F': {'symbol': 'GC=F', 'name': 'Gold', 'market': 'COMMODITY', 'timezone': '24/5'},
    'SI=F': {'symbol': 'SI=F', 'name': 'Silver', 'market': 'COMMODITY', 'timezone': '24/5'},
    'CL=F': {'symbol': 'CL=F', 'name': 'Crude Oil WTI', 'market': 'COMMODITY', 'timezone': '24/5'},
    'BZ=F': {'symbol': 'BZ=F', 'name': 'Brent Crude', 'market': 'COMMODITY', 'timezone': '24/5'},
}

# Market hours (EAT timezone)
MARKET_HOURS = {
    'US': {'open': 14.5, 'close': 21.0},  # 2:30 PM - 9:00 PM EAT
    'LONDON': {'open': 10.0, 'close': 19.0},  # 10:00 AM - 7:00 PM EAT
    'ASIAN': {'open': 2.0, 'close': 11.0},  # 2:00 AM - 11:00 AM EAT
    '24/7': {'open': 0.0, 'close': 24.0},
    '24/5': {'open': 0.0, 'close': 24.0},
}

def is_market_open(timezone_key: str) -> bool:
    """Check if market is currently open based on timezone"""
    now = datetime.now()
    current_hour = now.hour + now.minute / 60.0
    hours = MARKET_HOURS.get(timezone_key, {'open': 0, 'close': 24})
    return hours['open'] <= current_hour < hours['close']

def fetch_ohlcv(symbol: str, period: str = '3mo', interval: str = '1d') -> pd.DataFrame:
    """Fetch OHLCV data from yfinance"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=False)
        if df.empty:
            logger.warning(f"No data returned for {symbol}")
            return pd.DataFrame()
        
        # Ensure proper column names
        df.columns = [col.lower().replace(' ', '_') for col in df.columns]
        df = df[['open', 'high', 'low', 'close', 'volume']].dropna()
        return df
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return pd.DataFrame()

def calculate_indicators(df: pd.DataFrame) -> dict:
    """Calculate all technical indicators"""
    if len(df) < 50:
        return {}
    
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
    indicators = {}
    
    # Moving Averages
    indicators['sma_20'] = SMAIndicator(close, window=20).sma_indicator().iloc[-1]
    indicators['sma_50'] = SMAIndicator(close, window=50).sma_indicator().iloc[-1]
    indicators['sma_100'] = SMAIndicator(close, window=100).sma_indicator().iloc[-1] if len(df) >= 100 else None
    indicators['sma_200'] = SMAIndicator(close, window=200).sma_indicator().iloc[-1] if len(df) >= 200 else None
    indicators['ema_20'] = EMAIndicator(close, window=20).ema_indicator().iloc[-1]
    indicators['ema_50'] = EMAIndicator(close, window=50).ema_indicator().iloc[-1]
    indicators['ema_200'] = EMAIndicator(close, window=200).ema_indicator().iloc[-1] if len(df) >= 200 else None
    
    # RSI
    indicators['rsi_14'] = RSIIndicator(close, window=14).rsi().iloc[-1]
    indicators['rsi_7'] = RSIIndicator(close, window=7).rsi().iloc[-1]
    
    # MACD
    macd = MACD(close)
    indicators['macd'] = macd.macd().iloc[-1]
    indicators['macd_signal'] = macd.macd_signal().iloc[-1]
    indicators['macd_histogram'] = macd.macd_diff().iloc[-1]
    
    # Stochastic
    stoch = StochasticOscillator(high, low, close)
    indicators['stoch_k'] = stoch.stoch().iloc[-1]
    indicators['stoch_d'] = stoch.stoch_signal().iloc[-1]
    
    # Bollinger Bands
    bb = BollingerBands(close)
    indicators['bb_upper'] = bb.bollinger_hband().iloc[-1]
    indicators['bb_middle'] = bb.bollinger_mavg().iloc[-1]
    indicators['bb_lower'] = bb.bollinger_lband().iloc[-1]
    indicators['bb_width'] = (indicators['bb_upper'] - indicators['bb_lower']) / indicators['bb_middle']
    indicators['bb_position'] = (close.iloc[-1] - indicators['bb_lower']) / (indicators['bb_upper'] - indicators['bb_lower'])
    
    # ATR
    atr = AverageTrueRange(high, low, close)
    indicators['atr_14'] = atr.average_true_range().iloc[-1]
    
    # OBV
    obv = OnBalanceVolumeIndicator(close, volume)
    indicators['obv'] = obv.on_balance_volume().iloc[-1]
    indicators['obv_change'] = indicators['obv'] - obv.on_balance_volume().iloc[-2] if len(df) > 1 else 0
    
    # ADX (trend strength)
    try:
        from ta.trend import ADXIndicator
        adx = ADXIndicator(high, low, close)
        indicators['adx'] = adx.adx().iloc[-1]
    except:
        indicators['adx'] = None
    
    # Price action
    indicators['current_price'] = close.iloc[-1]
    indicators['prev_close'] = close.iloc[-2] if len(df) > 1 else close.iloc[-1]
    indicators['daily_change'] = ((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100) if len(df) > 1 else 0
    indicators['high_20'] = high.tail(20).max()
    indicators['low_20'] = low.tail(20).min()
    indicators['high_50'] = high.tail(50).max()
    indicators['low_50'] = low.tail(50).min()
    
    # Volume
    indicators['avg_volume_20'] = volume.tail(20).mean()
    indicators['volume_ratio'] = volume.iloc[-1] / indicators['avg_volume_20'] if indicators['avg_volume_20'] > 0 else 1
    
    return indicators

def analyze_trend(indicators: dict) -> dict:
    """Analyze trend direction and strength"""
    if not indicators:
        return {'direction': 'UNKNOWN', 'strength': 0, 'score': 0}
    
    price = indicators['current_price']
    score = 0
    reasons = []
    
    # MA Stack Analysis
    ma_bullish = 0
    ma_bearish = 0
    
    if indicators.get('sma_20') and price > indicators['sma_20']:
        ma_bullish += 1
    else:
        ma_bearish += 1
        
    if indicators.get('sma_50') and price > indicators['sma_50']:
        ma_bullish += 1
    else:
        ma_bearish += 1
        
    if indicators.get('ema_20') and price > indicators['ema_20']:
        ma_bullish += 1
    else:
        ma_bearish += 1
        
    if indicators.get('ema_50') and price > indicators['ema_50']:
        ma_bullish += 1
    else:
        ma_bearish += 1
    
    # EMA alignment
    if indicators.get('ema_20') and indicators.get('ema_50'):
        if indicators['ema_20'] > indicators['ema_50']:
            ma_bullish += 1
        else:
            ma_bearish += 1
    
    score += (ma_bullish - ma_bearish) * 0.15
    if ma_bullish > ma_bearish:
        reasons.append(f"MA stack bullish ({ma_bullish}/{ma_bullish+ma_bearish})")
    elif ma_bearish > ma_bullish:
        reasons.append(f"MA stack bearish ({ma_bearish}/{ma_bullish+ma_bearish})")
    
    # RSI
    rsi = indicators.get('rsi_14', 50)
    if rsi > 70:
        score -= 0.1
        reasons.append(f"RSI overbought ({rsi:.1f})")
    elif rsi > 60:
        score += 0.1
        reasons.append(f"RSI bullish zone ({rsi:.1f})")
    elif rsi < 30:
        score += 0.1
        reasons.append(f"RSI oversold ({rsi:.1f}) - bounce potential")
    elif rsi < 40:
        score -= 0.1
        reasons.append(f"RSI bearish zone ({rsi:.1f})")
    else:
        reasons.append(f"RSI neutral ({rsi:.1f})")
    
    # MACD
    macd = indicators.get('macd', 0)
    macd_signal = indicators.get('macd_signal', 0)
    macd_hist = indicators.get('macd_histogram', 0)
    
    if macd > macd_signal and macd_hist > 0:
        score += 0.2
        reasons.append("MACD bullish (histogram expanding)")
    elif macd > macd_signal and macd_hist < 0:
        score += 0.1
        reasons.append("MACD bullish (histogram contracting)")
    elif macd < macd_signal and macd_hist < 0:
        score -= 0.2
        reasons.append("MACD bearish (histogram expanding)")
    else:
        score -= 0.1
        reasons.append("MACD bearish (histogram contracting)")
    
    # Bollinger Bands
    bb_pos = indicators.get('bb_position', 0.5)
    if bb_pos > 0.8:
        score -= 0.1
        reasons.append("Near upper BB - overbought risk")
    elif bb_pos < 0.2:
        score += 0.1
        reasons.append("Near lower BB - oversold bounce potential")
    elif bb_pos > 0.5:
        score += 0.05
        reasons.append("Above BB middle - bullish bias")
    else:
        score -= 0.05
        reasons.append("Below BB middle - bearish bias")
    
    # ADX
    adx = indicators.get('adx')
    if adx and adx > 25:
        reasons.append(f"Strong trend (ADX: {adx:.1f})")
    elif adx and adx > 20:
        reasons.append(f"Moderate trend (ADX: {adx:.1f})")
    else:
        reasons.append("Weak/No trend (ADX < 20)")
    
    # Volume
    vol_ratio = indicators.get('volume_ratio', 1)
    if vol_ratio > 1.5:
        reasons.append(f"High volume ({vol_ratio:.1f}x avg) - conviction")
        if score > 0:
            score += 0.05
        else:
            score -= 0.05
    elif vol_ratio < 0.5:
        reasons.append("Low volume - lack of conviction")
    
    # Price momentum
    daily_change = indicators.get('daily_change', 0)
    if daily_change > 1:
        score += 0.05
        reasons.append(f"Strong daily gain (+{daily_change:.1f}%)")
    elif daily_change < -1:
        score -= 0.05
        reasons.append(f"Strong daily loss ({daily_change:.1f}%)")
    
    # Determine direction
    if score > 0.3:
        direction = 'STRONGLY_BULLISH'
    elif score > 0.1:
        direction = 'BULLISH'
    elif score > -0.1:
        direction = 'NEUTRAL'
    elif score > -0.3:
        direction = 'BEARISH'
    else:
        direction = 'STRONGLY_BEARISH'
    
    strength = min(abs(score) * 100, 100)
    confidence = min(50 + abs(score) * 50, 95)
    
    return {
        'direction': direction,
        'strength': round(strength, 1),
        'confidence': round(confidence, 1),
        'score': round(score, 3),
        'reasons': reasons
    }

def calculate_levels(indicators: dict, direction: str) -> dict:
    """Calculate support/resistance levels and trade setup"""
    if not indicators:
        return {}
    
    price = indicators['current_price']
    atr = indicators.get('atr_14', price * 0.01)
    bb_upper = indicators.get('bb_upper', price * 1.02)
    bb_lower = indicators.get('bb_lower', price * 0.98)
    bb_middle = indicators.get('bb_middle', price)
    sma_20 = indicators.get('sma_20', price)
    sma_50 = indicators.get('sma_50', price)
    high_20 = indicators.get('high_20', price * 1.02)
    low_20 = indicators.get('low_20', price * 0.98)
    high_50 = indicators.get('high_50', price * 1.05)
    low_50 = indicators.get('low_50', price * 0.95)
    
    if 'BULLISH' in direction:
        entry = round(price * 0.997, 2)  # Slight pullback entry
        stop_loss = round(min(sma_20, bb_lower, price - 1.5 * atr), 2)
        tp1 = round(max(bb_middle, high_20), 2)
        tp2 = round(high_50, 2)
        tp3 = round(high_50 * 1.02, 2)
    elif 'BEARISH' in direction:
        entry = round(price * 1.003, 2)  # Slight rally entry
        stop_loss = round(max(sma_20, bb_upper, price + 1.5 * atr), 2)
        tp1 = round(min(bb_middle, low_20), 2)
        tp2 = round(low_50, 2)
        tp3 = round(low_50 * 0.98, 2)
    else:
        entry = round(price, 2)
        stop_loss = round(price - 2 * atr, 2)
        tp1 = round(price + 1.5 * atr, 2)
        tp2 = round(price + 3 * atr, 2)
        tp3 = round(price + 4.5 * atr, 2)
    
    risk = abs(entry - stop_loss)
    reward1 = abs(tp1 - entry)
    reward2 = abs(tp2 - entry)
    reward3 = abs(tp3 - entry)
    
    rr1 = round(reward1 / risk, 2) if risk > 0 else 0
    rr2 = round(reward2 / risk, 2) if risk > 0 else 0
    rr3 = round(reward3 / risk, 2) if risk > 0 else 0
    
    return {
        'resistance_1': round(max(bb_upper, high_20), 2),
        'resistance_2': round(high_50, 2),
        'resistance_3': round(high_50 * 1.02, 2),
        'support_1': round(min(bb_lower, low_20), 2),
        'support_2': round(low_50, 2),
        'support_3': round(low_50 * 0.98, 2),
        'pivot': round(bb_middle, 2),
        'trade_setup': {
            'entry': entry,
            'stop_loss': stop_loss,
            'take_profit_1': tp1,
            'take_profit_2': tp2,
            'take_profit_3': tp3,
            'risk_reward_1': rr1,
            'risk_reward_2': rr2,
            'risk_reward_3': rr3,
        }
    }

def get_market_context(symbol: str, market: str) -> dict:
    """Get fundamental/market context"""
    context = {}
    
    if market == 'STOCK_INDEX' or market == 'STOCK':
        context['sector'] = 'Technology' if symbol in ['^NDX', 'AAPL', 'MSFT', 'NVDA', 'GOOGL'] else 'Broad Market'
        context['catalysts'] = ['Fed policy', 'Earnings', 'AI/Tech trends', 'Macro data']
    elif market == 'CRYPTO':
        context['sector'] = 'Digital Assets'
        context['catalysts'] = ['ETF flows', 'Regulatory news', 'On-chain metrics', 'Macro liquidity']
    elif market == 'FOREX':
        context['sector'] = 'Currencies'
        context['catalysts'] = ['Central bank policy', 'Inflation data', 'Employment', 'Geopolitics']
    elif market == 'COMMODITY':
        context['sector'] = 'Commodities'
        context['catalysts'] = ['Supply/demand', 'Geopolitics', 'Dollar strength', 'Inventory data']
    
    return context

async def generate_signal_for_instrument(key: str, info: dict) -> dict:
    """Generate complete trading signal for one instrument"""
    symbol = info['symbol']
    name = info['name']
    market = info['market']
    timezone = info['timezone']
    
    logger.info(f"Analyzing {name} ({symbol})...")
    
    # Fetch data
    df = fetch_ohlcv(symbol, period='6mo', interval='1d')
    if df.empty or len(df) < 50:
        logger.warning(f"Insufficient data for {symbol}")
        return None
    
    # Calculate indicators
    indicators = calculate_indicators(df)
    if not indicators:
        return None
    
    # Analyze trend
    trend = analyze_trend(indicators)
    
    # Calculate levels
    levels = calculate_levels(indicators, trend['direction'])
    
    # Market context
    context = get_market_context(symbol, market)
    
    # Check market hours
    market_open = is_market_open(timezone)
    
    # Build signal
    signal = {
        'instrument': name,
        'symbol': symbol,
        'market': market,
        'current_price': round(indicators['current_price'], 2),
        'daily_change_pct': round(indicators['daily_change'], 2),
        'direction': trend['direction'],
        'confidence': trend['confidence'],
        'strength': trend['strength'],
        'timeframe': 'Intraday / Swing (1-5 days)' if market in ['STOCK', 'STOCK_INDEX'] else 'Swing (3-10 days)',
        'market_open': market_open,
        'market_timezone': timezone,
        'technical_summary': {
            'rsi_14': round(indicators.get('rsi_14', 0), 2),
            'rsi_7': round(indicators.get('rsi_7', 0), 2),
            'macd': f"{'Bullish' if indicators.get('macd', 0) > indicators.get('macd_signal', 0) else 'Bearish'} ({indicators.get('macd', 0):.2f}), histogram {'expanding' if indicators.get('macd_histogram', 0) > 0 else 'contracting'}",
            'ma_trend': f"Price {'above' if indicators['current_price'] > indicators.get('sma_20', 0) else 'below'} MA20 ({indicators.get('sma_20', 0):.2f}), MA50 ({indicators.get('sma_50', 0):.2f})",
            'adx_14': round(indicators.get('adx', 0), 2) if indicators.get('adx') else None,
            'stoch_k': round(indicators.get('stoch_k', 0), 2),
            'stoch_d': round(indicators.get('stoch_d', 0), 2),
            'bb_position': f"{'Upper' if indicators.get('bb_position', 0.5) > 0.7 else 'Lower' if indicators.get('bb_position', 0.5) < 0.3 else 'Middle'} band ({indicators.get('bb_position', 0.5)*100:.0f}%)",
            'volume_trend': f"{'High' if indicators.get('volume_ratio', 1) > 1.5 else 'Low' if indicators.get('volume_ratio', 1) < 0.5 else 'Average'} ({indicators.get('volume_ratio', 1):.1f}x avg)",
            'atr_14': round(indicators.get('atr_14', 0), 2),
        },
        'key_levels': {
            'resistance_1': levels.get('resistance_1'),
            'resistance_2': levels.get('resistance_2'),
            'resistance_3': levels.get('resistance_3'),
            'support_1': levels.get('support_1'),
            'support_2': levels.get('support_2'),
            'support_3': levels.get('support_3'),
            'pivot': levels.get('pivot'),
        },
        'trade_setup': levels.get('trade_setup', {}),
        'market_context': context,
        'rationale': ' | '.join(trend['reasons']),
        'timestamp': datetime.now().isoformat(),
    }
    
    return signal

async def main():
    logger.info(f"🎯 Generating comprehensive trading signals at {datetime.now()}")
    
    all_signals = []
    
    for key, info in INSTRUMENTS.items():
        try:
            signal = await generate_signal_for_instrument(key, info)
            if signal:
                all_signals.append(signal)
                logger.info(f"✅ {info['name']}: {signal['direction']} (confidence: {signal['confidence']}%)")
            else:
                logger.warning(f"⚠️ Failed to generate signal for {info['name']}")
        except Exception as e:
            logger.error(f"Error processing {info['name']}: {e}")
    
    # Sort by confidence descending
    all_signals.sort(key=lambda x: x['confidence'], reverse=True)
    
    # Build report
    now_eat = datetime.now()
    report = {
        'report_timestamp': now_eat.strftime('%Y-%m-%d %H:%M:%S'),
        'timezone': 'Africa/Addis_Ababa (EAT, UTC+3)',
        'market_hours': 'US Market: 14:30-21:00 EAT | London: 10:00-19:00 EAT | Asian: 02:00-11:00 EAT | Crypto: 24/7 | Forex: 24/5',
        'disclaimer': 'Generated via automated technical analysis. Not financial advice. Always use risk management.',
        'total_signals': len(all_signals),
        'signals': all_signals
    }
    
    # Save to file
    output_file = CACHE_DIR / 'comprehensive_signals.json'
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Also save as latest
    latest_file = Path(__file__).parent / 'trading_signals_latest.json'
    with open(latest_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    # Generate text report
    text_report = generate_text_report(report)
    text_file = Path(__file__).parent / 'trading_signals_report.txt'
    with open(text_file, 'w') as f:
        f.write(text_report)
    
    logger.info(f"📁 Signals saved to {output_file}")
    logger.info(f"📁 Text report saved to {text_file}")
    
    # Print summary
    print("\n" + "="*80)
    print(f"TRADING SIGNALS REPORT - {now_eat.strftime('%Y-%m-%d %H:%M EAT')}")
    print("="*80)
    for s in all_signals:
        market_open_str = "🟢 OPEN" if s['market_open'] else "🔴 CLOSED"
        print(f"\n{s['instrument']} ({s['symbol']}) [{s['market']}] {market_open_str}")
        print(f"  Price: {s['current_price']} ({s['daily_change_pct']:+.2f}%) | {s['direction']} | Confidence: {s['confidence']}%")
        print(f"  Entry: {s['trade_setup'].get('entry', 'N/A')} | SL: {s['trade_setup'].get('stop_loss', 'N/A')} | TP1: {s['trade_setup'].get('take_profit_1', 'N/A')}")
        print(f"  R/R: 1:{s['trade_setup'].get('risk_reward_1', 'N/A')} | {s['rationale'][:100]}...")
    
    return report

def generate_text_report(report: dict) -> str:
    """Generate human-readable text report"""
    lines = []
    lines.append("=" * 80)
    lines.append(f"COMPREHENSIVE TRADING SIGNALS REPORT")
    lines.append(f"Generated: {report['report_timestamp']} {report['timezone']}")
    lines.append(f"Market Hours: {report['market_hours']}")
    lines.append(f"Total Signals: {report['total_signals']}")
    lines.append(f"Disclaimer: {report['disclaimer']}")
    lines.append("=" * 80)
    
    # Group by market
    markets = {}
    for s in report['signals']:
        m = s['market']
        if m not in markets:
            markets[m] = []
        markets[m].append(s)
    
    for market, signals in markets.items():
        lines.append(f"\n{'='*80}")
        lines.append(f"{market} SIGNALS ({len(signals)} instruments)")
        lines.append(f"{'='*80}")
        
        for s in signals:
            market_open = "🟢 MARKET OPEN" if s['market_open'] else "🔴 MARKET CLOSED"
            lines.append(f"\n--- {s['instrument']} ({s['symbol']}) ---")
            lines.append(f"Market Status: {market_open} ({s['market_timezone']})")
            lines.append(f"Current Price: {s['current_price']}  |  Daily Change: {s['daily_change_pct']:+.2f}%")
            lines.append(f"Direction: {s['direction']}  |  Confidence: {s['confidence']}%  |  Strength: {s['strength']}%")
            lines.append(f"Timeframe: {s['timeframe']}")
            
            lines.append(f"\nTechnical Indicators:")
            ts = s['technical_summary']
            lines.append(f"  RSI(14): {ts['rsi_14']}  |  RSI(7): {ts['rsi_7']}")
            lines.append(f"  MACD: {ts['macd']}")
            lines.append(f"  MA Trend: {ts['ma_trend']}")
            if ts['adx_14']:
                lines.append(f"  ADX(14): {ts['adx_14']}")
            lines.append(f"  Stoch K/D: {ts['stoch_k']:.1f} / {ts['stoch_d']:.1f}")
            bb_width = ts.get('bb_width', 0)
            lines.append(f"  BB Position: {ts['bb_position']}  |  BB Width: {bb_width*100:.1f}%")
            lines.append(f"  Volume: {ts['volume_trend']}  |  ATR(14): {ts['atr_14']:.2f}")
            
            lines.append(f"\nKey Levels:")
            kl = s['key_levels']
            lines.append(f"  Resistance: R1={kl['resistance_1']}  R2={kl['resistance_2']}  R3={kl['resistance_3']}")
            lines.append(f"  Support:    S1={kl['support_1']}  S2={kl['support_2']}  S3={kl['support_3']}")
            lines.append(f"  Pivot: {kl['pivot']}")
            
            lines.append(f"\nTrade Setup:")
            ts_setup = s['trade_setup']
            lines.append(f"  Entry Zone: {ts_setup.get('entry', 'N/A')}")
            lines.append(f"  Stop Loss: {ts_setup.get('stop_loss', 'N/A')}")
            lines.append(f"  Take Profit 1: {ts_setup.get('take_profit_1', 'N/A')} (R:R 1:{ts_setup.get('risk_reward_1', 'N/A')})")
            lines.append(f"  Take Profit 2: {ts_setup.get('take_profit_2', 'N/A')} (R:R 1:{ts_setup.get('risk_reward_2', 'N/A')})")
            lines.append(f"  Take Profit 3: {ts_setup.get('take_profit_3', 'N/A')} (R:R 1:{ts_setup.get('risk_reward_3', 'N/A')})")
            
            lines.append(f"\nMarket Context:")
            mc = s['market_context']
            lines.append(f"  Sector: {mc.get('sector', 'N/A')}")
            lines.append(f"  Key Catalysts: {', '.join(mc.get('catalysts', []))}")
            
            lines.append(f"\nRationale: {s['rationale']}")
            lines.append("")
    
    return "\n".join(lines)

if __name__ == "__main__":
    asyncio.run(main())
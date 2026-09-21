import os
from typing import List, Dict
from fastapi import APIRouter, Query
from supabase import create_client, Client
import numpy as np
import ta
from app.smart_money_concepts import smc

# --- CONFIG ---
def get_env_var(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

SUPABASE_URL = get_env_var("SUPABASE_URL", required=True)
SUPABASE_KEY = get_env_var("SUPABASE_KEY", required=True)

ASSETS = ["XAUUSD", "NASDAQ"]
TIMEFRAMES = ["1min", "5min", "15min", "1h", "4h", "1d"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
router = APIRouter()

# --- UTILS ---
def fetch_market_data(asset: str, timeframe: str, limit: int = 1000):
    res = supabase.table("market_data").select("*") \
        .eq("asset", asset) \
        .order("timestamp", desc=True) \
        .limit(limit) \
        .execute()
    return res.data[::-1]  # oldest first

def fetch_trade_signals(asset: str, timeframe: str, limit: int = 1000):
    res = supabase.table("trade_signals").select("*") \
        .eq("asset", asset) \
        .eq("timeframe", timeframe) \
        .order("entry_price", desc=True) \
        .limit(limit) \
        .execute()
    return res.data[::-1]

def atr(highs, lows, closes, period=14):
    return ta.volatility.AverageTrueRange(
        high=np.array(highs),
        low=np.array(lows),
        close=np.array(closes),
        window=period
    ).average_true_range()[-1]

def pip_value(asset: str):
    return 0.1 if asset == "XAUUSD" else 0.01

# --- POSITION SIZING ---
def position_size(balance, risk_pct, stop_loss_distance, pip_val):
    risk_amount = balance * (risk_pct / 100)
    return risk_amount / (stop_loss_distance * pip_val)

# --- RISK MANAGEMENT ---
def risk_management(trades: List[Dict], balance: float):
    max_risk_per_trade = 0.02 * balance
    daily_loss_limit = 0.05 * balance
    daily_loss = 0
    filtered = []
    for t in trades:
        risk = abs(t["entry_price"] - t["stop_loss"]) * pip_value(t["asset"])
        if risk > max_risk_per_trade:
            continue
        if daily_loss + risk > daily_loss_limit:
            break
        daily_loss += risk
        filtered.append(t)
    return filtered

def trail_stop(entry, atr_val, price_move):
    # Move stop to breakeven after 1x ATR profit
    if abs(price_move) >= atr_val:
        return entry["entry_price"]
    return entry["stop_loss"]

# --- PORTFOLIO METRICS ---
def portfolio_metrics(trades: List[Dict]):
    wins = [t for t in trades if t.get("result", 0) > 0]
    losses = [t for t in trades if t.get("result", 0) <= 0]
    rr = np.mean([abs(t["take_profit"] - t["entry_price"]) / abs(t["stop_loss"] - t["entry_price"]) for t in trades if t["stop_loss"] != t["entry_price"]]) if trades else 0
    win_rate = len(wins) / len(trades) if trades else 0
    # Drawdown
    equity = 0
    peak = 0
    max_dd = 0
    for t in trades:
        equity += t.get("result", 0)
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    return {"risk_reward_ratio": rr, "win_rate": win_rate, "drawdown": max_dd}

# --- BACKTESTING ---
def backtest_strategy(asset: str, timeframe: str, system: str, candles: List[Dict]):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    trades = []
    for i in range(40, len(candles)):
        window = candles[i-40:i]
        atr_val = atr(highs[i-40:i], lows[i-40:i], closes[i-40:i], 20)
        if system == "Turtle Soup":
            liq = smc.liquidity([c["high"] for c in window], [c["low"] for c in window], [c["close"] for c in window])
            if liq and volumes[i-1] > 2 * np.mean(volumes[i-20:i-1]):
                direction = "long" if closes[i-1] > closes[i-2] else "short"
                entry = closes[i-1]
                stop = (max([c["high"] for c in window]) + 1.5 * atr_val) if direction == "long" else (min([c["low"] for c in window]) - 1.5 * atr_val)
                tp = entry + 2 * atr_val if direction == "long" else entry - 2 * atr_val
                result = tp - entry if direction == "long" else entry - tp
                trades.append({"entry_price": entry, "stop_loss": stop, "take_profit": tp, "result": result})
        elif system == "CRT":
            price_range = max([c["high"] for c in window][-6:]) - min([c["low"] for c in window][-6:])
            if price_range < 0.005 * closes[i-1]:
                direction = "long" if closes[i-1] > closes[i-2] else "short"
                entry = closes[i-1]
                stop = (max([c["high"] for c in window][-6:]) + 1.5 * atr_val)
                tp = entry + 2 * atr_val
                result = tp - entry
                trades.append({"entry_price": entry, "stop_loss": stop, "take_profit": tp, "result": result})
        elif system == "Market Maker/IPDA":
            fvg = smc.fvg([c["high"] for c in window], [c["low"] for c in window], [c["close"] for c in window], [c["volume"] for c in window])
            if fvg and volumes[i-1] > 1.5 * np.mean(volumes[i-20:i-1]):
                entry = closes[i-1]
                stop = (max([c["high"] for c in window]) + 1.5 * atr_val)
                tp = entry + 2 * atr_val
                result = tp - entry
                trades.append({"entry_price": entry, "stop_loss": stop, "take_profit": tp, "result": result})
    return trades

# --- METRICS ENDPOINT ---
@router.get("/metrics")
def get_metrics(
    asset: str = Query(..., description="Asset symbol, e.g. XAUUSD or NASDAQ"),
    timeframe: str = Query(..., description="Timeframe, e.g. 1min, 5min, 15min, 1h, 4h, 1d"),
    limit: int = Query(100, description="Number of records to use")
):
    trades = fetch_trade_signals(asset, timeframe, limit)
    metrics = portfolio_metrics(trades)
    # Store in portfolio_metrics
    supabase.table("portfolio_metrics").insert(metrics).execute()
    return metrics

# --- BACKTEST ENDPOINT ---
@router.get("/backtest")
def run_backtest(
    asset: str = Query(..., description="Asset symbol, e.g. XAUUSD or NASDAQ"),
    timeframe: str = Query(..., description="Timeframe, e.g. 1min, 5min, 15min, 1h, 4h, 1d"),
    system: str = Query(..., description="System: Turtle Soup, CRT, Market Maker/IPDA"),
    limit: int = Query(200, description="Number of records to use")
):
    candles = fetch_market_data(asset, timeframe, limit)
    trades = backtest_strategy(asset, timeframe, system, candles)
    metrics = portfolio_metrics(trades)
    return {"trades": trades, "metrics": metrics} 
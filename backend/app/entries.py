import os
from typing import List, Dict
from fastapi import APIRouter, Query
from supabase import create_client, Client
import numpy as np
from smart_money_concepts import smc

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

def atr(highs, lows, closes, period=14):
    trs = [max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])) for i in range(1, len(highs))]
    return np.mean(trs[-period:]) if len(trs) >= period else np.mean(trs)

def get_higher_timeframe_bias(asset: str, timeframe: str):
    # Use /analysis endpoint or simple trend
    data = fetch_market_data(asset, "1d", 40)
    closes = [c["close"] for c in data]
    return "bullish" if closes[-1] > closes[0] else "bearish"

# --- ENTRY SYSTEMS ---
def turtle_soup(candles: List[Dict]):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    avg_vol = np.mean(volumes[-20:])
    liq = smc.liquidity(highs, lows, closes)
    ob = smc.ob(highs, lows, closes)
    entries = []
    # Look for false breakout and reversal
    if liq and volumes[-1] > 2 * avg_vol:
        direction = "long" if closes[-1] > closes[-2] else "short"
        breakout = highs[-1] if direction == "long" else lows[-1]
        stop_loss = breakout + 1.5 * atr_val if direction == "long" else breakout - 1.5 * atr_val
        invalidation = breakout  # retest
        tp = ob[-1]["price"] if ob else closes[-1] + 2 * atr_val
        entries.append({
            "system": "Turtle Soup",
            "entry_price": closes[-1],
            "stop_loss": stop_loss,
            "take_profit": tp,
            "invalidation_point": invalidation,
            "liquidity_zones": liq,
            "bias": direction
        })
    return entries

def crt(candles: List[Dict]):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    sessions = smc.sessions(highs, lows, closes)
    price_range = max(highs[-6:]) - min(lows[-6:])
    if price_range < 0.005 * closes[-1]:
        # Breakout
        direction = "long" if closes[-1] > closes[-2] else "short"
        stop_loss = (max(highs[-6:]) + min(lows[-6:])) / 2 + 1.5 * atr_val
        invalidation = (max(highs[-6:]) + min(lows[-6:])) / 2
        liq = smc.liquidity(highs, lows, closes)
        tp = liq[-1]["price"] if liq else closes[-1] + 2 * atr_val
        return [{
            "system": "CRT",
            "entry_price": closes[-1],
            "stop_loss": stop_loss,
            "take_profit": tp,
            "invalidation_point": invalidation,
            "liquidity_zones": liq,
            "bias": direction
        }]
    return []

def market_maker_ipda(candles: List[Dict]):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    avg_vol = np.mean(volumes[-20:])
    fvg = smc.fvg(highs, lows, closes, volumes)
    liq = smc.liquidity(highs, lows, closes)
    entries = []
    if fvg and volumes[-1] > 1.5 * avg_vol:
        zone = fvg[-1]["zone"] if "zone" in fvg[-1] else "premium"
        direction = "long" if zone == "discount" else "short"
        zone_boundary = highs[-1] if direction == "long" else lows[-1]
        stop_loss = zone_boundary + 1.5 * atr_val if direction == "long" else zone_boundary - 1.5 * atr_val
        invalidation = zone_boundary
        tp = liq[-1]["price"] if liq else closes[-1] + 2 * atr_val
        entries.append({
            "system": "Market Maker/IPDA",
            "entry_price": closes[-1],
            "stop_loss": stop_loss,
            "take_profit": tp,
            "invalidation_point": invalidation,
            "liquidity_zones": liq,
            "bias": direction
        })
    return entries

# --- STRATEGY SELECTOR ---
def select_strategy(candles: List[Dict], bias: str):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    atr_val = atr(highs, lows, closes, 20)
    atr_avg = np.mean([atr(highs, lows, closes, 20) for _ in range(5)])
    if atr_val > atr_avg:
        # High volatility: prefer Turtle Soup or Market Maker
        return [*turtle_soup(candles), *market_maker_ipda(candles)]
    else:
        # Low volatility: prefer CRT
        return crt(candles)

# --- ENTRIES ENDPOINT ---
@router.get("/entries")
def get_entries(
    asset: str = Query(..., description="Asset symbol, e.g. XAUUSD or NASDAQ"),
    timeframe: str = Query(..., description="Timeframe, e.g. 1min, 5min, 15min, 1h, 4h, 1d"),
    limit: int = Query(100, description="Number of records to use")
):
    candles = fetch_market_data(asset, timeframe, limit)
    if not candles or len(candles) < 40:
        return {"error": "Not enough data for entries."}
    bias = get_higher_timeframe_bias(asset, timeframe)
    entries = select_strategy(candles, bias)
    # Store in trade_signals
    for entry in entries:
        supabase.table("trade_signals").insert({
            "asset": asset,
            "timeframe": timeframe,
            "bias": entry["bias"],
            "liquidity_zones": str(entry["liquidity_zones"]),
            "entry_price": entry["entry_price"],
            "stop_loss": entry["stop_loss"],
            "take_profit": entry["take_profit"],
            "invalidation_point": entry["invalidation_point"],
            "system": entry["system"]
        }).execute()
    return entries 
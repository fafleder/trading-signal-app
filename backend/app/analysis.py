import os
from typing import List, Dict
from fastapi import APIRouter, Query
from supabase import create_client, Client
import requests
import numpy as np
from app.smart_money_concepts import smc
from sklearn.linear_model import LinearRegression

# --- CONFIG ---
def get_env_var(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

SUPABASE_URL = get_env_var("SUPABASE_URL", required=True)
SUPABASE_KEY = get_env_var("SUPABASE_KEY", required=True)
FRED_API_KEY = get_env_var("FRED_API_KEY", required=True)
NEWS_API_KEY = get_env_var("NEWS_API_KEY", required=True)

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

def fetch_fred_series(series_id: str):
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={FRED_API_KEY}&file_type=json"
    r = requests.get(url)
    if r.status_code == 200:
        return r.json().get("observations", [])
    return []

def fetch_news_sentiment(asset: str):
    url = f"https://newsapi.org/v2/everything?q={asset}&apiKey={NEWS_API_KEY}"
    r = requests.get(url)
    if r.status_code == 200:
        articles = r.json().get("articles", [])
        # Simple sentiment: count positive/negative words (placeholder)
        pos, neg = 0, 0
        for a in articles:
            text = (a.get("title", "") + " " + a.get("description", "")).lower()
            if "bullish" in text or "rally" in text or "gain" in text:
                pos += 1
            if "bearish" in text or "drop" in text or "loss" in text:
                neg += 1
        total = pos + neg
        if total == 0:
            return 0
        return (pos - neg) / total
    return 0

def correlate_fundamental_with_price(fundamental: List[float], prices: List[float]):
    if len(fundamental) != len(prices) or len(fundamental) < 2:
        return 0
    X = np.array(fundamental).reshape(-1, 1)
    y = np.array(prices)
    model = LinearRegression().fit(X, y)
    return float(np.corrcoef(np.ravel(X), y)[0, 1])

# --- ICT ANALYSIS ---
def ict_analysis(asset: str, timeframe: str, candles: List[Dict]):
    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles]
    timestamps = [c["timestamp"] for c in candles]
    swings = smc.swing_highs_lows(highs, lows)
    # Market Structure
    ms = "bullish" if swings[-1]["type"] == "higher_high" else "bearish"
    # Liquidity Sweeps
    liq = None
    avg_vol = np.mean(volumes[-40:])
    if highs[-1] >= max(highs[-20:-1]) and volumes[-1] > 2 * avg_vol:
        liq = "liquidity_sweep_high"
    elif lows[-1] <= min(lows[-20:-1]) and volumes[-1] > 2 * avg_vol:
        liq = "liquidity_sweep_low"
    # Order Blocks
    ob = smc.ob(highs, lows, closes)
    # Fair Value Gaps
    fvg = smc.fvg(highs, lows, closes, volumes)
    # IPDA
    ipda = smc.previous_high_low(highs, lows, [20, 40, 60])
    # Consolidation/Expansion/Etc (simplified)
    price_range = max(highs[-6:]) - min(lows[-6:])
    consolidation = price_range < 0.005 * closes[-1]
    expansion = (highs[-1] > max(highs[-20:-1]) or lows[-1] < min(lows[-20:-1])) and volumes[-1] > 2 * avg_vol
    retracement = abs(closes[-1] - (max(highs[-20:-1]) + min(lows[-20:-1])) / 2) < 0.01 * closes[-1]
    # Compose ICT signal
    ict_score = 0
    if ms == "bullish":
        ict_score += 0.3
    if liq:
        ict_score += 0.2
    if ob:
        ict_score += 0.1
    if fvg:
        ict_score += 0.1
    if expansion:
        ict_score += 0.2
    if retracement:
        ict_score += 0.1
    return ict_score, ms

# --- FUNDAMENTAL ANALYSIS ---
def fundamental_analysis(asset: str, candles: List[Dict]):
    closes = [c["close"] for c in candles]
    # FRED: CPI/GDP
    if asset == "XAUUSD":
        cpi = fetch_fred_series("CPIAUCSL")
        fundamental = [float(x["value"]) for x in cpi if x["value"] != "."][-len(closes):]
    else:
        gdp = fetch_fred_series("GDP")
        fundamental = [float(x["value"]) for x in gdp if x["value"] != "."][-len(closes):]
    coef = correlate_fundamental_with_price(fundamental, closes)
    # NewsAPI
    sentiment = fetch_news_sentiment(asset)
    fund_score = 0
    if coef > 0.5:
        fund_score += 0.2
    if sentiment > 0.3:
        fund_score += 0.1
    elif sentiment < -0.3:
        fund_score -= 0.1
    return fund_score, coef, sentiment

# --- ANALYSIS ENDPOINT ---
@router.get("/analysis")
def run_analysis(
    asset: str = Query(..., description="Asset symbol, e.g. XAUUSD or NASDAQ"),
    timeframe: str = Query(..., description="Timeframe, e.g. 1min, 5min, 15min, 1h, 4h, 1d"),
    limit: int = Query(100, description="Number of records to use")
):
    candles = fetch_market_data(asset, timeframe, limit)
    if not candles or len(candles) < 40:
        return {"error": "Not enough data for analysis."}
    ict_score, ict_bias = ict_analysis(asset, timeframe, candles)
    fund_score, coef, sentiment = fundamental_analysis(asset, candles)
    # Combine
    total_score = 0.7 * ict_score + 0.3 * fund_score
    bias = "bullish" if total_score > 0.2 else "bearish" if total_score < -0.2 else "neutral"
    # Store in trade_signals
    supabase.table("trade_signals").insert({
        "asset": asset,
        "timeframe": timeframe,
        "bias": bias
    }).execute()
    return {
        "asset": asset,
        "timeframe": timeframe,
        "ict_score": ict_score,
        "ict_bias": ict_bias,
        "fund_score": fund_score,
        "fundamental_coef": coef,
        "news_sentiment": sentiment,
        "bias": bias
    }

from dotenv import load_dotenv
load_dotenv()
# OpenAPI docs available at /docs and /redoc when running the backend 

import os
import time
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from functools import wraps
import logging
import threading
from dotenv import load_dotenv

import requests
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
import redis
import jwt
from app.analysis import router as analysis_router
from app.entries import router as entries_router
from app.risk import router as risk_router
from app.x_insights import router as x_insights_router

# --- CONFIG ---
def get_env_var(name, default=None, required=False):
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

ALPHA_VANTAGE_API_KEY = get_env_var("ALPHA_VANTAGE_API_KEY", required=True)
SUPABASE_URL = get_env_var("SUPABASE_URL", required=True)
SUPABASE_KEY = get_env_var("SUPABASE_KEY", required=True)
SUPABASE_JWT_SECRET = get_env_var("SUPABASE_SERVICE_ROLE_KEY", required=True)
REDIS_URL = get_env_var("REDIS_URL", "redis://localhost:6379/0")

ASSETS = {
    "XAUUSD": {"symbol": "XAUUSD", "market": "FOREX"},
    "NASDAQ": {"symbol": "NDX", "market": "INDEX"},  # NDX is NASDAQ 100 index
}
TIMEFRAMES = ["1min", "5min", "15min", "60min", "240min", "1d"]
ALPHA_INTERVALS = {
    "1min": "1min",
    "5min": "5min",
    "15min": "15min",
    "60min": "60min",
    "240min": "60min",  # 4h not directly supported, will aggregate
    "1d": "Daily"
}

# --- INIT ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)

# --- AUTH ---
def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid Authorization header")
    token = auth_header.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"])
        return payload  # Contains user info
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {e}")

@app.get("/protected")
def protected_route(user=Depends(get_current_user)):
    return {"message": "You are authenticated!", "user": user}

# --- UTILS ---
def rate_limit_key(asset, timeframe):
    return f"rate_limit:{asset}:{timeframe}"

def cache_key(asset, timeframe):
    return f"ohlc:{asset}:{timeframe}"

def alpha_vantage_url(asset, timeframe):
    if asset == "XAUUSD":
        function = "FX_INTRADAY"
        from_symbol = "XAU"
        to_symbol = "USD"
        interval = ALPHA_INTERVALS[timeframe]
        return f"https://www.alphavantage.co/query?function={function}&from_symbol={from_symbol}&to_symbol={to_symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}"
    elif asset == "NASDAQ":
        function = "TIME_SERIES_INTRADAY"
        symbol = "NDX"  # NASDAQ 100 index
        interval = ALPHA_INTERVALS[timeframe]
        return f"https://www.alphavantage.co/query?function={function}&symbol={symbol}&interval={interval}&apikey={ALPHA_VANTAGE_API_KEY}"
    return None

# --- DATA FETCHING ---
def fetch_ohlc_from_alpha(asset: str, timeframe: str):
    url = alpha_vantage_url(asset, timeframe)
    for attempt in range(3):
        try:
            # Rate limit: 5 calls/minute
            rl_key = rate_limit_key(asset, timeframe)
            calls = redis_client.get(rl_key)
            if calls and int(calls) >= 5:
                return {"error": "Rate limit exceeded. Try again later."}
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                redis_client.incr(rl_key, 1)
                redis_client.expire(rl_key, 60)
                return resp.json()
            else:
                time.sleep(5)
        except Exception as e:
            if attempt < 2:
                time.sleep(5)
            else:
                return {"error": str(e)}
    return {"error": "Failed to fetch data after retries."}

# --- SUPABASE ---
def store_ohlc_to_supabase(asset: str, ohlc: dict, timeframe: str):
    # ohlc: {timestamp, open, high, low, close, volume}
    data = {
        "timestamp": ohlc["timestamp"],
        "asset": asset,
        "open": ohlc["open"],
        "high": ohlc["high"],
        "low": ohlc["low"],
        "close": ohlc["close"],
        "volume": ohlc["volume"]
    }
    supabase.table("market_data").insert(data).execute()

# --- REDIS CACHE ---
def cache_ohlc(asset: str, timeframe: str, ohlc: dict):
    key = cache_key(asset, timeframe)
    redis_client.set(key, str(ohlc), ex=3600)

def get_cached_ohlc(asset: str, timeframe: str):
    key = cache_key(asset, timeframe)
    val = redis_client.get(key)
    if val:
        import ast
        return ast.literal_eval(val)
    return None

# --- WEBSOCKET MANAGER ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()

# --- API ENDPOINTS ---
def rate_limiter(limit: int = 30, period: int = 60):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = kwargs.get('request')
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break
            ip = request.client.host if request else 'unknown'
            key = f"rl:{ip}:{request.url.path}"
            count = redis_client.get(key)
            if count and int(count) >= limit:
                raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
            pipe = redis_client.pipeline()
            pipe.incr(key, 1)
            pipe.expire(key, period)
            pipe.execute()
            return await func(*args, **kwargs)
        return wrapper
    return decorator

@app.get("/market-data")
@rate_limiter(limit=30, period=60)
def get_market_data(request: Request,
    asset: str = Query(..., description="Asset symbol, e.g. XAUUSD or NASDAQ"),
    timeframe: str = Query(..., description="Timeframe, e.g. 1min, 5min, 15min, 60min, 240min, 1d"),
    limit: int = Query(100, description="Number of records to return")
):
    # Fetch from Supabase
    res = supabase.table("market_data").select("*") \
        .eq("asset", asset) \
        .order("timestamp", desc=True) \
        .limit(limit) \
        .execute()
    return res.data

@app.websocket("/ws/market-data")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/fetch-ohlc")
@rate_limiter(limit=10, period=60)
def fetch_and_store_ohlc(request: Request, asset: str, timeframe: str):
    # Check cache first
    cached = get_cached_ohlc(asset, timeframe)
    if cached:
        return cached
    # Fetch from Alpha Vantage
    data = fetch_ohlc_from_alpha(asset, timeframe)
    if "error" in data:
        return JSONResponse(status_code=429, content=data)
    # Parse and store
    # (Parsing logic depends on Alpha Vantage response structure)
    try:
        if asset == "XAUUSD":
            key = f"Time Series FX ({ALPHA_INTERVALS[timeframe]})"
        else:
            key = f"Time Series ({ALPHA_INTERVALS[timeframe]})"
        timeseries = data.get(key, {})
        if not timeseries:
            return {"error": "No data returned from Alpha Vantage."}
        latest_time = sorted(timeseries.keys())[-1]
        ohlc = timeseries[latest_time]
        ohlc_data = {
            "timestamp": latest_time,
            "open": float(ohlc["1. open"]),
            "high": float(ohlc["2. high"]),
            "low": float(ohlc["3. low"]),
            "close": float(ohlc["4. close"]),
            "volume": float(ohlc.get("5. volume", 0))
        }
        store_ohlc_to_supabase(asset, ohlc_data, timeframe)
        cache_ohlc(asset, timeframe, ohlc_data)
        # Broadcast to WebSocket clients
        asyncio.create_task(manager.broadcast({"asset": asset, "timeframe": timeframe, "ohlc": ohlc_data}))
        return ohlc_data
    except Exception as e:
        return {"error": str(e)}

app.include_router(analysis_router)
app.include_router(entries_router)
app.include_router(risk_router)
app.include_router(x_insights_router)

# --- LOGGING ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s %(message)s',
    handlers=[
        logging.FileHandler('backend.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

@app.middleware('http')
async def log_requests(request: Request, call_next):
    logger.info(f"Request: {request.method} {request.url}")
    try:
        response = await call_next(request)
        logger.info(f"Response: {response.status_code} {request.url}")
        return response
    except Exception as exc:
        logger.error(f"Unhandled error: {exc}", exc_info=True)
        return PlainTextResponse("Internal server error", status_code=500)

async def scheduled_data_fetch():
    while True:
        try:
            for asset in ASSETS:
                for timeframe in TIMEFRAMES:
                    logger.info(f"Scheduled fetch: {asset} {timeframe}")
                    fetch_and_store_ohlc(None, asset, timeframe)
        except Exception as e:
            logger.error(f"Scheduled fetch error: {e}")
        await asyncio.sleep(300)  # 5 minutes

@app.on_event("startup")
async def start_background_tasks():
    asyncio.create_task(scheduled_data_fetch()) 
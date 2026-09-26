import re

with open('C:\\Users\\lenovo\\trading-signal-app\\backend\\run_ict_enhanced.py', 'r') as f:
    content = f.read()

# Find and replace the generate_all_signals function
old_start = 'async def generate_all_signals():'
old_end = '# Generate swing signals (always check)'

# Find the start
start_idx = content.find(old_start)
if start_idx == -1:
    print("ERROR: Could not find generate_all_signals")
    exit(1)

# Find the end
end_idx = content.find(old_end, start_idx)
if end_idx == -1:
    print("ERROR: Could not find end marker")
    exit(1)

new_func = '''async def generate_all_signals():
    """Generate signals for all assets and setup types"""
    logger.info(f'🎯 Generating enhanced ICT signals at {datetime.now()}')
    # Use real EST time (not simulated) - GitHub Actions runs in UTC
    est_now = get_current_est_time()
    logger.info(f'🕐 Current EST time: {est_now.strftime("%H:%M")}')
    
    in_kz, kz_session, kz_note = is_in_kill_zone(est_now)
    in_macro, macro_name = is_in_macro_window(est_now)
    in_sb, sb_name = is_in_silver_bullet(est_now)
    
    logger.info(f'📊 Kill Zone: {kz_session.value if kz_session else "NONE"} ({kz_note})')
    logger.info(f'⚡ Macro Window: {macro_name if in_macro else "NONE"}')
    logger.info(f'🎯 Silver Bullet: {sb_name if in_sb else "NONE"}')
    
    all_signals = load_existing_signals()
    new_signals = []
    
    # Detect environment: if MT5 available, use it; otherwise use API fetcher
    use_mt5 = False
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            mt5.shutdown()
            use_mt5 = True
    except:
        pass
    
    if use_mt5:
        logger.info("📡 Using MT5 for data (local environment)")
        mt5_fetcher = MT5DataFetcher()
    else:
        logger.info("📡 Using API fetcher (cloud environment)")
        api_fetcher = APIDataFetcher()
    
    for asset_name, asset_config in ASSETS.items():
        if use_mt5:
            # Get data from MT5 (local)
            logger.info(f"  📡 Fetching MT5 data for {asset_name}...")
            try:
                mt5_data = mt5_fetcher.fetch_all_timeframes(asset_name, {
                    "daily": 100,
                    "4h": 200,
                    "15m": 500,
                    "5m": 1000,
                    "1m": 3000,
                })
                
                if not mt5_data:
                    logger.warning(f"  ⚠️ No MT5 data for {asset_name}, falling back to synthetic")
                    daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                    h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                    h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                    h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                    h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)
                else:
                    daily_candles = dataframe_to_candles(mt5_data.get("daily"))
                    h4_candles = dataframe_to_candles(mt5_data.get("4h"))
                    h15_candles = dataframe_to_candles(mt5_data.get("15m"))
                    h5_candles = dataframe_to_candles(mt5_data.get("5m"))
                    h1_candles = dataframe_to_candles(mt5_data.get("1m"))
                    logger.info(f"  ✅ MT5 data loaded: {len(daily_candles)} daily, {len(h15_candles)} 15m, {len(h5_candles)} 5m, {len(h1_candles)} 1m")
            except Exception as e:
                logger.error(f"  ❌ MT5 fetch failed for {asset_name}: {e}, using synthetic")
                daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)
        else:
            # Get data from API (cloud)
            logger.info(f"  📡 Fetching API data for {asset_name}...")
            try:
                api_data = api_fetcher.fetch_all_timeframes(asset_name)
                
                if not api_data:
                    logger.warning(f"  ⚠️ No API data for {asset_name}, falling back to synthetic")
                    daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                    h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                    h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                    h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                    h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)
                else:
                    daily_candles = dataframe_to_candles(api_data.get("daily"))
                    h4_candles = dataframe_to_candles(api_data.get("4h"))
                    h15_candles = dataframe_to_candles(api_data.get("15m"))
                    h5_candles = dataframe_to_candles(api_data.get("5m"))
                    h1_candles = dataframe_to_candles(api_data.get("1m"))
                    logger.info(f"  ✅ API data loaded: {len(daily_candles)} daily, {len(h15_candles)} 15m, {len(h5_candles)} 5m, {len(h1_candles)} 1m")
            except Exception as e:
                logger.error(f"  ❌ API fetch failed for {asset_name}: {e}, using synthetic")
                daily_candles = generate_synthetic_candles(asset_name, "daily", 100)
                h4_candles = generate_synthetic_candles(asset_name, "4h", 200)
                h15_candles = generate_synthetic_candles(asset_name, "15m", 500)
                h5_candles = generate_synthetic_candles(asset_name, "5m", 1000)
                h1_candles = generate_synthetic_candles(asset_name, "1m", 3000)

# Generate swing signals (always check)'''

# Replace
content = content[:start_idx] + new_func + content[end_idx:]

with open('C:\\Users\\lenovo\\trading-signal-app\\backend\\run_ict_enhanced.py', 'w') as f:
    f.write(content)

print("Done")
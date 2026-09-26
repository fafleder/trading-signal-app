with open('run_ict_enhanced.py', 'r') as f:
    content = f.read()

# Fix the entire block from entry_price to the target selection
old = '''    entry_price = ote_entry if has_ote else (entry_pd.price_bottom if direction == "long" else entry_pd.price_top)
    
        # Stop just beyond the PD array (not sweep)
        pd_range = entry_pd.price_top - entry_pd.price_bottom
        if direction == "long":
            stop_loss = entry_pd.price_bottom - pd_range * 0.1
        else:
            stop_loss = entry_pd.price_top + pd_range * 0.1
    \n
        # Also set invalidation at sweep level (for reference)
        invalidation_price = sweep_price
    \n
        # Target: Use proper ICT targets - IPDA levels, ADR, opposite range side
        # Calculate ADR for target projection
        adr = 0
        if len(h15_closes) >= 20:
            adr = np.mean([h15_highs[i] - h15_lows[i] for i in range(-20, 0)])
    \n
        # Get IPDA levels from daily data
        ipda_high_20d = ipda_low_20d = ipda_eq_20d = entry_price
        ipda_high_40d = ipda_low_40d = ipda_eq_40d = entry_price
        ipda_high_60d = ipda_low_60d = ipda_eq_60d = entry_price
    \n
        # Calculate IPDA from daily candles
        if len(h15_closes) >= 100:  # Need enough daily data
            daily_highs = [c.high for c in daily_candles] if 'daily_candles' in locals() else h15_highs[-100:]
            daily_lows = [c.low for c in daily_candles] if 'daily_candles' in locals() else h15_lows[-100:]
            if len(daily_highs) >= 20:
                ipda_high_20d = max(daily_highs[-20:])
                ipda_low_20d = min(daily_lows[-20:])
                ipda_eq_20d = (ipda_high_20d + ipda_low_20d) / 2
            if len(daily_highs) >= 40:
                ipda_high_40d = max(daily_highs[-40:])
                ipda_low_40d = min(daily_lows[-40:])
                ipda_eq_40d = (ipda_high_40d + ipda_low_40d) / 2
            if len(daily_highs) >= 60:
                ipda_high_60d = max(daily_highs[-60:])
                ipda_low_60d = min(daily_lows[-60:])
                ipda_eq_60d = (ipda_high_60d + ipda_low_60d) / 2
    \n
        # 15M range for opposite side target
        h15_range_high = max(h15_highs[-50:]) if len(h15_highs) >= 50 else max(h15_highs)
        h15_range_low = min(h15_lows[-50:]) if len(h15_lows) >= 50 else min(h15_lows)
    \n
        # Determine targets based on ICT methodology
        if direction == "long":
            # Priority 1: Opposite side of 15M range
            # Priority 2: IPDA 20-day high
            # Priority 3: IPDA 40-day high
            # Priority 4: ADR projection
        
            targets = []
        \n
            # Opposite 15M range high
            if h15_range_high > entry_price:
                targets.append(("15M_range_high", h15_range_high))
        \n
            # IPDA 20-day high
            if ipda_high_20d > entry_price:
                targets.append(("IPDA_20d_high", ipda_high_20d))
        \n
            # IPDA 40-day high
            if ipda_high_40d > entry_price:
                targets.append(("IPDA_40d_high", ipda_high_40d))
        \n
            # ADR target
            if adr > 0:
                targets.append(("ADR_1x", entry_price + adr))
                targets.append(("ADR_1.5x", entry_price + adr * 1.5))
        \n
            # Filter valid targets (> entry)
            valid_targets = [t for t in targets if t[1] > entry_price]
        \n
            if valid_targets:
                # Pick target with minimum 1.5R distance
                risk = abs(entry_price - stop_loss)
                min_target_dist = risk * 1.5
            \n
                # Sort by distance, prefer targets with good R:R
                valid_targets = [t for t in valid_targets if (t[1] - entry_price) >= min_target_dist]
            \n
                if valid_targets:
                    # Choose the closest valid target
                    target_pool_name, tp1 = min(valid_targets, key=lambda x: x[1])
                else:
                    # Fallback: measured move with 1.5R minimum
                    move_size = abs(displacement_price - sweep_price)
                    tp1 = entry_price + max(move_size, risk * 2)
                    target_pool_name = "measured_move"
            else:
                move_size = abs(displacement_price - sweep_price)
                tp1 = entry_price + max(move_size, risk * 2)
                target_pool_name = "measured_move"
        else:
            # Short direction - similar logic
            targets = []
        \n
            if h15_range_low < entry_price:
                targets.append(("15M_range_low", h15_range_low))
        \n
            if ipda_low_20d < entry_price:
                targets.append(("IPDA_20d_low", ipda_low_20d))
        \n
            if ipda_low_40d < entry_price:
                targets.append(("IPDA_40d_low", ipda_low_40d))
        \n
            if adr > 0:
                targets.append(("ADR_1x", entry_price - adr))
                targets.append(("ADR_1.5x", entry_price - adr * 1.5))
        \n
            valid_targets = [t for t in targets if t[1] < entry_price]
        \n
            if valid_targets:
                risk = abs(entry_price - stop_loss)
                min_target_dist = risk * 1.5
                valid_targets = [t for t in valid_targets if (entry_price - t[1]) >= min_target_dist]
            \n
                if valid_targets:
                    target_pool_name, tp1 = min(valid_targets, key=lambda x: abs(x[1] - entry_price))
                else:
                    move_size = abs(displacement_price - sweep_price)
                    tp1 = entry_price - max(move_size, risk * 2)
                    target_pool_name = "measured_move"
            else:
                move_size = abs(displacement_price - sweep_price)
                tp1 = entry_price - max(move_size, risk * 2)
                target_pool_name = "measured_move"
    \n
        tp2 = entry_price + 2 * abs(tp1 - entry_price) if direction == "long" else entry_price - 2 * abs(tp1 - entry_price)'''

new = '''    entry_price = ote_entry if has_ote else (entry_pd.price_bottom if direction == "long" else entry_pd.price_top)
    
    # Stop just beyond the PD array (not sweep)
    pd_range = entry_pd.price_top - entry_pd.price_bottom
    if direction == "long":
        stop_loss = entry_pd.price_bottom - pd_range * 0.1
    else:
        stop_loss = entry_pd.price_top + pd_range * 0.1
    
    # Also set invalidation at sweep level (for reference)
    invalidation_price = sweep_price
    
    # Target: Use proper ICT targets - IPDA levels, ADR, opposite range side
    # Calculate ADR for target projection
    adr = 0
    if len(h15_closes) >= 20:
        adr = np.mean([h15_highs[i] - h15_lows[i] for i in range(-20, 0)])
    
    # Get IPDA levels from daily data
    ipda_high_20d = ipda_low_20d = ipda_eq_20d = entry_price
    ipda_high_40d = ipda_low_40d = ipda_eq_40d = entry_price
    ipda_high_60d = ipda_low_60d = ipda_eq_60d = entry_price
    
    # Calculate IPDA from daily candles
    if len(h15_closes) >= 100:  # Need enough daily data
        daily_highs = [c.high for c in daily_candles] if 'daily_candles' in locals() else h15_highs[-100:]
        daily_lows = [c.low for c in daily_candles] if 'daily_candles' in locals() else h15_lows[-100:]
        if len(daily_highs) >= 20:
            ipda_high_20d = max(daily_highs[-20:])
            ipda_low_20d = min(daily_lows[-20:])
            ipda_eq_20d = (ipda_high_20d + ipda_low_20d) / 2
        if len(daily_highs) >= 40:
            ipda_high_40d = max(daily_highs[-40:])
            ipda_low_40d = min(daily_lows[-40:])
            ipda_eq_40d = (ipda_high_40d + ipda_low_40d) / 2
        if len(daily_highs) >= 60:
            ipda_high_60d = max(daily_highs[-60:])
            ipda_low_60d = min(daily_lows[-60:])
            ipda_eq_60d = (ipda_high_60d + ipda_low_60d) / 2
    
    # 15M range for opposite side target
    h15_range_high = max(h15_highs[-50:]) if len(h15_highs) >= 50 else max(h15_highs)
    h15_range_low = min(h15_lows[-50:]) if len(h15_lows) >= 50 else min(h15_lows)
    
    # Determine targets based on ICT methodology
    if direction == "long":
        # Priority 1: Opposite side of 15M range
        # Priority 2: IPDA 20-day high
        # Priority 3: IPDA 40-day high
        # Priority 4: ADR projection
        
        targets = []
        
        # Opposite 15M range high
        if h15_range_high > entry_price:
            targets.append(("15M_range_high", h15_range_high))
        
        # IPDA 20-day high
        if ipda_high_20d > entry_price:
            targets.append(("IPDA_20d_high", ipda_high_20d))
        
        # IPDA 40-day high
        if ipda_high_40d > entry_price:
            targets.append(("IPDA_40d_high", ipda_high_40d))
        
        # ADR target
        if adr > 0:
            targets.append(("ADR_1x", entry_price + adr))
            targets.append(("ADR_1.5x", entry_price + adr * 1.5))
        
        # Filter valid targets (> entry)
        valid_targets = [t for t in targets if t[1] > entry_price]
        
        if valid_targets:
            # Pick target with minimum 1.5R distance
            risk = abs(entry_price - stop_loss)
            min_target_dist = risk * 1.5
            
            # Sort by distance, prefer targets with good R:R
            valid_targets = [t for t in valid_targets if (t[1] - entry_price) >= min_target_dist]
            
            if valid_targets:
                # Choose the closest valid target
                target_pool_name, tp1 = min(valid_targets, key=lambda x: x[1])
            else:
                # Fallback: measured move with 1.5R minimum
                move_size = abs(displacement_price - sweep_price)
                tp1 = entry_price + max(move_size, risk * 2)
                target_pool_name = "measured_move"
        else:
            move_size = abs(displacement_price - sweep_price)
            tp1 = entry_price + max(move_size, risk * 2)
            target_pool_name = "measured_move"
    else:
        # Short direction - similar logic
        targets = []
        
        if h15_range_low < entry_price:
            targets.append(("15M_range_low", h15_range_low))
        
        if ipda_low_20d < entry_price:
            targets.append(("IPDA_20d_low", ipda_low_20d))
        
        if ipda_low_40d < entry_price:
            targets.append(("IPDA_40d_low", ipda_low_40d))
        
        if adr > 0:
            targets.append(("ADR_1x", entry_price - adr))
            targets.append(("ADR_1.5x", entry_price - adr * 1.5))
        
        valid_targets = [t for t in targets if t[1] < entry_price]
        
        if valid_targets:
            risk = abs(entry_price - stop_loss)
            min_target_dist = risk * 1.5
            valid_targets = [t for t in valid_targets if (entry_price - t[1]) >= min_target_dist]
            
            if valid_targets:
                target_pool_name, tp1 = min(valid_targets, key=lambda x: abs(x[1] - entry_price))
            else:
                move_size = abs(displacement_price - sweep_price)
                tp1 = entry_price - max(move_size, risk * 2)
                target_pool_name = "measured_move"
        else:
            move_size = abs(displacement_price - sweep_price)
            tp1 = entry_price - max(move_size, risk * 2)
            target_pool_name = "measured_move"
    
    tp2 = entry_price + 2 * abs(tp1 - entry_price) if direction == "long" else entry_price - 2 * abs(tp1 - entry_price)'''

content = content.replace(old, new)

with open('run_ict_enhanced.py', 'w') as f:
    f.write(content)

print('Fixed')
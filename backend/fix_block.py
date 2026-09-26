entry_price = ote_entry if has_ote else (entry_pd.price_bottom if direction == "long" else entry_pd.price_top)

        # CRITICAL: Check if current price is near the entry zone for valid signal
        current_price = h5_closes[-1]  # Current 5M close
        if direction == "long":
            # Price should be near or above entry (not already way past)
            if current_price > entry_price * 1.002:  # More than 0.2% past entry
                logger.info(f"  ⏭️ Skipping {asset}: price {current_price:.5f} already {((current_price/entry_price)-1)*100:.2f}% past entry {entry_price:.5f}")
                return setups
            # Also check if price hasn't retraced enough (below OTE start)
            if current_price < ote_start:
                logger.info(f"  ⏭️ Skipping {asset}: price {current_price:.5f} hasn't retraced to OTE zone (start={ote_start:.5f})")
                return setups
        else:
            # Short: price should be near or below entry
            if current_price < entry_price * 0.998:  # More than 0.2% past entry
                logger.info(f"  ⏭️ Skipping {asset}: price {current_price:.5f} already {((1-current_price/entry_price))*100:.2f}% past entry {entry_price:.5f}")
                return setups
            # Also check if price hasn't retraced enough (above OTE end)
            if current_price > ote_end:
                logger.info(f"  ⏭️ Skipping {asset}: price {current_price:.5f} hasn't retraced to OTE zone (end={ote_end:.5f})")
                return setups

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